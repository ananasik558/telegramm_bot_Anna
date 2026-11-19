from __future__ import annotations

from bot.rag.ingest import build_parser


def test_page_option_collects_multiple_urls() -> None:
    args = build_parser().parse_args(["--page", "https://ensi.tech/solutions/pim", "https://ensi.tech/price"])
    assert args.page == [
        "https://ensi.tech/solutions/pim",
        "https://ensi.tech/price",
    ]
    assert args.urls is None


def test_page_option_can_be_repeated() -> None:
    args = build_parser().parse_args(["--page", "https://ensi.tech/price", "--page", "https://ensi.cloud/tariffs"])
    assert args.page == [
        "https://ensi.tech/price",
        "https://ensi.cloud/tariffs",
    ]


def test_page_option_absent_by_default() -> None:
    assert build_parser().parse_args([]).page is None
