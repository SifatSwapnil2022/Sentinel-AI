from __future__ import annotations

import httpx
import pytest

from sentinel_server.api import main as api_main
from sentinel_server.api.main import create_app
from sentinel_server.api.routes import documents
from sentinel_server.settings import Settings
from support import Keys


async def test_method_not_allowed_is_a_problem(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/ingest/predictions")
    assert r.status_code == 405
    assert r.headers["content-type"] == "application/problem+json"


async def test_unknown_route_is_a_problem(client: httpx.AsyncClient) -> None:
    r = await client.get("/v2/nothing")
    assert r.status_code == 404
    assert r.json()["title"] == "Not found"


async def test_unexpected_errors_are_500_without_details(
    settings: Settings,
    keys: Keys,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def boom(*_: object) -> None:
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(documents, "fleet_document", boom)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get("/v1/fleet", headers=keys.read)
    assert r.status_code == 500
    assert "secret" not in r.text
    assert r.json()["type"].endswith("#internal")
    assert "unhandled error" in caplog.text
    assert api_main.MAX_BODY_BYTES > 0
