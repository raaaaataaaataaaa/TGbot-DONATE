"""Интеграция с Platega (https://platega.io).

REST API мерчанта: https://app.platega.io / docs — базовый URL api.platega.io.
Создание платежа POST /transaction/process, callback шлётся на указанный URL.
"""
from __future__ import annotations

import aiohttp

from app.config import config
from app.payments.base import InvoiceResult, PaymentProviderBase

API_URL = "https://api.platega.io"


class PlategaProvider(PaymentProviderBase):
    key = "platega"
    title = "Platega"

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {config.PLATEGA_API_KEY}",
            "Content-Type": "application/json",
        }

    def is_configured(self) -> bool:
        return bool(config.PLATEGA_MERCHANT_ID and config.PLATEGA_API_KEY)

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
            "amount": round(amount, 2),
            "currency": currency.upper(),
            "description": description,
            "referenceId": str(payment_id),          # наш id платежа
            "returnUrl": f"{config.WEBHOOK_BASE_URL}/donate/success?pid={payment_id}",
            "failedUrl": f"{config.WEBHOOK_BASE_URL}/donate/failed?pid={payment_id}",
            "notificationUrl": f"{config.WEBHOOK_BASE_URL}/webhooks/platega",
            "lifetime": 3600,
            "shouldRequireConfirmation": False,
            "metadata": {"tg_user": str(payer_user_id)},
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{API_URL}/transaction/process", json=payload, headers=self._headers) as resp:
                data = await resp.json(content_type=None)
                if resp.status >= 400:
                    raise RuntimeError(f"Platega create_invoice error {resp.status}: {data}")
        return InvoiceResult(
            external_id=str(data.get("id") or data.get("transactionId") or ""),
            pay_url=data.get("redirectUrl") or data.get("url"),
            raw=data,
        )

    async def get_status(self, external_id: str) -> str:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_URL}/transaction/{external_id}", headers=self._headers) as resp:
                data = await resp.json(content_type=None)
        return self._map_status(str(data.get("status", "")))

    @staticmethod
    def _map_status(state: str) -> str:
        state = state.lower()
        if state in ("completed", "paid", "confirmed"):
            return "paid"
        if state in ("expired",):
            return "expired"
        if state in ("declined", "canceled", "cancelled", "failed", "refunded", "chargeback"):
            return "failed"
        return "pending"  # new / pending / initialization / authentication / sentForProcessing

    def parse_webhook(self, data: dict) -> tuple[str | None, str | None]:
        ext_id = str(data.get("id") or data.get("transactionId") or "") or None
        status = self._map_status(str(data.get("status", "")))
        return ext_id, status
