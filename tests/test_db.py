from __future__ import annotations

from bot.db import Database, NewChunk, TelegramUser


def test_user_lead_and_knowledge_flow(tmp_path) -> None:
    db = Database(tmp_path / "test.sqlite3")
    db.migrate()

    user = TelegramUser(id=1, username="ivan", first_name="Иван")
    assert db.upsert_user(user) is True
    assert db.upsert_user(user) is False
    assert db.stats()["users"] == 1

    lead_id = db.create_lead(1, name="Иван", site="example.ru", contact="@ivan")
    leads = db.list_leads()
    assert leads[0]["id"] == lead_id
    assert db.set_lead_status(lead_id, "in_progress") is True
    assert db.stats()["leads_new"] == 0

    db.replace_document(
        url="https://ensi.cloud/search",
        title="Search",
        content_hash="abc",
        chars=100,
        chunks=[NewChunk(text="Умный поиск по каталогу", embedding=[1.0, 0.0])],
        embedding_model="test-model",
    )
    assert db.document_hash("https://ensi.cloud/search") == "abc"
    assert db.document_has_vectors("https://ensi.cloud/search", "test-model") is True
    assert db.document_has_vectors("https://ensi.cloud/search", "other-model") is False

    chunks = db.fetch_chunks("test-model")
    assert len(chunks) == 1
    assert chunks[0].embedding == [1.0, 0.0]
    assert db.fetch_chunks("other-model")[0].embedding is None

    db.log_question(1, "Что такое Search?", "Ответ", ["https://ensi.cloud/search"], 0.9)
    db.log_question(1, "А сколько стоит?", "Ответ", [], 0.8)
    assert db.recent_questions(1) == ["А сколько стоит?", "Что такое Search?"]
    assert db.questions_count(1) == 2

    history = db.question_history(1, limit=1)
    assert len(history) == 1
    assert history[0]["question"] == "А сколько стоит?"
    assert db.question_history(1, limit=1, offset=1)[0]["question"] == "Что такое Search?"
    assert db.question_history(999) == []

    assert db.find_user_by_username("ivan") == 1
    assert db.find_user_by_username("@IVAN") == 1
    assert db.find_user_by_username("nobody") is None

    assert db.leads_count() == 1
    assert db.leads_count(user_id=1) == 1
    assert db.leads_count(user_id=2) == 0
    assert db.list_leads(user_id=1)[0]["id"] == lead_id
    assert db.list_leads(user_id=2) == []

    assert db.get_setting("missing") is None
    db.set_setting("staff_scopes", "[111, 222]")
    assert db.get_setting("staff_scopes") == "[111, 222]"
    db.set_setting("staff_scopes", "[]")
    assert db.get_setting("staff_scopes") == "[]"

    db.reset_knowledge()
    assert db.stats()["chunks"] == 0
    db.close()
