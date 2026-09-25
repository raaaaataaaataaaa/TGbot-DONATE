"""Точка входа: запуск long-polling бота + HTTP-сервер вебхуков платежей."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot_state import set_bot
from app.config import config
from app.db.models import init_db
from app.handlers import admin as admin_handlers
from app.handlers import user as user_handlers
from app.webhooks import start_webhook_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN не задан. Скопируйте .env.example в .env и заполните.")

    bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    set_bot(bot)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(user_handlers.router)
    dp.include_router(admin_handlers.router)

    await init_db()
    runner = await start_webhook_server()
    logger.info("Bot is starting (polling). Webhooks on :%s", config.WEBHOOK_PORT)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as e:
        if isinstance(e, SystemExit) and e.code:
            raise
        logger.info("Bot stopped")
