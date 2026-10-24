"""Errors as RFC 9457 problem details (``application/problem+json``).

Every error response has the same shape: ``type``, ``title``, ``status``, ``detail``, plus
fields specific to the problem (``errors`` for validation, ``problems`` for a rejected upload).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

PROBLEM = "application/problem+json"
TYPE_BASE = "https://github.com/SifatSwapnil2022/Sentinel-AI/blob/main/docs/api.md#"


class ApiError(Exception):
    """An error the client can act on."""

    def __init__(
        self,
        status: int,
        slug: str,
        title: str,
        detail: str,
        *,
        headers: dict[str, str] | None = None,
        **extra: Any,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.slug = slug
        self.title = title
        self.detail = detail
        self.headers = headers
        self.extra = extra


def problem(
    status: int,
    slug: str,
    title: str,
    detail: str,
    *,
    headers: dict[str, str] | None = None,
    **extra: Any,
) -> JSONResponse:
    """A problem-details response."""
    body = {"type": TYPE_BASE + slug, "title": title, "status": status, "detail": detail, **extra}
    return JSONResponse(body, status_code=status, media_type=PROBLEM, headers=headers)


def install(app: FastAPI) -> None:
    """Route every error through :func:`problem`."""

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return problem(
            exc.status, exc.slug, exc.title, exc.detail, headers=exc.headers, **exc.extra
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"location": [str(p) for p in e["loc"]], "message": e["msg"]} for e in exc.errors()[:50]
        ]
        return problem(
            422,
            "invalid-request",
            "Invalid request",
            f"{len(exc.errors())} field(s) failed validation",
            errors=errors,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        slug = {404: "not-found", 405: "method-not-allowed"}.get(exc.status_code, "http-error")
        return problem(
            exc.status_code,
            slug,
            str(exc.detail) if exc.status_code != 404 else "Not found",
            str(exc.detail),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", exc_info=exc)
        return problem(500, "internal", "Internal error", "Something went wrong on our side.")
