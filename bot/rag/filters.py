"""Фильтры путей для инжеста: блок-лист из настроек и CLI.

Примеры записей:
    /contacts           — страница и всё, что ниже (/contacts/ivan)
    /resources/*        — wildcard-шаблон
    https://ensi.tech/price  — полный URL (учитывается только путь)
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterable
from urllib.parse import urlparse


def normalize_path_entry(raw: str) -> str:
    entry = raw.strip().strip(",;").strip()
    if not entry:
        return ""
    if "://" in entry:
        entry = urlparse(entry).path or "/"
    else:
        entry = entry.split("?", 1)[0].split("#", 1)[0]
    if not entry.startswith("/"):
        entry = f"/{entry}"
    return entry.rstrip("/").lower() or "/"


def path_patterns(entries: Iterable[str]) -> tuple[str, ...]:
    """Превращает пути блок-листа в регулярные выражения для краулера."""
    patterns: list[str] = []
    for raw in entries:
        path = normalize_path_entry(raw)
        if not path:
            continue
        if "*" in path:
            pattern = fnmatch.translate(path)
        else:
            pattern = re.escape(path) + r"(?:/|$)"
        if pattern not in patterns:
            patterns.append(pattern)
    return tuple(patterns)
