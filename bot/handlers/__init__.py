from aiogram import Dispatcher

from bot.handlers import dm, group, membership


def setup_routers(dp: Dispatcher) -> None:
    dp.include_router(membership.router)
    dp.include_router(group.router)
    dp.include_router(dm.router)
