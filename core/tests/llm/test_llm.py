from __future__ import annotations

import pytest

from sentinel_core.llm import (
    DayMetrics,
    LLMRule,
    LLMTrace,
    day_metrics,
    evaluate,
    find_pii,
    is_refusal,
    topic_shift,
    unsupported_sentences,
)

CONTEXT = (
    "Card replacement costs 300 taka and takes 7 working days. "
    "Lost cards can be blocked from the app under Cards, then Block card."
)


def test_grounded_answer_passes() -> None:
    answer = "Replacing a card costs 300 taka. It takes 7 working days."
    assert unsupported_sentences(answer, CONTEXT) == []


def test_invented_number_is_flagged_even_with_overlap() -> None:
    answer = "Card replacement costs 500 taka and takes 7 working days."
    assert unsupported_sentences(answer, CONTEXT) == [answer]


def test_invented_policy_is_flagged() -> None:
    answer = "You can also get a free premium upgrade with cashback rewards every month."
    assert len(unsupported_sentences(answer, CONTEXT)) == 1


def test_no_context_means_no_judgement() -> None:
    assert unsupported_sentences("Anything at all goes here today.", "") == []


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("Call 01712345678 for help.", True),
        ("Call +8801912345678 for help.", True),
        ("Email rahim.uddin@example.com today.", True),
        ("Card 4111 1111 1111 1111 is active.", True),  # Luhn-valid test number
        ("Reference 4111 1111 1111 1112 is active.", False),  # fails Luhn
        ("The fee is 300 taka for 7 days.", False),
    ],
)
def test_find_pii(text: str, found: bool) -> None:
    assert bool(find_pii(text)) is found


def test_refusal() -> None:
    assert is_refusal("Sorry, I can't help with that request.")
    assert not is_refusal("Here is how to block your card.")


def _trace(**kw: object) -> LLMTrace:
    base: dict[str, object] = {
        "day": "2026-10-01",
        "prompt_version": "v1",
        "topic": "cards",
        "input_tokens": 1000,
        "output_tokens": 200,
        "latency_ms": 800.0,
        "status": "ok",
        "answer": "Card replacement costs 300 taka.",
        "context": CONTEXT,
    }
    base.update(kw)
    return LLMTrace(**base)  # type: ignore[arg-type]


def test_day_metrics_counts_and_cost() -> None:
    traces = [
        _trace(feedback=1),
        _trace(answer="It costs 900 taka.", feedback=-1),
        _trace(status="error", answer=""),
        _trace(answer="Call 01712345678 now for card help."),
    ]
    m = day_metrics("2026-10-01", traces, price_in=1.0, price_out=4.0)
    assert (m.requests, m.errors, m.answered) == (4, 1, 3)
    assert m.unsupported == 2  # the invented fee, and the answer quoting a number not in context
    assert m.pii == 1
    assert (m.feedback, m.negative) == (2, 1)
    # errors still cost their input tokens; only answered calls produce output tokens
    assert m.cost_usd == pytest.approx((4000 * 1 + 600 * 4) / 1e6)


def test_topic_shift_bounds() -> None:
    assert topic_shift({"a": 5, "b": 5}, {"a": 50, "b": 50}) == pytest.approx(0.0)
    assert topic_shift({"a": 10}, {"b": 10}) == pytest.approx(1.0)


def _day(**kw: object) -> DayMetrics:
    base: dict[str, object] = {
        "day": "d",
        "requests": 2000,
        "errors": 20,
        "answered": 1980,
        "unsupported": 80,
        "pii": 0,
        "refusals": 10,
        "feedback": 200,
        "negative": 20,
        "input_tokens": 0,
        "output_tokens": 0,
        "p50_latency_ms": 700.0,
        "p95_latency_ms": 1500.0,
        "cost_usd": 0.0,
        "topics": {"cards": 1000, "fees": 1000},
    }
    base.update(kw)
    return DayMetrics(**base)  # type: ignore[arg-type]


REFERENCE = [_day() for _ in range(14)]


def test_normal_day_is_quiet() -> None:
    assert (
        evaluate(_day(unsupported=95, errors=28, negative=27, p95_latency_ms=1800), REFERENCE) == []
    )


def test_each_rule_fires() -> None:
    rules = {
        s.rule
        for s in evaluate(
            _day(
                unsupported=300,
                errors=150,
                negative=60,
                p95_latency_ms=3000,
                pii=2,
                topics={"cards": 300, "fees": 300, "loans": 1400},
            ),
            REFERENCE,
        )
    }
    assert rules == set(LLMRule)


def test_severity() -> None:
    (unsupported,) = evaluate(_day(unsupported=300), REFERENCE)
    assert unsupported.severity == "critical"  # 15% against 4%
    (pii,) = evaluate(_day(pii=1), [])
    assert pii.severity == "critical"


def test_incident_lifecycle() -> None:
    from sentinel_core.llm import LLMSignal, incidents

    dates = [f"2026-10-{d:02d}" for d in range(1, 21)]
    warn = [LLMSignal(LLMRule.LATENCY, "warning", 3000, 1500)]
    leak = [LLMSignal(LLMRule.PII, "critical", 1, 0)]
    signals: list[list[LLMSignal]] = [[] for _ in dates]
    signals[2] = warn  # one day alone: no incident
    signals[5] = signals[6] = signals[7] = warn
    signals[18] = leak
    latency, pii = incidents(dates, signals)
    assert (latency.rule, latency.opened_on, latency.resolved_on) == (
        LLMRule.LATENCY,
        "2026-10-07",
        "2026-10-09",
    )
    assert (pii.rule, pii.opened_on, pii.resolved_on, pii.severity) == (
        LLMRule.PII,
        "2026-10-19",
        None,
        "critical",
    )


def test_overlapping_rules_are_one_incident_but_pii_stands_alone() -> None:
    from sentinel_core.llm import LLMSignal, incidents

    dates = [f"2026-10-{d:02d}" for d in range(1, 21)]
    slow = LLMSignal(LLMRule.LATENCY, "warning", 3000, 1500)
    failing = LLMSignal(LLMRule.ERRORS, "critical", 0.2, 0.01)
    leak = LLMSignal(LLMRule.PII, "critical", 1, 0)
    signals: list[list[LLMSignal]] = [[] for _ in dates]
    signals[3] = [slow]
    signals[4] = [slow, failing, leak]
    signals[5] = [failing]
    pii, outage = incidents(dates, signals)  # opened the same day; PII ranks first
    assert outage.rule is LLMRule.LATENCY
    assert outage.rules == [LLMRule.LATENCY, LLMRule.ERRORS]
    assert outage.severity == "critical"
    assert pii.rules == [LLMRule.PII]
