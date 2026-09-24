"""Админ-панель прямо в Telegram.

Вход: /adminpanel <секретная_фраза> (или пользователь уже в ADMIN_IDS).
Разделы: статистика, платежи, пользователи, настройки, рассылка, провайдеры.
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from app.config import config
from app.db.models import Payment, PaymentProvider, PaymentStatus, Setting, User, session_factory
from app.handlers.common import AdminStates
from app.payments import PROVIDERS, available_providers

logger = logging.getLogger(__name__)
router = Router()

SETTINGS_LABELS = {
    "welcome_text": "Текст приветствия",
    "thanks_text": "Текст благодарности после доната",
    "min_amount": "Минимальная сумма доната",
    "max_amount": "Максимальная сумма доната",
}


async def is_admin(tg_id: int) -> bool:
    if tg_id in config.ADMIN_IDS:
        return True
    async with session_factory() as s:
        u = await s.scalar(select(User).where(User.tg_id == tg_id))
        return bool(u and u.is_admin)


def main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats")],
        [InlineKeyboardButton(text="💳 Платежи", callback_data="adm:payments")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="adm:users")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="adm:settings")],
        [InlineKeyboardButton(text="💳 Провайдеры", callback_data="adm:providers")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="adm:broadcast")],
        [InlineKeyboardButton(text="🔒 Выйти из панели", callback_data="adm:exit")],
    ])


# ---------- Вход ----------

@router.message(Command("adminpanel"))
async def cmd_adminpanel(message: Message, command: CommandObject, state: FSMContext):
    allowed = message.from_user.id in config.ADMIN_IDS
    if not allowed and command.args and command.args.strip() == config.ADMIN_PANEL_SECRET:
        # Разрешаем вход по секрету и повышаем пользователя до админа
        async with session_factory() as s:
            u = await s.scalar(select(User).where(User.tg_id == message.from_user.id))
            if not u:
                u = User(
                    tg_id=message.from_user.id,
                    username=message.from_user.username,
                    full_name=message.from_user.full_name,
                    is_admin=True,
                )
                s.add(u)
            else:
                u.is_admin = True
            await s.commit()
        allowed = True
    if not allowed:
        await message.answer("⛔ Доступ запрещён.")
        return
    await state.clear()
    await message.answer("🛠 <b>Админ-панель донат-бота</b>", reply_markup=main_kb(), parse_mode="HTML")


# ---------- Навигация ----------

@router.callback_query(F.data.startswith("adm:"))
async def adm_nav(cb: CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    action = cb.data.split(":")[1]

    if action == "stats":
        await _show_stats(cb)
    elif action == "payments":
        await _show_payments(cb)
    elif action == "users":
        await _show_users(cb)
    elif action == "settings":
        await _show_settings(cb)
    elif action == "providers":
        await _show_providers(cb)
    elif action == "broadcast":
        await state.set_state(AdminStates.broadcast)
        await cb.message.edit_text(
            "📢 Отправьте текст рассылки всем пользователям бота:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Меню", callback_data="adm:menu")]
            ]),
        )
    elif action == "menu":
        await state.clear()
        await cb.message.edit_text("🛠 <b>Админ-панель</b>", reply_markup=main_kb(), parse_mode="HTML")
    elif action == "exit":
        await state.clear()
        await cb.message.edit_text("Вы вышли из админ-панели.")
    await cb.answer()


async def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Меню", callback_data="adm:menu")]
    ])


async def _show_stats(cb: CallbackQuery):
    async with session_factory() as s:
        users_total = await s.scalar(select(func.count(User.id)))
        paid = PaymentStatus.PAID
        total_sum = await s.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.status == paid)
        )
        payments_total = await s.scalar(select(func.count(Payment.id)))
        payments_pending = await s.scalar(
            select(func.count(Payment.id)).where(Payment.status == PaymentStatus.NEW)
        )
        today = await s.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .where(Payment.status == paid, func.date(Payment.paid_at) == func.date(func.now()))
        )
        by_provider_rows = (await s.execute(
            select(Payment.provider, func.sum(Payment.amount), func.count(Payment.id))
            .where(Payment.status == paid)
            .group_by(Payment.provider)
        )).all()

    prov_lines = "\n".join(
        f"  • {p.value}: {int(cnt)} на {amount:.2f}" for p, amount, cnt in by_provider_rows
    ) or "  • пока пусто"

    text = (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: <b>{users_total}</b>\n"
        f"💳 Всего платежей: <b>{payments_total}</b> (в ожидании: {payments_pending})\n"
        f"💰 Собрано всего: <b>{total_sum:.2f} {config.CURRENCY}</b>\n"
        f"📅 Собрано сегодня: <b>{today:.2f} {config.CURRENCY}</b>\n\n"
        f"По системам оплаты:\n{prov_lines}"
    )
    await cb.message.edit_text(text, reply_markup=await back_kb(), parse_mode="HTML")


async def _show_payments(cb: CallbackQuery):
    async with session_factory() as s:
        rows = (await s.execute(
            select(Payment, User)
            .join(User, Payment.user_id == User.id)
            .order_by(Payment.id.desc())
            .limit(15)
        )).all()
    status_icon = {
        PaymentStatus.PAID: "✅", PaymentStatus.NEW: "⏳",
        PaymentStatus.FAILED: "❌", PaymentStatus.EXPIRED: "⌛", PaymentStatus.REFUNDED: "↩️",
    }
    lines = []
    for p, u in rows:
        icon = status_icon.get(p.status, "•") if isinstance(p.status, PaymentStatus) else "•"
        st = p.status.value if isinstance(p.status, PaymentStatus) else p.status
        lines.append(
            f"{icon} №{p.id} | {p.amount:.2f} {p.currency} | {p.provider.value} | {st} | @{u.username or u.tg_id}"
        )
    text = "💳 <b>Последние платежи</b>\n\n" + ("\n".join(lines) or "Платежей нет")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔎 Проверить платёж у провайдера", callback_data="adm2:check")],
        [InlineKeyboardButton(text="⬅️ Меню", callback_data="adm:menu")],
    ])
    await cb.message.edit_text(text[:4000], reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "adm2:check")
async def adm_check_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.check_status)
    await cb.message.answer("Введите ID платежа для принудительной проверки/подтверждения:")
    await cb.answer()


@router.message(AdminStates.check_status, F.text)
async def adm_check_do(message: Message, state: FSMContext):
    from app.handlers.user import finalize_if_paid

    await state.clear()
    try:
        pid = int(message.text.strip())
    except ValueError:
        await message.answer("Не число.")
        return
    paid = await finalize_if_paid(pid)
    await message.answer("✅ Платёж подтверждён и проведён." if paid else "Оплата не найдена/не прошла.")


async def _show_users(cb: CallbackQuery):
    async with session_factory() as s:
        rows = (await s.execute(
            select(User).order_by(User.total_donated.desc()).limit(10)
        )).scalars().all()
    lines = [
        f"{i+1}. @{u.username or u.tg_id} — {u.total_donated:.2f} {config.CURRENCY}"
        + (" 👑" if u.is_admin else "")
        for i, u in enumerate(rows)
    ]
    text = "👥 <b>Топ донатеров</b>\n\n" + ("\n".join(lines) or "Пользователей нет")
    await cb.message.edit_text(text, reply_markup=await back_kb(), parse_mode="HTML")


async def _show_settings(cb: CallbackQuery):
    async with session_factory() as s:
        rows = (await s.execute(select(Setting))).scalars().all()
        current = {r.key: r.value for r in rows}
    lines = []
    for key, label in SETTINGS_LABELS.items():
        val = current.get(key) or "(по умолчанию)"
        lines.append(f"• <code>{key}</code> — {label}\n   Значение: {val[:80]}")
    text = (
        "⚙️ <b>Настройки</b>\n\n" + "\n".join(lines) +
        "\n\nЧтобы изменить: /setkey <ключ> <значение>"
    )
    await cb.message.edit_text(text, reply_markup=await back_kb(), parse_mode="HTML")


@router.message(Command("setkey"))
async def cmd_setkey(message: Message, command: CommandObject):
    if not await is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    if not command.args or " " not in command.args:
        await message.answer("Формат: /setkey welcome_text Привет, друг!")
        return
    key, value = command.args.split(" ", 1)
    if key not in SETTINGS_LABELS:
        await message.answer(f"Неизвестный ключ. Доступные: {', '.join(SETTINGS_LABELS)}")
        return
    async with session_factory() as s:
        row = await s.get(Setting, key)
        if not row:
            s.add(Setting(key=key, value=value))
        else:
            row.value = value
        await s.commit()
    await message.answer(f"✅ Настройка <code>{key}</code> обновлена.", parse_mode="HTML")


async def _show_providers(cb: CallbackQuery):
    lines = []
    for p in PROVIDERS.values():
        mark = "🟢 подключён" if p.is_configured() else "🔴 не настроен"
        lines.append(f"• <b>{p.title}</b> (<code>{p.key}</code>) — {mark}")
    text = (
        "💳 <b>Платёжные системы</b>\n\n" + "\n".join(lines) +
        "\n\nКлючи задаются в .env (ROLLYPAY_*, CRYPTOBOT_API_TOKEN, PLATEGA_*)."
    )
    await cb.message.edit_text(text, reply_markup=await back_kb(), parse_mode="HTML")


# ---------- Рассылка ----------

@router.message(AdminStates.broadcast, F.text)
async def msg_broadcast(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    await state.clear()
    text = message.text
    sent = failed = 0
    async with session_factory() as s:
        users = (await s.execute(select(User))).scalars().all()
    for u in users:
        try:
            await message.bot.send_message(u.tg_id, text)
            sent += 1
        except Exception:  # noqa: BLE001
            failed += 1
    await message.answer(f"📢 Рассылка завершена: доставлено {sent}, ошибок {failed}.")
