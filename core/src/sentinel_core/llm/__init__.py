"""Monitoring for LLM applications: per-call checks, daily metrics and alert rules.

An LLM call is logged as a trace: prompt version, topic, tokens, latency, status, the context
the answer was meant to use (for retrieval-augmented apps), the answer, and user feedback when
there is any. Three checks run on each trace without calling another model:

- **Unsupported answer.** Each answer sentence is compared with the retrieved context. A sentence
  whose content words and numbers mostly don't appear in the context is unsupported. This is a
  lexical check: cheap, deterministic and explainable, it catches invented figures and policies
  but not paraphrases that change meaning. An LLM judge can replace it behind the same interface.
- **PII in the answer.** Email addresses, Bangladeshi mobile numbers and card numbers (Luhn
  checked) that the answer exposes.
- **Refusal.** The answer declines instead of helping.

Daily metrics are compared with a reference window (the app's normal weeks); see ``evaluate``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from math import sqrt

import numpy as np

__all__ = [
    "DayMetrics",
    "LLMIncident",
    "LLMRule",
    "LLMSignal",
    "LLMTrace",
    "Thresholds",
    "day_metrics",
    "evaluate",
    "find_pii",
    "incidents",
    "is_refusal",
    "topic_shift",
    "unsupported_sentences",
]

_STOP = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "if",
        "then",
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "for",
        "with",
        "from",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "you",
        "your",
        "we",
        "our",
        "they",
        "their",
        "i",
        "me",
        "my",
        "he",
        "she",
        "his",
        "her",
        "them",
        "can",
        "will",
        "would",
        "should",
        "could",
        "may",
        "might",
        "do",
        "does",
        "did",
        "not",
        "no",
        "yes",
        "so",
        "than",
        "too",
        "very",
        "just",
        "also",
        "into",
        "about",
        "there",
        "here",
        "what",
        "which",
        "who",
        "whom",
        "when",
        "where",
        "how",
        "all",
        "any",
        "each",
        "per",
        "has",
        "have",
        "had",
    ]
)
_WORD = re.compile(r"[a-z]+|\d+(?:[.,]\d+)?")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_BD_PHONE = re.compile(r"(?<!\d)(?:\+?880|0)1[3-9]\d{8}(?!\d)")
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_REFUSAL = re.compile(
    r"\b(i can(?:no|')t help|i'm (?:not able|unable) to|i am (?:not able|unable) to|"
    r"i cannot (?:assist|help|share)|i can't (?:assist|share))\b"
)


@dataclass(frozen=True)
class LLMTrace:
    """One LLM call, as an app logs it."""

    day: str
    prompt_version: str
    topic: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    status: str  # "ok", "error" or "timeout"
    answer: str = ""
    context: str = ""
    feedback: int | None = None  # +1, -1, or None when the user gave none


def _content(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 1]


def unsupported_sentences(answer: str, context: str, min_support: float = 0.6) -> list[str]:
    """Answer sentences whose content words and numbers are mostly absent from the context.

    Numbers must match exactly: an answer quoting a fee the context doesn't contain is
    unsupported however many other words overlap.
    """
    if not context.strip():
        return []
    known = set(_content(context))
    flagged = []
    for sentence in _SENTENCE.split(answer.strip()):
        words = _content(sentence)
        if len(words) < 3:
            continue
        numbers = [w for w in words if w[0].isdigit()]
        support = sum(w in known for w in words) / len(words)
        if support < min_support or any(n not in known for n in numbers):
            flagged.append(sentence)
    return flagged


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def find_pii(text: str) -> list[str]:
    """Personal data in text: emails, Bangladeshi mobile numbers, and Luhn-valid card numbers."""
    found = _EMAIL.findall(text) + _BD_PHONE.findall(text)
    for match in _CARD.findall(text):
        digits = re.sub(r"\D", "", match)
        if 13 <= len(digits) <= 19 and _luhn(digits):
            found.append(match.strip())
    return found


def is_refusal(answer: str) -> bool:
    """The answer declines to help instead of answering."""
    return bool(_REFUSAL.search(answer.lower()))


@dataclass
class DayMetrics:
    """One day of an LLM app, overall or for one prompt version."""

    day: str
    requests: int
    errors: int
    answered: int
    unsupported: int
    pii: int
    refusals: int
    feedback: int
    negative: int
    input_tokens: int
    output_tokens: int
    p50_latency_ms: float
    p95_latency_ms: float
    cost_usd: float
    topics: dict[str, int] = field(default_factory=dict)

    @property
    def error_rate(self) -> float:
        """Failed or timed-out calls as a share of requests."""
        return self.errors / self.requests if self.requests else 0.0

    @property
    def unsupported_rate(self) -> float:
        """Answers with an unsupported sentence, as a share of answered calls."""
        return self.unsupported / self.answered if self.answered else 0.0

    @property
    def negative_rate(self) -> float:
        """Thumbs-down as a share of answers that got any feedback."""
        return self.negative / self.feedback if self.feedback else 0.0


def day_metrics(
    day: str,
    traces: Sequence[LLMTrace],
    price_in: float,
    price_out: float,
) -> DayMetrics:
    """Aggregate one day's traces. Prices are US dollars per million tokens."""
    ok = [t for t in traces if t.status == "ok"]
    latency = np.array([t.latency_ms for t in traces]) if traces else np.zeros(1)
    topics: dict[str, int] = {}
    for t in traces:
        topics[t.topic] = topics.get(t.topic, 0) + 1
    tokens_in = sum(t.input_tokens for t in traces)
    tokens_out = sum(t.output_tokens for t in ok)
    rated = [t for t in ok if t.feedback is not None]
    return DayMetrics(
        day=day,
        requests=len(traces),
        errors=len(traces) - len(ok),
        answered=len(ok),
        unsupported=sum(
            not is_refusal(t.answer) and bool(unsupported_sentences(t.answer, t.context))
            for t in ok
        ),
        pii=sum(bool(find_pii(t.answer)) for t in ok),
        refusals=sum(is_refusal(t.answer) for t in ok),
        feedback=len(rated),
        negative=sum(t.feedback == -1 for t in rated),
        input_tokens=tokens_in,
        output_tokens=tokens_out,
        p50_latency_ms=float(np.percentile(latency, 50)),
        p95_latency_ms=float(np.percentile(latency, 95)),
        cost_usd=(tokens_in * price_in + tokens_out * price_out) / 1e6,
        topics=topics,
    )


