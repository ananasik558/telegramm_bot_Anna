from __future__ import annotations

from bot.rag.store import KnowledgeDoc, SearchIndex


def _docs() -> list[KnowledgeDoc]:
    return [
        KnowledgeDoc(
            id=1,
            url="https://ensi.cloud/search",
            title="Умный поиск Search",
            text="Облачный поиск по каталогу и контенту. Поиск помогает находить товары быстрее.",
        ),
        KnowledgeDoc(
            id=2,
            url="https://ensi.cloud/visual-search",
            title="Поиск по фото Visual Search",
            text="Поиск по фото: когда не нужно слов. Загрузите изображение товара.",
        ),
        KnowledgeDoc(
            id=3,
            url="https://ensi.cloud/express-audit",
            title="Экспресс-аудит поиска и каталога",
            text="Бесплатный аудит за 1 день. Изучаем поиск, карточки товаров и каталог.",
        ),
    ]


def test_lexical_search_finds_relevant_page() -> None:
    index = SearchIndex(_docs())
    hits = index.search("бесплатный аудит каталога", top_k=3)
    assert hits
    assert hits[0].doc.url.endswith("/express-audit")


def test_empty_index_returns_nothing() -> None:
    assert SearchIndex([]).search("что угодно") == []


def test_vector_search_works_without_lexical_overlap() -> None:
    docs = [
        KnowledgeDoc(id=1, url="https://a", title="A", text="альфа", vector=[1.0, 0.0]),
        KnowledgeDoc(id=2, url="https://b", title="B", text="бета", vector=[0.0, 1.0]),
    ]
    index = SearchIndex(docs)
    hits = index.search("совсем другой запрос", query_vector=[0.0, 1.0], top_k=2)
    assert hits
    assert hits[0].doc.id == 2


def test_vectors_are_normalized() -> None:
    docs = [KnowledgeDoc(id=1, url="https://a", title="A", text="альфа", vector=[10.0, 0.0])]
    hits = SearchIndex(docs).search("альфа", query_vector=[1.0, 0.0], top_k=1)
    assert hits[0].vector == 1.0
