import pytest

from bot.services.draw import build_assignments


def test_assignments_are_derangement() -> None:
    for size in range(3, 30):
        user_ids = list(range(size))
        mapping = build_assignments(user_ids)

        assert set(mapping) == set(user_ids)
        assert set(mapping.values()) == set(user_ids)
        assert all(giver != receiver for giver, receiver in mapping.items())


def test_assignments_form_single_cycle() -> None:
    user_ids = list(range(10))
    mapping = build_assignments(user_ids)

    visited: list[int] = []
    current = user_ids[0]
    while current not in visited:
        visited.append(current)
        current = mapping[current]

    assert current == user_ids[0]
    assert len(visited) == len(user_ids)


def test_too_few_participants() -> None:
    with pytest.raises(ValueError):
        build_assignments([1, 2])
