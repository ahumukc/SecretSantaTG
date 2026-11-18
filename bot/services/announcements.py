"""Обновление закреплённого сообщения-анонса в группе."""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup

from bot.constants import GameStatus
from bot.db.models import Game, Participant, User
from bot.keyboards.inline import join_keyboard
from bot.services.texts import announcement_text

logger = logging.getLogger(__name__)


async def refresh_announcement(
    bot: Bot,
    game: Game,
    participants: list[tuple[Participant, User]],
) -> None:
    if not game.announcement_msg_id:
        return

    if game.status == GameStatus.RECRUITING:
        bot_username = (await bot.me()).username or ""
        markup: InlineKeyboardMarkup = join_keyboard(bot_username, game.id)
    else:
        markup = InlineKeyboardMarkup(inline_keyboard=[])

    try:
        await bot.edit_message_text(
            chat_id=game.chat_id,
            message_id=game.announcement_msg_id,
            text=announcement_text(game, participants),
            reply_markup=markup,
        )
    except TelegramAPIError as exc:
        # Сообщение могли удалить или у бота нет прав на редактирование.
        logger.debug("Не удалось обновить анонс игры %s: %s", game.id, exc)
