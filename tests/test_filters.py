from __future__ import annotations

import re

from bot.rag.filters import normalize_path_entry, path_patterns


def _matches(patterns: tuple[str, ...], path: str) -> bool:
    return any(re.search(pattern, path) for pattern in patterns)


def test_exact_path_blocks_page_and_children() -> None:
    patterns = path_patterns(["/contacts"])
    assert _matches(patterns, "/contacts")
    assert _matches(patterns, "/contacts/ivan")
    assert not _matches(patterns, "/contact")
    assert not _matches(patterns, "/contacts-old")


def test_wildcard_paths() -> None:
    patterns = path_patterns(["/resources/*"])
    assert _matches(patterns, "/resources/backlog")
    assert _matches(patterns, "/resources/faq/extra")
    assert not _matches(patterns, "/resources")
    assert not _matches(patterns, "/solutions/resources")


def test_full_url_is_reduced_to_path() -> None:
    assert normalize_path_entry("https://ensi.tech/price/?utm=1") == "/price"
    patterns = path_patterns(["https://ensi.tech/price/"])
    assert _matches(patterns, "/price")
    assert _matches(patterns, "/price/details")


def test_empty_and_duplicate_entries() -> None:
    assert path_patterns(["", "  ", "/"]) == (re.escape("/") + r"(?:/|$)",)
    patterns = path_patterns(["/price", "/price/", "/price"])
    assert len(patterns) == 1
