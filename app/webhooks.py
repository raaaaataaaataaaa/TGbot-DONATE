"""HTTP-сервер для callback-вебхуков платёжных систем (RollyPay, CryptoBot, Platega).

Запускается в том же event loop, что и бот (aiohttp web).
Эндпоинты:
  POST /webhooks/rollypay
  POST /webhooks/cryptobot   (заголовок X-Api-Secret-Token проверяется, если задан)
  POST /webhooks/platega
  GET  /healthz
"""
from __future__ import annotations

import json
import logging

from aiohttp import web

from app.config import config
from app.db.models import Payment, PaymentStatus, User, session_factory
from app.payments import PROVIDERS

logger = logging.getLogger(__name__)


async def _apply_status(provider_key: str, external_id: str | None, status: str | None,
                        payload_hint: str | None = None) -> None:
    """Находит платёж по external_id (или payload 'payment:<id>') и обновляет статус."""
    if not status or status == "pending":
        return
    async with session_factory() as s:
        from sqlalchemy import select

        payment = await s.scalar(
            select(Payment).where(Payment.external_id == external_id)
        ) if external_id else None
        if payment is None and payload_hint:
            # CryptoBot кладёт наш payload вида "payment:123"
            try:
                pid = int(payload_hint.split(":")[1])
                payment = await s.get(Payment, pid)
            except (ValueError, IndexError):
                pass
        if payment is None:
            logger.warning("Webhook %s: payment not found (ext=%s)", provider_key, external_id)
            return
        if payment.status == PaymentStatus.PAID:
            return  # идемпотентность
        mapping = {"paid": PaymentStatus.PAID, "failed": PaymentStatus.FAILED, "expired": PaymentStatus.EXPIRED}
        new_status = mapping.get(status)
        if not new_status:
            return
        payment.status = new_status
        if new_status == PaymentStatus.PAID:
            from datetime import datetime, timezone

            payment.paid_at = datetime.now(timezone.utc)
            user = await s.get(User, payment.user_id)
            user.total_donated += payment.amount
        await s.commit()

        if new_status == PaymentStatus.PAID:
            from app.handlers.user import notify_paid

            user = await s.get(User, payment.user_id)
            await notify_paid(payment, user)
            logger.info("Payment #%s marked PAID via webhook (%s)", payment.id, provider_key)


def _make_handler(provider_key: str):
    async def handler(request: web.Request) -> web.Response:
        provider = PROVIDERS[provider_key]
        try:
            body_bytes = await request.read()
            data = json.loads(body_bytes.decode("utf-8", errors="replace"))
            if not isinstance(data, dict):
                raise ValueError("not an object")
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "bad json"}, status=400)

        # Проверка секрета CryptoBot (задаётся при регистрации вебхука)
        if provider_key == "cryptobot":
            secret = request.headers.get("X-Api-Secret-Token")
            if getattr(config, "CRYPTOBOT_WEBHOOK_SECRET", "") and secret != config.CRYPTOBOT_WEBHOOK_SECRET:
                return web.json_response({"error": "forbidden"}, status=403)

        ext_id, status = provider.parse_webhook(data)
        payload_hint = (data.get("payload") or {}).get("payload") if isinstance(data.get("payload"), dict) else None
        if ext_id is None and payload_hint is None:
            return web.json_response({"error": "cannot parse"}, status=400)
        await _apply_status(provider_key, ext_id, status, payload_hint=payload_hint)
        return web.json_response({"ok": True})

    return handler


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/healthz", lambda r: web.json_response({"ok": True}))
    for key in PROVIDERS:
        app.router.add_post(f"/webhooks/{key}", _make_handler(key))

    # Простые страницы успешной/неудачной оплаты (redirect из провайдеров)
    async def success_page(request: web.Request) -> web.Response:
        pid = request.query.get("pid", "?")
        # Принудительно перепроверим у провайдера на случай потери вебхука
        try:
            from app.handlers.user import finalize_if_paid

            await finalize_if_paid(int(pid))
        except (ValueError, TypeError):
            pass
        return web.Response(
            text="<h2>✅ Спасибо! Оплата принята.</h2><p>Вернитесь в Telegram-бот.</p>",
            content_type="text/html",
        )

    async def failed_page(request: web.Request) -> web.Response:
        return web.Response(
            text="<h2>❌ Оплата не прошла.</h2><p>Попробуйте ещё раз в Telegram-боте.</p>",
            content_type="text/html",
        )

    app.router.add_get("/donate/success", success_page)
    app.router.add_get("/donate/failed", failed_page)
    return app


async def start_webhook_server() -> web.AppRunner:
    app = build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=config.WEBHOOK_PORT)
    await site.start()
    logger.info("Webhook server started on port %s", config.WEBHOOK_PORT)
    return runner
