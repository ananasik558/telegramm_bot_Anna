from __future__ import annotations

from bot.config import Settings


def test_default_knowledge_sites() -> None:
    settings = Settings()
    sites = settings.knowledge_sites
    assert sites[0] == "https://ensi.cloud"
    assert "https://ensi.tech" in sites
    assert len(sites) == len(set(sites))


def test_extra_sites_are_normalized_and_deduplicated() -> None:
    settings = Settings(
        site_base_url="https://ensi.cloud/",
        extra_sites="ensi.tech, https://example.com/, https://ensi.cloud",
    )
    assert settings.knowledge_sites == [
        "https://ensi.cloud",
        "https://ensi.tech",
        "https://example.com",
    ]


def test_extra_sites_can_be_disabled() -> None:
    settings = Settings(extra_sites="")
    assert settings.knowledge_sites == ["https://ensi.cloud"]


def test_custom_seeds_parsing() -> None:
    settings = Settings(seed_urls="https://ensi.tech/solutions, https://ensi.tech/price")
    assert settings.custom_seeds == [
        "https://ensi.tech/solutions",
        "https://ensi.tech/price",
    ]
    assert Settings(seed_urls="  ").custom_seeds == []
