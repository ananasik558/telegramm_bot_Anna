from __future__ import annotations

from bot.formatting import to_plain_text


def test_removes_urls_html_and_markdown() -> None:
    source = (
        "<b>PIM</b> — управление каталогом. "
        "Подробнее: https://ensi.tech/solutions/pim и www.ensi.tech. "
        "Телеграм: t.me/Greensight_telegram. "
        "Или напишите @Greensight_telegram. "
        "См. [документацию](https://docs.ensi.tech)."
    )
    result = to_plain_text(source)

    assert "PIM" in result
    assert "документацию" in result
    assert "http" not in result
    assert "www." not in result
    assert "t.me" not in result
    assert "@Greensight_telegram" not in result
    assert "ensi.tech" not in result
    assert "<b>" not in result


def test_does_not_break_email() -> None:
    result = to_plain_text("Пишите на mail@ensi.tech, сайт ensi.cloud")
    assert "mail@ensi.tech" in result
    assert "сайт" in result
    assert "ensi.cloud" not in result


def test_plain_text_stays_plain() -> None:
    assert to_plain_text("Обычный ответ без ссылок.") == "Обычный ответ без ссылок."
