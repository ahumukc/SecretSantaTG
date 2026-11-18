"""Личные сообщения: список игр пользователя, вступление, вишлист, статистика."""

from __future__ import annotations

from html import unescape

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.types import User as TgUser
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.constants import ACTIVE_STATUSES, MAX_WISHLIST_LENGTH, GameStatus
from bot.db import repo
from bot.db.models import Chat, Game
from bot.keyboards.inline import game_card_keyboard, games_keyboard, main_menu_keyboard
from bot.services.announcements import refresh_announcement
from bot.services.membership import ensure_member, filter_member_chats, is_member
from bot.services.texts import (
    HELP_TEXT,
    esc,
    game_card,
    games_list_text,
    wishlist_text,
)

router = Router(name="dm")
router.message.filter(F.chat.type == ChatType.PRIVATE)


class WishlistForm(StatesGroup):
    waiting = State()


def _parse_game_id(data: str | None) -> int | None:
    if not data:
        return None
    try:
        return int(data.split(":", 1)[1])
    except (IndexError, ValueError):
        return None


def _short(text: str, limit: int = 190) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def _load_user_games(
    bot: Bot,
    session: AsyncSession,
    user_id: int,
) -> list[tuple[Game, Chat, int]]:
    games = await repo.get_active_games_with_chats(session)
    if not games:
        return []

    member_chats = set(
        await filter_member_chats(
            bot,
            session,
            user_id,
            [chat.chat_id for _, chat in games],
        )
    )
    counts = await repo.count_participants_by_games(
        session, [game.id for game, _ in games]
    )
    return [
        (game, chat, counts.get(game.id, 0))
        for game, chat in games
        if chat.chat_id in member_chats
    ]


async def _send_games_list(
    bot: Bot,
    session: AsyncSession,
    message: Message,
    *,
    user_id: int | None = None,
    edit: bool = False,
) -> None:
    if user_id is None:
        if message.from_user is None:
            return
        user_id = message.from_user.id

    games = await _load_user_games(bot, session, user_id)
    text = games_list_text(games)
    markup = games_keyboard(games) if games else main_menu_keyboard()

    if edit:
        try:
            await message.edit_text(text, reply_markup=markup)
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc):
                return
        except TelegramAPIError:
            pass

    await message.answer(text, reply_markup=markup)


async def _join_game(
    bot: Bot,
    session: AsyncSession,
    user: TgUser,
    game_id: int,
) -> tuple[bool, str, Game | None]:
    game = await repo.get_game(session, game_id)
    if game is None:
        return False, "Игра не найдена.", None
    if game.status != GameStatus.RECRUITING:
        return False, "Набор участников уже завершён.", None

    chat = await repo.get_chat(session, game.chat_id)
    if chat is None or not chat.is_active:
        return False, "Группа больше не доступна.", None

    if not await ensure_member(bot, session, game.chat_id, user.id):
        return (
            False,
            (
                f"Вы не состоите в группе «{esc(chat.title)}». "
                "Сначала вступите в неё, затем нажмите кнопку ещё раз."
            ),
            None,
        )

    await repo.upsert_user(session, user)

    existing = await repo.get_participant(session, game.id, user.id)
    if existing is not None:
        participants = await repo.get_participants(session, game.id)
        return True, f"Вы уже участвуете. Участников: {len(participants)}.", game

    try:
        async with session.begin_nested():
            await repo.add_participant(session, game.id, user.id)
    except IntegrityError:
        # Параллельный клик: участник уже добавлен.
        pass

    participants = await repo.get_participants(session, game.id)
    await refresh_announcement(bot, game, participants)
    return (
        True,
        f"✅ Вы в игре «{esc(chat.title)}». Участников: {len(participants)}.",
        game,
    )


async def _handle_join_message(
    bot: Bot,
    session: AsyncSession,
    message: Message,
    game_id: int,
) -> None:
    if message.from_user is None:
        return
    _ok, text, _game = await _join_game(bot, session, message.from_user, game_id)
    await message.answer(text)
    await _send_games_list(bot, session, message)


async def _ask_wishlist(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    user_id: int,
) -> None:
    user = await repo.get_user(session, user_id)
    current = user.wishlist if user is not None else None
    await state.set_state(WishlistForm.waiting)
    await message.answer(
        wishlist_text(current)
        + "\n\nОтправьте новый текст вишлиста одним сообщением "
        f"(до {MAX_WISHLIST_LENGTH} символов). Отмена — /cancel."
    )


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    session: AsyncSession,
    bot: Bot,
    state: FSMContext,
) -> None:
    if message.from_user is None:
        return

    await state.clear()
    await repo.upsert_user(session, message.from_user)

    parts = (message.text or "").split(maxsplit=1)
    payload = parts[1].strip() if len(parts) > 1 else ""

    if payload.startswith("join_"):
        raw_game_id = payload[len("join_") :]
        if raw_game_id.isdigit():
            await _handle_join_message(bot, session, message, int(raw_game_id))
            return

    await _send_games_list(bot, session, message)


