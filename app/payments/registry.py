"""Реестр платёжных провайдеров."""
from __future__ import annotations

from app.payments.base import InvoiceResult, PaymentProviderBase
from app.payments.cryptobot import CryptoBotProvider
from app.payments.platega import PlategaProvider
from app.payments.rollypay import RollyPayProvider

PROVIDERS: dict[str, PaymentProviderBase] = {
    p.key: p
    for p in (RollyPayProvider(), CryptoBotProvider(), PlategaProvider())
}


def get_provider(key: str) -> PaymentProviderBase:
    return PROVIDERS[key]


def available_providers() -> list[PaymentProviderBase]:
    """Провайдеры, у которых заданы ключи в конфиге."""
    return [p for p in PROVIDERS.values() if p.is_configured()]


__all__ = ["PROVIDERS", "InvoiceResult", "get_provider", "available_providers"]
