"""Нарезка текста страницы на чанки для RAG."""

from __future__ import annotations

import re

_WS_RE = re.compile(r"[ \t\u00a0]+")
_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+")
_MAX_SENTENCE = 400
_MIN_CHUNK = 60


def normalize_text(text: str) -> str:
    lines: list[str] = []
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = _WS_RE.sub(" ", raw_line).strip()
        if line:
            lines.append(line)
        elif lines and lines[-1] != "":
            lines.append("")
    return "\n".join(lines).strip()


def _hard_split(text: str, limit: int) -> list[str]:
    parts: list[str] = []
    while len(text) > limit:
        cut = text.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        parts.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        parts.append(text)
    return parts


def _units(text: str) -> list[str]:
    """Разбивает текст на предложения/короткие блоки, сохраняя границы абзацев."""
    units: list[str] = []
    for paragraph in re.split(r"\n+", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        for sentence in _SENTENCE_RE.split(paragraph):
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(sentence) <= _MAX_SENTENCE:
                units.append(sentence)
            else:
                units.extend(_hard_split(sentence, _MAX_SENTENCE))
    return units


def _tail(text: str, overlap: int) -> str:
    if overlap <= 0 or not text:
        return ""
    tail = text[-overlap:]
    space = tail.find(" ")
    if space != -1:
        tail = tail[space + 1 :]
    return tail.strip()


def split_text(text: str, max_chars: int = 1200, overlap: int = 150) -> list[str]:
    """Режет текст на чанки не длиннее max_chars с перекрытием overlap."""
    if max_chars <= 0:
        raise ValueError("max_chars должен быть больше нуля")
    if overlap >= max_chars:
        overlap = max_chars // 4

    units = _units(normalize_text(text))
    # Единица не должна быть длиннее чанка, иначе чанк выйдет за лимит.
    normalized_units: list[str] = []
    for unit in units:
        if len(unit) > max_chars:
            normalized_units.extend(_hard_split(unit, max_chars))
        else:
            normalized_units.append(unit)

    chunks: list[str] = []
    current = ""

    for unit in normalized_units:
        candidate = f"{current} {unit}".strip() if current else unit
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        tail = _tail(current, overlap)
        if tail and len(tail) + len(unit) + 1 <= max_chars:
            current = f"{tail} {unit}".strip()
        else:
            current = unit
    if current:
        chunks.append(current)

    # Склеиваем слишком короткие огрызки с предыдущим чанком.
    result: list[str] = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        if len(chunk) < _MIN_CHUNK and result:
            merged = f"{result[-1]} {chunk}"
            if len(merged) <= max_chars + overlap:
                result[-1] = merged
                continue
        result.append(chunk)
    return result
