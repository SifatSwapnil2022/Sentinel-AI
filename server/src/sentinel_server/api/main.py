"""The HTTP API."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text

import sentinel_server
from sentinel_server.db.session import make_engine, make_sessionmaker
from sentinel_server.logs import configure_logging
from sentinel_server.settings import Settings, get_settings

from . import errors
from .routes import documents, ingest, registry

MAX_BODY_BYTES = 8 * 1024 * 1024
"""Request bodies above this are refused before being read (uploads have their own limit)."""


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Tests pass their own settings."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(settings.database_url)
        app.state.settings = settings
        app.state.engine = engine
        app.state.sessions = make_sessionmaker(engine)
        app.state.redis = Redis.from_url(settings.redis_url)
        app.state.targets = ingest.TargetCache()
        try:
            yield
        finally:
            await app.state.redis.aclose()
            await engine.dispose()

    app = FastAPI(
        title="Sentinel",
        version=sentinel_server.__version__,
        summary="Monitoring for classification models in production.",
        lifespan=lifespan,
    )
    errors.install(app)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "PUT"],
            allow_headers=["Authorization", "Content-Type"],
            max_age=600,
        )

    @app.middleware("http")
    async def limit_body(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        limit = (
            settings.max_reference_bytes + 1024 * 1024
            if request.url.path.endswith("/versions")
            else MAX_BODY_BYTES
        )
        length = request.headers.get("content-length")
        if length is not None and length.isdigit() and int(length) > limit:
            return errors.problem(
                413,
                "body-too-large",
                "Request too large",
                f"Request bodies are limited to {limit // (1024 * 1024)} MB.",
            )
        return await call_next(request)

    @app.get("/healthz", tags=["health"], include_in_schema=False)
    async def healthz() -> dict[str, str]:
        """Liveness: the process is serving."""
        return {"status": "ok"}

    @app.get("/readyz", tags=["health"], include_in_schema=False)
    async def readyz(request: Request) -> Response:
        """Readiness: the database and Redis answer."""
        checks: dict[str, str] = {}
        try:
            async with request.app.state.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {type(exc).__name__}"
        try:
            await request.app.state.redis.ping()
            checks["redis"] = "ok"
        except Exception as exc:
            checks["redis"] = f"error: {type(exc).__name__}"
        ok = all(v == "ok" for v in checks.values())
        return JSONResponse(
            {"status": "ok" if ok else "unavailable", **checks}, status_code=200 if ok else 503
        )

    app.include_router(ingest.router)
    app.include_router(registry.router)
    app.include_router(documents.router)
    return app


def run() -> None:
    """Entry point for ``sentinel-api``."""
    import uvicorn

    configure_logging()
    uvicorn.run(
        "sentinel_server.api.main:create_app",
        factory=True,
        host="0.0.0.0",
        port=8000,
        proxy_headers=True,
        log_config=None,
    )
