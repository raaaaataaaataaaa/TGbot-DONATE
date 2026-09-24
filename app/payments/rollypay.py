"""Интеграция с RollyPay (https://rollypay.io).

Используется REST API проекта: создание транзакции + callback-вебхук.
Документация: https://docs.rollypay.io
"""
from __future__ import annotations

import hashlib
import hmac

import aiohttp

from app.config import config
from app.payments.base import InvoiceResult, PaymentProviderBase

API_URL = "https://api.rollypay.io/v1"


class RollyPayProvider(PaymentProviderBase):
    key = "rollypay"
    title = "RollyPay"

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {config.ROLLYPAY_API_KEY}",
            "Content-Type": "application/json",
        }

    def is_configured(self) -> bool:
        return bool(config.ROLLYPAY_API_KEY and config.ROLLYPAY_PROJECT_ID)

    async def create_invoice(
        self,
        *,
        payment_id: int,
        amount: float,
        currency: str,
        description: str,
        payer_user_id: int,
    ) -> InvoiceResult:
        payload = {
            "project_id": config.ROLLYPAY_PROJECT_ID,
            "amount": int(round(amount * 100)),  # копейки
            "currency": currency,
            "description": description,
            "metadata": {"payment_id": payment_id, "tg_user": payer_user_id},
            "success_url": f"{config.WEBHOOK_BASE_URL}/donate/success?pid={payment_id}",
            "callback_url": f"{config.WEBHOOK_BASE_URL}/webhooks/rollypay",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{API_URL}/transactions", json=payload, headers=self._headers) as resp:
                data = await resp.json(content_type=None)
                if resp.status >= 400:
                    raise RuntimeError(f"RollyPay create_invoice error {resp.status}: {data}")
        return InvoiceResult(
            external_id=str(data.get("id") or data.get("transaction_id") or ""),
            pay_url=data.get("payment_url") or data.get("url") or data.get("checkout_url"),
            raw=data,
        )

    async def get_status(self, external_id: str) -> str:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_URL}/transactions/{external_id}", headers=self._headers) as resp:
                data = await resp.json(content_type=None)
        state = str(data.get("status", "")).lower()
        return self._map_status(state)

    @staticmethod
    def _map_status(state: str) -> str:
        if state in ("paid", "success", "confirmed", "completed"):
            return "paid"
        if state in ("expired",):
            return "expired"
        if state in ("failed", "canceled", "cancelled", "declined", "reversed"):
            return "failed"
        return "pending"

    def verify_signature(self, body: bytes, signature: str) -> bool:
        """Проверка подписи вебхука: HMAC-SHA256 по секретному ключу API."""
        expected = hmac.new(
            config.ROLLYPAY_API_KEY.encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature or "")

    def parse_webhook(self, data: dict) -> tuple[str | None, str | None]:
        ext_id = str(data.get("id") or data.get("transaction_id") or "") or None
        status = self._map_status(str(data.get("status", "")))
        return ext_id, status
