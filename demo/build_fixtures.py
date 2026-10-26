"""Build the dashboard's demo data by running synthetic production traffic through Sentinel.

Every number comes from the same analysis code the API's worker runs
(``sentinel_server.analysis``); only the traffic is synthetic.

Usage:
    uv run python demo/build_fixtures.py [--out web/public/data]

Writes the documents the dashboard reads (``fleet.json``, ``fleet-daily.json``, ``models/``,
``alerts/``) and the BI star schema as CSV (``bi/``). The output is deterministic for a given
seed, so the committed files only change when the engine, the analysis or the scenarios do.
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
    TABLES,
    UNLABELLED,
    DayData,
    ModelInfo,
    bi_tables,
    compute_day,
    concat,
    episode_document,
    episodes,
    fleet_daily,
    fleet_document,
    investigation_window,
    model_document,
    model_summary,
    segment_table,
    to_csv,
)

TODAY = date(2026, 10, 24)
DAYS = 90
SEED = 20261024
REFERENCE_ROWS = 20_000
SEGMENT_DAYS = 7
"""Segments compare the reference with the last week of traffic."""


def simulate(
    spec: ModelSpec,
    trained: TrainedModel,
    rng: np.random.Generator,
    today: date = TODAY,
    days: int = DAYS,
) -> list[DayData]:
    """``days`` days of production traffic up to ``today``; labels arrive after a random delay."""
    out = []
    for i in range(days):
        n = int(spec.daily_rows * rng.uniform(0.88, 1.12))
        frame, outcome = sample(spec, rng, n, intensity(spec, i, days))
        proba = trained.predict(frame)
        age = days - 1 - i  # days since these predictions were made
        lag = rng.uniform(1, spec.label_delay_days, n)
        latency = rng.lognormal(np.log(spec.latency_ms), 0.25, n)
        out.append(
            DayData(
                date=today - timedelta(days=age),
                frame=trained.monitors.schema.coerce(frame),
                proba=proba,
                pred=(proba >= 0.5).astype(np.int64),
                outcome=np.where(lag <= age, outcome, UNLABELLED),
                latency_ms=latency,
            )
        )
    return out


def prepare(
    spec: ModelSpec, rng: np.random.Generator, today: date = TODAY, days: int = DAYS
) -> tuple[TrainedModel, list[DayData]]:
    """Train the model and generate its traffic.

    Both the static demo and the live pipeline (see the server's parity test) start from these.
    """
    trained = train(spec, rng, reference_rows=REFERENCE_ROWS)
    return trained, simulate(spec, trained, rng, today, days)


def build_model(
    spec: ModelSpec, rng: np.random.Generator
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    return documents(spec, *prepare(spec, rng))


def documents(
    spec: ModelSpec, trained: TrainedModel, data: list[DayData]
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Overview row, model page and incidents (oldest first), computed in memory."""
    monitors = trained.monitors
    day_docs = []
    for i in range(len(data)):
        doc = compute_day(monitors, data[max(0, i - CONCEPT_WINDOW_DAYS + 1) : i + 1])
        if doc is not None:
            day_docs.append(doc)
    by_date = {d["date"]: d for d in day_docs}

    incidents = []
    for k, episode in enumerate(episodes(monitors.reference_accuracy, day_docs), start=1):
        start, end = investigation_window(episode)
        span = concat([d for d in data if start <= d.date <= end])
        incidents.append(
            episode_document(f"{spec.id}-{k}", spec.id, episode, span, by_date, monitors)
        )

    info = ModelInfo(
        id=spec.id,
        name=spec.name,
        version=spec.version,
        team=spec.team,
        description=spec.description,
        label_delay_days=spec.label_delay_days,
    )
    open_incidents = [i for i in incidents if i["status"] == "open"]
    segments = segment_table(monitors, concat(data[-SEGMENT_DAYS:]))
    return (
        model_summary(info, monitors, day_docs, open_incidents),
        model_document(info, monitors, day_docs, [i["id"] for i in reversed(incidents)], segments),
        incidents,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("web/public/data"))
    args = parser.parse_args()
    out: Path = args.out
    for sub in ("models", "alerts", "bi"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    for stale in (*(out / "models").glob("*.json"), *(out / "alerts").glob("*.json")):
        stale.unlink()

    summaries, model_docs, all_incidents = [], [], []
    for k, spec in enumerate(MODELS):
        summary, model_doc, incidents = build_model(spec, np.random.default_rng(SEED + k))
        summaries.append(summary)
        model_docs.append(model_doc)
        all_incidents.extend(incidents)
        _write(out / "models" / f"{spec.id}.json", model_doc)
        for incident in incidents:
            _write(out / "alerts" / f"{incident['id']}.json", incident)
        states = ", ".join(f"{i['id']} {i['status']}" for i in incidents) or "no incidents"
        print(f"{spec.id:18} {summary['status']:8} {states}")

    open_incidents = [i for i in all_incidents if i["status"] == "open"]
    resolved = [i for i in all_incidents if i["status"] == "resolved"]
    fleet = fleet_document(TODAY, DAYS, summaries, open_incidents, resolved)
    _write(out / "fleet.json", fleet)
    _write(out / "fleet-daily.json", fleet_daily(model_docs))
    tables = bi_tables(fleet, model_docs, all_incidents)
    for name in TABLES:
        (out / "bi" / f"{name}.csv").write_text(to_csv(tables[name]))


def _write(path: Path, doc: dict[str, Any]) -> None:
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
