"""Команды в группах: создание игры, статус, жеребьёвка, завершение."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.constants import MIN_PARTICIPANTS, STATUS_LABELS, GameStatus
from bot.db import repo
from bot.db.models import Game, utcnow
from bot.keyboards.inline import join_keyboard
from bot.services.announcements import refresh_announcement
from bot.services.draw import build_assignments
from bot.services.membership import (
    MembershipCheckError,
    is_bot_admin,
    is_chat_admin,
    recheck_members,
)
from bot.services.texts import (
    HELP_TEXT,
    announcement_text,
    assignment_text,
    esc,
    game_card,
    game_started_text,
)

logger = logging.getLogger(__name__)

router = Router(name="group")
router.message.filter(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))


async def _require_admin(message: Message, bot: Bot) -> bool:
    if message.from_user is None:
        return False
    if await is_chat_admin(bot, message.chat.id, message.from_user.id):
        return True
    await message.reply("⛔ Команда доступна только администраторам группы.")
    return False


async def _active_game_or_reply(
    message: Message,
    session: AsyncSession,
) -> Game | None:
    await repo.upsert_chat(session, message.chat.id, message.chat.title or "")
    game = await repo.get_active_game(session, message.chat.id)
    if game is None:
        await message.reply(
            "Сейчас в группе нет активной игры. "
            "Администратор может создать её командой /newgame."
        )
    return game


@router.message(CommandStart())
async def cmd_start_in_group(message: Message, bot: Bot) -> None:
    username = (await bot.me()).username or ""
    await message.reply(
        "Привет! 🎅 Чтобы участвовать в игре, откройте меня в личных сообщениях:\n"
        f"https://t.me/{username}"
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.reply(HELP_TEXT)


@router.message(Command("newgame"))
async def cmd_newgame(
    message: Message,
    session: AsyncSession,
    bot: Bot,
) -> None:
    if message.from_user is None or not await _require_admin(message, bot):
        return

    if not await is_bot_admin(bot, message.chat.id):
        await repo.upsert_chat(
            session,
            message.chat.id,
            message.chat.title or "",
            is_admin=False,
            is_active=True,
        )
        await message.reply(
            "Чтобы создать игру, назначьте меня <b>администратором группы</b>. "
            "Это нужно, чтобы точно отслеживать участников."
        )
        return

    await repo.upsert_chat(
        session,
        message.chat.id,
        message.chat.title or "",
        is_admin=True,
        is_active=True,
    )

    active_game = await repo.get_active_game(session, message.chat.id)
    if active_game is not None:
        label = STATUS_LABELS.get(active_game.status, active_game.status)
        await message.reply(
            f"В группе уже есть игра: <b>{label}</b>.\n"
            "Завершите её командой /endgame, чтобы создать новую."
        )
        return

    game = await repo.create_game(session, message.chat.id, message.from_user.id)
    bot_username = (await bot.me()).username or ""
    sent = await message.answer(
        announcement_text(game, []),
        reply_markup=join_keyboard(bot_username, game.id),
    )
    game.announcement_msg_id = sent.message_id


@router.message(Command("status", "stats"))
async def cmd_status(message: Message, session: AsyncSession) -> None:
    game = await _active_game_or_reply(message, session)
    if game is None:
        return
    participants = await repo.get_participants(session, game.id)
    await message.reply(game_card(game, message.chat.title or "", participants))


@router.message(Command("draw"))
async def cmd_draw(
    message: Message,
    session: AsyncSession,
    bot: Bot,
) -> None:
    if message.from_user is None or not await _require_admin(message, bot):
        return

    game = await _active_game_or_reply(message, session)
    if game is None:
        return
    if game.status != GameStatus.RECRUITING:
        await message.reply("Жеребьёвка уже проведена. Завершить игру — /endgame.")
        return

    participants = await repo.get_participants(session, game.id)
    if len(participants) < MIN_PARTICIPANTS:
        await message.reply(
            f"Для жеребьёвки нужно минимум {MIN_PARTICIPANTS} участника. "
            f"Сейчас: {len(participants)}."
        )
        return

    try:
        member_ids = await recheck_members(
            bot,
            session,
            message.chat.id,
            [participant.user_id for participant, _ in participants],
        )
    except MembershipCheckError:
        await message.reply(
            "Не удалось проверить участников из-за ошибки Telegram API. "
            "Попробуйте ещё раз через минуту."
        )
        return

    removed = [
        (participant, user)
        for participant, user in participants
        if participant.user_id not in member_ids
    ]
    for participant, _ in removed:
        await repo.remove_participant(session, game.id, participant.user_id)

    if removed:
        names = ", ".join(esc(user.full_name) for _, user in removed)
        await message.reply(f"Исключены из игры, так как вышли из группы: {names}.")

    participants = [
        (participant, user)
        for participant, user in participants
        if participant.user_id in member_ids
    ]
    if len(participants) < MIN_PARTICIPANTS:
        if removed:
            await refresh_announcement(bot, game, participants)
        await message.reply(
            f"После проверки осталось {len(participants)} участник(ов). "
            f"Нужно минимум {MIN_PARTICIPANTS}. Жеребьёвка отменена."
        )
        return

    users_by_id = {user.user_id: user for _, user in participants}
    mapping = build_assignments([user.user_id for _, user in participants])
    assignments = await repo.save_assignments(session, game.id, mapping)

    game.status = GameStatus.STARTED.value
    game.started_at = utcnow()
    await session.commit()

    failed: list[str] = []
    for giver_id, assignment in assignments.items():
        receiver = users_by_id[mapping[giver_id]]
        try:
            await bot.send_message(giver_id, assignment_text(receiver))
        except TelegramAPIError as exc:
            logger.warning("Не удалось отправить назначение %s: %s", giver_id, exc)
            failed.append(esc(users_by_id[giver_id].full_name))
        else:
            assignment.notified = True

    await refresh_announcement(bot, game, participants)
    await message.answer(game_started_text(participants))

    if failed:
        await message.answer(
            "⚠️ Не удалось отправить назначения: "
            + ", ".join(failed)
            + ".\nПопросите их нажать /start в личке с ботом, затем выполните /resend."
        )


@router.message(Command("resend"))
async def cmd_resend(
    message: Message,
    session: AsyncSession,
    bot: Bot,
) -> None:
    if not await _require_admin(message, bot):
        return

    game = await _active_game_or_reply(message, session)
    if game is None:
        return
    if game.status != GameStatus.STARTED:
        await message.reply("Игра ещё не начата. Сначала выполните /draw.")
        return

    pending = await repo.get_unnotified_assignments(session, game.id)
    if not pending:
        await message.reply("Все назначения уже отправлены.")
        return

    users = await repo.get_users_by_ids(
        session,
        [assignment.giver_id for assignment in pending]
        + [assignment.receiver_id for assignment in pending],
    )

    failed: list[str] = []
    for assignment in pending:
        receiver = users.get(assignment.receiver_id)
        if receiver is None:
            logger.warning("Не найден получатель %s", assignment.receiver_id)
            giver = users.get(assignment.giver_id)
            failed.append(esc(giver.full_name if giver else str(assignment.giver_id)))
            continue
        try:
            await bot.send_message(assignment.giver_id, assignment_text(receiver))
        except TelegramAPIError as exc:
            logger.warning("Повторная отправка %s не удалась: %s", assignment.giver_id, exc)
            giver = users.get(assignment.giver_id)
            failed.append(esc(giver.full_name if giver else str(assignment.giver_id)))
        else:
            assignment.notified = True

    if failed:
        await message.reply(
            "⚠️ Всё ещё не удалось отправить: " + ", ".join(failed) + "."
        )
    else:
        await message.reply("✅ Назначения отправлены.")


@router.message(Command("cancelgame"))
async def cmd_cancelgame(
    message: Message,
    session: AsyncSession,
    bot: Bot,
) -> None:
    if not await _require_admin(message, bot):
        return

    game = await _active_game_or_reply(message, session)
    if game is None:
        return
    if game.status == GameStatus.STARTED:
        await message.reply("Игра уже начата. Для завершения используйте /endgame.")
        return

    game.status = GameStatus.CANCELLED.value
    await session.commit()
    participants = await repo.get_participants(session, game.id)
    await refresh_announcement(bot, game, participants)
    await message.reply("Игра отменена. Можно создать новую командой /newgame.")


@router.message(Command("endgame"))
async def cmd_endgame(
    message: Message,
    session: AsyncSession,
    bot: Bot,
) -> None:
    if not await _require_admin(message, bot):
        return

    game = await _active_game_or_reply(message, session)
    if game is None:
        return

    game.status = GameStatus.FINISHED.value
    game.finished_at = utcnow()
    await session.commit()
    participants = await repo.get_participants(session, game.id)
    await refresh_announcement(bot, game, participants)
    await message.reply(
        "✅ Игра завершена. Спасибо всем за участие!\n"
        "Создать новую игру — /newgame."
    )
