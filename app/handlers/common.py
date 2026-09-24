"""Общие FSM-состояния и утилиты."""
from __future__ import annotations

import re

from aiogram.fsm.state import State, StatesGroup

AMOUNT_RE = re.compile(r"^\d{1,6}([.,]\d{1,2})?$")


class DonateStates(StatesGroup):
    waiting_amount = State()
    waiting_comment = State()


class AdminStates(StatesGroup):
    setting_value = State()          # ввод нового значения настройки
    broadcast = State()              # текст рассылки
    check_status = State()           # id платежа для ручной проверки/подтверждения


def parse_amount(text: str) -> float | None:
    """Парсит сумму вида '100', '99.90', '99,90'. Возвращает None если не число."""
    text = text.strip().replace(",", ".")
    if not AMOUNT_RE.match(text):
        return None
    try:
        return float(text)
    except ValueError:
        return None
