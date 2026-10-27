"""Build the LLM monitoring demo: 90 days of a retrieval-augmented support assistant.

The app answers customer questions for a fictional mobile bank from its help-centre articles.
Traffic is synthetic; every metric, signal and incident comes from ``sentinel_core.llm``.

Four things go wrong, one at a time:

- Sep 1 to Sep 14: prompt v2 tells the model to "be more helpful", and it starts filling gaps
  with fees and offers that aren't in the articles. Rolled back to v1 on Sep 15.
- Oct 9 to Oct 11: the model provider degrades; latency triples and some calls time out.
- From Oct 17: a festival remittance campaign changes what people ask about.
- From Oct 21: a new account-lookup tool passes customers' phone numbers into the context,
  and some answers repeat them.

Usage:
    uv run python demo/build_llm.py [--out web/public/data/llm.json]
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from sentinel_core.llm import (
    LLMRule,
    LLMTrace,
    day_metrics,
    evaluate,
    find_pii,
    incidents,
    topic_shift,
    unsupported_sentences,
)

TODAY = date(2026, 10, 24)
DAYS = 90
REFERENCE_DAYS = 21
SEED = 7
MODEL = {"name": "gpt-4o-mini", "priceIn": 0.15, "priceOut": 0.60}

# topic: (question, help-centre article, grounded answer, invented answer)
ARTICLES: dict[str, list[tuple[str, str, str, str]]] = {
    "cards": [
        (
            "How much does a replacement card cost?",
            "A replacement debit card costs 300 taka. It is delivered to your branch in 7 working days. "
            "You can block a lost card in the app under Cards, then Block card.",
            "A replacement debit card costs 300 taka. It reaches your branch in 7 working days.",
            "A replacement debit card costs 150 taka for premium customers. It can be delivered to your home in 2 days.",
        ),
    ],
    "transfers": [
        (
            "What is the daily send money limit?",
            "You can send up to 50000 taka per day and 300000 taka per month. Transfers to other banks "
            "through NPSB arrive within minutes and cost 10 taka.",
            "You can send up to 50000 taka per day and 300000 taka per month. Transfers to other banks cost 10 taka.",
            "You can send up to 100000 taka per day after verifying your account. Transfers to other banks are free this month.",
        ),
    ],
    "loans": [
        (
            "Can I get a small loan in the app?",
            "Instant loans of 5000 to 50000 taka are available to customers with 6 months of salary deposits. "
            "The interest rate is 9 percent per year and repayment is in 12 monthly instalments.",
            "Instant loans of 5000 to 50000 taka need 6 months of salary deposits. The rate is 9 percent per year over 12 instalments.",
            "Instant loans up to 200000 taka are approved within an hour at 4 percent with no salary history needed.",
        ),
    ],
    "account": [
        (
            "How do I update my phone number?",
            "To update your phone number, visit a branch with your national ID. The change takes effect "
            "within 24 hours and you will get a confirmation SMS.",
            "Visit a branch with your national ID to update your phone number. It takes effect within 24 hours.",
            "You can update your phone number in the app instantly by answering two security questions.",
        ),
    ],
    "remittance": [
        (
            "How do I receive money from abroad?",
            "Remittances from partner exchange houses arrive in your account the same day. The government "
            "adds a 2.5 percent incentive on remittances received through banks.",
            "Remittances from partner exchange houses arrive the same day, with a 2.5 percent government incentive.",
            "Remittances arrive instantly from any country with a 5 percent bonus from the bank.",
        ),
    ],
}
NORMAL_MIX = {"cards": 0.28, "transfers": 0.30, "loans": 0.14, "account": 0.20, "remittance": 0.08}
CAMPAIGN_MIX = {
    "cards": 0.17,
    "transfers": 0.24,
    "loans": 0.09,
    "account": 0.12,
    "remittance": 0.38,
}
REFUSAL = "Sorry, I can't help with that request. Please contact your branch."

TITLES = {
    LLMRule.PII: "Answers exposed customer phone numbers",
    LLMRule.UNSUPPORTED: "Answers stated things the articles don't say",
    LLMRule.ERRORS: "Calls failing or timing out",
    LLMRule.LATENCY: "Responses slowed down",
    LLMRule.NEGATIVE: "More thumbs-down from users",
    LLMRule.TOPICS: "Questions shifted to different topics",
}


def scenario(day: date) -> dict[str, Any]:
    """What is going on in the app on a given day."""
    prompt = "v2" if date(2026, 9, 1) <= day <= date(2026, 9, 14) else "v1"
    if day >= date(2026, 10, 21):
        prompt = "v1.1"  # adds the account-lookup tool
    return {
        "prompt": prompt,
        "invent": 0.16 if prompt == "v2" else 0.035,
        "outage": date(2026, 10, 9) <= day <= date(2026, 10, 11),
        "mix": CAMPAIGN_MIX if day >= date(2026, 10, 17) else NORMAL_MIX,
        "leak": 0.03 if day >= date(2026, 10, 21) else 0.0,
    }


def phone(rng: np.random.Generator) -> str:
    return f"01{rng.integers(3, 10)}{rng.integers(10_000_000, 99_999_999)}"


def simulate_day(
    day: date, rng: np.random.Generator
) -> tuple[list[LLMTrace], list[dict[str, Any]]]:
    s = scenario(day)
    n = int(rng.normal(1400, 90) * (1.15 if day.weekday() in (4, 5) else 1.0))
    topics = rng.choice(list(s["mix"]), size=n, p=list(s["mix"].values()))
    traces, examples = [], []
    for topic in topics:
        question, article, good, bad = ARTICLES[str(topic)][0]
        context = article
        latency = float(rng.lognormal(np.log(900), 0.35)) * (3.0 if s["outage"] else 1.0)
        status = "ok"
        if s["outage"] and rng.random() < 0.09:
            status = "timeout"
            latency = 30_000.0
        elif rng.random() < 0.006:
            status = "error"
        invented = rng.random() < s["invent"]
        answer = bad if invented else good
        leaked = rng.random() < s["leak"]
        if s["leak"]:
            number = phone(rng)
            context = f"Customer phone number on file: {number}. {article}"
            if leaked:
                answer = f"Your phone number on file is {number}. {answer}"
        if rng.random() < 0.012:
            answer = REFUSAL
        if status != "ok":
            answer = ""
        feedback = None
        if status == "ok" and rng.random() < 0.11:
            p_down = 0.45 if invented else (0.30 if s["outage"] else 0.08)
            feedback = -1 if rng.random() < p_down else 1
        trace = LLMTrace(
            day=day.isoformat(),
            prompt_version=s["prompt"],
            topic=str(topic),
            input_tokens=int(rng.normal(1150, 120)) + len(context) // 4,
            output_tokens=int(rng.normal(140, 30)) if status == "ok" else 0,
            latency_ms=latency,
            status=status,
            answer=answer,
            context=context,
            feedback=feedback,
        )
        traces.append(trace)
        flagged = unsupported_sentences(answer, context) if status == "ok" else []
        pii = find_pii(answer)
        if (flagged or pii) and len(examples) < 4:
            examples.append(
                {
                    "promptVersion": s["prompt"],
                    "topic": str(topic),
                    "question": question,
                    "context": context,
                    "answer": answer,
                    "unsupported": flagged,
                    "pii": pii,
                    "feedback": feedback,
                }
            )
    return traces, examples


def r(x: float, digits: int = 4) -> float:
    return round(float(x), digits)


def build() -> dict[str, Any]:
    rng = np.random.default_rng(SEED)
    dates = [TODAY - timedelta(days=DAYS - 1 - i) for i in range(DAYS)]
    metrics, by_version, examples = [], [], {}
    for d in dates:
        traces, ex = simulate_day(d, rng)
        examples[d.isoformat()] = ex
        metrics.append(day_metrics(d.isoformat(), traces, MODEL["priceIn"], MODEL["priceOut"]))
        versions = {}
        for v in sorted({t.prompt_version for t in traces}):
            vm = day_metrics(
                d.isoformat(),
                [t for t in traces if t.prompt_version == v],
                MODEL["priceIn"],
                MODEL["priceOut"],
            )
            versions[v] = vm
        by_version.append(versions)

    reference = metrics[:REFERENCE_DAYS]
    signals = [evaluate(m, reference) for m in metrics]
    found = incidents([m.day for m in metrics], signals)
    ref_topics: dict[str, int] = {}
    for m in reference:
        for k, v in m.topics.items():
            ref_topics[k] = ref_topics.get(k, 0) + v

    days = []
    for m, sig, versions in zip(metrics, signals, by_version, strict=True):
        days.append(
            {
                "date": m.day,
                "requests": m.requests,
                "errorRate": r(m.error_rate),
                "unsupportedRate": r(m.unsupported_rate),
                "piiAnswers": m.pii,
                "refusalRate": r(m.refusals / max(m.answered, 1)),
                "negativeRate": r(m.negative_rate),
                "feedback": m.feedback,
                "p50LatencyMs": r(m.p50_latency_ms, 0),
                "p95LatencyMs": r(m.p95_latency_ms, 0),
                "inputTokens": m.input_tokens,
                "outputTokens": m.output_tokens,
                "costUsd": r(m.cost_usd, 2),
                "topicShift": r(topic_shift(ref_topics, m.topics)),
                "topics": m.topics,
                "versions": {
                    v: {"requests": vm.requests, "unsupportedRate": r(vm.unsupported_rate)}
                    for v, vm in versions.items()
                },
                "signals": [s.rule.value for s in sig],
            }
        )

    out_incidents = []
    for k, inc in enumerate(found, start=1):
        sample = [
            e
            for d in inc.days
            for e in examples[d]
            if (e["pii"] if inc.rule is LLMRule.PII else e["unsupported"])
        ][:3]
        if inc.rule not in (LLMRule.PII, LLMRule.UNSUPPORTED):
            sample = []
        out_incidents.append(
            {
                "id": f"support-assistant-llm-{k}",
                "rule": inc.rule.value,
                "title": TITLES[inc.rule],
                "severity": inc.severity,
                "status": "open" if inc.resolved_on is None else "resolved",
                "openedOn": inc.opened_on,
                "resolvedOn": inc.resolved_on,
                "days": len(inc.days),
                "rules": [rule.value for rule in inc.rules],
                "examples": sample,
            }
        )

    versions_table: dict[str, dict[str, Any]] = {}
    for versions in by_version:
        for v, vm in versions.items():
            row = versions_table.setdefault(
                v,
                {
                    "version": v,
                    "from": vm.day,
                    "to": vm.day,
                    "requests": 0,
                    "answered": 0,
                    "unsupported": 0,
                    "feedback": 0,
                    "negative": 0,
                    "cost": 0.0,
                    "p95": [],
                },
            )
            row["to"] = vm.day
            row["requests"] += vm.requests
            row["answered"] += vm.answered
            row["unsupported"] += vm.unsupported
            row["feedback"] += vm.feedback
            row["negative"] += vm.negative
            row["cost"] += vm.cost_usd
            row["p95"].append(vm.p95_latency_ms)
    return {
        "schemaVersion": 1,
        "today": TODAY.isoformat(),
        "app": {
            "id": "support-assistant",
            "name": "support-assistant",
            "description": "Answers customer questions for a mobile bank from its help-centre articles (retrieval-augmented).",
            "model": MODEL,
            "referenceWindow": {"from": metrics[0].day, "to": metrics[REFERENCE_DAYS - 1].day},
        },
        "reference": {
            "unsupportedRate": r(
                sum(m.unsupported for m in reference) / sum(m.answered for m in reference)
            ),
            "errorRate": r(sum(m.errors for m in reference) / sum(m.requests for m in reference)),
            "negativeRate": r(
                sum(m.negative for m in reference) / sum(m.feedback for m in reference)
            ),
            "p95LatencyMs": r(float(np.median([m.p95_latency_ms for m in reference])), 0),
            "topics": ref_topics,
        },
        "days": days,
        "versions": [
            {
                "version": v["version"],
                "from": v["from"],
                "to": v["to"],
                "requests": v["requests"],
                "unsupportedRate": r(v["unsupported"] / max(v["answered"], 1)),
                "negativeRate": r(v["negative"] / max(v["feedback"], 1)),
                "p95LatencyMs": r(float(np.median(v["p95"])), 0),
                "costPer1k": r(v["cost"] / v["requests"] * 1000, 3),
            }
            for v in versions_table.values()
        ],
        "incidents": out_incidents,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("web/public/data/llm.json"))
    args = parser.parse_args()
    doc = build()
    args.out.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n")
    for i in doc["incidents"]:
        print(f"{i['id']:26} {i['rule']:20} {i['severity']:8} {i['openedOn']} -> {i['resolvedOn']}")


if __name__ == "__main__":
    main()
