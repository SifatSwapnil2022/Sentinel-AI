"""The live pipeline and the static demo are the same system.

A demo scenario is pushed through the real path (reference CSV upload, HTTP ingest, Redis, the
worker, Postgres, the read API) and must produce exactly the documents the fixture builder
computes in memory from the same traffic. Any drift between the two (a serialisation
round trip that changes a value, rows reordered, a rule applied differently) fails here.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pandas as pd
import pytest

from support import Keys, Worker

DEMO = Path(__file__).resolve().parents[2] / "demo"
sys.path.insert(0, str(DEMO))
build_fixtures = pytest.importorskip("build_fixtures")
scenarios = pytest.importorskip("scenarios")

# Ingest refuses timestamps in the future, so the scenario ends yesterday. Thirty days keep the
# test quick; scenarios are timed back from the last day, so every story still fits.
TODAY = datetime.now(UTC).date() - timedelta(days=1)
DAYS = 30


def _jsonable(frame: pd.DataFrame) -> list[dict[str, Any]]:
    values = frame.astype(object).where(frame.notna(), None)
    return [
        {k: (v.item() if isinstance(v, np.generic) else v) for k, v in row.items()}
        for row in values.to_dict("records")
    ]


def _normalise(doc: Any) -> Any:
    """What a document looks like after JSON serialisation."""
    return json.loads(json.dumps(doc))


@pytest.mark.slow
@pytest.mark.parametrize(
    "model_id", ["credit-risk", "claims-triage", "upsell-propensity", "sme-credit"]
)
async def test_live_pipeline_matches_static_demo(
    client: httpx.AsyncClient, keys: Keys, worker: Worker, model_id: str
) -> None:
    index = next(i for i, m in enumerate(scenarios.MODELS) if m.id == model_id)
    spec = scenarios.MODELS[index]
    trained, data = build_fixtures.prepare(
        spec, np.random.default_rng(build_fixtures.SEED + index), TODAY, DAYS
    )
    summary, model_doc, incidents = build_fixtures.documents(spec, trained, data)

    # register and upload the same reference the demo fitted its monitors on
    r = await client.put(
        f"/v1/registry/models/{spec.id}",
        json={
            "name": spec.name,
            "team": spec.team,
            "description": spec.description,
            "label_delay_days": spec.label_delay_days,
        },
        headers=keys.admin,
    )
    assert r.status_code == 201
    r = await client.post(
        f"/v1/registry/models/{spec.id}/versions",
        data={"version": spec.version},
        files={
            "reference": ("ref.csv", trained.reference.to_csv(index=False).encode(), "text/csv")
        },
        headers=keys.admin,
    )
    assert r.status_code == 202, r.text
    await worker.fit()

    # replay the traffic, in generation order, one second apart
    for day in data:
        start = datetime.combine(day.date, time.min, tzinfo=UTC)
        rows = _jsonable(day.frame)
        records = [
            {
                "request_id": f"{day.date:%Y%m%d}-{i:05d}",
                "ts": (start + timedelta(seconds=i)).isoformat(),
                "features": rows[i],
                "score": float(day.proba[i]),
                "latency_ms": float(day.latency_ms[i]),  # type: ignore[index]
            }
            for i in range(day.rows)
        ]
        labels = [
            {"request_id": records[i]["request_id"], "label": int(day.outcome[i])}
            for i in np.flatnonzero(day.labelled)
        ]
        for k in range(0, len(records), 500):
            r = await client.post(
                "/v1/ingest/predictions",
                json={"model_id": spec.id, "predictions": records[k : k + 500]},
                headers=keys.ingest,
            )
            assert r.status_code == 202, r.text
        for k in range(0, len(labels), 500):
            r = await client.post(
                "/v1/ingest/labels",
                json={"model_id": spec.id, "labels": labels[k : k + 500]},
                headers=keys.ingest,
            )
            assert r.status_code == 202, r.text
    await worker.settle(today=TODAY)

    live_model = (await client.get(f"/v1/models/{spec.id}", headers=keys.read)).json()
    assert live_model == _normalise(model_doc)

    fleet = (await client.get("/v1/fleet", headers=keys.read)).json()
    assert fleet["models"] == [_normalise(summary)]

    assert incidents, "the scenario should cause at least one incident"
    for expected in incidents:
        live = (await client.get(f"/v1/incidents/{expected['id']}", headers=keys.read)).json()
        assert live == _normalise(expected)
    daily = (await client.get("/v1/fleet/daily", headers=keys.read)).json()
    assert daily == _normalise(build_fixtures.fleet_daily([model_doc]))
