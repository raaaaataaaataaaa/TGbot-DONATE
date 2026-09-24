"""Интеграция с CryptoBot (https://cryptobot.app / @CryptoBot API).

API-токен получается в @CryptoBot -> Кошелёк -> Crypto Bot API.
Документация: https://cryptobotappa.stoplight.io / https://www.cryptobot.app/api-docs
"""
from __future__ import annotations

import aiohttp

from app.config import config
from app.payments.base import InvoiceResult, PaymentProviderBase

API_URL = "https://pay.crypt.bot/api"


class CryptoBotProvider(PaymentProviderBase):
    key = "cryptobot"
    title = "CryptoBot (криптовалюта)"

    @property
    def _headers(self) -> dict:
        return {"Cryptobot-Api-Token": config.CRYPTOBOT_API_TOKEN}

    def is_configured(self) -> bool:
        return bool(config.CRYPTOBOT_API_TOKEN)

    async def create_invoice(
        self,
        *,
        payment_id: int,
        amount: float,
        currency: str,
        description: str,
        payer_user_id: int,
    ) -> InvoiceResult:
        # CryptoBot умеет и фиатные инвойсы (RUB/UAZ и т.д.), и крипто (USDT...).
        # Для не-крипто валют просим fiat-инвойс, иначе — USDT.
        crypto_assets = {"BTC", "ETH", "TON", "USDT", "USDC", "BNB", "TRX", "LTC"}
        if currency.upper() in crypto_assets:
            payload = {
                "currency_type": "crypto",
                "crypto_asset": currency.upper(),
                "amount": f"{amount:.6f}",
            }
        else:
            payload = {
                "currency_type": "fiat",
                "fiat_currency": currency.upper(),
                "amount": f"{amount:.2f}",
            }
        payload.update({
            "description": description,
            "payload": f"payment:{payment_id}",
            "expires_in": 3600,
            "allow_comments": False,
            "allow_anonymous": True,
        })
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{API_URL}/createInvoice", json=payload, headers=self._headers) as resp:
                data = await resp.json(content_type=None)
        if not data.get("ok", False):
            raise RuntimeError(f"CryptoBot create_invoice error: {data}")
        res = data["result"]
        return InvoiceResult(
            external_id=str(res.get("invoice_id")),
            pay_url=res.get("pay_url") or res.get("bot_pay_url"),
            raw=res,
        )

    async def get_status(self, external_id: str) -> str:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_URL}/getInvoices?invoice_ids={external_id}", headers=self._headers) as resp:
                data = await resp.json(content_type=None)
        if not data.get("ok", False):
            return "pending"
        items = data["result"].get("items", [])
        status = items[0].get("status") if items else "active"
        return self._map_status(status)

    @staticmethod
    def _map_status(state: str) -> str:
        state = str(state).lower()
        if state == "paid":
            return "paid"
        if state == "expired":
            return "expired"
        if state in ("failed", "cancelled"):
            return "failed"
        return "pending"  # active / creating

    def parse_webhook(self, data: dict) -> tuple[str | None, str | None]:
        # CryptoBot webhook: {"update_type": "invoice_paid", "payload": {...}}
        payload = data.get("payload") or {}
        ext_id = str(payload.get("invoice_id") or "") or None
        utype = str(data.get("update_type", ""))
        if utype == "invoice_paid":
            return ext_id, "paid"
        if payload.get("status"):
            return ext_id, self._map_status(payload["status"])
        return ext_id, None
