"""The BI exports and the daily facts behind the dashboard's slicers."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta

import httpx
import numpy as np
import pytest

from sentinel_server.analysis import TABLES
from support import Keys, Worker, prediction_records, register, send_predictions, traffic

TODAY = datetime.now(UTC).date()


@pytest.fixture
async def history(client: httpx.AsyncClient, keys: Keys, worker: Worker) -> None:
    await register(client, keys.admin)
    await worker.fit()
    rng = np.random.default_rng(3)
    for k in range(3, 0, -1):
        day = TODAY - timedelta(days=k)
        await send_predictions(
            client, keys.ingest, "loans", prediction_records(traffic(rng, 150), day)
        )
    await worker.settle(today=TODAY - timedelta(days=1))


def rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


async def test_daily_facts(client: httpx.AsyncClient, keys: Keys, history: None) -> None:
    daily = (await client.get("/v1/fleet/daily", headers=keys.read)).json()
    assert [(r["modelId"], r["rows"]) for r in daily["rows"]] == [("loans", 150)] * 3
    first = daily["rows"][0]
    assert first["date"] == (TODAY - timedelta(days=3)).isoformat()
    assert first["lower"] <= first["estimate"] <= first["upper"]
    assert first["team"] == "Risk"


@pytest.mark.parametrize("table", TABLES)
async def test_every_table_exports_as_csv(
    client: httpx.AsyncClient, keys: Keys, history: None, table: str
) -> None:
    r = await client.get(f"/v1/export/{table}.csv", headers=keys.read)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert f"sentinel_{table}.csv" in r.headers["content-disposition"]
    if table in ("fact_incident", "fact_incident_signal"):
        assert r.text == ""  # three quiet days: nothing to report, and no header to guess
    else:
        assert rows(r.text), table


async def test_export_contents(client: httpx.AsyncClient, keys: Keys, history: None) -> None:
    (model,) = rows((await client.get("/v1/export/dim_model.csv", headers=keys.read)).text)
    assert model["model_id"] == "loans"
    assert model["status"] == "healthy"
    facts = rows((await client.get("/v1/export/fact_model_day.csv", headers=keys.read)).text)
    assert [f["predictions"] for f in facts] == ["150"] * 3
    assert {f["multivariate_drifted"] for f in facts} <= {"true", "false"}
    features = rows((await client.get("/v1/export/fact_feature_day.csv", headers=keys.read)).text)
    assert {f["feature"] for f in features} == {"income", "region", "tenure"}
    assert len(features) == 9


async def test_unknown_table_and_auth(client: httpx.AsyncClient, keys: Keys) -> None:
    r = await client.get("/v1/export/passwords.csv", headers=keys.read)
    assert r.status_code == 404
    assert "dim_model" in r.json()["detail"]
    assert (await client.get("/v1/export/dim_model.csv")).status_code == 401