@router.message(Command("stats"))
async def cmd_stats(
    message: Message,
    session: AsyncSession,
    bot: Bot,
) -> None:
    if message.from_user is None:
        return
    await repo.upsert_user(session, message.from_user)
    await _send_games_list(bot, session, message)


@router.message(Command("wishlist"))
async def cmd_wishlist(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    if message.from_user is None:
        return
    await repo.upsert_user(session, message.from_user)
    await _ask_wishlist(message, session, state, message.from_user.id)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(WishlistForm.waiting, Command("cancel"))
async def cmd_cancel_wishlist(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отмена. Вишлист не изменён.")


@router.message(WishlistForm.waiting, F.text & ~F.text.startswith("/"))
async def save_wishlist(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    if message.from_user is None:
        return

    text = (message.text or "").strip()
    if not text:
        await message.answer("Отправьте текст вишлиста или /cancel.")
        return
    if len(text) > MAX_WISHLIST_LENGTH:
        await message.answer(
            f"Слишком длинно: {len(text)} символов. "
            f"Максимум — {MAX_WISHLIST_LENGTH}. Попробуйте короче."
        )
        return

    await repo.set_wishlist(session, message.from_user.id, text)
    await state.clear()
    await message.answer("✅ Вишлист сохранён.")


@router.message(WishlistForm.waiting)
async def wishlist_other(message: Message) -> None:
    await message.answer("Отправьте текст одним сообщением или /cancel.")


@router.callback_query(F.data == "mygames")
async def cb_mygames(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
) -> None:
    await callback.answer()
    if callback.message is not None:
        await _send_games_list(
            bot,
            session,
            callback.message,
            user_id=callback.from_user.id,
            edit=True,
        )


@router.callback_query(F.data == "stats")
async def cb_stats(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
) -> None:
    await callback.answer()
    if callback.from_user is not None:
        await repo.upsert_user(session, callback.from_user)
    if callback.message is not None:
        await _send_games_list(
            bot,
            session,
            callback.message,
            user_id=callback.from_user.id,
            edit=True,
        )


@router.callback_query(F.data == "wishlist")
async def cb_wishlist(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None:
        return
    await repo.upsert_user(session, callback.from_user)
    await _ask_wishlist(callback.message, session, state, callback.from_user.id)


@router.callback_query(F.data.startswith("game:"))
async def cb_game(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
) -> None:
    game_id = _parse_game_id(callback.data)
    if game_id is None:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    game = await repo.get_game(session, game_id)
    if game is None or game.status not in ACTIVE_STATUSES:
        await callback.answer("Игра недоступна.", show_alert=True)
        return

    chat = await repo.get_chat(session, game.chat_id)
    if chat is None:
        await callback.answer("Группа не найдена.", show_alert=True)
        return

    if not await is_member(bot, session, game.chat_id, callback.from_user.id):
        await callback.answer("Вы не состоите в этой группе.", show_alert=True)
        return

    participants = await repo.get_participants(session, game.id)
    joined = any(
        participant.user_id == callback.from_user.id
        for participant, _ in participants
    )
    if callback.message is not None:
        try:
            await callback.message.edit_text(
                game_card(game, chat.title, participants),
                reply_markup=game_card_keyboard(
                    game.id,
                    joined=joined,
                    status=game.status,
                ),
            )
        except TelegramAPIError:
            pass
    await callback.answer()


@router.callback_query(F.data.startswith("join:"))
async def cb_join(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
) -> None:
    game_id = _parse_game_id(callback.data)
    if game_id is None:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    ok, text, game = await _join_game(bot, session, callback.from_user, game_id)
    await callback.answer(_short(unescape(text)), show_alert=not ok)

    if not ok or game is None or callback.message is None:
        return

    chat = await repo.get_chat(session, game.chat_id)
    if chat is None:
        return

    participants = await repo.get_participants(session, game.id)
    try:
        await callback.message.edit_text(
            game_card(game, chat.title, participants),
            reply_markup=game_card_keyboard(
                game.id,
                joined=True,
                status=game.status,
            ),
        )
    except TelegramAPIError:
        pass


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer("Вы уже участвуете в этой игре.")
