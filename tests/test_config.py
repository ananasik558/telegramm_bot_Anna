from __future__ import annotations

from bot.config import Settings


def _settings(**kwargs) -> Settings:
    """Настройки без чтения реального .env — тесты не зависят от машины."""
    return Settings(_env_file=None, **kwargs)


def test_default_knowledge_sites() -> None:
    settings = _settings()
    sites = settings.knowledge_sites
    assert sites[0] == "https://ensi.cloud"
    assert "https://ensi.tech" in sites
    assert len(sites) == len(set(sites))


def test_extra_sites_are_normalized_and_deduplicated() -> None:
    settings = _settings(
        site_base_url="https://ensi.cloud/",
        extra_sites="ensi.tech, https://example.com/, https://ensi.cloud",
    )
    assert settings.knowledge_sites == [
        "https://ensi.cloud",
        "https://ensi.tech",
        "https://example.com",
    ]


def test_extra_sites_with_path_query_and_fragment_become_origins() -> None:
    settings = _settings(
        extra_sites="https://docs.ensi.tech/?utm=1#top, ensi.tech/price, https://greensight.ru",
    )
    assert settings.knowledge_sites == [
        "https://ensi.cloud",
        "https://docs.ensi.tech",
        "https://ensi.tech",
        "https://greensight.ru",
    ]


def test_extra_sites_can_be_disabled() -> None:
    settings = _settings(extra_sites="")
    assert settings.knowledge_sites == ["https://ensi.cloud"]


def test_custom_seeds_parsing() -> None:
    settings = _settings(seed_urls="https://ensi.tech/solutions, https://ensi.tech/price")
    assert settings.custom_seeds == [
        "https://ensi.tech/solutions",
        "https://ensi.tech/price",
    ]
    assert _settings(seed_urls="  ").custom_seeds == []


def test_blocked_paths_parsing() -> None:
    settings = _settings(blocked_paths="/contacts, /resources/*;https://ensi.tech/price")
    assert settings.blocked_path_list == [
        "/contacts",
        "/resources/*",
        "https://ensi.tech/price",
    ]
    assert _settings(blocked_paths="").blocked_path_list == []


def test_ingest_max_pages() -> None:
    assert _settings().ingest_max_pages == 200
    assert _settings(ingest_max_pages=300).ingest_max_pages == 300
