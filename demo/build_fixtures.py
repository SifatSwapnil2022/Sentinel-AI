"""Build the dashboard's demo data by running synthetic production traffic through Sentinel.

Every number comes from the same analysis code the API's worker runs
(``sentinel_server.analysis``); only the traffic is synthetic.

Usage:
    uv run python demo/build_fixtures.py [--out web/public/data]

The output is deterministic for a given seed, so the committed JSON only changes when the
engine, the analysis or the scenarios change.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from scenarios import MODELS, ModelSpec, TrainedModel, intensity, sample, train
from sentinel_server.analysis import (
    CONCEPT_WINDOW_DAYS,
    UNLABELLED,
    DayData,
    ModelInfo,
    compute_day,
    concat,
    evaluate,
    fleet_document,
    incident_document,
    investigate,
    model_document,
    model_summary,
)

TODAY = date(2026, 10, 24)
DAYS = 30
SEED = 20261024
REFERENCE_ROWS = 20_000


def simulate(
    spec: ModelSpec, trained: TrainedModel, rng: np.random.Generator, today: date = TODAY
) -> list[DayData]:
    """Thirty days of production traffic up to ``today``; labels arrive after a random delay."""
    days = []
    for i in range(DAYS):
        n = int(spec.daily_rows * rng.uniform(0.88, 1.12))
        frame, outcome = sample(spec, rng, n, intensity(spec, i))
        proba = trained.predict(frame)
        age = DAYS - 1 - i  # days since these predictions were made
        lag = rng.uniform(1, spec.label_delay_days, n)
        latency = rng.lognormal(np.log(spec.latency_ms), 0.25, n)
        days.append(
            DayData(
                date=today - timedelta(days=age),
                frame=trained.monitors.schema.coerce(frame),
                proba=proba,
                pred=(proba >= 0.5).astype(np.int64),
                outcome=np.where(lag <= age, outcome, UNLABELLED),
                latency_ms=latency,
            )
        )
    return days


def prepare(
    spec: ModelSpec, rng: np.random.Generator, today: date = TODAY
) -> tuple[TrainedModel, list[DayData]]:
    """Train the model and generate its traffic.

    Both the static demo and the live pipeline (see the server's parity test) start from these.
    """
    trained = train(spec, rng, reference_rows=REFERENCE_ROWS)
    return trained, simulate(spec, trained, rng, today)


def build_model(
    spec: ModelSpec, rng: np.random.Generator
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    return documents(spec, *prepare(spec, rng))


def documents(
    spec: ModelSpec, trained: TrainedModel, data: list[DayData]
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Overview row, model page and incidents, computed in memory."""
    monitors = trained.monitors
    today = data[-1].date

    day_docs = []
    for i in range(len(data)):
        doc = compute_day(monitors, data[max(0, i - CONCEPT_WINDOW_DAYS + 1) : i + 1])
        if doc is not None:
            day_docs.append(doc)

    incidents = []
    episode = evaluate(monitors.reference_accuracy, day_docs)
    if episode is not None and episode.resolved_on is None:
        opened = episode.opened_on
        # Same bounds as the worker: the day before it opened, at most two weeks back.
        window_from = max(opened - timedelta(days=1), today - timedelta(days=13))
        span = concat([d for d in data if d.date >= window_from])
        incidents.append(
            incident_document(
                incident_id=f"{spec.id}-1",
                model_id=spec.id,
                signals=episode.signals,
                lead=episode.lead,
                opened_on=opened,
                window_from=window_from,
                window_to=today,
                investigation=investigate(monitors, episode.lead.kind, span),
                latest_day=day_docs[-1],
                monitors=monitors,
            )
        )

    info = ModelInfo(
        id=spec.id,
        name=spec.name,
        version=spec.version,
        team=spec.team,
        description=spec.description,
        label_delay_days=spec.label_delay_days,
    )
    return (
        model_summary(info, monitors, day_docs, incidents),
        model_document(info, monitors, day_docs, [i["id"] for i in incidents]),
        incidents,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("web/public/data"))
    args = parser.parse_args()
    out: Path = args.out
    (out / "models").mkdir(parents=True, exist_ok=True)
    (out / "alerts").mkdir(parents=True, exist_ok=True)

    summaries, all_incidents = [], []
    for k, spec in enumerate(MODELS):
        summary, model_doc, incidents = build_model(spec, np.random.default_rng(SEED + k))
        summaries.append(summary)
        all_incidents.extend(incidents)
        _write(out / "models" / f"{spec.id}.json", model_doc)
        for incident in incidents:
            _write(out / "alerts" / f"{incident['id']}.json", incident)
        print(f"{spec.id}: {summary['status']:<8} incidents={len(incidents)}")

    _write(out / "fleet.json", fleet_document(TODAY, DAYS, summaries, all_incidents))


def _write(path: Path, doc: dict[str, Any]) -> None:
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
