"""Отслеживание состава групп: бот видит chat_member, когда он админ."""

from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatMemberUpdated
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db import repo

logger = logging.getLogger(__name__)

router = Router(name="membership")

_GROUP_TYPES = {"group", "supergroup"}


@router.my_chat_member()
async def on_my_chat_member(
    event: ChatMemberUpdated,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Бота добавили/повысили/удалили — обновляем состояние чата."""
    if event.chat.type not in _GROUP_TYPES:
        return

    new_status = event.new_chat_member.status
    old_status = event.old_chat_member.status
    is_active = new_status not in {"left", "kicked"}
    is_admin = new_status in {"creator", "administrator"}

    await repo.upsert_chat(
        session,
        event.chat.id,
        event.chat.title or "",
        is_admin=is_admin,
        is_active=is_active,
    )

    was_absent = old_status in {"left", "kicked"}
    if is_active and was_absent and not is_admin:
        try:
            await bot.send_message(
                event.chat.id,
                "Спасибо, что добавили меня! 🎅\n\n"
                "Чтобы игра работала корректно, назначьте меня "
                "<b>администратором группы</b> — так я смогу точно отслеживать, "
                "кто вступил или вышел.\n\n"
                "После этого администратор может создать игру командой /newgame.",
            )
        except TelegramAPIError as exc:
            logger.debug("Не удалось попросить права админа в %s: %s", event.chat.id, exc)


@router.chat_member()
async def on_chat_member(
    event: ChatMemberUpdated,
    session: AsyncSession,
) -> None:
    """Обновляем кэш членства. Приходит только если бот — админ группы."""
    if event.chat.type not in _GROUP_TYPES:
        return

    member = event.new_chat_member
    status = member.status
    if status == "restricted":
        status = "member" if getattr(member, "is_member", False) else "restricted"

    await repo.upsert_membership(
        session,
        event.chat.id,
        member.user.id,
        status,
    )
