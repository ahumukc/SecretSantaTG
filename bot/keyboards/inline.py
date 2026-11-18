from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.constants import MAX_GAMES_IN_LIST, STATUS_LABELS, GameStatus
from bot.db.models import Chat, Game


def _button_title(title: str, limit: int = 32) -> str:
    return title if len(title) <= limit else title[: limit - 1] + "…"


def join_keyboard(bot_username: str, game_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎁 Участвовать",
                    url=f"https://t.me/{bot_username}?start=join_{game_id}",
                )
            ]
        ]
    )


def _secondary_row(builder: InlineKeyboardBuilder) -> None:
    builder.row(
        InlineKeyboardButton(text="📝 Мой вишлист", callback_data="wishlist"),
        InlineKeyboardButton(text="📊 Статистика", callback_data="stats"),
    )


def main_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _secondary_row(builder)
    return builder.as_markup()


def games_keyboard(games: list[tuple[Game, Chat, int]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for game, chat, count in games[:MAX_GAMES_IN_LIST]:
        label = STATUS_LABELS.get(game.status, game.status)
        builder.button(
            text=f"{_button_title(chat.title)} — {label} ({count})",
            callback_data=f"game:{game.id}",
        )
    builder.adjust(1)
    _secondary_row(builder)
    return builder.as_markup()


def game_card_keyboard(
    game_id: int,
    *,
    joined: bool,
    status: str,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if status == GameStatus.RECRUITING:
        if joined:
            builder.button(text="✅ Вы участвуете", callback_data="noop")
        else:
            builder.button(text="🎁 Участвовать", callback_data=f"join:{game_id}")
    builder.button(text="⬅️ К списку игр", callback_data="mygames")
    builder.adjust(1)
    return builder.as_markup()
