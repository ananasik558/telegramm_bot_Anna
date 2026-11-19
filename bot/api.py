"""HTTP API для чата на сайте компании.

Запускается в одном процессе с Telegram-ботом:
    POST /api/chat   {"question": "...", "session_id": "optional"}
    GET  /health

Ответ содержит только текст (без источников и ссылок).
"""

from __future__ import annotations

import hmac
import logging
import time
from collections import defaultdict, deque
from typing import Any

from aiohttp import web

from .config import Settings
from .services.web_chat import WebChatService

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 64 * 1024

SETTINGS_KEY: web.AppKey[Settings] = web.AppKey("settings", Settings)
SERVICE_KEY: web.AppKey[WebChatService] = web.AppKey("service", WebChatService)
RATE_BUCKETS_KEY: web.AppKey[dict[str, deque[float]]] = web.AppKey("rate_buckets", dict)


def _error(status: int, message: str) -> web.Response:
    return web.json_response({"ok": False, "error": message}, status=status)


def _provided_token(request: web.Request) -> str:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.headers.get("X-API-Key", "").strip()


@web.middleware
async def cors_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
    settings: Settings = request.app[SETTINGS_KEY]
    origin = request.headers.get("Origin")
    allowed = settings.api_cors_list
    allow_origin = "*" if "*" in allowed else (origin if origin in allowed else None)

    if request.method == "OPTIONS":
        response: web.StreamResponse = web.Response(status=204)
    else:
        try:
            response = await handler(request)
        except web.HTTPException as error:
            response = error

    if allow_origin:
        response.headers["Access-Control-Allow-Origin"] = allow_origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-API-Key"
        response.headers["Access-Control-Max-Age"] = "600"
    return response


@web.middleware
async def auth_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
    if request.method == "OPTIONS" or request.path == "/health":
        return await handler(request)

    token = request.app[SETTINGS_KEY].api_token.strip()
    if token and not hmac.compare_digest(_provided_token(request).encode(), token.encode()):
        return _error(401, "unauthorized")
    return await handler(request)


@web.middleware
async def rate_limit_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
    if request.method == "OPTIONS" or request.path == "/health":
        return await handler(request)

    settings: Settings = request.app[SETTINGS_KEY]
    limit = settings.api_rate_limit_per_minute
    if limit <= 0:
        return await handler(request)

    forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    client = forwarded or request.remote or "unknown"
    now = time.monotonic()
    bucket: deque[float] = request.app[RATE_BUCKETS_KEY][client]
    while bucket and now - bucket[0] >= 60:
        bucket.popleft()
    if len(bucket) >= limit:
        response = _error(429, "too many requests")
        response.headers["Retry-After"] = "60"
        return response
    bucket.append(now)
    return await handler(request)


async def handle_health(request: web.Request) -> web.Response:
    service: WebChatService = request.app[SERVICE_KEY]
    return web.json_response(
        {
            "status": "ok",
            "documents": service.documents,
            "vectors": service.vectors,
            "llm": service.llm_enabled,
        }
    )


async def handle_chat(request: web.Request) -> web.Response:
    service: WebChatService = request.app[SERVICE_KEY]
    settings: Settings = request.app[SETTINGS_KEY]

    try:
        payload = await request.json()
    except (ValueError, TypeError):
        return _error(400, "invalid json")

    if not isinstance(payload, dict):
        return _error(400, "json object expected")

    question = payload.get("question")
    if not isinstance(question, str) or not question.strip():
        return _error(400, "question is required")
    question = " ".join(question.split())
    if len(question) < 2:
        return _error(400, "question is too short")
    if len(question) > settings.api_max_question_chars:
        return _error(400, f"question is too long (max {settings.api_max_question_chars})")

    session_id = payload.get("session_id")
    if session_id is not None and not isinstance(session_id, str):
        return _error(400, "session_id must be a string")

    try:
        result = await service.ask(question, session_id)
    except Exception:
        logger.exception("Ошибка обработки запроса к чату на сайте")
        return _error(500, "internal error")

    response = web.json_response(
        {
            "ok": True,
            "answer": result.answer,
            "session_id": result.session_id,
            "degraded": result.degraded,
            "used_context": result.used_context,
        }
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def create_app(service: WebChatService, settings: Settings) -> web.Application:
    app = web.Application(
        middlewares=[cors_middleware, rate_limit_middleware, auth_middleware],
        client_max_size=MAX_BODY_BYTES,
    )
    app[SERVICE_KEY] = service
    app[SETTINGS_KEY] = settings
    app[RATE_BUCKETS_KEY] = defaultdict(deque)
    app.router.add_get("/health", handle_health)
    app.router.add_post("/api/chat", handle_chat)
    return app


async def start_api(service: WebChatService, settings: Settings) -> web.AppRunner:
    app = create_app(service, settings)
    runner = web.AppRunner(app, access_log=logger)
    await runner.setup()
    site = web.TCPSite(runner, settings.api_host, settings.api_port)
    await site.start()
    return runner
