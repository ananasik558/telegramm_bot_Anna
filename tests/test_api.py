from __future__ import annotations

import asyncio

from aiohttp.test_utils import TestClient, TestServer

from bot.api import create_app
from bot.config import Settings
from bot.services.web_chat import WebAnswer


class FakeService:
    documents = 12
    vectors = 3
    llm_enabled = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def ask(self, question: str, session_id: str | None = None) -> WebAnswer:
        self.calls.append((question, session_id))
        return WebAnswer(
            answer="PIM — управление товарами.",
            session_id=session_id or "generated-session",
            degraded=False,
            used_context=True,
        )


def _settings(**kwargs) -> Settings:
    values = {
        "api_enabled": True,
        "api_token": "",
        "api_cors_origins": "*",
        "api_rate_limit_per_minute": 0,
    }
    values.update(kwargs)
    return Settings(_env_file=None, **values)


def test_chat_endpoint_returns_plain_answer_and_cors() -> None:
    async def scenario() -> None:
        app = create_app(FakeService(), _settings())
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            response = await client.post("/api/chat", json={"question": "Что такое PIM?"})
            assert response.status == 200
            data = await response.json()
            assert data["ok"] is True
            assert data["answer"] == "PIM — управление товарами."
            assert data["used_context"] is True
            assert "sources" not in data
            assert response.headers["Access-Control-Allow-Origin"] == "*"

            health = await client.get("/health")
            assert health.status == 200
            health_data = await health.json()
            assert health_data["documents"] == 12
        finally:
            await client.close()

    asyncio.run(scenario())


def test_chat_endpoint_validates_question() -> None:
    async def scenario() -> None:
        app = create_app(FakeService(), _settings())
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            empty = await client.post("/api/chat", json={"question": "  "})
            assert empty.status == 400
            missing = await client.post("/api/chat", json={})
            assert missing.status == 400
            long = await client.post("/api/chat", json={"question": "x" * 600})
            assert long.status == 400
        finally:
            await client.close()

    asyncio.run(scenario())


def test_token_auth() -> None:
    async def scenario() -> None:
        app = create_app(FakeService(), _settings(api_token="secret"))
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            unauthorized = await client.post("/api/chat", json={"question": "PIM?"})
            assert unauthorized.status == 401

            authorized = await client.post(
                "/api/chat",
                json={"question": "PIM?"},
                headers={"X-API-Key": "secret"},
            )
            assert authorized.status == 200

            bearer = await client.post(
                "/api/chat",
                json={"question": "PIM?"},
                headers={"Authorization": "Bearer secret"},
            )
            assert bearer.status == 200
        finally:
            await client.close()

    asyncio.run(scenario())


def test_cors_preflight() -> None:
    async def scenario() -> None:
        app = create_app(FakeService(), _settings(api_cors_origins="https://ensi.cloud"))
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            response = await client.options(
                "/api/chat",
                headers={
                    "Origin": "https://ensi.cloud",
                    "Access-Control-Request-Method": "POST",
                },
            )
            assert response.status == 204
            assert response.headers["Access-Control-Allow-Origin"] == "https://ensi.cloud"
        finally:
            await client.close()

    asyncio.run(scenario())


def test_rate_limit() -> None:
    async def scenario() -> None:
        app = create_app(FakeService(), _settings(api_rate_limit_per_minute=1))
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            first = await client.post("/api/chat", json={"question": "PIM?"})
            assert first.status == 200
            second = await client.post("/api/chat", json={"question": "PIM?"})
            assert second.status == 429
            assert second.headers["Retry-After"] == "60"
        finally:
            await client.close()

    asyncio.run(scenario())
