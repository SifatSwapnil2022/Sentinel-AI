"""A background-batching client for Sentinel's ingest API.

Monitoring must never hurt the service it monitors, so:

* ``log_prediction`` and ``log_label`` only append to an in-memory buffer: O(1), no I/O, and
  they never raise. A background thread sends batches.
* The buffer is bounded. If Sentinel is unreachable for long enough to fill it, the oldest
  records are dropped and counted (``stats.dropped``) rather than growing memory or blocking.
* Transient failures (network errors, 429, 5xx) are retried with exponential backoff and
  jitter, honouring ``Retry-After``. A batch the API rejects as invalid (4xx) is not retried:
  it is logged and counted (``stats.rejected``), since resending it cannot succeed.
* ``flush()`` waits for everything buffered to be sent; ``close()`` (also run at interpreter
  exit) flushes with a deadline and stops the thread.
"""

from __future__ import annotations

import atexit
import json
import logging
import math
import random
import threading
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal

import httpx

log = logging.getLogger("sentinel_sdk")

Kind = Literal["predictions", "labels"]
RETRYABLE = frozenset({408, 425, 429, 500, 502, 503, 504})


@dataclass
class Stats:
    """Counters since the client started. Read them to alert on monitoring gaps."""

    sent: int = 0
    """Records the API accepted."""
    dropped: int = 0
    """Records discarded because the buffer was full (oldest first)."""
    rejected: int = 0
    """Records in batches the API refused as invalid."""
    failed: int = 0
    """Records given up on after exhausting retries."""
    invalid: int = 0
    """Records refused locally (not serialisable, bad score), never sent."""
    last_error: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def add(self, **counts: int) -> None:
        """Increment counters atomically."""
        with self._lock:
            for name, n in counts.items():
                setattr(self, name, getattr(self, name) + n)


