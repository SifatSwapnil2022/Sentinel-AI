"""An incident's whole life, through the API and worker: open, update, resolve, reopen."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import httpx
import numpy as np

from support import (
    Keys,
    Worker,
    prediction_records,
    register,
    send_labels,
    send_predictions,
    traffic,
)

TODAY = datetime.now(UTC).date()
ROWS = 500


async def play(
    client: httpx.AsyncClient,
    keys: Keys,
    rng: np.random.Generator,
    days: list[date],
    *,
    broken: bool,
) -> None:
    """A stretch of traffic, labelled at once. ``broken``: the model is wrong for one region."""
    for day in days:
        records = prediction_records(traffic(rng, ROWS, broken=broken), day, with_label=True)
        await send_predictions(client, keys.ingest, "loans", records)
        await send_labels(
            client, keys.ingest, "loans", [(r["request_id"], r["label"]) for r in records]
        )


def span(first: int, last: int) -> list[date]:
    """Days ``first`` to ``last`` days ago."""
    return [TODAY - timedelta(days=k) for k in range(first, last - 1, -1)]


async def test_incident_lifecycle(client: httpx.AsyncClient, keys: Keys, worker: Worker) -> None:
    rng = np.random.default_rng(7)
    await register(client, keys.admin)
    await worker.fit()

    # 1. healthy, then the model starts failing for region 'east'
    await play(client, keys, rng, span(29, 25), broken=False)
    await play(client, keys, rng, span(24, 20), broken=True)
    await worker.settle(today=TODAY - timedelta(days=20))

    fleet = (await client.get("/v1/fleet", headers=keys.read)).json()
    (alert,) = fleet["alerts"]
    assert alert["id"] == "loans-1"
    assert alert["kind"] == "concept_drift"
    assert alert["severity"] == "critical"
    (row,) = fleet["models"]
    assert row["status"] == "critical"
    assert row["openAlerts"] == 1

    incident = (await client.get("/v1/incidents/loans-1", headers=keys.read)).json()
    assert incident["metric"]["basis"] == "measured"
    top = incident["findings"][0]["conditions"]
    assert {"feature": "region", "value": "east"} in top
    assert incident["sampleRows"]["columns"] == ["income", "region", "tenure"]
    assert all(r["values"][1] == "east" for r in incident["sampleRows"]["rows"])
    opened_on = incident["openedOn"]

    model = (await client.get("/v1/models/loans", headers=keys.read)).json()
    assert model["alertIds"] == ["loans-1"]
    assert model["days"][-1]["date"] == (TODAY - timedelta(days=20)).isoformat()
    assert [f["name"] for f in model["features"]] == ["income", "region", "tenure"]

    # 2. fixed, but not instantly resolved: a few quiet days could be labels lagging
    await play(client, keys, rng, span(19, 14), broken=False)
    await worker.settle(today=TODAY - timedelta(days=14))
    fleet = (await client.get("/v1/fleet", headers=keys.read)).json()
    assert [a["id"] for a in fleet["alerts"]] == ["loans-1"]

    # a full quiet week later it resolves, dated from the first quiet day
    await play(client, keys, rng, span(13, 6), broken=False)
    await worker.settle(today=TODAY - timedelta(days=6))
    fleet = (await client.get("/v1/fleet", headers=keys.read)).json()
    assert fleet["alerts"] == []
    assert fleet["models"][0]["status"] == "healthy"
    resolved = (await client.get("/v1/incidents?status=resolved", headers=keys.read)).json()
    assert [(i["id"], i["openedOn"]) for i in resolved] == [("loans-1", opened_on)]
    # dated when the rule stopped holding, not when the worker happened to look
    assert opened_on < resolved[0]["resolvedOn"] < (TODAY - timedelta(days=6)).isoformat()

    # 3. it breaks again: a new episode, a new incident
    await play(client, keys, rng, span(5, 1), broken=True)
    await worker.settle(today=TODAY - timedelta(days=1))
    every = (await client.get("/v1/incidents?status=all", headers=keys.read)).json()
    other = await client.get("/v1/incidents?status=all&model_id=other", headers=keys.read)
    assert other.json() == []
    assert [(i["id"], i["status"]) for i in every] == [("loans-2", "open"), ("loans-1", "resolved")]
    second = (await client.get("/v1/incidents/loans-2", headers=keys.read)).json()
    assert second["openedOn"] > resolved[0]["resolvedOn"]
    model = (await client.get("/v1/models/loans", headers=keys.read)).json()
    assert model["alertIds"] == ["loans-2", "loans-1"]


async def test_documents_404_until_data(
    client: httpx.AsyncClient, keys: Keys, worker: Worker
) -> None:
    await register(client, keys.admin)
    await worker.fit()
    r = await client.get("/v1/models/loans", headers=keys.read)
    assert r.status_code == 404
    assert r.json()["type"].endswith("#no-model-data")
    assert (await client.get("/v1/incidents/loans-1", headers=keys.read)).status_code == 404
    fleet = (await client.get("/v1/fleet", headers=keys.read)).json()
    assert fleet["models"] == []
    assert fleet["schemaVersion"] == 1


async def test_predictions_before_fit_are_computed_after(
    client: httpx.AsyncClient, keys: Keys, worker: Worker
) -> None:
    await register(client, keys.admin)
    day = TODAY - timedelta(days=1)
    records = prediction_records(traffic(np.random.default_rng(9), 200), day)
    r = await client.post(
        "/v1/ingest/predictions",
        json={"model_id": "loans", "version": "v1", "predictions": records},
        headers=keys.ingest,
    )
    assert r.status_code == 202
    await worker.drain()
    assert await worker.recompute() == 0  # not fitted: its days wait
    await worker.fit()
    assert await worker.recompute() >= 1
    model = (await client.get("/v1/models/loans", headers=keys.read)).json()
    assert model["days"][-1]["rows"] == 200
