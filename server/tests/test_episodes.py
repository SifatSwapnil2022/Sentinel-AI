"""When incidents open and resolve: ``analysis.evaluate`` on hand-built day documents."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sentinel_server.analysis import QUIET_DAYS_TO_RESOLVE, SignalKind, evaluate, rule_holds

REFERENCE = 0.90
START = date(2026, 10, 1)


def day(
    i: int, *, concept: bool | None = False, upper: float = 0.93, mv: bool = False
) -> dict[str, Any]:
    return {
        "date": (START + timedelta(days=i)).isoformat(),
        "estimate": {"accuracy": {"value": upper - 0.02, "lower": upper - 0.04, "upper": upper}},
        "conceptFlag": concept,
        "multivariate": {"drifted": mv},
        "features": {"a": {"drifted": False}, "b": None},
    }


def run(flags: str) -> list[dict[str, Any]]:
    """One day per character: 'C' concept flag, '.' quiet, '?' label check unavailable."""
    return [day(i, concept={"C": True, ".": False, "?": None}[c]) for i, c in enumerate(flags)]


def test_nothing_fired() -> None:
    assert evaluate(REFERENCE, run("..C.C..")) is None  # never two days running


def test_opens_on_the_second_sustained_day() -> None:
    episode = evaluate(REFERENCE, run("...CC.."))
    assert episode is not None
    assert episode.lead.kind is SignalKind.CONCEPT_DRIFT
    assert episode.opened_on == START + timedelta(days=4)
    assert episode.resolved_on is None


def test_resolves_only_after_a_quiet_week() -> None:
    quiet = "." * (QUIET_DAYS_TO_RESOLVE - 1)
    assert evaluate(REFERENCE, run("CC" + quiet)).resolved_on is None  # type: ignore[union-attr]
    episode = evaluate(REFERENCE, run("CC" + quiet + "."))
    assert episode is not None
    assert episode.resolved_on == START + timedelta(days=2)  # the first quiet day


def test_a_relapse_restarts_the_quiet_count() -> None:
    episode = evaluate(REFERENCE, run("CC....C......"))
    assert episode is not None
    assert episode.resolved_on is None


def test_missing_label_evidence_is_not_recovery_but_is_quiet() -> None:
    # '?' means too few labels to check; no rule holds on such a day.
    episode = evaluate(REFERENCE, run("CC" + "?" * QUIET_DAYS_TO_RESOLVE))
    assert episode is not None
    assert episode.resolved_on == START + timedelta(days=2)


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
    episode = evaluate(REFERENCE, days)
    assert episode is not None
    assert {s.kind for s in episode.signals} == {SignalKind.CONCEPT_DRIFT, SignalKind.MULTIVARIATE}
    assert episode.lead.kind is SignalKind.CONCEPT_DRIFT
