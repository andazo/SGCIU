"""Bound HTTP input and abuse across all Cloud Run instances without storing PII."""

from __future__ import annotations

import hashlib
import json
import logging
import time

import anyio
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import get_settings
from app.db import SessionLocal
from app.models import SecurityRequestBucket

MAX_BODY_BYTES = 65_536
logger = logging.getLogger(__name__)


class QuotaExceeded(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after


def consume_quotas(limits: list[tuple[str, int, int]], now: int | None = None):
    """Atomic UPSERTs serialize each bucket in PostgreSQL, including concurrent instances."""
    now = int(time.time()) if now is None else now
    with SessionLocal() as db:
        insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
        # Sorted keys avoid deadlocks when requests share several buckets.
        entries = []
        for name, limit, seconds in limits:
            end = (now // seconds + 1) * seconds
            key = hashlib.sha256(f"{name}:{now // seconds}".encode()).hexdigest()
            entries.append((key, limit, end))
        for key, limit, end in sorted(entries):
            stmt = insert(SecurityRequestBucket).values(key=key, count=1, expires_at=end)
            stmt = stmt.on_conflict_do_update(
                index_elements=[SecurityRequestBucket.key],
                set_={"count": SecurityRequestBucket.count + 1},
            ).returning(SecurityRequestBucket.count)
            count = db.scalar(stmt)
            if count > limit:
                db.rollback()
                raise QuotaExceeded(max(1, end - now))
        db.execute(delete(SecurityRequestBucket).where(SecurityRequestBucket.expires_at <= now))
        db.commit()


def request_limits(scope: Scope, body: bytes) -> list[tuple[str, int, int]]:
    path, method = scope["path"], scope["method"]
    # Use the ASGI peer, never a caller-controlled forwarded header. Global buckets
    # remain authoritative even when an attacker changes addresses or session IDs.
    client = scope.get("client")
    peer = client[0] if client else "unknown"
    limits = [(f"http:{peer}", 120, 60), ("http:global", 600, 60)]
    if method == "POST" and path == "/v1/auth/login":
        try:
            username = str(json.loads(body).get("username", "")).strip().casefold()[:80]
        except (ValueError, AttributeError):
            username = "invalid"
        limits += [(f"login:{username}", 5, 60), (f"login-peer:{peer}", 20, 60)]
    if method == "POST" and path == "/v1/intake/sessions":
        limits += [(f"new-session:{peer}", 10, 60), ("new-session:global", 500, 86_400)]
    ai_request = method == "POST" and (
        path.endswith(("/messages", "/submit", "/query", "/semantic-index"))
        or path in {"/complaints", "/ai/intake/chat", "/v1/incidents"}
    )
    if ai_request:
        limits += [
            (f"ai-peer:{peer}", 15, 60),
            ("ai:global", 60, 60),
            ("ai:daily", get_settings().public_ai_daily_request_limit, 86_400),
        ]
    return limits


class SecurityMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        settings = get_settings()
        headers = Headers(scope=scope)

        async def secured_send(message: Message):
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                response_headers["Cache-Control"] = "no-store"
                response_headers["X-Content-Type-Options"] = "nosniff"
                response_headers["X-Frame-Options"] = "DENY"
                response_headers["Referrer-Policy"] = "no-referrer"
                if settings.is_production:
                    response_headers["Strict-Transport-Security"] = "max-age=31536000"
            await send(message)

        async def reject(status: int, detail: str, extra: dict | None = None):
            await JSONResponse({"detail": detail}, status_code=status, headers=extra)(
                scope,
                receive,
                secured_send,
            )

        # Legacy direct-write endpoints accept client-supplied analysis and provenance.
        # The shipped UI uses the bounded persistent intake instead.
        if (
            settings.is_production
            and scope["method"] == "POST"
            and scope["path"]
            in {
                "/submissions",
                "/complaints",
                "/ai/intake/chat",
            }
        ):
            return await reject(404, "Ruta no disponible.")
        try:
            if int(headers.get("content-length", "0")) > MAX_BODY_BYTES:
                return await reject(413, "La solicitud supera el tamaño permitido.")
        except ValueError:
            return await reject(400, "Longitud de solicitud inválida.")
        chunks, size = [], 0
        try:
            with anyio.fail_after(15):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    size += len(chunk)
                    if size > MAX_BODY_BYTES:
                        return await reject(413, "La solicitud supera el tamaño permitido.")
                    chunks.append(chunk)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            return await reject(408, "Se agotó el tiempo para recibir la solicitud.")
        body = b"".join(chunks)
        if settings.is_production and scope["path"] not in {"/health", "/ready", "/metrics"}:
            if scope["method"] != "OPTIONS":
                try:
                    await run_in_threadpool(consume_quotas, request_limits(scope, body))
                except QuotaExceeded as exc:
                    return await reject(
                        429,
                        "Límite temporal alcanzado. Inténtelo más tarde.",
                        {"Retry-After": str(exc.retry_after)},
                    )
                except SQLAlchemyError:
                    logger.error("Shared request quota storage unavailable")
                    return await reject(503, "Servicio temporalmente no disponible.")
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, secured_send)
