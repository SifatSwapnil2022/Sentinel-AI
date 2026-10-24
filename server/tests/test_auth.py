from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sentinel_server.api.main import create_app
from sentinel_server.keys import revoke
from sentinel_server.settings import Settings
from support import Keys

PROBLEM = "application/problem+json"


async def test_missing_key_is_401_with_challenge(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/fleet")
    assert r.status_code == 401
    assert r.headers["content-type"] == PROBLEM
    assert r.headers["www-authenticate"].startswith("Bearer")
    body = r.json()
    assert body["status"] == 401
    assert body["type"].endswith("#unauthenticated")


async def test_malformed_and_unknown_keys_are_rejected(client: httpx.AsyncClient) -> None:
    for header in ("Basic abc", "Bearer ", "Bearer not-a-key", "Bearer snl_" + "x" * 43):
        r = await client.get("/v1/fleet", headers={"Authorization": header})
        assert r.status_code == 401, header


async def test_scopes(client: httpx.AsyncClient, keys: Keys) -> None:
    assert (await client.get("/v1/fleet", headers=keys.read)).status_code == 200
    r = await client.post(
        "/v1/ingest/labels",
        json={"model_id": "m", "labels": [{"request_id": "a", "label": 1}]},
        headers=keys.read,
    )
    assert r.status_code == 403
    assert "ingest" in r.json()["detail"]
    r = await client.put("/v1/registry/models/m", json={"name": "m"}, headers=keys.ingest)
    assert r.status_code == 403
    # admin implies every scope
    assert (await client.get("/v1/fleet", headers=keys.admin)).status_code == 200


async def test_revoked_key_stops_working(
    client: httpx.AsyncClient, keys: Keys, sessions: async_sessionmaker[AsyncSession]
) -> None:
    secret = keys.read["Authorization"].removeprefix("Bearer ")
    assert (await client.get("/v1/fleet", headers=keys.read)).status_code == 200
    async with sessions() as session:
        assert await revoke(session, secret[:12])
        assert not await revoke(session, secret[:12])
    assert (await client.get("/v1/fleet", headers=keys.read)).status_code == 401


async def test_public_read_opens_reads_only(
    settings: Settings, engine: object, redis: object
) -> None:
    del engine, redis
    app = create_app(settings.model_copy(update={"public_read": True}))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c,
    ):
        assert (await c.get("/v1/fleet")).status_code == 200
        r = await c.post(
            "/v1/ingest/labels",
            json={"model_id": "m", "labels": [{"request_id": "a", "label": 1}]},
        )
        assert r.status_code == 401


async def test_health(client: httpx.AsyncClient) -> None:
    assert (await client.get("/healthz")).json() == {"status": "ok"}
    r = await client.get("/readyz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": "ok", "redis": "ok"}
