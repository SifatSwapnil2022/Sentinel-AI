"""API keys: ``snl_`` followed by 43 random URL-safe characters (256 bits).

Only a SHA-256 digest is stored. A slow password hash (bcrypt, argon2) protects low-entropy
secrets against guessing; a 256-bit random key cannot be guessed, so a fast digest is enough,
and it lets a request be authenticated with one indexed lookup.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_server.db.models import ApiKey, Scope

PREFIX = "snl_"
TOUCH_INTERVAL = timedelta(minutes=5)
"""``last_used_at`` is written at most this often per key, so reads don't each cost a write."""


def digest(secret: str) -> str:
    """Hex SHA-256 of a key."""
    return hashlib.sha256(secret.encode()).hexdigest()


def looks_like_key(secret: str) -> bool:
    """Cheap shape check before touching the database."""
    return secret.startswith(PREFIX) and 40 <= len(secret) <= 64


async def create_key(
    session: AsyncSession, name: str, scopes: Iterable[Scope]
) -> tuple[str, ApiKey]:
    """A new key. The secret is returned once and never stored."""
    secret = PREFIX + secrets.token_urlsafe(32)
    key = ApiKey(
        name=name,
        prefix=secret[:12],
        digest=digest(secret),
        scopes=sorted({Scope(s).value for s in scopes}),
    )
    session.add(key)
    await session.flush()
    return secret, key


async def authenticate(session: AsyncSession, secret: str) -> ApiKey | None:
    """The live key matching ``secret``, or None."""
    if not looks_like_key(secret):
        return None
    key = await session.scalar(
        select(ApiKey).where(ApiKey.digest == digest(secret), ApiKey.revoked_at.is_(None))
    )
    if key is None:
        return None
    now = datetime.now(UTC)
    if key.last_used_at is None or now - key.last_used_at > TOUCH_INTERVAL:
        await session.execute(update(ApiKey).where(ApiKey.id == key.id).values(last_used_at=now))
        await session.commit()
    return key


async def revoke(session: AsyncSession, prefix: str) -> bool:
    """Revoke the key with this display prefix; False if none is live."""
    result = await session.execute(
        update(ApiKey)
        .where(ApiKey.prefix == prefix, ApiKey.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await session.commit()
    return bool(result.rowcount)  # type: ignore[attr-defined]
