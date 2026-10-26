"""Product logic on top of sentinel_core: per-day metrics, alert rules, investigations, documents.

Pure functions on data frames, with no database or network access, shared by the background
worker and the demo builder.
"""

from .bi import TABLES, bi_tables, fleet_daily, to_csv
from .days import CONCEPT_WINDOW_DAYS, UNLABELLED, DayData, compute_day, concat
from .documents import (
    INVESTIGATION_MAX_DAYS,
    ModelInfo,
    episode_document,
    fleet_document,
    incident_document,
    incident_ref,
    investigation_window,
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
    episodes,
    investigate,
    lead_signal,
    rule_holds,
    rules_holding,
)
from .monitors import Monitors
from .segments import segment_table

__all__ = [
    "CONCEPT_WINDOW_DAYS",
    "INVESTIGATION_MAX_DAYS",
    "QUIET_DAYS_TO_RESOLVE",
    "TABLES",
    "UNLABELLED",
    "DayData",
    "Episode",
    "FeatureKind",
    "FeatureSchema",
    "ModelInfo",
    "Monitors",
    "Signal",
    "SignalKind",
    "bi_tables",
    "compute_day",
    "concat",
    "detect_signals",
    "episode_document",
    "episodes",
    "fleet_daily",
    "fleet_document",
    "incident_document",
    "incident_ref",
    "investigate",
    "investigation_window",
    "lead_signal",
    "model_document",
    "model_summary",
    "rule_holds",
    "rules_holding",
    "segment_table",
    "to_csv",
]
