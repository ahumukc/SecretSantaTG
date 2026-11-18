"""Проверка членства с кэшем и ограничением нагрузки на Telegram API."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.constants import MEMBER_STATUSES
from bot.db import repo
from bot.db.models import utcnow

logger = logging.getLogger(__name__)

# Не больше 20 запросов в секунду и 10 одновременно — с запасом от лимита Telegram.
_API_RATE = 20
_API_CONCURRENCY = 10
_POSITIVE_TTL = timedelta(hours=24)
_NEGATIVE_TTL = timedelta(minutes=15)
_ADMIN_TTL = timedelta(minutes=5)

_ADMIN_CACHE: dict[tuple[int, int], tuple[bool, datetime]] = {}


class MembershipCheckError(RuntimeError):
    """Не удалось достоверно проверить членство (сеть/API)."""


class _RateLimiter:
    def __init__(self, rate_per_second: float) -> None:
        self._interval = 1.0 / rate_per_second
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = self._last_call + self._interval - now
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_call = time.monotonic()


_rate_limiter = _RateLimiter(_API_RATE)
_api_semaphore = asyncio.Semaphore(_API_CONCURRENCY)


def _is_member(status: str | None) -> bool:
    return status in MEMBER_STATUSES


async def _fetch_status(bot: Bot, chat_id: int, user_id: int) -> str | None:
    """Возвращает статус участника или None, если проверить не удалось."""
    await _rate_limiter.wait()
    async with _api_semaphore:
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        except TelegramAPIError as exc:
            logger.debug(
                "get_chat_member failed chat=%s user=%s: %s", chat_id, user_id, exc
            )
            return None

    if member.status == "restricted":
        return "member" if getattr(member, "is_member", False) else "restricted"
    return member.status


def _cache_is_fresh(status: str, updated_at: datetime) -> bool:
    ttl = _POSITIVE_TTL if _is_member(status) else _NEGATIVE_TTL
    return utcnow() - updated_at <= ttl


async def ensure_member(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    user_id: int,
) -> bool:
    """Свежая проверка (один запрос к API) с записью результата в кэш."""
    status = await _fetch_status(bot, chat_id, user_id)
    if status is None:
        return False
    await repo.upsert_membership(session, chat_id, user_id, status)
    return _is_member(status)


async def is_member(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    *,
    fresh: bool = False,
) -> bool:
    if not fresh:
        cached = await repo.get_membership(session, chat_id, user_id)
        if cached is not None and _cache_is_fresh(cached.status, cached.updated_at):
            return _is_member(cached.status)
    return await ensure_member(bot, session, chat_id, user_id)


async def filter_member_chats(
    bot: Bot,
    session: AsyncSession,
    user_id: int,
    chat_ids: list[int],
) -> list[int]:
    """Оставляет только чаты, где пользователь состоит.

    Сначала читает кэш одним запросом, недостающие проверяет параллельно.
    """
    unique_chat_ids = list(dict.fromkeys(chat_ids))
    if not unique_chat_ids:
        return []

    cached_rows = await repo.get_membership_rows(session, user_id, unique_chat_ids)
    members: set[int] = set()
    to_check: list[int] = []

    for chat_id in unique_chat_ids:
        row = cached_rows.get(chat_id)
        if row is None or not _cache_is_fresh(row.status, row.updated_at):
            to_check.append(chat_id)
        elif _is_member(row.status):
            members.add(chat_id)

    if to_check:
        statuses = await asyncio.gather(
            *(_fetch_status(bot, chat_id, user_id) for chat_id in to_check)
        )
        for chat_id, status in zip(to_check, statuses, strict=True):
            if status is None:
                # API недоступен — доверяем устаревшему кэшу, если он был.
                cached = cached_rows.get(chat_id)
                if cached is not None and _is_member(cached.status):
                    members.add(chat_id)
                continue
            await repo.upsert_membership(session, chat_id, user_id, status)
            if _is_member(status):
                members.add(chat_id)

    return [chat_id for chat_id in unique_chat_ids if chat_id in members]


async def recheck_members(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    user_ids: list[int],
) -> set[int]:
    """Свежая проверка всех участников перед жеребьёвкой.

    Если хотя бы одного проверить не удалось — бросает MembershipCheckError,
    чтобы не исключить человека из-за сетевого сбоя.
    """
    unique_user_ids = list(dict.fromkeys(user_ids))
    if not unique_user_ids:
        return set()

    statuses = await asyncio.gather(
        *(_fetch_status(bot, chat_id, user_id) for user_id in unique_user_ids)
    )

    unknown = [
        user_id
        for user_id, status in zip(unique_user_ids, statuses, strict=True)
        if status is None
    ]
    if unknown:
        raise MembershipCheckError(f"Не удалось проверить: {unknown}")

    members: set[int] = set()
    for user_id, status in zip(unique_user_ids, statuses, strict=True):
        assert status is not None
        await repo.upsert_membership(session, chat_id, user_id, status)
        if _is_member(status):
            members.add(user_id)
    return members


async def is_chat_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    key = (chat_id, user_id)
    cached = _ADMIN_CACHE.get(key)
    if cached is not None and utcnow() - cached[1] <= _ADMIN_TTL:
        return cached[0]

    status = await _fetch_status(bot, chat_id, user_id)
    if status is None:
        return False

    is_admin = status in {"creator", "administrator"}
    _ADMIN_CACHE[key] = (is_admin, utcnow())
    return is_admin


async def is_bot_admin(bot: Bot, chat_id: int) -> bool:
    status = await _fetch_status(bot, chat_id, bot.id)
    return status in {"creator", "administrator"}
