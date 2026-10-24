"""Synthetic models and the production stories the demo tells.

Each model has a ground-truth data generator (features and the real probability of the outcome)
and a scenario that changes production traffic on a given day. The deployed model is trained once
on clean data and never sees the change, which is exactly the situation monitoring is for.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

from sentinel_server.analysis import Monitors

Frame = pd.DataFrame
Rng = np.random.Generator


@dataclass(frozen=True)
class Scenario:
    """How production traffic departs from the reference on and after ``start_day``."""

    kind: str
    """One of: none, covariate_shift, concept_drift, correlation_break."""
    start_day: int = 0
    summary: str = ""


@dataclass(frozen=True)
class ModelSpec:
    """A synthetic model: its domain, label delay, traffic volume and scenario."""

    id: str
    name: str
    version: str
    team: str
    description: str
    label_delay_days: int
    """Days until roughly all labels for a day's predictions have arrived."""
    daily_rows: int
    features: Callable[[Rng, int, float], Frame]
    """Draw ``n`` rows; the float is scenario intensity in [0, 1] for that day."""
    true_logit: Callable[[Frame, float], np.ndarray]
    """Real log-odds of the positive outcome; may depend on scenario intensity."""
    scenario: Scenario
    categorical: tuple[str, ...] = field(default_factory=tuple)
    latency_ms: float = 38.0
    """Typical (median) serving latency."""


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


# ---------------------------------------------------------------------------- credit risk

_DIVISIONS = ["Dhaka", "Chattogram", "Khulna", "Rajshahi", "Sylhet"]


def _credit_features(rng: Rng, n: int, _: float) -> Frame:
    income = rng.lognormal(np.log(42_000), 0.55, n)
    return pd.DataFrame(
        {
            "monthly_income": income.round(-2),
            "credit_limit": (income * rng.uniform(1.5, 4.0, n)).round(-3),
            "utilization": rng.beta(2.2, 3.5, n).round(3),
            "age": np.clip(rng.normal(36, 9, n), 21, 70).round(),
            "months_on_book": rng.integers(3, 120, n),
            "division": rng.choice(_DIVISIONS, n, p=[0.38, 0.22, 0.14, 0.14, 0.12]),
            "channel": rng.choice(["app", "branch", "web"], n, p=[0.55, 0.25, 0.20]),
        }
    )


def _credit_logit(df: Frame, intensity: float) -> np.ndarray:
    base = (
        -1.4
        + 3.2 * (df["utilization"].to_numpy() - 0.38)
        - 1.1 * (np.log(df["monthly_income"].to_numpy()) - np.log(42_000))
        - 0.012 * (df["months_on_book"].to_numpy() - 60)
        - 0.02 * (df["age"].to_numpy() - 36)
        + np.where(df["channel"].to_numpy() == "web", 0.35, 0.0)
    )
    # Concept drift: after a local shock, lower-income Khulna borrowers default far more,
    # even though nothing in their application data looks different.
    hit = (df["division"].to_numpy() == "Khulna") & (df["monthly_income"].to_numpy() < 40_000)
    return base + intensity * 3.0 * hit


# ---------------------------------------------------------------------------- fraud screening

_MERCHANTS = ["grocery", "fuel", "electronics", "travel", "digital_goods", "fashion"]


def _fraud_features(rng: Rng, n: int, intensity: float) -> Frame:
    # Covariate shift: a festival-season surge in large digital-goods and electronics payments.
    p = np.array([0.30, 0.16, 0.12, 0.10, 0.14, 0.18])
    shifted = np.array([0.18, 0.10, 0.22, 0.08, 0.30, 0.12])
    mix = (1 - intensity) * p + intensity * shifted
    merchant = rng.choice(_MERCHANTS, n, p=mix / mix.sum())
    amount = rng.lognormal(np.log(1_800) + 0.75 * intensity, 0.9, n)
    return pd.DataFrame(
        {
            "amount_bdt": amount.round(),
            "merchant_category": merchant,
            "hour_of_day": rng.integers(0, 24, n),
            "card_age_days": rng.gamma(2.0, 260, n).round(),
            "txn_last_24h": rng.poisson(1.6 + 1.4 * intensity, n),
            "is_international": rng.random(n) < (0.04 + 0.05 * intensity),
        }
    )


