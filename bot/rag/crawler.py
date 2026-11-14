"""Краулер сайта: обходит страницы и превращает их в чистый текст."""

from __future__ import annotations

import asyncio
import logging
import re
from collections import deque
from dataclasses import dataclass, field
from typing import AsyncIterator, Iterable, Sequence
from urllib.parse import urldefrag, urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

USER_AGENT = "EnsiCloudRAGBot/0.1 (+https://ensi.cloud)"

EXCLUDE_PATH_PATTERNS = (
    r"/agreement/?$",
    r"/privacy-policy/?$",
    r"/rights/?$",
    r"/programming_languages/?$",
    r"/soglasie[^/]*/?$",
    r"/search-results/?$",
    r"/resources/logos/?$",
    r"/contacts/[^/]+/?$",
    r"/hraderlogo/?$",
)

_BINARY_EXTENSIONS = (
    ".pdf",
    ".zip",
    ".rar",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".mp4",
    ".mp3",
    ".ico",
)

# Строки интерфейса Tilda, которые не несут смысла для RAG.
_BOILERPLATE = (
    "нажимая на кнопку",
    "обязательное поле",
    "электронная почта содержит ошибку",
    "мы на связи",
    "все свежие новости",
    "продукт разработан при поддержке",
    "еще мы доступны",
    "выберите удобный слот",
    "возможность быстро и эффективно обсудить",
    "подпишитесь на новости",
    "редко и без спама",
    "закрыть",
)

# Короткие CTA-надписи: встречаются десятки раз и только засоряют контекст.
_CTA_LINES = frozenset(
    {
        "подробнее",
        "читать",
        "читать далее",
        "смотреть",
        "смотреть ещё",
        "смотреть еще",
        "оставить заявку",
        "заявка на демо",
        "запись на встречу",
        "записаться на встречу",
        "записаться на встречу с экспертом",
        "записаться самостоятельно →",
        "выбрать день и время",
        "выбрать слот",
        "получать",
        "подписаться",
        "отправить",
        "написать в телеграм",
        "написать в максе",
        "р.",
        "₽",
    }
)

_MIN_LINE = 2
_MIN_DUP_LINE = 12


@dataclass(slots=True)
class Page:
    url: str
    title: str
    text: str
    links: list[str] = field(default_factory=list)


def normalize_url(url: str) -> str | None:
    """Убирает якоря/query и приводит URL к каноничному виду.

    Tilda-сайты работают по HTTPS и не различают регистр пути, поэтому
    http-ссылки и варианты вроде /solutions/DIY не должны плодить дубликаты.
    """
    clean, _ = urldefrag(url.strip())
    parsed = urlparse(clean)
    if parsed.scheme not in ("http", "https"):
        return None
    if parsed.path.lower().endswith(_BINARY_EXTENSIONS):
        return None
    host = parsed.netloc.lower()
    path = (parsed.path or "/").lower()
    if path != "/":
        path = path.rstrip("/")
    return f"https://{host}{path}"


