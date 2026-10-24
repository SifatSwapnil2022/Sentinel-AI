from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta

import httpx
import numpy as np
import pytest

from sentinel_server.settings import Settings
from sentinel_server.worker.main import _forever, run_worker
from support import Keys, prediction_records, register, send_predictions, traffic


async def test_worker_process_end_to_end(
    client: httpx.AsyncClient, keys: Keys, settings: Settings
) -> None:
    stop = asyncio.Event()
    task = asyncio.create_task(
        run_worker(settings.model_copy(update={"worker_block_ms": 100}), stop)
    )
    try:
        assert (await register(client, keys.admin)).status_code == 202
        for _ in range(100):  # the running worker fits the version in the background
            version = await client.get("/v1/registry/models/loans/versions/v1", headers=keys.read)
            if version.json()["status"] == "ready":
                break
            await asyncio.sleep(0.1)
        assert version.json()["status"] == "ready"
        day = datetime.now(UTC).date() - timedelta(days=1)
        records = prediction_records(traffic(np.random.default_rng(0), 300), day)
        await send_predictions(client, keys.ingest, "loans", records)
        for _ in range(200):  # written and recomputed by the running worker
            r = await client.get("/v1/models/loans", headers=keys.read)
            if r.status_code == 200:
                break
            await asyncio.sleep(0.1)
        assert r.status_code == 200, r.text
        assert r.json()["days"][-1]["rows"] == 300
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=10)  # shuts down promptly and cleanly


async def test_a_failing_loop_backs_off_and_keeps_going(caplog: pytest.LogCaptureFixture) -> None:
    stop = asyncio.Event()
    calls = 0

    async def flaky() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("database blip")
        stop.set()

    await asyncio.wait_for(_forever("flaky", flaky, 0, stop), timeout=5)
    assert calls == 2
    assert "flaky loop failed" in caplog.text


async def test_stop_interrupts_the_wait() -> None:
    stop = asyncio.Event()

    async def job() -> None:
        stop.set()

    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(_forever("slow", job, 3600, stop), timeout=2)
    assert stop.is_set()
