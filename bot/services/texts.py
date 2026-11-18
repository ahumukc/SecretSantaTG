"""Тексты сообщений (HTML, все пользовательские данные экранируются)."""

from __future__ import annotations

from html import escape

from bot.constants import (
    MAX_GAMES_IN_LIST,
    MAX_PARTICIPANTS_IN_LIST,
    STATUS_LABELS,
    GameStatus,
)
from bot.db.models import Chat, Game, User


def esc(value: str | None) -> str:
    return escape(value or "", quote=False)


def user_label(user: User) -> str:
    name = esc(user.full_name) or "Без имени"
    if user.username:
        return f"{name} (@{esc(user.username)})"
    return name


def participants_block(
    participants: list[tuple[object, User]],
    limit: int = MAX_PARTICIPANTS_IN_LIST,
    max_chars: int = 3000,
) -> str:
    lines: list[str] = []
    total_chars = 0
    for index, (_, user) in enumerate(participants[:limit], start=1):
        line = f"{index}. {user_label(user)}"
        if total_chars + len(line) + 1 > max_chars:
            remaining = len(participants) - (index - 1)
            lines.append(f"… и ещё {remaining}")
            return "\n".join(lines)
        lines.append(line)
        total_chars += len(line) + 1

    if len(participants) > limit:
        lines.append(f"… и ещё {len(participants) - limit}")
    return "\n".join(lines)


def status_label(game: Game) -> str:
    return STATUS_LABELS.get(game.status, game.status)


def game_card(
    game: Game,
    chat_title: str,
    participants: list[tuple[object, User]],
) -> str:
    parts = [
        f"🎅 <b>Тайный Санта</b> — <b>{esc(chat_title)}</b>",
        f"Этап: <b>{status_label(game)}</b>",
        f"Участников: <b>{len(participants)}</b>",
        "",
    ]
    if participants:
        parts.append(participants_block(participants))
    else:
        parts.append("Пока никто не участвует.")
    return "\n".join(parts)


def announcement_text(
    game: Game,
    participants: list[tuple[object, User]],
) -> str:
    parts = [
        "🎅 <b>Тайный Санта</b>",
        f"Этап: <b>{status_label(game)}</b>",
        f"Участников: <b>{len(participants)}</b>",
        "",
    ]
    if participants:
        parts.append(participants_block(participants))
    else:
        parts.append("Пока никто не участвует. Нажмите кнопку ниже, чтобы присоединиться!")

    if game.status == GameStatus.RECRUITING:
        parts.extend(["", "Нажмите «Участвовать», чтобы вступить в игру."])
    return "\n".join(parts)


def games_list_text(games: list[tuple[Game, Chat, int]]) -> str:
    if not games:
        return (
            "🎅 <b>Тайный Санта</b>\n\n"
            "У вас нет групп с активной игрой.\n\n"
            "Добавьте меня в группу и попросите администратора создать игру "
            "командой /newgame."
        )

    lines = ["🎅 <b>Тайный Санта</b>", "", "Ваши активные игры:", ""]
    for game, chat, count in games[:MAX_GAMES_IN_LIST]:
        lines.append(
            f"• <b>{esc(chat.title)}</b> — {status_label(game)} ({count})"
        )
    if len(games) > MAX_GAMES_IN_LIST:
        lines.append(f"… и ещё {len(games) - MAX_GAMES_IN_LIST}")
    lines.extend(["", "Выберите группу, чтобы посмотреть участников."])
    return "\n".join(lines)


def assignment_text(receiver: User) -> str:
    parts = [
        "🎁 <b>Ваш получатель</b>",
        "",
        f"<b>{esc(receiver.full_name) or 'Без имени'}</b>",
    ]
    if receiver.username:
        parts.append(f"@{esc(receiver.username)}")
    parts.append("")
    if receiver.wishlist:
        parts.extend(["<b>Вишлист:</b>", esc(receiver.wishlist)])
    else:
        parts.append("Вишлист не заполнен.")
    parts.extend(["", "Никому не рассказывайте, кому вы дарите! 🎅"])
    return "\n".join(parts)


def game_started_text(participants: list[tuple[object, User]]) -> str:
    parts = [
        "🎅 <b>Игра началась!</b>",
        f"Участников: <b>{len(participants)}</b>",
        "",
        participants_block(participants),
        "",
        "Каждый участник получил имя своего получателя в личные сообщения.",
    ]
    return "\n".join(parts)


def wishlist_text(wishlist: str | None) -> str:
    if wishlist:
        return f"📝 <b>Ваш вишлист:</b>\n\n{esc(wishlist)}"
    return "📝 Вишлист пока не заполнен."


HELP_TEXT = (
    "🎅 <b>Тайный Санта</b>\n\n"
    "<b>В группе:</b>\n"
    "/newgame — создать игру (админ)\n"
    "/status — этап и участники\n"
    "/draw — провести жеребьёвку (админ)\n"
    "/resend — повторно отправить назначения (админ)\n"
    "/cancelgame — отменить набор (админ)\n"
    "/endgame — завершить игру (админ)\n\n"
    "<b>В личке:</b>\n"
    "/wishlist — заполнить вишлист\n"
    "/stats — ваши активные игры\n\n"
    "Чтобы участвовать, нажмите кнопку «Участвовать» в группе."
)
