from __future__ import annotations

import httpx
import numpy as np
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sentinel_server.db.models import ModelVersion
from support import Keys, Worker, register, traffic


async def test_register_and_update_model(client: httpx.AsyncClient, keys: Keys) -> None:
    body = {"name": "Loan default", "team": "Risk", "description": "", "label_delay_days": 30}
    r = await client.put("/v1/registry/models/loans", json=body, headers=keys.admin)
    assert r.status_code == 201
    assert r.json()["active_version"] is None
    r = await client.put(
        "/v1/registry/models/loans", json={**body, "team": "Credit"}, headers=keys.admin
    )
    assert r.status_code == 200
    assert r.json()["team"] == "Credit"
    listed = (await client.get("/v1/registry/models", headers=keys.read)).json()
    assert [m["id"] for m in listed] == ["loans"]


@pytest.mark.parametrize("model_id", ["Loans", "-loans", "a" * 65, "lo ans"])
async def test_model_ids_are_slugs(client: httpx.AsyncClient, keys: Keys, model_id: str) -> None:
    r = await client.put(f"/v1/registry/models/{model_id}", json={"name": "x"}, headers=keys.admin)
    assert r.status_code in (404, 422)


async def test_upload_fit_and_activate(
    client: httpx.AsyncClient, keys: Keys, worker: Worker
) -> None:
    r = await register(client, keys.admin)
    assert r.status_code == 202, r.text
    version = r.json()
    assert version["status"] == "pending"
    # features keep the file's column order
    assert [f["name"] for f in version["features"]] == ["income", "region", "tenure"]
    assert {f["name"]: f["kind"] for f in version["features"]}["region"] == "categorical"

    assert await worker.fit() == 1
    assert await worker.fit() == 0
    r = await client.get("/v1/registry/models/loans/versions/v1", headers=keys.read)
    fitted = r.json()
    assert fitted["status"] == "ready"
    assert fitted["active"] is True
    assert fitted["summary"]["referenceRows"] == 1500
    assert 0.5 < fitted["summary"]["referenceAccuracy"] < 1


async def test_duplicate_version_is_409(client: httpx.AsyncClient, keys: Keys) -> None:
    assert (await register(client, keys.admin)).status_code == 202
    r = await register(client, keys.admin)
    assert r.status_code == 409
    assert r.json()["type"].endswith("#version-exists")


async def test_new_version_can_wait_to_be_activated(
    client: httpx.AsyncClient, keys: Keys, worker: Worker
) -> None:
    await register(client, keys.admin, version="v1")
    await register(client, keys.admin, version="v2", activate="false")
    r = await client.post("/v1/registry/models/loans/versions/v2/activate", headers=keys.admin)
    assert r.status_code == 409  # not fitted yet
    await worker.fit()
    model = (await client.get("/v1/registry/models/loans", headers=keys.read)).json()
    assert model["active_version"] == "v1"
    r = await client.post("/v1/registry/models/loans/versions/v2/activate", headers=keys.admin)
    assert r.status_code == 200
    assert r.json()["active_version"] == "v2"


def _csv(frame: object) -> bytes:
    return frame.to_csv(index=False).encode()  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda f: f.drop(columns="label"), "missing column(s): label"),
        (lambda f: f.assign(label=f["label"] + 1), "label: "),
        (lambda f: f.assign(score=f["score"] * 2), "outside [0, 1]"),
        (lambda f: f.head(50), "at least 200 rows"),
        (lambda f: f.assign(label=0), "needs both outcomes"),
        (lambda f: f[["score", "label"]], "no feature columns"),
    ],
)
async def test_bad_reference_is_rejected_with_reasons(
    client: httpx.AsyncClient, keys: Keys, mutate: object, expected: str
) -> None:
    frame = traffic(np.random.default_rng(1), 400)
    r = await register(client, keys.admin, csv=_csv(mutate(frame)))  # type: ignore[operator]
    assert r.status_code == 422
    body = r.json()
    assert body["type"].endswith("#invalid-reference")
    assert any(expected in p for p in body["problems"]), body["problems"]


async def test_unreadable_reference(client: httpx.AsyncClient, keys: Keys) -> None:
    r = await register(client, keys.admin, csv=b"\x00\xff\xfe binary junk")
    assert r.status_code == 422


async def test_custom_columns_and_threshold(
    client: httpx.AsyncClient, keys: Keys, worker: Worker
) -> None:
    frame = traffic(np.random.default_rng(2), 600).rename(columns={"score": "p", "label": "y"})
    r = await register(
        client,
        keys.admin,
        csv=_csv(frame),
        score_column="p",
        label_column="y",
        decision_threshold=0.3,
    )
    assert r.status_code == 202, r.text
    assert r.json()["decision_threshold"] == 0.3
    await worker.fit()
    status = (await client.get("/v1/registry/models/loans/versions/v1", headers=keys.read)).json()
    assert status["status"] == "ready"


async def test_fit_failure_is_recorded(
    client: httpx.AsyncClient,
    keys: Keys,
    worker: Worker,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await register(client, keys.admin)
    async with sessions() as session:
        await session.execute(update(ModelVersion).values(reference_csv=b"not,a\ncsv"))
        await session.commit()
    await worker.fit()
    status = (await client.get("/v1/registry/models/loans/versions/v1", headers=keys.read)).json()
    assert status["status"] == "failed"
    assert "missing column" in status["error"]
    r = await client.post(
        "/v1/ingest/predictions",
        json={
            "model_id": "loans",
            "version": "v1",
            "predictions": [{"request_id": "a", "features": {}, "score": 0.5}],
        },
        headers=keys.ingest,
    )
    assert r.status_code == 409