def topic_shift(reference: dict[str, int], current: dict[str, int]) -> float:
    """Jensen–Shannon distance (base 2, 0 to 1) between two topic mixes."""
    keys = sorted(set(reference) | set(current))
    p = np.array([reference.get(k, 0) for k in keys], dtype=float)
    q = np.array([current.get(k, 0) for k in keys], dtype=float)
    if p.sum() == 0 or q.sum() == 0:
        return 0.0
    p, q = p / p.sum(), q / q.sum()
    m = (p + q) / 2

    def kl(a: np.ndarray, b: np.ndarray) -> float:
        mask = a > 0
        return float(np.sum(a[mask] * np.log2(a[mask] / b[mask])))

    return sqrt(max((kl(p, m) + kl(q, m)) / 2, 0.0))


class LLMRule(StrEnum):
    """The checks that can open an LLM incident."""

    PII = "pii_leak"
    UNSUPPORTED = "unsupported_answers"
    ERRORS = "errors"
    LATENCY = "latency"
    NEGATIVE = "negative_feedback"
    TOPICS = "topic_shift"


@dataclass(frozen=True)
class Thresholds:
    """When a daily metric counts as a failing check."""

    z: float = 3.0
    """A rate alerts when it is this many standard errors above its reference rate."""
    min_rise: float = 0.02
    """...and at least this much higher in absolute terms, so tiny rates don't page anyone."""
    latency_ratio: float = 1.5
    """p95 latency alerts at this multiple of the reference p95."""
    topic_distance: float = 0.15
    """Jensen–Shannon distance of the topic mix from the reference."""


@dataclass(frozen=True)
class LLMSignal:
    """One failing check on one day, with the value that failed and its reference."""

    rule: LLMRule
    severity: str
    value: float
    reference: float


def _rate_rise(count: int, n: int, ref_rate: float, t: Thresholds) -> bool:
    if n == 0:
        return False
    rate = count / n
    se = sqrt(max(ref_rate * (1 - ref_rate), 1e-6) / n)
    return rate - ref_rate >= t.min_rise and (rate - ref_rate) / se >= t.z


