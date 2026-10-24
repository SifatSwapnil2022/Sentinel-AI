from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import orjson
import pytest
from redis.asyncio import Redis

from sentinel_server.contracts import PredictionMessage, decode
from sentinel_server.settings import Settings
from support import Keys, Worker, register

URL = "/v1/ingest/predictions"


def batch(n: int = 1, **overrides: Any) -> dict[str, Any]:
    def record(i: int) -> dict[str, Any]:
        features = {"income": 50_000.0, "region": "east"}  # a fresh dict per record
        return {"request_id": f"r{i}", "features": features, "score": 0.7, **overrides}

    return {"model_id": "loans", "predictions": [record(i) for i in range(n)]}


@pytest.fixture
async def ready(client: httpx.AsyncClient, keys: Keys, worker: Worker) -> None:
    assert (await register(client, keys.admin)).status_code == 202
    await worker.fit()


async def test_queued_with_defaults(
    client: httpx.AsyncClient, keys: Keys, redis: Redis, settings: Settings, ready: None
) -> None:
    before = datetime.now(UTC)
    r = await client.post(URL, json=batch(3), headers=keys.ingest)
    assert r.status_code == 202
    assert r.json()["accepted"] == 3
    (entry,) = await redis.xrange(settings.ingest_stream)
    message = decode(entry[1])
    assert isinstance(message, PredictionMessage)
    record = message.records[0]
    assert before <= record.ts <= datetime.now(UTC)  # defaulted to receipt time
    assert record.prediction == 1  # 0.7 >= the 0.5 threshold
    assert record.latency_ms is None


async def test_explicit_prediction_and_timestamp_kept(
    client: httpx.AsyncClient, keys: Keys, redis: Redis, settings: Settings, ready: None
) -> None:
    ts = "2026-10-20T08:30:00+06:00"
    if datetime.fromisoformat(ts) > datetime.now(UTC):
        pytest.skip("fixed timestamp is in the future on this clock")
    r = await client.post(URL, json=batch(1, ts=ts, prediction=0), headers=keys.ingest)
    assert r.status_code == 202, r.text
    record = decode((await redis.xrange(settings.ingest_stream))[0][1]).records[0]  # type: ignore[union-attr]
    assert record.prediction == 0
    assert record.ts == datetime(2026, 10, 20, 2, 30, tzinfo=UTC)


async def test_naive_timestamps_are_utc(
    client: httpx.AsyncClient, keys: Keys, redis: Redis, settings: Settings, ready: None
) -> None:
    ts = (datetime.now(UTC) - timedelta(hours=1)).replace(tzinfo=None, microsecond=0)
    await client.post(URL, json=batch(1, ts=ts.isoformat()), headers=keys.ingest)
    record = decode((await redis.xrange(settings.ingest_stream))[0][1]).records[0]  # type: ignore[union-attr]
    assert record.ts == ts.replace(tzinfo=UTC)


async def test_unknown_model_and_version(
    client: httpx.AsyncClient, keys: Keys, ready: None
) -> None:
    r = await client.post(URL, json={**batch(), "model_id": "nope"}, headers=keys.ingest)
    assert r.status_code == 404
    r = await client.post(URL, json={**batch(), "version": "v9"}, headers=keys.ingest)
    assert r.status_code == 404
    assert r.json()["type"].endswith("#unknown-version")


async def test_model_without_active_version(client: httpx.AsyncClient, keys: Keys) -> None:
    await register(client, keys.admin)  # uploaded, not fitted yet
    r = await client.post(URL, json=batch(), headers=keys.ingest)
    assert r.status_code == 409
    # naming the pending version explicitly works: it is computed once fitted
    r = await client.post(URL, json={**batch(), "version": "v1"}, headers=keys.ingest)
    assert r.status_code == 202


async def test_record_problems_reject_the_whole_batch(
    client: httpx.AsyncClient, keys: Keys, redis: Redis, settings: Settings, ready: None
) -> None:
    body = batch(4)
    body["predictions"][1]["features"]["colour"] = "red"
    body["predictions"][2]["ts"] = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    body["predictions"][3]["ts"] = (datetime.now(UTC) - timedelta(days=200)).isoformat()
    r = await client.post(URL, json=body, headers=keys.ingest)
    assert r.status_code == 422
    errors = r.json()["errors"]
    assert [e["index"] for e in errors] == [1, 2, 3]
    assert "colour" in errors[0]["message"]
    assert "future" in errors[1]["message"]
    assert "older than" in errors[2]["message"]
    assert await redis.xlen(settings.ingest_stream) == 0


@pytest.mark.parametrize(
    "record",
    [
        {"score": 1.5},
        {"score": -0.1},
        {"prediction": 2},
        {"latency_ms": -1},
        {"request_id": ""},
        {"request_id": "has space"},
        {"surprise": True},
        {"features": {"income": [1, 2]}},
    ],
)
async def test_schema_violations_are_422(
    client: httpx.AsyncClient, keys: Keys, ready: None, record: dict[str, Any]
) -> None:
    r = await client.post(URL, json=batch(1, **record), headers=keys.ingest)
    assert r.status_code == 422
    body = r.json()
    assert body["type"].endswith("#invalid-request")
    assert body["errors"][0]["location"][0] == "body"


async def test_non_finite_numbers_are_rejected(
    client: httpx.AsyncClient, keys: Keys, ready: None
) -> None:
    raw = orjson.dumps(batch(1)).replace(b"50000.0", b"NaN")
    r = await client.post(
        URL, content=raw, headers={**keys.ingest, "Content-Type": "application/json"}
    )
    assert r.status_code == 422


async def test_batch_limit(client: httpx.AsyncClient, keys: Keys, ready: None) -> None:
    r = await client.post(URL, json=batch(501), headers=keys.ingest)
    assert r.status_code == 413
    assert "500" in r.json()["detail"]


async def test_oversized_body_refused_before_parsing(client: httpx.AsyncClient, keys: Keys) -> None:
    r = await client.post(
        URL, content=b"{}", headers={**keys.ingest, "Content-Length": str(64 * 1024 * 1024)}
    )
    assert r.status_code == 413


async def test_backpressure(
    client: httpx.AsyncClient, keys: Keys, redis: Redis, settings: Settings, ready: None
) -> None:
    for _ in range(settings.max_stream_length):
        await redis.xadd(settings.ingest_stream, {"filler": "1"})
    r = await client.post(URL, json=batch(), headers=keys.ingest)
    assert r.status_code == 503
    assert r.headers["retry-after"] == "5"
    assert await redis.xlen(settings.ingest_stream) == settings.max_stream_length


async def test_labels_queue(
    client: httpx.AsyncClient, keys: Keys, redis: Redis, settings: Settings, ready: None
) -> None:
    body = {"model_id": "loans", "labels": [{"request_id": "r0", "label": 1}]}
    r = await client.post("/v1/ingest/labels", json=body, headers=keys.ingest)
    assert r.status_code == 202
    r = await client.post(
        "/v1/ingest/labels", json={**body, "model_id": "nope"}, headers=keys.ingest
    )
    assert r.status_code == 404
    r = await client.post(
        "/v1/ingest/labels",
        json={"model_id": "loans", "labels": [{"request_id": "a", "label": 0.5}]},
        headers=keys.ingest,
    )
    assert r.status_code == 422
    assert await redis.xlen(settings.ingest_stream) == 1
