from __future__ import annotations

import asyncio

import pytest

from sentinel_server import admin
from sentinel_server.db.session import make_engine, make_sessionmaker
from sentinel_server.keys import authenticate
from sentinel_server.settings import Settings, get_settings


@pytest.fixture
def env(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("SENTINEL_DATABASE_URL", settings.database_url)
    get_settings.cache_clear()
    yield settings  # type: ignore[misc]
    get_settings.cache_clear()


async def _scopes(url: str, secret: str) -> list[str] | None:
    engine = make_engine(url, pool_size=1)
    try:
        async with make_sessionmaker(engine)() as session:
            key = await authenticate(session, secret)
            return None if key is None else list(key.scopes)
    finally:
        await engine.dispose()


def test_create_and_revoke_key(env: Settings, capsys: pytest.CaptureFixture[str]) -> None:
    assert admin.main(["create-key", "--name", "ci", "--scope", "ingest", "--scope", "read"]) == 0
    out, err = capsys.readouterr()
    secret = out.strip()
    assert secret.startswith("snl_")
    assert "not shown again" in err
    assert asyncio.run(_scopes(env.database_url, secret)) == ["ingest", "read"]

    assert admin.main(["revoke-key", secret[:12]]) == 0
    assert admin.main(["revoke-key", secret[:12]]) == 1
    assert "no live key" in capsys.readouterr().err
    assert asyncio.run(_scopes(env.database_url, secret)) is None


def test_migrate_is_idempotent(env: Settings) -> None:
    assert admin.main(["migrate"]) == 0


def test_unknown_scope_is_refused(env: Settings) -> None:
    with pytest.raises(SystemExit):
        admin.main(["create-key", "--name", "x", "--scope", "root"])
