"""Слой доступа к данным: все запросы к БД собраны здесь."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from aiogram.types import User as TgUser
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.constants import ACTIVE_STATUSES, GameStatus
from bot.db.models import Assignment, Chat, ChatMember, Game, Participant, User, utcnow

_ACTIVE_VALUES = [status.value for status in ACTIVE_STATUSES]


# --------------------------------------------------------------------------- #
# Пользователи
# --------------------------------------------------------------------------- #


async def get_user(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def upsert_user(session: AsyncSession, tg_user: TgUser) -> User:
    user = await session.get(User, tg_user.id)
    if user is None:
        user = User(user_id=tg_user.id)
        session.add(user)
    user.username = tg_user.username
    user.full_name = tg_user.full_name
    user.started_bot = True
    user.updated_at = utcnow()
    return user


async def set_wishlist(session: AsyncSession, user_id: int, wishlist: str) -> None:
    user = await session.get(User, user_id)
    if user is None:
        user = User(user_id=user_id, full_name="")
        session.add(user)
    user.wishlist = wishlist
    user.updated_at = utcnow()


async def get_users_by_ids(session: AsyncSession, user_ids: Iterable[int]) -> dict[int, User]:
    ids = list(dict.fromkeys(user_ids))
    if not ids:
        return {}
    result = await session.execute(select(User).where(User.user_id.in_(ids)))
    return {user.user_id: user for user in result.scalars()}


# --------------------------------------------------------------------------- #
# Чаты
# --------------------------------------------------------------------------- #


async def get_chat(session: AsyncSession, chat_id: int) -> Chat | None:
    return await session.get(Chat, chat_id)


async def upsert_chat(
    session: AsyncSession,
    chat_id: int,
    title: str,
    *,
    is_admin: bool | None = None,
    is_active: bool | None = None,
) -> Chat:
    chat = await session.get(Chat, chat_id)
    if chat is None:
        chat = Chat(
            chat_id=chat_id,
            title=title,
            is_admin=bool(is_admin),
            is_active=True if is_active is None else is_active,
        )
        session.add(chat)
        return chat

    if title:
        chat.title = title
    if is_admin is not None:
        chat.is_admin = is_admin
    if is_active is not None:
        chat.is_active = is_active
    return chat


# --------------------------------------------------------------------------- #
# Игры
# --------------------------------------------------------------------------- #


async def get_game(session: AsyncSession, game_id: int) -> Game | None:
    return await session.get(Game, game_id)


async def get_active_game(session: AsyncSession, chat_id: int) -> Game | None:
    result = await session.execute(
        select(Game)
        .where(Game.chat_id == chat_id, Game.status.in_(_ACTIVE_VALUES))
        .order_by(Game.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_active_games_with_chats(session: AsyncSession) -> list[tuple[Game, Chat]]:
    result = await session.execute(
        select(Game, Chat)
        .join(Chat, Chat.chat_id == Game.chat_id)
        .where(Game.status.in_(_ACTIVE_VALUES), Chat.is_active.is_(True))
        .order_by(Game.created_at.desc(), Game.id.desc())
    )
    return [(game, chat) for game, chat in result.all()]


async def create_game(session: AsyncSession, chat_id: int, created_by: int) -> Game:
    game = Game(
        chat_id=chat_id,
        created_by=created_by,
        status=GameStatus.RECRUITING.value,
    )
    session.add(game)
    await session.flush()
    return game


# --------------------------------------------------------------------------- #
# Участники
# --------------------------------------------------------------------------- #


async def get_participant(
    session: AsyncSession,
    game_id: int,
    user_id: int,
) -> Participant | None:
    result = await session.execute(
        select(Participant).where(
            Participant.game_id == game_id,
            Participant.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def get_participants(
    session: AsyncSession,
    game_id: int,
) -> list[tuple[Participant, User]]:
    result = await session.execute(
        select(Participant, User)
        .join(User, User.user_id == Participant.user_id)
        .where(Participant.game_id == game_id)
        .order_by(Participant.joined_at, Participant.id)
    )
    return [(participant, user) for participant, user in result.all()]


async def add_participant(session: AsyncSession, game_id: int, user_id: int) -> None:
    session.add(Participant(game_id=game_id, user_id=user_id))
    await session.flush()


async def remove_participant(session: AsyncSession, game_id: int, user_id: int) -> None:
    await session.execute(
        delete(Participant).where(
            Participant.game_id == game_id,
            Participant.user_id == user_id,
        )
    )


async def count_participants(session: AsyncSession, game_id: int) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(Participant)
        .where(Participant.game_id == game_id)
    )
    return int(result.scalar_one())


async def count_participants_by_games(
    session: AsyncSession,
    game_ids: Sequence[int],
) -> dict[int, int]:
    if not game_ids:
        return {}
    result = await session.execute(
        select(Participant.game_id, func.count())
        .where(Participant.game_id.in_(game_ids))
        .group_by(Participant.game_id)
    )
    return {game_id: int(count) for game_id, count in result.all()}


# --------------------------------------------------------------------------- #
# Назначения
# --------------------------------------------------------------------------- #


async def save_assignments(
    session: AsyncSession,
    game_id: int,
    mapping: dict[int, int],
) -> dict[int, Assignment]:
    assignments: dict[int, Assignment] = {}
    for giver_id, receiver_id in mapping.items():
        assignment = Assignment(
            game_id=game_id,
            giver_id=giver_id,
            receiver_id=receiver_id,
        )
        session.add(assignment)
        assignments[giver_id] = assignment
    await session.flush()
    return assignments


async def get_unnotified_assignments(
    session: AsyncSession,
    game_id: int,
) -> list[Assignment]:
    result = await session.execute(
        select(Assignment)
        .where(Assignment.game_id == game_id, Assignment.notified.is_(False))
        .order_by(Assignment.id)
    )
    return list(result.scalars())


# --------------------------------------------------------------------------- #
# Кэш членства
# --------------------------------------------------------------------------- #


async def get_membership(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
) -> ChatMember | None:
    return await session.get(ChatMember, (chat_id, user_id))


async def get_membership_rows(
    session: AsyncSession,
    user_id: int,
    chat_ids: Sequence[int],
) -> dict[int, ChatMember]:
    if not chat_ids:
        return {}
    result = await session.execute(
        select(ChatMember).where(
            ChatMember.user_id == user_id,
            ChatMember.chat_id.in_(list(chat_ids)),
        )
    )
    return {row.chat_id: row for row in result.scalars()}


async def upsert_membership(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    status: str,
) -> None:
    member = await session.get(ChatMember, (chat_id, user_id))
    if member is None:
        session.add(
            ChatMember(
                chat_id=chat_id,
                user_id=user_id,
                status=status,
                updated_at=utcnow(),
            )
        )
    else:
        member.status = status
        member.updated_at = utcnow()
