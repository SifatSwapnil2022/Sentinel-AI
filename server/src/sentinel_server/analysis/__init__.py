"""Product logic on top of sentinel_core: per-day metrics, alert rules, investigations, documents.

Pure functions on data frames, with no database or network access, shared by the background
worker and the demo builder.
"""

from .days import CONCEPT_WINDOW_DAYS, UNLABELLED, DayData, compute_day, concat
from .documents import (
    ModelInfo,
    fleet_document,
    incident_document,
    incident_ref,
    model_document,
    model_summary,
)
from .features import FeatureKind, FeatureSchema
from .incidents import (
    QUIET_DAYS_TO_RESOLVE,
    Episode,
    Signal,
    SignalKind,
    detect_signals,
    evaluate,
    investigate,
    lead_signal,
    rule_holds,
)
from .monitors import Monitors

__all__ = [
    "CONCEPT_WINDOW_DAYS",
    "QUIET_DAYS_TO_RESOLVE",
    "UNLABELLED",
    "DayData",
    "Episode",
    "FeatureKind",
    "FeatureSchema",
    "ModelInfo",
    "Monitors",
    "Signal",
    "SignalKind",
    "compute_day",
    "concat",
    "detect_signals",
    "evaluate",
    "fleet_document",
    "incident_document",
    "incident_ref",
    "investigate",
    "lead_signal",
    "model_document",
    "model_summary",
    "rule_holds",
]
