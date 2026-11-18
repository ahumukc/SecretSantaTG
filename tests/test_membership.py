import asyncio
from datetime import timedelta
from types import SimpleNamespace

from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bot.db import repo
from bot.db.models import Base, utcnow
from bot.services.membership import filter_member_chats


class FakeBot:
    id = 999

    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    async def get_chat_member(self, chat_id: int, user_id: int):
        self.calls += 1
        if self.fail:
            raise TelegramAPIError(None, "boom")
        return SimpleNamespace(status="member", is_member=True)


def _run(tmp_path, scenario) -> None:
    async def runner() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                await scenario(session)
        finally:
            await engine.dispose()

    asyncio.run(runner())


def test_fresh_cache_skips_api(tmp_path) -> None:
    async def scenario(session) -> None:
        bot = FakeBot()
        await repo.upsert_membership(session, -100, 10, "member")
        await session.commit()

        result = await filter_member_chats(bot, session, 10, [-100])

        assert result == [-100]
        assert bot.calls == 0

    _run(tmp_path, scenario)


def test_stale_cache_is_refreshed(tmp_path) -> None:
    async def scenario(session) -> None:
        bot = FakeBot()
        await repo.upsert_membership(session, -100, 10, "left")
        row = await repo.get_membership(session, -100, 10)
        assert row is not None
        row.updated_at = utcnow() - timedelta(hours=2)
        await session.commit()

        result = await filter_member_chats(bot, session, 10, [-100])

        assert result == [-100]
        assert bot.calls == 1
        refreshed = await repo.get_membership(session, -100, 10)
        assert refreshed is not None
        assert refreshed.status == "member"

    _run(tmp_path, scenario)


def test_api_error_falls_back_to_stale_positive_cache(tmp_path) -> None:
    async def scenario(session) -> None:
        bot = FakeBot(fail=True)
        await repo.upsert_membership(session, -100, 10, "member")
        row = await repo.get_membership(session, -100, 10)
        assert row is not None
        row.updated_at = utcnow() - timedelta(days=2)
        await session.commit()

        result = await filter_member_chats(bot, session, 10, [-100])

        assert result == [-100]
        assert bot.calls == 1

    _run(tmp_path, scenario)
