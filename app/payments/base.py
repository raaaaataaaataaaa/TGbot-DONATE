"""Базовый класс платёжного провайдера."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class InvoiceResult:
    """Результат создания счёта на оплату."""
    external_id: str | None      # id платежа на стороне провайдера
    pay_url: str | None          # ссылка для оплаты (если есть)
    raw: dict                    # сырой ответ API


class PaymentProviderBase(ABC):
    key: str = ""
    title: str = ""

    @abstractmethod
    async def create_invoice(
        self,
        *,
        payment_id: int,
        amount: float,
        currency: str,
        description: str,
        payer_user_id: int,
    ) -> InvoiceResult:
        """Создаёт счёт/инвойс в платёжной системе."""

    @abstractmethod
    async def get_status(self, external_id: str) -> str:
        """Возвращает статус платежа: 'paid' | 'pending' | 'failed' | 'expired'."""

    @abstractmethod
    def parse_webhook(self, data: dict) -> tuple[str | None, str | None]:
        """Разбирает тело вебхука.

        Возвращает кортеж (external_id, status), где status один из:
        'paid' | 'pending' | 'failed' | 'expired' | None.
        """

    def is_configured(self) -> bool:
        raise NotImplementedError
