"""BM25 — лексический поиск без внешних зависимостей."""

from __future__ import annotations

import math
from collections import Counter
from typing import Sequence

from .tokenizer import tokenize


class BM25:
    def __init__(self, documents: Sequence[str], k1: float = 1.5, b: float = 0.75) -> None:
        self._term_freqs: list[Counter[str]] = []
        self._lengths: list[int] = []
        self._doc_freq: Counter[str] = Counter()
        for document in documents:
            tokens = tokenize(document)
            term_freq = Counter(tokens)
            self._term_freqs.append(term_freq)
            self._lengths.append(len(tokens))
            self._doc_freq.update(term_freq.keys())
        self._total = len(self._term_freqs)
        self._avg_length = sum(self._lengths) / self._total if self._total else 0.0
        self._k1 = k1
        self._b = b

    def __len__(self) -> int:
        return self._total

    def scores(self, query_tokens: Sequence[str]) -> list[float]:
        if not self._total or not query_tokens:
            return [0.0] * self._total

        terms = list(dict.fromkeys(query_tokens))
        idf: dict[str, float] = {}
        for term in terms:
            df = self._doc_freq.get(term, 0)
            idf[term] = math.log(1 + (self._total - df + 0.5) / (df + 0.5))

        result = [0.0] * self._total
        for index, term_freq in enumerate(self._term_freqs):
            length = self._lengths[index] or 1
            score = 0.0
            for term in terms:
                freq = term_freq.get(term, 0)
                if not freq:
                    continue
                denominator = freq + self._k1 * (1 - self._b + self._b * length / self._avg_length)
                score += idf[term] * freq * (self._k1 + 1) / denominator
            result[index] = score
        return result