class Sentinel:
    """Log predictions and labels for one model.

    Example:
        >>> sentinel = Sentinel("https://sentinel.example.com", api_key, model_id="credit-risk")
        >>> sentinel.log_prediction(request_id, features, score=0.82, latency_ms=31.0)
        >>> # later, when the outcome is known
        >>> sentinel.log_label(request_id, 1)
    """

    def __init__(
        self,
        url: str,
        api_key: str,
        *,
        model_id: str,
        version: str | None = None,
        batch_size: int = 500,
        flush_interval: float = 1.0,
        max_buffer: int = 100_000,
        max_retries: int = 6,
        retry_delay: float = 0.5,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Create a client and start its sender thread.

        Args:
            url: Base URL of the Sentinel API.
            api_key: A key with the ``ingest`` scope.
            model_id: The registered model these predictions belong to.
            version: The model version; defaults to the model's active version.
            batch_size: Records per request (the API accepts at most 500).
            flush_interval: Seconds between sends when batches aren't full.
            max_buffer: Records held per kind before the oldest are dropped.
            max_retries: Attempts per batch for transient failures.
            retry_delay: First backoff in seconds; doubles per attempt (with jitter) up to 30.
            timeout: Seconds per HTTP request.
            transport: Custom ``httpx`` transport, for tests.
        """
        if not 1 <= batch_size <= 500:
            raise ValueError("batch_size must be between 1 and 500")
        self.model_id = model_id
        self.version = version
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.stats = Stats()
        self._buffers: dict[Kind, deque[dict[str, Any]]] = {
            "predictions": deque(maxlen=max_buffer),
            "labels": deque(maxlen=max_buffer),
        }
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._idle = threading.Event()
        self._idle.set()
        self._stop = threading.Event()
        self._http = httpx.Client(
            base_url=url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "sentinel-sdk-python/0.1.0",
            },
            timeout=timeout,
            transport=transport,
        )
        self._thread = threading.Thread(target=self._run, name="sentinel-sender", daemon=True)
        self._thread.start()
        atexit.register(self.close)

    # ------------------------------------------------------------------ public API

    def log_prediction(
        self,
        request_id: str,
        features: Mapping[str, Any],
        score: float,
        *,
        prediction: int | None = None,
        ts: datetime | None = None,
        latency_ms: float | None = None,
    ) -> None:
        """Record one prediction. Returns immediately; never raises."""
        try:
            score = float(score)
            if not 0.0 <= score <= 1.0:  # also rejects NaN
                raise ValueError(f"score {score} is outside [0, 1]")
            record: dict[str, Any] = {
                "request_id": str(request_id),
                "ts": (ts or datetime.now(UTC)).isoformat(),
                "features": {str(k): _plain(v) for k, v in features.items()},
                "score": score,
            }
            if prediction is not None:
                record["prediction"] = int(prediction)
            if latency_ms is not None:
                latency = float(latency_ms)
                if not (math.isfinite(latency) and latency >= 0):
                    raise ValueError(f"latency {latency_ms} is not a non-negative number")
                record["latency_ms"] = latency
        except Exception as exc:
            self.stats.add(invalid=1)
            self.stats.last_error = f"invalid prediction {request_id!r}: {exc}"
            log.warning("sentinel: dropping invalid prediction %r: %s", request_id, exc)
            return
        self._append("predictions", record)

    def log_label(self, request_id: str, label: int) -> None:
        """Record the true outcome (0 or 1) of an earlier prediction. Never raises."""
        try:
            value = int(label)
            if value not in (0, 1):
                raise ValueError(f"label {label!r} is not 0 or 1")
        except Exception as exc:
            self.stats.add(invalid=1)
            log.warning("sentinel: dropping invalid label %r: %s", request_id, exc)
            return
        self._append("labels", {"request_id": str(request_id), "label": value})

    def flush(self, timeout: float | None = None) -> bool:
        """Send everything buffered so far; True if it all went out within ``timeout``."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            with self._lock:
                empty = not any(self._buffers.values())
            if empty and self._idle.is_set():
                return True
            if not self._thread.is_alive():
                return False
            self._wake.set()
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                return False
            time.sleep(0.01 if remaining is None else min(0.01, remaining))

    def close(self, timeout: float = 5.0) -> None:
        """Flush (up to ``timeout`` seconds) and stop. Safe to call more than once."""
        if self._stop.is_set():
            return
        self.flush(timeout)
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout=1.0)
        self._http.close()
        atexit.unregister(self.close)
        pending = sum(len(b) for b in self._buffers.values())
        if pending:
            log.warning("sentinel: closed with %d record(s) unsent", pending)

    def __enter__(self) -> Sentinel:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------ internals

    def _append(self, kind: Kind, record: dict[str, Any]) -> None:
        buffer = self._buffers[kind]
        with self._lock:
            if len(buffer) == buffer.maxlen:
                self.stats.add(dropped=1)
            buffer.append(record)
            full = len(buffer) >= self.batch_size
        if full:
            self._wake.set()

    def _take(self, kind: Kind) -> list[dict[str, Any]]:
        buffer = self._buffers[kind]
        with self._lock:
            n = min(len(buffer), self.batch_size)
            batch = [buffer.popleft() for _ in range(n)]
            if batch:
                self._idle.clear()
            return batch

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(self.flush_interval)
            self._wake.clear()
            self._drain()
        self._drain()

    def _drain(self) -> None:
        try:
            for kind in ("predictions", "labels"):  # predictions first: labels refer to them
                while batch := self._take(kind):
                    self._send(kind, batch)
                    self._idle.set()
        except Exception as exc:  # the sender thread must survive anything
            self.stats.last_error = repr(exc)
            log.exception("sentinel: sender error")
        finally:
            self._idle.set()

    def _send(self, kind: Kind, batch: list[dict[str, Any]]) -> None:
        body: dict[str, Any] = {"model_id": self.model_id, kind: batch}
        if kind == "predictions" and self.version is not None:
            body["version"] = self.version
        content = json.dumps(body, default=_plain, allow_nan=False)
        delay = self.retry_delay
        for attempt in range(1, self.max_retries + 1):
            retry_after: float | None = None
            try:
                response = self._http.post(
                    f"/v1/ingest/{kind}",
                    content=content,
                    headers={"Content-Type": "application/json"},
                )
            except httpx.TransportError as exc:
                error = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code == 202:
                    self.stats.add(sent=len(batch))
                    return
                error = f"HTTP {response.status_code}: {response.text[:300]}"
                if response.status_code not in RETRYABLE:
                    self.stats.add(rejected=len(batch))
                    self.stats.last_error = error
                    log.error("sentinel: %d %s rejected: %s", len(batch), kind, error)
                    return
                retry_after = _retry_after(response.headers.get("retry-after"))
            self.stats.last_error = error
            if attempt == self.max_retries or self._stop.is_set():
                break
            wait = retry_after if retry_after is not None else delay * (0.5 + random.random())
            log.debug("sentinel: %s, retrying in %.1fs", error, wait)
            # Wakes early if the client is closing, for one last immediate attempt.
            self._stop.wait(min(wait, 30.0))
            delay = min(delay * 2, 30.0)
        self.stats.add(failed=len(batch))
        log.error("sentinel: gave up on %d %s: %s", len(batch), kind, self.stats.last_error)


def _retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def _plain(value: Any) -> Any:
    """JSON-ready form of a feature value: numpy scalars, dates, NaN as null."""
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, datetime | date):
        return value.isoformat()
    item = getattr(value, "item", None)  # numpy and pandas scalars
    if callable(item):
        return _plain(item())
    raise TypeError(f"feature value of type {type(value).__name__} is not supported")
