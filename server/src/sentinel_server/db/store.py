"""Reads and writes that touch more than one table, as plain SQL.

Bulk paths use ``unnest`` over parallel arrays: one round trip and one statement per batch,
which is several times faster than ``executemany`` and keeps ``ON CONFLICT`` semantics.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, time, timedelta

import numpy as np
import orjson
import pandas as pd
from sqlalchemy import text

from sentinel_server.analysis import CONCEPT_WINDOW_DAYS, UNLABELLED, DayData, FeatureSchema
from sentinel_server.contracts import PredictionRecord

from .partitions import Executor, ensure_partitions


def utc_day(ts: datetime) -> date:
    """The UTC calendar day of a timestamp; days are always bucketed in UTC."""
    return ts.astimezone(UTC).date()


def day_start(day: date) -> datetime:
    """UTC midnight at the start of ``day``."""
    return datetime.combine(day, time.min, tzinfo=UTC)


def affected_days(day: date, today: date) -> list[date]:
    """Days whose documents depend on data from ``day``.

    That is the day itself and the following ones whose rolling label check includes it, up to
    today.
    """
    return [
        day + timedelta(days=k)
        for k in range(CONCEPT_WINDOW_DAYS)
        if day + timedelta(days=k) <= today
    ]


async def insert_predictions(
    conn: Executor, model_id: str, version_id: int, records: Sequence[PredictionRecord]
) -> tuple[int, set[date]]:
    """Write predictions, skipping exact retries.

    Returns how many rows were new, and the UTC days that received them.
    """
    if not records:
        return 0, set()
    await ensure_partitions(conn, {utc_day(r.ts) for r in records})
    result = await conn.execute(
        text(
            """
            INSERT INTO predictions
                (model_id, request_id, ts, version_id, features, score, prediction, latency_ms)
            SELECT :model_id, r, t, :version_id, f::jsonb, s, p, l
            FROM unnest(
                CAST(:request_ids AS text[]),
                CAST(:ts AS timestamptz[]),
                CAST(:features AS text[]),
                CAST(:scores AS float8[]),
                CAST(:predictions AS int2[]),
                CAST(:latencies AS float8[])
            ) AS u(r, t, f, s, p, l)
            ON CONFLICT DO NOTHING
            RETURNING ts
            """
        ),
        {
            "model_id": model_id,
            "version_id": version_id,
            "request_ids": [r.request_id for r in records],
            "ts": [r.ts for r in records],
            "features": [orjson.dumps(r.features).decode() for r in records],
            "scores": [r.score for r in records],
            "predictions": [r.prediction for r in records],
            "latencies": [r.latency_ms for r in records],
        },
    )
    inserted = [row[0] for row in result]
    return len(inserted), {utc_day(ts) for ts in inserted}


async def upsert_labels(
    conn: Executor, model_id: str, labels: Sequence[tuple[str, int]]
) -> dict[int, set[date]]:
    """Write labels (a later label for the same request replaces the earlier one).

    Returns, per model version, the UTC days of predictions whose label is new or changed.
    Labels for predictions not yet received are stored and picked up when they arrive.
    """
    if not labels:
        return {}
    latest = dict(labels)  # one batch may repeat a request; the last label wins
    changed = await conn.execute(
        text(
            """
            INSERT INTO labels (model_id, request_id, label)
            SELECT :model_id, r, l FROM unnest(CAST(:ids AS text[]), CAST(:labels AS int2[]))
                AS u(r, l)
            ON CONFLICT (model_id, request_id) DO UPDATE
                SET label = excluded.label, received_at = now()
                WHERE labels.label IS DISTINCT FROM excluded.label
            RETURNING request_id
            """
        ),
        {"model_id": model_id, "ids": list(latest), "labels": list(latest.values())},
    )
    ids = [row[0] for row in changed]
    if not ids:
        return {}
    rows = await conn.execute(
        text(
            """
            SELECT DISTINCT version_id, (ts AT TIME ZONE 'UTC')::date
            FROM predictions WHERE model_id = :model_id AND request_id = ANY(:ids)
            """
        ),
        {"model_id": model_id, "ids": ids},
    )
    days: dict[int, set[date]] = defaultdict(set)
    for version_id, day in rows:
        days[int(version_id)].add(day)
    return dict(days)


async def mark_dirty(conn: Executor, pairs: Iterable[tuple[int, date]]) -> int:
    """Queue (version, day) documents for recomputation; repeated marks just refresh the time."""
    unique = sorted(set(pairs))
    if not unique:
        return 0
    await conn.execute(
        text(
            """
            INSERT INTO dirty_days (version_id, day)
            SELECT v, d FROM unnest(CAST(:versions AS int8[]), CAST(:days AS date[])) AS u(v, d)
            ON CONFLICT (version_id, day) DO UPDATE SET marked_at = now()
            """
        ),
        {"versions": [v for v, _ in unique], "days": [d for _, d in unique]},
    )
    return len(unique)


async def load_days(
    conn: Executor, version_id: int, schema: FeatureSchema, first: date, last: date
) -> dict[date, DayData]:
    """Every prediction of a version from ``first`` to ``last`` inclusive, with labels so far.

    Rows come back in time order so that results which depend on order (example rows) are
    reproducible.
    """
    result = await conn.execute(
        text(
            """
            SELECT p.ts, p.features::text, p.score, p.prediction, p.latency_ms,
                   coalesce(l.label, :unlabelled)
            FROM predictions p
            LEFT JOIN labels l ON l.model_id = p.model_id AND l.request_id = p.request_id
            WHERE p.version_id = :version_id AND p.ts >= :start AND p.ts < :end
            ORDER BY p.ts, p.request_id
            """
        ),
        {
            "version_id": version_id,
            "start": day_start(first),
            "end": day_start(last + timedelta(days=1)),
            "unlabelled": UNLABELLED,
        },
    )
    rows = result.all()
    if not rows:
        return {}
    ts = pd.DatetimeIndex([r[0] for r in rows]).tz_convert(UTC)
    days = ts.date
    frame = schema.coerce(
        pd.DataFrame.from_records([orjson.loads(r[1]) for r in rows], columns=schema.names)
    )
    proba = np.fromiter((r[2] for r in rows), dtype=np.float64, count=len(rows))
    pred = np.fromiter((r[3] for r in rows), dtype=np.int64, count=len(rows))
    latency = np.array([np.nan if r[4] is None else r[4] for r in rows], dtype=np.float64)
    outcome = np.fromiter((r[5] for r in rows), dtype=np.int64, count=len(rows))

    out: dict[date, DayData] = {}
    for day in sorted(set(days)):
        mask = days == day
        out[day] = DayData(
            date=day,
            frame=frame[mask].reset_index(drop=True),
            proba=proba[mask],
            pred=pred[mask],
            outcome=outcome[mask],
            latency_ms=latency[mask],
        )
    return out