def _host(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _clean_title(soup: BeautifulSoup, url: str) -> str:
    if soup.title and soup.title.string:
        title = " ".join(soup.title.string.split())
        if title:
            return title[:200]
    heading = soup.find("h1")
    if heading:
        heading_text = " ".join(heading.get_text(" ", strip=True).split())
        if heading_text:
            return heading_text[:200]
    return url


def _clean_lines(raw_text: str) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for raw_line in raw_text.split("\n"):
        line = " ".join(raw_line.replace("\u00a0", " ").split())
        if len(line) < _MIN_LINE:
            continue
        lowered = line.lower()
        if lowered in _CTA_LINES:
            continue
        if any(boiler in lowered for boiler in _BOILERPLATE):
            continue
        if line in seen and len(line) >= _MIN_DUP_LINE:
            continue
        if len(line) >= _MIN_DUP_LINE:
            seen.add(line)
        lines.append(line)
    return "\n".join(lines)


def extract_page(html: str, url: str) -> Page:
    soup = BeautifulSoup(html, "html.parser")
    title = _clean_title(soup, url)

    links: list[str] = []
    seen_links: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        normalized = normalize_url(urljoin(url, anchor["href"]))
        if normalized and normalized not in seen_links:
            seen_links.add(normalized)
            links.append(normalized)

    for tag in soup(["script", "style", "noscript", "svg", "iframe", "form", "nav", "footer", "header"]):
        tag.decompose()

    text = _clean_lines(soup.get_text("\n"))
    return Page(url=url, title=title, text=text, links=links)


class SiteCrawler:
    def __init__(
        self,
        base_url: str,
        session: aiohttp.ClientSession,
        *,
        max_pages: int = 50,
        max_depth: int = 1,
        delay: float = 0.4,
        timeout: float = 30.0,
        respect_robots: bool = True,
        exclude_patterns: Sequence[str] = EXCLUDE_PATH_PATTERNS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._session = session
        self._max_pages = max_pages
        self._max_depth = max_depth
        self._delay = delay
        self._timeout = timeout
        self._respect_robots = respect_robots
        self._exclude = tuple(re.compile(pattern) for pattern in exclude_patterns)
        self._robots: list[str] = []
        self._robots_loaded = False

    def in_scope(self, url: str) -> bool:
        if _host(url) != _host(self.base_url):
            return False
        path = urlparse(url).path or "/"
        return not any(pattern.search(path) for pattern in self._exclude)

    async def _load_robots(self) -> None:
        if self._robots_loaded:
            return
        self._robots_loaded = True
        robots_url = f"{self.base_url}/robots.txt"
        try:
            async with self._session.get(robots_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    return
                body = await response.text()
        except (TimeoutError, aiohttp.ClientError):
            return

        active = False
        disallow: list[str] = []
        for line in body.splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            key, value = (part.strip() for part in line.split(":", 1))
            if key.lower() == "user-agent":
                active = value == "*"
            elif active and key.lower() == "disallow" and value:
                disallow.append(value)
        self._robots = disallow

    def _allowed(self, url: str) -> bool:
        if not self._respect_robots:
            return True
        path = urlparse(url).path or "/"
        for rule in self._robots:
            if path.startswith(rule):
                return False
        return True

    async def _fetch(self, url: str) -> tuple[str, str] | None:
        try:
            async with self._session.get(
                url,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=self._timeout),
                headers={"User-Agent": USER_AGENT, "Accept-Language": "ru,en;q=0.8"},
            ) as response:
                if response.status != 200:
                    logger.debug("Пропуск %s: HTTP %s", url, response.status)
                    return None
                content_type = response.headers.get("Content-Type", "")
                if "html" not in content_type.lower() and content_type:
                    logger.debug("Пропуск %s: не HTML (%s)", url, content_type)
                    return None
                body = await response.text(errors="replace")
                if len(body) > 3_000_000:
                    logger.warning("Пропуск %s: слишком большая страница", url)
                    return None
                final_url = normalize_url(str(response.url)) or url
                return final_url, body
        except (TimeoutError, aiohttp.ClientError) as error:
            logger.warning("Ошибка загрузки %s: %s", url, error)
            return None

    async def crawl(self, seeds: Iterable[str], *, follow_links: bool = True) -> AsyncIterator[Page]:
        await self._load_robots()
        queue: deque[tuple[str, int]] = deque()
        for seed in seeds:
            normalized = normalize_url(seed)
            if normalized and self.in_scope(normalized):
                queue.append((normalized, 0))

        seen: set[str] = set()
        fetched = 0

        while queue and fetched < self._max_pages:
            url, depth = queue.popleft()
            if url in seen:
                continue
            seen.add(url)
            if not self._allowed(url):
                logger.debug("robots.txt запрещает %s", url)
                continue

            html = await self._fetch(url)
            if self._delay:
                await asyncio.sleep(self._delay)
            if html is None:
                continue

            final_url, html_body = html
            if final_url in seen and final_url != url:
                continue
            if not self.in_scope(final_url):
                logger.debug("Пропуск %s: редирект вне сайта (%s)", url, final_url)
                continue
            seen.add(final_url)

            page = extract_page(html_body, final_url)
            fetched += 1
            yield page

            if follow_links and depth < self._max_depth:
                for link in page.links:
                    if link not in seen and self.in_scope(link):
                        queue.append((link, depth + 1))
