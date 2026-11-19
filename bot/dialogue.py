"""Короткая память диалога (последние N пар вопрос-ответ).

Хранится в памяти процесса: при рестарте история теряется. Для продакшена
можно положить в Redis или в SQLite.
"""

from __future__ import annotations

from collections import defaultdict, deque


class DialogueHistory:
    def __init__(self, max_turns: int = 6) -> None:
        self._max_turns = max(1, max_turns)
        self._store: dict[str | int, deque[tuple[str, str]]] = defaultdict(lambda: deque(maxlen=self._max_turns))

    def get(self, user_id: str | int) -> list[tuple[str, str]]:
        return list(self._store[user_id])

    def add(self, user_id: str | int, question: str, answer: str) -> None:
        self._store[user_id].append((question, answer))

    def clear(self, user_id: str | int) -> None:
        self._store.pop(user_id, None)