def evaluate(
    day: DayMetrics, reference: Iterable[DayMetrics], thresholds: Thresholds | None = None
) -> list[LLMSignal]:
    """Rules that fail on ``day`` against the reference days.

    Any PII in an answer is critical on its own. Rates (unsupported answers, errors, negative
    feedback) use a one-sided binomial test against the pooled reference rate plus a minimum
    absolute rise. Latency compares p95s; topics compare mixes.
    """
    t = thresholds or Thresholds()
    ref = list(reference)
    signals: list[LLMSignal] = []
    if day.pii > 0:
        signals.append(LLMSignal(LLMRule.PII, "critical", day.pii, 0))
    if not ref:
        return signals

    answered = sum(r.answered for r in ref)
    requests = sum(r.requests for r in ref)
    rated = sum(r.feedback for r in ref)
    ref_unsupported = sum(r.unsupported for r in ref) / max(answered, 1)
    ref_errors = sum(r.errors for r in ref) / max(requests, 1)
    ref_negative = sum(r.negative for r in ref) / max(rated, 1)
    ref_p95 = float(np.median([r.p95_latency_ms for r in ref]))
    ref_topics: dict[str, int] = {}
    for r in ref:
        for k, v in r.topics.items():
            ref_topics[k] = ref_topics.get(k, 0) + v

    if _rate_rise(day.unsupported, day.answered, ref_unsupported, t):
        severe = day.unsupported_rate >= 2 * ref_unsupported + 0.05
        signals.append(
            LLMSignal(
                LLMRule.UNSUPPORTED,
                "critical" if severe else "warning",
                day.unsupported_rate,
                ref_unsupported,
            )
        )
    if _rate_rise(day.errors, day.requests, ref_errors, t):
        severe = day.error_rate >= 0.10
        signals.append(
            LLMSignal(
                LLMRule.ERRORS, "critical" if severe else "warning", day.error_rate, ref_errors
            )
        )
    if _rate_rise(day.negative, day.feedback, ref_negative, t):
        signals.append(LLMSignal(LLMRule.NEGATIVE, "warning", day.negative_rate, ref_negative))
    if day.p95_latency_ms >= t.latency_ratio * ref_p95:
        signals.append(LLMSignal(LLMRule.LATENCY, "warning", day.p95_latency_ms, ref_p95))
    shift = topic_shift(ref_topics, day.topics)
    if shift >= t.topic_distance:
        signals.append(LLMSignal(LLMRule.TOPICS, "warning", shift, 0.0))
    return signals


@dataclass
class LLMIncident:
    """Rules that held long enough to page someone, and when they stopped.

    ``rule`` is the one that fired first; ``rules`` every rule in the incident, in that order.
    """

    rule: LLMRule
    severity: str
    opened_on: str
    resolved_on: str | None
    days: list[str] = field(default_factory=list)
    rules: list[LLMRule] = field(default_factory=list)


# When rules open together, the earliest leads; ties go to the most specific cause.
PRIORITY = [
    LLMRule.PII,
    LLMRule.UNSUPPORTED,
    LLMRule.ERRORS,
    LLMRule.LATENCY,
    LLMRule.NEGATIVE,
    LLMRule.TOPICS,
]


def _merge(found: list[LLMIncident]) -> list[LLMIncident]:
    """Group rules whose incidents overlap in time into one incident; a PII leak stands alone."""
    found.sort(key=lambda i: (i.opened_on, PRIORITY.index(i.rule)))
    merged: list[LLMIncident] = []
    for inc in found:
        group = next(
            (
                g
                for g in merged
                if LLMRule.PII not in (g.rule, inc.rule)
                and LLMRule.TOPICS not in (g.rule, inc.rule)
                and (g.resolved_on is None or inc.opened_on <= g.resolved_on)
            ),
            None,
        )
        if group is None:
            inc.rules = [inc.rule]
            merged.append(inc)
            continue
        group.rules.append(inc.rule)
        group.days = sorted(set(group.days) | set(inc.days))
        if inc.severity == "critical":
            group.severity = "critical"
        if group.resolved_on is not None and (
            inc.resolved_on is None or inc.resolved_on > group.resolved_on
        ):
            group.resolved_on = inc.resolved_on
    return merged


def incidents(
    dates: Sequence[str],
    signals: Sequence[Sequence[LLMSignal]],
    sustained: int = 2,
    quiet: int = 7,
) -> list[LLMIncident]:
    """Turn daily signals into incidents, the same lifecycle as model incidents.

    A rule opens an incident on its ``sustained``-th consecutive day (PII on the first day: one
    leaked number is already a breach) and resolves on the first of ``quiet`` days without it.
    Rules whose incidents overlap are one incident, except a PII leak and a topic shift, which
    have causes and owners of their own.
    """
    out: list[LLMIncident] = []
    for rule in LLMRule:
        streak, open_, calm = 0, None, 0
        for day, day_signals in zip(dates, signals, strict=True):
            hit = next((s for s in day_signals if s.rule is rule), None)
            if hit:
                streak += 1
                calm = 0
                need = 1 if rule is LLMRule.PII else sustained
                if open_ is None and streak >= need:
                    open_ = LLMIncident(rule, hit.severity, day, None, [day])
                    out.append(open_)
                elif open_ is not None:
                    open_.days.append(day)
                    if hit.severity == "critical":
                        open_.severity = "critical"
            else:
                streak = 0
                if open_ is not None:
                    calm += 1
                    if calm == quiet:
                        open_.resolved_on = dates[dates.index(day) - quiet + 1]
                        open_ = None
                        calm = 0
    return _merge(out)
