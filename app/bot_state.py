"""Глобальное состояние: ссылка на активный Bot (для отправки из вебхуков/фоновых задач)."""
from __future__ import annotations

from aiogram import Bot

# Простой мутабельный контейнер, чтобы модуль вебхуков мог достать экземпляр бота.
bot_ref: dict[str, Bot | None] = {"bot": None}


def set_bot(bot: Bot) -> None:
    bot_ref["bot"] = bot


def get_bot() -> Bot | None:
    return bot_ref["bot"]
