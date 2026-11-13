"""Гибридный индекс: BM25 + косинус по эмбеддингам, объединение через RRF."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from .bm25 import BM25
from .tokenizer import expand_query, tokenize

RRF_K = 60


@dataclass(slots=True)
class KnowledgeDoc:
    id: int
    url: str
    title: str
    text: str
    vector: list[float] | None = None


@dataclass(slots=True)
class Hit:
    doc: KnowledgeDoc
    score: float
    lexical: float
    vector: float | None


def _normalize(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return list(vector)
    return [value / norm for value in vector]


class SearchIndex:
    """Индекс в памяти. Для нескольких тысяч чанков этого достаточно;
    при росте стоит перейти на pgvector/FAISS/Qdrant."""

    def __init__(self, docs: Sequence[KnowledgeDoc]) -> None:
        self.docs: list[KnowledgeDoc] = list(docs)
        self._bm25 = BM25([f"{doc.title}\n{doc.text}" for doc in self.docs])
        self._vectors: list[list[float] | None] = [_normalize(doc.vector) if doc.vector else None for doc in self.docs]

    def __len__(self) -> int:
        return len(self.docs)

    @property
    def vector_count(self) -> int:
        return sum(1 for vector in self._vectors if vector is not None)

    def search(
        self,
        query: str,
        *,
        query_vector: Sequence[float] | None = None,
        top_k: int = 5,
        min_score: float = 0.15,
    ) -> list[Hit]:
        if not self.docs:
            return []

        query_tokens = tokenize(expand_query(query))
        lexical = self._bm25.scores(query_tokens) if query_tokens else [0.0] * len(self.docs)
        lexical_order = sorted(range(len(self.docs)), key=lambda index: lexical[index], reverse=True)[: top_k * 4]

        vector_scores: list[float | None] = [None] * len(self.docs)
        vector_order: list[int] = []
        if query_vector:
            normalized_query = _normalize(query_vector)
            scored: list[tuple[int, float]] = []
            for index, vector in enumerate(self._vectors):
                if vector is None:
                    continue
                similarity = sum(a * b for a, b in zip(normalized_query, vector, strict=False))
                vector_scores[index] = similarity
                scored.append((index, similarity))
            scored.sort(key=lambda item: item[1], reverse=True)
            vector_order = [index for index, _ in scored[: top_k * 4]]

        # Reciprocal Rank Fusion — устойчивее простого сложения скоров.
        fused: dict[int, float] = {}
        for rank, index in enumerate(lexical_order):
            if lexical[index] <= 0 and index not in vector_order:
                continue
            fused[index] = fused.get(index, 0.0) + 1.0 / (RRF_K + rank + 1)
        for rank, index in enumerate(vector_order):
            fused[index] = fused.get(index, 0.0) + 1.0 / (RRF_K + rank + 1)

        hits: list[Hit] = []
        for index, fused_score in fused.items():
            lexical_score = lexical[index]
            vector_score = vector_scores[index]
            if lexical_score <= 0 and (vector_score is None or vector_score < min_score):
                continue
            hits.append(
                Hit(
                    doc=self.docs[index],
                    score=fused_score,
                    lexical=lexical_score,
                    vector=vector_score,
                )
            )

        hits.sort(key=lambda hit: hit.score, reverse=True)
        if hits:
            best = hits[0].score
            for hit in hits:
                hit.score = hit.score / best if best else 0.0
        return hits[:top_k]
