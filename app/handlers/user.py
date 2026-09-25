"""Пользовательские хендлеры: старт, выбор суммы, провайдера, оплата."""
from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from app.config import config
from app.db.models import (
    Payment,
    PaymentProvider,
    PaymentStatus,
    User,
    session_factory,
)
from app.handlers.common import DonateStates, parse_amount
from app.payments import available_providers, get_provider

logger = logging.getLogger(__name__)
router = Router()

PRESET_AMOUNTS = [50, 100, 250, 500, 1000, 2500]


def amount_kb() -> InlineKeyboardMarkup:
    rows = []
    row = []
    for a in PRESET_AMOUNTS:
        row.append(InlineKeyboardButton(text=f"{a} ₽", callback_data=f"amt:{a}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="✍️ Своя сумма", callback_data="amt:custom")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def provider_kb(payment_id: int) -> InlineKeyboardMarkup:
    rows = []
    for p in available_providers():
        rows.append([
            InlineKeyboardButton(
                text=f"💳 {p.title}",
                callback_data=f"pay:{p.key}:{payment_id}",
            )
        ])
    # Telegram Stars доступны всегда (нативная оплата, provider_token = "")
    rows.append([InlineKeyboardButton(text="⭐ Telegram Stars", callback_data="stars:start")])
    if not available_providers():
        rows.insert(0, [InlineKeyboardButton(text="⚠️ Внешние системы не настроены (.env)", callback_data="noop")])
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def get_or_create_user(tg_id: int, username: str | None, full_name: str) -> User:
    from sqlalchemy import select

    async with session_factory() as s:
        user = await s.scalar(select(User).where(User.tg_id == tg_id))
        if not user:
            user = User(
                tg_id=tg_id,
                username=username,
                full_name=full_name,
                is_admin=tg_id in config.ADMIN_IDS,
            )
            s.add(user)
            await s.commit()
            await s.refresh(user)
        return user


@router.message(CommandStart(deep_link=True))
async def cmd_start_deep(message: Message, command: CommandObject, state: FSMContext):
    """Поддержка deep-link /start donate_<amount>."""
    if command.args and command.args.startswith("donate"):
        parts = command.args.split("_")
        if len(parts) > 1 and parse_amount(parts[1]):
            await _ask_comment(message, state, float(parts[1]))
            return
    await cmd_start(message, state)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    text = (
        "👋 Привет! Это бот для поддержки проекта донатами.\n\n"
        "💛 Выберите сумму пожертвования или напишите свою:"
    )
    await message.answer(text, reply_markup=amount_kb())


@router.callback_query(F.data == "amt:custom")
async def cb_custom_amount(cb, state: FSMContext):
    await state.set_state(DonateStates.waiting_amount)
    await cb.message.edit_text(
        f"✍️ Введите сумму от {config.DONATE_MIN_AMOUNT} "
        f"до {config.DONATE_MAX_AMOUNT} {config.CURRENCY}:"
    )
    await cb.answer()


@router.callback_query(F.data.startswith("amt:"))
async def cb_preset_amount(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    amount = float(cb.data.split(":")[1])
    await _ask_comment(cb, state, amount)
    await cb.answer()


@router.message(DonateStates.waiting_amount, F.text)
async def msg_amount(message: Message, state: FSMContext):
    amount = parse_amount(message.text or "")
    if amount is None:
        await message.answer("❌ Неверный формат. Введите число, например 300 или 99.90")
        return
    if not (config.DONATE_MIN_AMOUNT <= amount <= config.DONATE_MAX_AMOUNT):
        await message.answer(
            f"❌ Сумма должна быть от {config.DONATE_MIN_AMOUNT} "
            f"до {config.DONATE_MAX_AMOUNT} {config.CURRENCY}"
        )
        return
    await state.clear()
    await _ask_comment(message, state, amount)


async def _ask_comment(message: Message | CallbackQuery, state: FSMContext, amount: float):
    await state.set_state(DonateStates.waiting_comment)
    await state.update_data(amount=amount)
    text = (
        f"💛 Сумма доната: <b>{amount:.2f} {config.CURRENCY}</b>\n\n"
        "Напишите комментарий / пожелание (или «-» чтобы пропустить):"
    )
    if isinstance(message, CallbackQuery):
        await message.message.edit_text(text, parse_mode="HTML")
    else:
        await message.answer(text, parse_mode="HTML")


@router.message(DonateStates.waiting_comment, F.text)
async def msg_comment(message: Message, state: FSMContext):
    data = await state.get_data()
    amount = float(data["amount"])
    comment = None if (message.text or "").strip() in {"-", "—"} else message.text.strip()[:500]
    await state.clear()

    user = await get_or_create_user(
        message.from_user.id, message.from_user.username, message.from_user.full_name
    )
    async with session_factory() as s:
        payment = Payment(
            user_id=user.id,
            provider=PaymentProvider.ROLLYPAY,  # будет перезаписан при выборе способа
            amount=amount,
            currency=config.CURRENCY,
            status=PaymentStatus.NEW,
            comment=comment,
        )
        s.add(payment)
        await s.commit()
        await s.refresh(payment)
        pid = payment.id

    await message.answer(
        f"🧾 Создан счёт №{pid} на <b>{amount:.2f} {config.CURRENCY}</b>.\n"
        "Выберите способ оплаты:",
        reply_markup=provider_kb(pid),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "cancel")
async def cb_cancel(cb, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("❌ Отменено. Выбери сумму:", reply_markup=amount_kb())
    await cb.answer()


@router.callback_query(F.data.startswith("pay:"))
async def cb_choose_provider(cb, state: FSMContext):
    _, prov_key, payment_id = cb.data.split(":")
    payment_id = int(payment_id)

    async with session_factory() as s:
        from sqlalchemy import select

        payment = await s.get(Payment, payment_id)
        if not payment or payment.status != PaymentStatus.NEW:
            await cb.answer("Этот счёт уже неактивен", show_alert=True)
            return
        try:
            provider = get_provider(prov_key)
            result = await provider.create_invoice(
                payment_id=payment.id,
                amount=payment.amount,
                currency=payment.currency,
                description=f"Донат {payment.amount:.2f} {payment.currency}",
                payer_user_id=cb.from_user.id,
            )
            payment.provider = PaymentProvider(prov_key)
            payment.external_id = result.external_id
            payment.invoice_url = result.pay_url
            await s.commit()
        except Exception as e:  # noqa: BLE001
            logger.exception("Invoice creation failed")
            await cb.answer(f"Ошибка создания счёта: {e}", show_alert=True)
            return

    btns = []
    if result.pay_url:
        btns.append([InlineKeyboardButton(text="🔗 Оплатить", url=result.pay_url)])
    btns.append([InlineKeyboardButton(text="✅ Я оплатил — проверить", callback_data=f"check:{payment_id}")])
    kb = InlineKeyboardMarkup(inline_keyboard=btns)
    await cb.message.edit_text(
        f"🧾 Счёт №{payment_id} на <b>{payment.amount:.2f} {payment.currency}</b>\n"
        f"Способ оплаты: <b>{provider.title}</b>\n\n"
        f"После оплаты нажмите «Я оплатил» — статус проверим автоматически.",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await cb.answer()


@router.callback_query(F.data.startswith("check:"))
async def cb_check_payment(cb):
    payment_id = int(cb.data.split(":")[1])
    paid = await finalize_if_paid(payment_id)
    if paid:
        await cb.answer("Оплата подтверждена ✅", show_alert=True)
    else:
        await cb.answer("Оплата пока не поступила. Попробуйте через минуту.", show_alert=True)


async def finalize_if_paid(payment_id: int, *, mark_paid: bool = True) -> bool:
    """Проверяет статус платежа у провайдера и при оплате проводит его + шлёт уведомления."""
    from sqlalchemy import select

    async with session_factory() as s:
        payment = await s.get(Payment, payment_id)
        if not payment:
            return False
        if payment.status == PaymentStatus.PAID:
            return True
        if payment.provider == PaymentProvider.TG_STARS or not payment.external_id:
            return False
        provider = get_provider(payment.provider.value)
        status = await provider.get_status(payment.external_id)
        if status != "paid" or not mark_paid:
            return False
        payment.status = PaymentStatus.PAID
        from datetime import datetime, timezone

        payment.paid_at = datetime.now(timezone.utc)
        user = await s.get(User, payment.user_id)
        user.total_donated += payment.amount
        await s.commit()
        await notify_paid(payment, user)
        return True


async def notify_paid(payment: Payment, user: User):
    from app.bot_state import bot_ref

    bot = bot_ref.get("bot")
    if not bot:
        return
    # Пользователю
    try:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Ещё донат 💛", callback_data="amt:100"),
        ]])
        await bot.send_message(
            user.tg_id,
            f"🎉 Спасибо за донат <b>{payment.amount:.2f} {payment.currency}</b>! "
            f"№{payment.id} оплачен ✅\nТвой вклад в развитие проекта очень ценен 💛",
            parse_mode="HTML",
            reply_markup=kb,
        )
    except TelegramAPIError:
        pass
    # Админам
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"💰 Новый донат №{payment.id}: {payment.amount:.2f} {payment.currency} "
                f"от @{user.username or user.full_name} ({payment.provider.value})",
            )
        except TelegramAPIError:
            pass


# ---------- Telegram Stars (нативная оплата) ----------

@router.callback_query(F.data == "stars:start")
async def cb_stars_start(cb):
    prices = [LabeledPrice(label="Донат (Stars)", amount=100)]
    try:
        await cb.message.answer_invoice(
            title="Донат проекту ⭐",
            description="Поддержка проекта через Telegram Stars",
            payload=f"stars:{cb.from_user.id}",
            provider_token="",           # пустой токен = оплата Stars
            currency="XTR",
            prices=prices,
        )
    except TelegramAPIError as e:
        await cb.answer(f"Не удалось: {e}", show_alert=True)
    await cb.answer()


@router.pre_checkout_query()
async def process_pre_checkout(pcq: PreCheckoutQuery):
    if pcq.currency == "XTR":
        await pcq.answer(ok=True)
    else:
        await pcq.answer(ok=False, error_message="Оплата недоступна")


@router.message(F.successful_payment)
async def process_successful_payment(message: Message):
    sp = message.successful_payment
    if sp.currency != "XTR":
        return
    tg_user_id = int(sp.payload.split(":")[1])
    user = await get_or_create_user(
        message.from_user.id, message.from_user.username,
        message.from_user.full_name,
    )
    stars = sp.total_amount
    async with session_factory() as s:
        p = Payment(
            user_id=user.id,
            provider=PaymentProvider.TG_STARS,
            amount=stars,
            currency="XTR",
            status=PaymentStatus.PAID,
            external_id=sp.telegram_payment_charge_id,
            comment="Telegram Stars",
        )
        from datetime import datetime, timezone

        p.paid_at = datetime.now(timezone.utc)
        s.add(p)
        db_user = await s.get(User, user.id)
        db_user.total_donated += stars
        await s.commit()
    await message.answer(
        f"🎉 Спасибо за донат ⭐ {stars} Stars! Оплата прошла успешно."
    )
    for admin_id in config.ADMIN_IDS:
        try:
            await message.bot.send_message(
                admin_id,
                f"💰 Новый донат ⭐ {stars} Stars от @{message.from_user.username or ''}",
            )
        except TelegramAPIError:
            pass
