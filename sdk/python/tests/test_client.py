from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from typing import Any

import httpx
import numpy as np
import pytest

from sentinel_sdk import Sentinel

Handler = Callable[[httpx.Request], httpx.Response]


class FakeApi:
    """Records requests; answers with a scripted sequence of status codes, then 202."""

    def __init__(self, script: list[int | Exception] | None = None) -> None:
        self.script = list(script or [])
        self.requests: list[dict[str, Any]] = []
        self.lock = threading.Lock()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        with self.lock:
            step = self.script.pop(0) if self.script else 202
            body = json.loads(request.content)
            self.requests.append({"path": request.url.path, "body": body, "status": step})
        if isinstance(step, Exception):
            raise step
        headers = {"Retry-After": "0"} if step in (429, 503) else {}
        return httpx.Response(step, json={"accepted": 1}, headers=headers)

    def records(self, kind: str) -> list[dict[str, Any]]:
        return [
            r
            for req in self.requests
            if req["path"] == f"/v1/ingest/{kind}" and req["status"] == 202
            for r in req["body"][kind]
        ]


@pytest.fixture
def make() -> Iterator[Callable[..., tuple[Sentinel, FakeApi]]]:
    clients: list[Sentinel] = []

    def factory(
        script: list[int | Exception] | None = None, **kwargs: Any
    ) -> tuple[Sentinel, FakeApi]:
        api = FakeApi(script)
        options = {"flush_interval": 0.02, "retry_delay": 0.01, **kwargs}
        client = Sentinel(
            "http://sentinel.test",
            "snl_test",
            model_id="loans",
            transport=httpx.MockTransport(api),
            **options,
        )
        clients.append(client)
        return client, api

    yield factory
    for c in clients:
        c.close(timeout=0.2)


def test_batches_and_sends(make: Callable[..., tuple[Sentinel, FakeApi]]) -> None:
    client, api = make(batch_size=100)
    for i in range(250):
        client.log_prediction(f"r{i}", {"income": 1000.0 + i, "region": "east"}, score=0.4)
    client.log_label("r0", 1)
    assert client.flush(timeout=2)
    sent = api.records("predictions")
    assert [r["request_id"] for r in sent] == [f"r{i}" for i in range(250)]
    assert max(len(req["body"].get("predictions", [])) for req in api.requests) <= 100
    assert api.records("labels") == [{"request_id": "r0", "label": 1}]
    assert client.stats.sent == 251
    first = api.requests[0]["body"]
    assert first["model_id"] == "loans"
    assert "version" not in first


def test_record_shape(make: Callable[..., tuple[Sentinel, FakeApi]]) -> None:
    client, api = make(version="v2")
    ts = datetime(2026, 10, 24, 9, 30, tzinfo=UTC)
    client.log_prediction(
        "a",
        {
            "n": np.int64(3),
            "x": np.float32(0.5),
            "flag": np.bool_(True),
            "missing": float("nan"),
            "none": None,
            "day": date(2026, 1, 2),
        },
        score=np.float64(0.25),
        prediction=0,
        ts=ts,
        latency_ms=12,
    )
    client.flush(timeout=2)
    body = api.requests[0]["body"]
    assert body["version"] == "v2"
    (record,) = body["predictions"]
    assert record == {
        "request_id": "a",
        "ts": "2026-10-24T09:30:00+00:00",
        "features": {
            "n": 3,
            "x": 0.5,
            "flag": True,
            "missing": None,
            "none": None,
            "day": "2026-01-02",
        },
        "score": 0.25,
        "prediction": 0,
        "latency_ms": 12.0,
    }


