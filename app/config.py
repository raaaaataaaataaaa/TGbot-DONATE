"""Конфигурация донат-бота. Секреты берутся из переменных окружения / файла .env."""
from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv(path: str = ".env") -> None:
    """Минималистичный загрузчик .env (без внешних зависимостей)."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        os.environ.setdefault(key, value)


_load_dotenv()


def _csv_ints(raw: str) -> list[int]:
    return [int(x) for x in raw.replace(" ", "").split(",") if x.isdigit()]


class Config:
    def __init__(self) -> None:
        self.BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
        self.WEBHOOK_BASE_URL: str = os.getenv("WEBHOOK_BASE_URL", "http://localhost:8081").rstrip("/")
        self.WEBHOOK_PORT: int = int(os.getenv("WEBHOOK_PORT", "8081"))

        # ID админов через запятую, напр. "111,222"
        self.ADMIN_IDS: list[int] = _csv_ints(os.getenv("ADMIN_IDS", ""))
        # Секретная фраза для входа в админ-панель (/adminpanel <секрет>)
        self.ADMIN_PANEL_SECRET: str = os.getenv("ADMIN_PANEL_SECRET", "change-me-please")

        # RollyPay
        self.ROLLYPAY_API_KEY: str = os.getenv("ROLLYPAY_API_KEY", "")
        self.ROLLYPAY_PROJECT_ID: str = os.getenv("ROLLYPAY_PROJECT_ID", "")

        # CryptoBot (API token от @CryptoBot -> My Wallet -> Crypto Bot API)
        self.CRYPTOBOT_API_TOKEN: str = os.getenv("CRYPTOBOT_API_TOKEN", "")
        self.CRYPTOBOT_WEBHOOK_SECRET: str = os.getenv("CRYPTOBOT_WEBHOOK_SECRET", "")

        # Platega
        self.PLATEGA_MERCHANT_ID: str = os.getenv("PLATEGA_MERCHANT_ID", "")
        self.PLATEGA_API_KEY: str = os.getenv("PLATEGA_API_KEY", "")
        self.PLATEGA_CALLBACK_SECRET: str = os.getenv("PLATEGA_CALLBACK_SECRET", "")

        self.DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./donate.db")

        self.CURRENCY: str = os.getenv("CURRENCY", "RUB")
        self.DONATE_MIN_AMOUNT: int = int(os.getenv("DONATE_MIN_AMOUNT", "50"))
        self.DONATE_MAX_AMOUNT: int = int(os.getenv("DONATE_MAX_AMOUNT", "100000"))
        self.CHANNEL_ID: str = os.getenv("CHANNEL_ID", "")


config = Config()
