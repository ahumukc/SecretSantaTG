"""Жеребьёвка: алгоритм Саттоло — одна случайная цепочка без самоподарков."""

from __future__ import annotations

import random


def build_assignments(user_ids: list[int]) -> dict[int, int]:
    """Возвращает {дарящий: получатель}.

    Алгоритм Саттоло даёт перестановку из одного цикла, поэтому:
    - никто не дарит сам себе;
    - каждый получает ровно одного подарка;
    - все участники связаны в одну цепочку.
    """
    if len(user_ids) < 3:
        raise ValueError("Для жеребьёвки нужно минимум 3 участника")

    order = list(user_ids)
    rng = random.SystemRandom()
    for index in range(len(order) - 1, 0, -1):
        swap_with = rng.randrange(index)
        order[index], order[swap_with] = order[swap_with], order[index]

    return {
        order[index]: order[(index + 1) % len(order)]
        for index in range(len(order))
    }
