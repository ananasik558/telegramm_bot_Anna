from __future__ import annotations

from bot.rag.crawler import normalize_url


def test_url_is_canonicalized() -> None:
    assert normalize_url("http://ensi.tech/") == "https://ensi.tech/"
    assert normalize_url("https://ENSI.tech/solutions/DIY/") == "https://ensi.tech/solutions/diy"
    assert normalize_url("https://ensi.tech/page?utm_source=x#top") == "https://ensi.tech/page"


def test_binary_links_are_skipped() -> None:
    assert normalize_url("https://ensi.tech/files/price.pdf") is None
    assert normalize_url("https://ensi.tech/logo.svg") is None
    assert normalize_url("mailto:mail@ensi.tech") is None
    assert normalize_url("tel:+74993916669") is None
