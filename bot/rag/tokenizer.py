"""Токенизация и очень лёгкий стеммер для русского/английского.

Нужны для BM25-поиска, когда эмбеддинги отключены или недоступны.
Для продакшена лучше заменить на нормальный стеммер (pymorphy3) или
полностью положиться на векторный поиск.
"""

from __future__ import annotations

import re

_WORD_RE = re.compile(r"[a-zа-яё0-9]+")

STOP_WORDS = frozenset(
    """и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по
	только ее мне было вот от меня еще нет о из ему теперь когда даже ну вдруг ли если уже
	или ни быть был него до вас нибудь опять уж вам ведь там потом себя ничего ей может они
	тут где есть надо ней для мы тебя их чем была сам чтоб без будто чего раз тоже себе под
	будет ж тогда кто этот того потому этого какой совсем ним здесь этом один почти мой тем
	чтобы нее сейчас были куда зачем сказать всех никогда сегодня можно при наконец два об
	другой хоть после над больше тот через эти нас про всего них какая много разве три эту моя
	впрочем хорошо свою этой перед иногда лучше чуть том нельзя такой им более всегда конечно
	всю между the a an and or of to in for on with is are was were be been it this that these
	those as at by from we you they i he she not no do does did can could should would will
	just about into over under more most other than then there here""".split()
)

# Длинные окончания идут первыми, чтобы не отрезать лишнего.
_SUFFIXES: tuple[str, ...] = (
    "иями",
    "ями",
    "ами",
    "ыми",
    "ими",
    "ией",
    "иях",
    "ях",
    "ах",
    "ов",
    "ев",
    "ий",
    "ый",
    "ая",
    "ое",
    "ые",
    "ей",
    "ой",
    "ам",
    "ям",
    "ом",
    "ем",
    "ую",
    "юю",
    "ия",
    "ию",
    "ья",
    "ье",
    "ьи",
    "а",
    "я",
    "ы",
    "и",
    "е",
    "о",
    "у",
    "ю",
    "ь",
)

_MIN_STEM = 4

# Расширение запроса доменными синонимами: пользователи спрашивают «сколько стоит»,
# а на сайте написано «тарифы» и «стоимость».
_SYNONYMS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\b(цена|цены|цену|ценник|стоимость|стоимости|стоит|стоят|почём|почем|прайс)\b", re.I),
        " цена стоимость тариф ",
    ),
    (
        re.compile(r"\b(продукт|продукты|продуктов|решение|решения|решений|сервис|сервисы)\b", re.I),
        " продукт решение сервис ",
    ),
    (
        re.compile(r"\b(интеграция|интеграции|интегрировать|интегрируется)\b", re.I),
        " интеграция api ",
    ),
    (
        re.compile(r"\b(аудит|аудита|аудите)\b", re.I),
        " аудит экспресс-аудит ",
    ),
)


def expand_query(text: str) -> str:
    """Добавляет к запросу синонимы, чтобы BM25 находил нужные страницы."""
    expanded = text
    for pattern, replacement in _SYNONYMS:
        expanded = pattern.sub(replacement, expanded)
    return expanded


def stem(word: str) -> str:
    if len(word) < 6:
        return word
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= _MIN_STEM:
            return word[: -len(suffix)]
    return word


def tokenize(text: str) -> list[str]:
    """Возвращает значимые нормализованные токены."""
    tokens: list[str] = []
    for raw in _WORD_RE.findall(text.lower()):
        if len(raw) < 2 or raw in STOP_WORDS:
            continue
        tokens.append(stem(raw))
    return tokens