@pytest.mark.parametrize(
    "call",
    [
        lambda c: c.log_prediction("a", {"x": 1}, score=1.5),
        lambda c: c.log_prediction("a", {"x": 1}, score=float("nan")),
        lambda c: c.log_prediction("a", {"x": object()}, score=0.5),
        lambda c: c.log_prediction("a", {"x": 1}, score=0.5, latency_ms=float("inf")),
        lambda c: c.log_prediction("a", {"x": 1}, score="high"),
        lambda c: c.log_label("a", 2),
        lambda c: c.log_label("a", "yes"),
    ],
)
def test_bad_input_never_raises(
    make: Callable[..., tuple[Sentinel, FakeApi]], call: Callable[[Sentinel], None]
) -> None:
    client, api = make()
    call(client)  # must not raise into the serving path
    assert client.flush(timeout=1)
    assert client.stats.invalid == 1
    assert api.requests == []


def test_transient_failures_are_retried(make: Callable[..., tuple[Sentinel, FakeApi]]) -> None:
    client, api = make([httpx.ConnectError("refused"), 503, 429, 500])
    client.log_prediction("a", {"x": 1}, score=0.5)
    assert client.flush(timeout=10)
    assert [r["status"] for r in api.requests][-1] == 202
    assert len(api.requests) == 5
    assert client.stats.sent == 1
    assert client.stats.failed == 0


def test_invalid_batches_are_not_retried(make: Callable[..., tuple[Sentinel, FakeApi]]) -> None:
    client, api = make([422])
    client.log_prediction("a", {"x": 1}, score=0.5)
    client.flush(timeout=2)
    assert len(api.requests) == 1
    assert client.stats.rejected == 1
    assert "422" in (client.stats.last_error or "")


def test_gives_up_after_max_retries(make: Callable[..., tuple[Sentinel, FakeApi]]) -> None:
    client, api = make([503] * 10, max_retries=3)
    client.log_prediction("a", {"x": 1}, score=0.5)
    client.flush(timeout=5)
    assert len(api.requests) == 3
    assert client.stats.failed == 1


def test_full_buffer_drops_oldest(make: Callable[..., tuple[Sentinel, FakeApi]]) -> None:
    gate = threading.Event()

    def slow(request: httpx.Request) -> httpx.Response:
        gate.wait(5)
        return httpx.Response(202, json={})

    client = Sentinel(
        "http://sentinel.test",
        "k",
        model_id="loans",
        batch_size=10,
        max_buffer=20,
        flush_interval=0.01,
        transport=httpx.MockTransport(slow),
    )
    try:
        client.log_prediction("first", {}, score=0.5)
        time.sleep(0.1)  # the sender has taken "first" and is blocked sending it
        for i in range(25):
            client.log_prediction(f"r{i}", {}, score=0.5)
        assert client.stats.dropped == 5
        buffered = [r["request_id"] for r in client._buffers["predictions"]]
        assert buffered == [f"r{i}" for i in range(5, 25)]
    finally:
        gate.set()
        client.close(timeout=2)


def test_logging_is_fast_when_api_is_down(make: Callable[..., tuple[Sentinel, FakeApi]]) -> None:
    client, _ = make([httpx.ConnectError("down")] * 1000)
    start = time.perf_counter()
    for i in range(10_000):
        client.log_prediction(f"r{i}", {"x": i}, score=0.5)
    per_call = (time.perf_counter() - start) / 10_000
    assert per_call < 100e-6  # well under 0.1 ms, whatever the network is doing


def test_close_flushes_and_is_idempotent(make: Callable[..., tuple[Sentinel, FakeApi]]) -> None:
    client, api = make(flush_interval=60)  # nothing would be sent on the timer
    client.log_prediction("a", {}, score=0.5)
    client.close(timeout=2)
    client.close()
    assert [r["request_id"] for r in api.records("predictions")] == ["a"]
    with Sentinel("http://x", "k", model_id="m", transport=httpx.MockTransport(api)) as c:
        c.log_label("a", 0)
    assert api.records("labels") == [{"request_id": "a", "label": 0}]


def test_batch_size_is_bounded() -> None:
    with pytest.raises(ValueError, match="batch_size"):
        Sentinel("http://x", "k", model_id="m", batch_size=501)
