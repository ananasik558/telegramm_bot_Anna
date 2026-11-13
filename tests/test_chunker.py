from __future__ import annotations

from bot.rag.chunker import normalize_text, split_text


def test_normalize_text_strips_spaces_and_blank_lines() -> None:
    raw = "  Привет,   мир!\u00a0 \n\n\nВторая строка.  \n"
    assert normalize_text(raw) == "Привет, мир!\n\nВторая строка."


def test_split_text_respects_limit_and_overlap() -> None:
    text = " ".join(f"Предложение номер {index} про умный поиск и каталог." for index in range(200))
    chunks = split_text(text, max_chars=400, overlap=80)
    assert len(chunks) > 3
    assert all(len(chunk) <= 480 for chunk in chunks), [len(chunk) for chunk in chunks]
    assert all(chunk.strip() for chunk in chunks)


def test_split_text_handles_short_text() -> None:
    assert split_text("Короткий текст про аудит.") == ["Короткий текст про аудит."]
    assert split_text("   ") == []


def test_split_text_hard_splits_long_sentence() -> None:
    long_sentence = "слово " * 600
    chunks = split_text(long_sentence, max_chars=300, overlap=40)
    assert chunks
    assert all(len(chunk) <= 340 for chunk in chunks)
