"""Request-scoped dependencies: database session, Redis, and API-key authorisation."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_server.db.models import ApiKey, Scope
from sentinel_server.keys import authenticate
from sentinel_server.settings import Settings

from .errors import ApiError


def get_settings(request: Request) -> Settings:
    """The app's settings."""
    settings: Settings = request.app.state.settings
    return settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """A session for the request, closed afterwards."""
    async with request.app.state.sessions() as session:
        yield session


def get_redis(request: Request) -> Redis:
    """The shared Redis client."""
    redis: Redis = request.app.state.redis
    return redis


Session = Annotated[AsyncSession, Depends(get_session)]
RedisDep = Annotated[Redis, Depends(get_redis)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

_UNAUTHORISED = {"WWW-Authenticate": 'Bearer realm="sentinel"'}


def require(scope: Scope) -> Callable[..., Awaitable[ApiKey | None]]:
    """A dependency that admits keys holding ``scope`` (or ``admin``).

    Read endpoints admit anyone when ``public_read`` is on, for a public demo dashboard.
    """

    async def check(request: Request, session: Session, settings: SettingsDep) -> ApiKey | None:
        if scope is Scope.READ and settings.public_read:
            return None
        header = request.headers.get("authorization", "")
        scheme, _, secret = header.partition(" ")
        if scheme.lower() != "bearer" or not secret:
            raise ApiError(
                401,
                "unauthenticated",
                "Missing API key",
                "Send an API key as 'Authorization: Bearer <key>'.",
                headers=_UNAUTHORISED,
            )
        key = await authenticate(session, secret.strip())
        if key is None:
            raise ApiError(
                401,
                "unauthenticated",
                "Invalid API key",
                "The API key is unknown or has been revoked.",
                headers=_UNAUTHORISED,
            )
        if scope.value not in key.scopes and Scope.ADMIN.value not in key.scopes:
            raise ApiError(
                403,
                "forbidden",
                "Insufficient scope",
                f"This key lacks the '{scope.value}' scope.",
            )
        return key

    return check


CanIngest = Depends(require(Scope.INGEST))
CanRead = Depends(require(Scope.READ))
CanAdmin = Depends(require(Scope.ADMIN))
