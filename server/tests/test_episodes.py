"""When incidents open and resolve: ``analysis.episodes`` on hand-built day documents."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sentinel_server.analysis import (
    QUIET_DAYS_TO_RESOLVE,
    SignalKind,
    episodes,
    rule_holds,
    rules_holding,
)

REFERENCE = 0.90
START = date(2026, 10, 1)


def day(
    i: int,
    *,
    concept: bool | None = False,
    upper: float = 0.93,
    mv: bool = False,
    missing: float = 0.0,
) -> dict[str, Any]:
    return {
        "date": (START + timedelta(days=i)).isoformat(),
        "estimate": {"accuracy": {"value": upper - 0.02, "lower": upper - 0.04, "upper": upper}},
        "conceptFlag": concept,
        "multivariate": {"drifted": mv},
        "features": {"a": {"drifted": False}, "b": None},
        "dataQuality": {
            "a": {"nullRate": 0.01, "referenceNullRate": 0.01},
            "b": {"nullRate": 0.01 + missing, "referenceNullRate": 0.01},
        },
    }


def run(flags: str) -> list[dict[str, Any]]:
    """One day per character: C concept flag, M missing values, . quiet, ? no label check."""
    return [
        day(i, concept={"C": True, "?": None}.get(c, False), missing=0.4 if c == "M" else 0.0)
        for i, c in enumerate(flags)
    ]


def on(i: int) -> date:
    return START + timedelta(days=i)


def test_nothing_fired() -> None:
    assert episodes(REFERENCE, run("..C.C..M.M")) == []  # never the same rule two days running


def test_opens_on_the_second_sustained_day() -> None:
    (episode,) = episodes(REFERENCE, run("...CC.."))
    assert episode.lead.kind is SignalKind.CONCEPT_DRIFT
    assert episode.opened_on == on(4)
    assert episode.resolved_on is None
    assert episode.last_day == on(6)


def test_resolves_after_a_quiet_week_dated_from_the_first_quiet_day() -> None:
    quiet = "." * QUIET_DAYS_TO_RESOLVE
    (still_open,) = episodes(REFERENCE, run("CC" + quiet[:-1]))
    assert still_open.resolved_on is None
    (episode,) = episodes(REFERENCE, run("CC" + quiet))
    assert episode.resolved_on == on(2)
    assert episode.last_day == on(1)


def test_a_relapse_restarts_the_quiet_count() -> None:
    (episode,) = episodes(REFERENCE, run("CC....C......"))
    assert episode.resolved_on is None


def test_history_keeps_every_episode() -> None:
    history = run("CC" + "." * QUIET_DAYS_TO_RESOLVE + "..MM" + "." * 3)
    first, second = episodes(REFERENCE, history)
    assert (first.opened_on, first.resolved_on) == (on(1), on(2))
    assert first.lead.kind is SignalKind.CONCEPT_DRIFT
    assert second.lead.kind is SignalKind.DATA_QUALITY
    assert second.opened_on == on(12)
    assert second.resolved_on is None


def test_missing_label_evidence_counts_as_quiet() -> None:
    (episode,) = episodes(REFERENCE, run("CC" + "?" * QUIET_DAYS_TO_RESOLVE))
    assert episode.resolved_on == on(2)


def test_missing_values_are_a_data_quality_signal() -> None:
    assert rules_holding(REFERENCE, day(0, missing=0.04)) == set()
    assert rules_holding(REFERENCE, day(0, missing=0.06)) == {SignalKind.DATA_QUALITY}
    (warning,) = episodes(REFERENCE, [day(0, missing=0.1), day(1, missing=0.1)])
    assert warning.severity == "warning"
    (critical,) = episodes(REFERENCE, run("MM"))
    assert critical.severity == "critical"


def test_data_quality_leads_the_drop_it_causes() -> None:
    days = [day(i, missing=0.4, upper=0.80) for i in range(3)]
    (episode,) = episodes(REFERENCE, days)
    assert {s.kind for s in episode.signals} == {SignalKind.DATA_QUALITY, SignalKind.ESTIMATE_DROP}
    assert episode.lead.kind is SignalKind.DATA_QUALITY


def test_rule_holds_covers_every_rule() -> None:
    assert not rule_holds(REFERENCE, day(0))
    assert rule_holds(REFERENCE, day(0, concept=True))
    assert rule_holds(REFERENCE, day(0, upper=0.89))
    assert rule_holds(REFERENCE, day(0, mv=True))
    two = day(0)
    two["features"] = {"a": {"drifted": True}, "b": {"drifted": True}}
    assert rule_holds(REFERENCE, two)
    one = day(0)
    one["features"] = {"a": {"drifted": True}, "b": None}
    assert not rule_holds(REFERENCE, one)


def test_earliest_signal_leads_ties_by_priority() -> None:
    days = [day(i, concept=i >= 2, mv=i >= 2) for i in range(5)]
    (episode,) = episodes(REFERENCE, days)
    assert {s.kind for s in episode.signals} == {SignalKind.CONCEPT_DRIFT, SignalKind.MULTIVARIATE}
    assert episode.lead.kind is SignalKind.CONCEPT_DRIFT


def test_days_without_data_quality_are_treated_as_clean() -> None:
    legacy = day(0)
    del legacy["dataQuality"]
    assert rules_holding(REFERENCE, legacy) == set()
