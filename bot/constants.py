from enum import StrEnum


class GameStatus(StrEnum):
    RECRUITING = "recruiting"
    STARTED = "started"
    FINISHED = "finished"
    CANCELLED = "cancelled"


ACTIVE_STATUSES = (GameStatus.RECRUITING, GameStatus.STARTED)

STATUS_LABELS = {
    GameStatus.RECRUITING: "Набор участников",
    GameStatus.STARTED: "Игра начата",
    GameStatus.FINISHED: "Игра завершена",
    GameStatus.CANCELLED: "Игра отменена",
}

MEMBER_STATUSES = {"creator", "administrator", "member"}

MIN_PARTICIPANTS = 3
MAX_WISHLIST_LENGTH = 1000
MAX_PARTICIPANTS_IN_LIST = 50
MAX_GAMES_IN_LIST = 25
