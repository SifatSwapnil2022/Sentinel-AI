r"""Stream the demo scenarios into a running Sentinel, the way a real deployment would.

Registers each model, uploads its reference data, waits for the monitors to fit, then replays
thirty days of traffic through the Python SDK, with each label sent only once it would have
arrived. The dashboard pointed at that Sentinel then shows the same picture as the static demo
(``build_fixtures.py``), computed live.

Usage:
    uv run python demo/simulate.py --url http://localhost:8000 \\
        --admin-key snl_... --ingest-key snl_... [--models credit-risk,fraud-screen]
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime, timedelta
from datetime import time as dtime

import httpx
import numpy as np
import pandas as pd

from build_fixtures import SEED, prepare
from scenarios import MODELS, ModelSpec
from sentinel_sdk import Sentinel
from sentinel_server.analysis import DayData


def register(http: httpx.Client, spec: ModelSpec, reference: pd.DataFrame) -> None:
    r = http.put(
        f"/v1/registry/models/{spec.id}",
        json={
            "name": spec.name,
            "team": spec.team,
            "description": spec.description,
            "label_delay_days": spec.label_delay_days,
        },
    )
    r.raise_for_status()
    r = http.post(
        f"/v1/registry/models/{spec.id}/versions",
        data={"version": spec.version},
        files={"reference": ("reference.csv", reference.to_csv(index=False).encode(), "text/csv")},
    )
    if r.status_code == 409:
        print(f"  {spec.id} {spec.version} already registered")
        return
    r.raise_for_status()
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        status = http.get(f"/v1/registry/models/{spec.id}/versions/{spec.version}").json()
        if status["status"] == "ready":
            return
        if status["status"] == "failed":
            raise RuntimeError(f"{spec.id}: fitting failed: {status['error']}")
        time.sleep(1)
    raise TimeoutError(f"{spec.id}: monitors not fitted after 5 minutes")


def replay(sentinel: Sentinel, spec: ModelSpec, days: list[DayData], now: datetime) -> int:
    """Send the scenario's traffic, ending now; returns the number of predictions sent."""
    sent = 0
    for day in days:
        start = datetime.combine(day.date, dtime.min, tzinfo=UTC)
        # Spread the day's traffic over the day, but never past now.
        span = min(86_400.0, (now - start).total_seconds() - 1)
        step = span / max(day.rows, 1)
        frame = day.frame.astype(object).where(day.frame.notna(), None)
        rows = frame.to_dict("records")
        for i in range(day.rows):
            request_id = f"{spec.id}-{day.date:%Y%m%d}-{i:05d}"
            sentinel.log_prediction(
                request_id,
                rows[i],
                score=float(day.proba[i]),
                ts=start + timedelta(seconds=i * step),
                latency_ms=float(day.latency_ms[i]) if day.latency_ms is not None else None,
            )
            if day.outcome[i] >= 0:
                sentinel.log_label(request_id, int(day.outcome[i]))
        sent += day.rows
    return sent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--admin-key", required=True)
    parser.add_argument("--ingest-key", required=True)
    parser.add_argument("--models", default=",".join(m.id for m in MODELS))
    args = parser.parse_args()
    wanted = set(args.models.split(","))

    admin = httpx.Client(
        base_url=args.url, headers={"Authorization": f"Bearer {args.admin_key}"}, timeout=120
    )
    for index, spec in enumerate(MODELS):
        if spec.id not in wanted:
            continue
        print(f"{spec.id}: training and uploading reference")
        now = datetime.now(UTC)
        trained, days = prepare(spec, np.random.default_rng(SEED + index), now.date())
        register(admin, spec, trained.reference)
        started = time.perf_counter()
        with Sentinel(args.url, args.ingest_key, model_id=spec.id, max_buffer=500_000) as sentinel:
            n = replay(sentinel, spec, days, now)
            sentinel.flush(timeout=300)
            stats = sentinel.stats
        elapsed = time.perf_counter() - started
        print(
            f"{spec.id}: {n:,} predictions in {elapsed:.1f}s ({n / elapsed:,.0f}/s); "
            f"sent {stats.sent:,}, dropped {stats.dropped}, failed {stats.failed}, "
            f"rejected {stats.rejected}"
        )
        if stats.dropped or stats.failed or stats.rejected:
            print(f"  last error: {stats.last_error}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
