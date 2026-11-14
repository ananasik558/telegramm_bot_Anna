"""CLI: собирает сайты Ensi (ensi.cloud и ensi.tech) в базу знаний RAG.

Пример:
    python -m bot.rag.ingest
    python -m bot.rag.ingest --reset --max-pages 150
    python -m bot.rag.ingest --sites https://ensi.tech --max-pages 20
    python -m bot.rag.ingest --dry-run --max-pages 5
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import aiohttp

from ..config import DEFAULT_SEED_PATHS, Settings
from ..db import Database, NewChunk
from ..llm import EmbeddingClient
from .chunker import split_text
from .crawler import EXCLUDE_PATH_PATTERNS, USER_AGENT, SiteCrawler, normalize_url

logger = logging.getLogger(__name__)


async def load_sitemap(session: aiohttp.ClientSession, base_url: str) -> list[str]:
    """Читает sitemap.xml (включая sitemapindex) и возвращает список URL."""
    url = f"{base_url.rstrip('/')}/sitemap.xml"
    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=20),
            headers={"User-Agent": USER_AGENT},
        ) as response:
            if response.status != 200:
                logger.info("%s: sitemap.xml недоступен (HTTP %s)", base_url, response.status)
                return []
            body = await response.text(errors="replace")
    except (TimeoutError, aiohttp.ClientError) as error:
        logger.info("%s: sitemap.xml не прочитан: %s", base_url, error)
        return []

    locations = [loc.strip() for loc in re.findall(r"<loc>\s*(.*?)\s*</loc>", body, re.S | re.I)]
    if "<sitemapindex" in body.lower():
        result: list[str] = []
        for location in locations[:10]:
            try:
                async with session.get(
                    location,
                    timeout=aiohttp.ClientTimeout(total=20),
                    headers={"User-Agent": USER_AGENT},
                ) as response:
                    if response.status != 200:
                        continue
                    nested = await response.text(errors="replace")
                result.extend(loc.strip() for loc in re.findall(r"<loc>\s*(.*?)\s*</loc>", nested, re.S | re.I))
            except (TimeoutError, aiohttp.ClientError):
                continue
        return result
    return locations


def _filter_seeds(urls: list[str], patterns: tuple[str, ...]) -> list[str]:
    compiled = [re.compile(pattern) for pattern in patterns]
    result: list[str] = []
    seen: set[str] = set()
    for url in urls:
        normalized = normalize_url(url)
        if not normalized or normalized in seen:
            continue
        path = normalized.split("://", 1)[-1].split("/", 1)[-1]
        if any(pattern.search(f"/{path}") for pattern in compiled):
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _default_seeds(site: str, primary_site: str) -> list[str]:
    """Для основного сайта — известные разделы, для остальных — главная + sitemap."""
    site = site.rstrip("/")
    if site == primary_site.rstrip("/"):
        return [f"{site}{path}" for path in DEFAULT_SEED_PATHS]
    return [f"{site}/"]


async def ingest(args: argparse.Namespace, settings: Settings) -> int:
    db = Database(args.db or settings.db_path)
    db.migrate()

    # SEED_URLS/--urls полностью управляют списком страниц и сайтов.
    custom_seeds = [url for url in (normalize_url(raw) for raw in (args.urls or settings.custom_seeds)) if url]
    if custom_seeds:
        sites = list(dict.fromkeys(_origin(url) for url in custom_seeds))
        seeds_by_site: dict[str, list[str]] = {site: [] for site in sites}
        for url in custom_seeds:
            seeds_by_site[_origin(url)].append(url)
    else:
        sites = [site.rstrip("/") for site in (args.sites or settings.knowledge_sites)]
        seeds_by_site = {site: _default_seeds(site, settings.site_base_url) for site in sites}

    async with aiohttp.ClientSession() as session:
        if args.reset:
            db.reset_knowledge()
            print("База знаний очищена.")

        embedder = EmbeddingClient(session, settings)
        embeddings_off = args.no_embeddings or not embedder.enabled
        if embeddings_off:
            print("Эмбеддинги выключены — будет только лексический поиск (BM25).")

        counter: Counter[str] = Counter()
        total_chunks = 0
        vectors_used = False
        remaining = args.max_pages

        print(f"Источники: {', '.join(sites)}. Лимит: {remaining} страниц.\n")

        for site in sites:
            if remaining <= 0:
                print(f"Достигнут лимит страниц — {site} пропущен.")
                break

            seeds = list(seeds_by_site.get(site, []))
            if not args.no_sitemap and not custom_seeds:
                sitemap_urls = await load_sitemap(session, site)
                if sitemap_urls:
                    logger.info("%s: sitemap.xml — %s URL", site, len(sitemap_urls))
                    seeds.extend(sitemap_urls)
            seeds = _filter_seeds(seeds, EXCLUDE_PATH_PATTERNS)
            if not seeds:
                print(f"\n{site}: нет страниц для обхода, пропуск.")
                continue

            counter["sites"] += 1
            print(f"\n=== {site}: {len(seeds)} стартовых URL, осталось страниц: {remaining} ===")
            crawler = SiteCrawler(
                site,
                session,
                max_pages=remaining,
                max_depth=args.max_depth,
                delay=args.delay,
            )

            async for page in crawler.crawl(seeds):
                remaining -= 1
                counter["pages"] += 1
                chunks = split_text(page.text, args.max_chars, args.overlap)
                if not chunks:
                    counter["empty"] += 1
                    print(f"  · {page.url} — пусто, пропуск")
                    continue

                digest = hashlib.sha256(page.text.encode("utf-8")).hexdigest()
                unchanged = db.document_hash(page.url) == digest
                has_vectors = embeddings_off or db.document_has_vectors(page.url, settings.embedding_model)
                if not args.force and not args.dry_run and unchanged and has_vectors:
                    counter["unchanged"] += 1
                    print(f"  = {page.url} — без изменений ({len(chunks)} чанков)")
                    continue

                if args.dry_run:
                    counter["saved"] += 1
                    total_chunks += len(chunks)
                    print(f"  + {page.url} — {len(chunks)} чанков (dry-run)")
                    continue

                embeddings: list[list[float]] | None = None
                if not embeddings_off:
                    try:
                        embeddings = await embedder.embed_many(chunks, batch_size=args.batch_size)
                        vectors_used = True
                    except Exception as error:
                        logger.warning("Эмбеддинги не удались, дальше без них: %s", error)
                        print(f"  ! Эмбеддинги недоступны ({error}); продолжаю без векторов.")
                        embeddings_off = True
                        embeddings = None

                saved = db.replace_document(
                    url=page.url,
                    title=page.title,
                    content_hash=digest,
                    chars=len(page.text),
                    chunks=[
                        NewChunk(text=chunk, embedding=embeddings[index] if embeddings else None)
                        for index, chunk in enumerate(chunks)
                    ],
                    embedding_model=settings.embedding_model,
                )
                counter["saved"] += 1
                total_chunks += saved
                mark = "векторы" if embeddings else "BM25"
                print(f"  + {page.url} — {saved} чанков, {mark}")

        if not args.dry_run:
            stats = db.stats()
            print(
                "\nГотово."
                f"\n  источников: {counter['sites']}"
                f"\n  страниц обработано: {counter['pages']}"
                f"\n  сохранено: {counter['saved']}, без изменений: {counter['unchanged']}, пустых: {counter['empty']}"
                f"\n  чанков в базе: {stats['chunks']} (добавлено сейчас: {total_chunks})"
                f"\n  документов в базе: {stats['documents']}"
                f"\n  эмбеддинги: {'да' if vectors_used else 'нет'}"
                "\n\nПерезапустите бота, чтобы он перечитал базу знаний."
            )
        else:
            print(f"\nDry-run: {counter['pages']} страниц, {total_chunks} чанков.")
        db.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m bot.rag.ingest",
        description="Собирает сайты Ensi в локальную базу знаний для RAG-бота.",
    )
    parser.add_argument("--urls", nargs="*", help="Стартовые URL; заменяют сайты, seed'ы и sitemap.")
    parser.add_argument("--sites", nargs="*", help="Сайты-источники, например https://ensi.cloud https://ensi.tech.")
    parser.add_argument("--max-pages", type=int, default=150, help="Максимум страниц за один запуск.")
    parser.add_argument("--max-depth", type=int, default=1, help="Глубина обхода ссылок от стартовых страниц.")
    parser.add_argument("--max-chars", type=int, default=1200, help="Максимальная длина чанка.")
    parser.add_argument("--overlap", type=int, default=150, help="Перекрытие чанков, символов.")
    parser.add_argument("--delay", type=float, default=0.4, help="Пауза между запросами, секунд.")
    parser.add_argument("--batch-size", type=int, default=64, help="Размер пачки для эмбеддингов.")
    parser.add_argument("--db", type=Path, default=None, help="Путь к SQLite (по умолчанию из настроек).")
    parser.add_argument("--reset", action="store_true", help="Очистить базу знаний перед загрузкой.")
    parser.add_argument("--force", action="store_true", help="Переиндексировать даже неизменившиеся страницы.")
    parser.add_argument("--no-embeddings", action="store_true", help="Не считать эмбеддинги (только BM25).")
    parser.add_argument("--no-sitemap", action="store_true", help="Не читать sitemap.xml.")
    parser.add_argument("--dry-run", action="store_true", help="Только показать, что будет собрано.")
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args()
    settings = Settings()
    raise SystemExit(asyncio.run(ingest(args, settings)))


if __name__ == "__main__":
    main()
