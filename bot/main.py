from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    ErrorEvent,
)

from bot.config import get_settings
from bot.db.session import close_db, init_db
from bot.handlers import setup_routers
from bot.middlewares.db import DbSessionMiddleware

logger = logging.getLogger(__name__)

PRIVATE_COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="wishlist", description="Мой вишлист"),
    BotCommand(command="stats", description="Мои игры"),
    BotCommand(command="help", description="Помощь"),
]

GROUP_COMMANDS = [
    BotCommand(command="newgame", description="Создать игру"),
    BotCommand(command="status", description="Этап и участники"),
    BotCommand(command="draw", description="Провести жеребьёвку"),
    BotCommand(command="resend", description="Повторить отправку назначений"),
    BotCommand(command="cancelgame", description="Отменить набор"),
    BotCommand(command="endgame", description="Завершить игру"),
    BotCommand(command="help", description="Помощь"),
]


async def main() -> None:
    settings = get_settings()

    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )

    await init_db(settings.database_url)

    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
            link_preview_is_disabled=True,
        ),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.middleware(DbSessionMiddleware())
    setup_routers(dp)

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        logger.exception(
            "Ошибка при обработке обновления: %s",
            event.exception,
            exc_info=event.exception,
        )
        return True

    try:
        await bot.set_my_commands(
            PRIVATE_COMMANDS,
            scope=BotCommandScopeAllPrivateChats(),
        )
        await bot.set_my_commands(
            GROUP_COMMANDS,
            scope=BotCommandScopeAllGroupChats(),
        )
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Бот запущен (long polling)")
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await close_db()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен")