def _fraud_logit(df: Frame, _: float) -> np.ndarray:
    night = np.isin(df["hour_of_day"].to_numpy(), [0, 1, 2, 3, 4])
    risky = np.isin(df["merchant_category"].to_numpy(), ["digital_goods", "electronics"])
    return (
        -2.6
        + 0.9 * (np.log(df["amount_bdt"].to_numpy()) - np.log(1_800))
        + 0.8 * risky
        + 0.7 * night
        - 0.0015 * df["card_age_days"].to_numpy()
        + 0.25 * df["txn_last_24h"].to_numpy()
        + 1.0 * df["is_international"].to_numpy()
    )


# ---------------------------------------------------------------------------- churn


def _churn_features(rng: Rng, n: int, _: float) -> Frame:
    return pd.DataFrame(
        {
            "tenure_months": rng.integers(1, 72, n),
            "monthly_spend": rng.lognormal(np.log(650), 0.5, n).round(),
            "support_tickets_90d": rng.poisson(0.8, n),
            "data_usage_gb": rng.gamma(3.0, 4.0, n).round(1),
            "plan": rng.choice(["prepaid", "postpaid", "family"], n, p=[0.6, 0.3, 0.1]),
            "region": rng.choice(_DIVISIONS, n, p=[0.40, 0.20, 0.15, 0.13, 0.12]),
        }
    )


def _churn_logit(df: Frame, _: float) -> np.ndarray:
    return (
        -0.4
        - 0.045 * df["tenure_months"].to_numpy()
        + 0.55 * df["support_tickets_90d"].to_numpy()
        - 0.04 * df["data_usage_gb"].to_numpy()
        + np.where(df["plan"].to_numpy() == "prepaid", 0.6, -0.2)
    )


# ---------------------------------------------------------------------------- claims triage


def _claims_features(rng: Rng, n: int, intensity: float) -> Frame:
    policy = rng.lognormal(np.log(600_000), 0.6, n)
    ratio = np.clip(rng.normal(0.18, 0.06, n), 0.01, None)
    # Correlation break: a new intake form records claim amounts from a different system, so
    # amounts no longer scale with policy value. Each column's own distribution barely moves.
    independent = rng.permutation(policy) * ratio
    claim = (1 - intensity) * policy * ratio + intensity * independent
    return pd.DataFrame(
        {
            "policy_value_bdt": policy.round(-3),
            "claim_amount_bdt": claim.round(-2),
            "days_since_policy_start": rng.integers(10, 3_000, n),
            "prior_claims": rng.poisson(0.5, n),
            "vehicle_age_years": rng.integers(0, 18, n),
            "garage_network": rng.choice(["partner", "independent"], n, p=[0.7, 0.3]),
        }
    )


def _claims_logit(df: Frame, _: float) -> np.ndarray:
    ratio = df["claim_amount_bdt"].to_numpy() / df["policy_value_bdt"].to_numpy()
    return (
        -1.0
        + 6.0 * (ratio - 0.18)
        + 0.5 * df["prior_claims"].to_numpy()
        - 0.0004 * df["days_since_policy_start"].to_numpy()
        + np.where(df["garage_network"].to_numpy() == "independent", 0.6, 0.0)
    )


MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(
        id="credit-risk",
        name="credit-risk",
        version="v3",
        team="Lending",
        description="Predicts whether a new credit card applicant will default within 6 months.",
        label_delay_days=14,
        daily_rows=1_600,
        features=_credit_features,
        true_logit=_credit_logit,
        categorical=("division", "channel"),
        scenario=Scenario(
            kind="concept_drift",
            start_day=19,
            summary="Default risk rose for lower-income applicants in Khulna; inputs look normal.",
        ),
    ),
    ModelSpec(
        id="fraud-screen",
        name="fraud-screen",
        version="v5",
        team="Payments",
        description="Scores card transactions for fraud before authorisation.",
        label_delay_days=45,
        daily_rows=2_400,
        features=_fraud_features,
        true_logit=_fraud_logit,
        categorical=("merchant_category", "is_international"),
        latency_ms=61.0,
        scenario=Scenario(
            kind="covariate_shift",
            start_day=17,
            summary="Festival-season traffic: larger digital-goods and electronics payments.",
        ),
    ),
    ModelSpec(
        id="churn-predictor",
        name="churn-predictor",
        version="v2",
        team="Growth",
        description="Flags mobile subscribers likely to leave in the next 30 days.",
        label_delay_days=30,
        daily_rows=1_200,
        features=_churn_features,
        true_logit=_churn_logit,
        categorical=("plan", "region"),
        scenario=Scenario(kind="none"),
    ),
    ModelSpec(
        id="claims-triage",
        name="claims-triage",
        version="v1",
        team="Insurance ops",
        description="Routes motor insurance claims to fast-track or manual review.",
        label_delay_days=10,
        daily_rows=900,
        features=_claims_features,
        true_logit=_claims_logit,
        categorical=("garage_network",),
        scenario=Scenario(
            kind="correlation_break",
            start_day=23,
            summary="A new intake form decoupled claim amount from policy value.",
        ),
    ),
)


def intensity(spec: ModelSpec, day: int) -> float:
    """Scenario strength on ``day``: ramps from 0 to 1 over three days after the start."""
    if spec.scenario.kind == "none" or day < spec.scenario.start_day:
        return 0.0
    return float(min(1.0, (day - spec.scenario.start_day + 1) / 3))


def sample(spec: ModelSpec, rng: Rng, n: int, level: float) -> tuple[Frame, np.ndarray]:
    """Draw ``n`` rows and their true outcomes at scenario intensity ``level``."""
    frame = spec.features(rng, n, level)
    outcome = rng.random(n) < _sigmoid(spec.true_logit(frame, level))
    return frame, outcome.astype(np.int64)


# ---------------------------------------------------------------------------- the deployed model

TRAIN_ROWS = 8_000


@dataclass(eq=False)
class TrainedModel:
    """The 'deployed' model, trained once on clean data, plus monitors fitted on a reference."""

    spec: ModelSpec
    pipeline: Pipeline
    monitors: Monitors
    reference: Frame
    """Reference rows as uploaded to Sentinel: features, ``score`` and ``label``."""

    def predict(self, frame: Frame) -> np.ndarray:
        """Positive-class probability for each row."""
        return _predict(self.pipeline, self.spec, frame)


def _predict(pipeline: Pipeline, spec: ModelSpec, frame: Frame) -> np.ndarray:
    prepared = frame.astype(dict.fromkeys(spec.categorical, str))
    return np.asarray(pipeline.predict_proba(prepared)[:, 1], dtype=np.float64)


def train(spec: ModelSpec, rng: Rng, *, reference_rows: int = 6_000) -> TrainedModel:
    """Train on clean data, then score a held-out reference and fit Sentinel's monitors on it."""
    x_train, y_train = sample(spec, rng, TRAIN_ROWS, 0.0)
    categorical = list(spec.categorical)
    encoder = ColumnTransformer(
        [
            (
                "cat",
                OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1),
                categorical,
            )
        ],
        remainder="passthrough",
    )
    gbm = HistGradientBoostingClassifier(
        max_iter=150,
        learning_rate=0.08,
        categorical_features=list(range(len(categorical))),
        random_state=0,
    )
    pipeline = Pipeline([("encode", encoder), ("gbm", gbm)])
    pipeline.fit(x_train.astype(dict.fromkeys(categorical, str)), y_train)

    ref_frame, ref_outcome = sample(spec, rng, reference_rows, 0.0)
    score = _predict(pipeline, spec, ref_frame)
    return TrainedModel(
        spec=spec,
        pipeline=pipeline,
        monitors=Monitors.fit(ref_frame, ref_outcome, score),
        reference=ref_frame.assign(score=score, label=ref_outcome),
    )
