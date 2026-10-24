"""Feature schema: the one canonical form every frame is coerced to before analysis.

Production data arrives as JSON from the SDK (``true``, ``3``, ``"app"``) and reference data as
CSV or JSON rows (``"True"``, ``"3"``). Without a fixed schema the same value can reach the drift
tests as two different categories, and a drift alert fires on nothing but a type mismatch. The
schema is inferred once from the reference data and stored with the model version.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import numpy as np
import pandas as pd

from sentinel_core.errors import InvalidInputError


class FeatureKind(StrEnum):
    """How a feature is stored and compared."""

    NUMERIC = "numeric"
    CATEGORICAL = "categorical"


@dataclass(frozen=True, slots=True)
class FeatureSchema:
    """Ordered features and their kinds, fixed at reference time."""

    kinds: dict[str, FeatureKind]

    @property
    def names(self) -> list[str]:
        """Feature names in order."""
        return list(self.kinds)

    @property
    def categorical(self) -> list[str]:
        """Names of categorical features."""
        return [n for n, k in self.kinds.items() if k is FeatureKind.CATEGORICAL]

    @classmethod
    def infer(cls, frame: pd.DataFrame) -> FeatureSchema:
        """Infer kinds from reference data.

        A column is numeric when every non-missing value parses as a number and it is not boolean.
        Booleans are categorical: they have two values, and ``True``/``"True"``/``1`` must all
        compare equal later.
        """
        if frame.shape[1] == 0:
            raise InvalidInputError("reference data has no feature columns")
        kinds: dict[str, FeatureKind] = {}
        for column in frame.columns:
            values = frame[column]
            non_missing = values.dropna()
            if pd.api.types.is_bool_dtype(values) or _looks_boolean(non_missing):
                kinds[str(column)] = FeatureKind.CATEGORICAL
                continue
            parsed = pd.to_numeric(non_missing, errors="coerce")
            numeric = len(non_missing) > 0 and bool(parsed.notna().all())
            kinds[str(column)] = FeatureKind.NUMERIC if numeric else FeatureKind.CATEGORICAL
        return cls(kinds)

    def coerce(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Return ``frame`` with exactly the schema's columns, in order, in canonical types.

        Numeric features become float64 (unparseable values become missing). Categorical features
        become strings, with booleans normalised to ``"True"``/``"False"`` and missing kept
        missing. Columns absent from ``frame`` are added as all-missing; extra columns are dropped.
        """
        out = {}
        for name, kind in self.kinds.items():
            values = frame[name] if name in frame.columns else pd.Series(np.nan, index=frame.index)
            if kind is FeatureKind.NUMERIC:
                out[name] = pd.to_numeric(values, errors="coerce").astype(np.float64)
            else:
                out[name] = values.map(_canonical_category).astype(object)
        return pd.DataFrame(out, index=frame.index)

    def to_json(self) -> list[dict[str, str]]:
        """Serialisable form for storage.

        A list, because column order matters and JSON object key order does not survive every
        store (Postgres ``jsonb`` reorders keys).
        """
        return [{"name": name, "kind": kind.value} for name, kind in self.kinds.items()]

    @classmethod
    def from_json(cls, data: list[dict[str, str]]) -> FeatureSchema:
        """Inverse of :meth:`to_json`."""
        return cls({item["name"]: FeatureKind(item["kind"]) for item in data})


_TRUE = {"true", "True", "TRUE"}
_FALSE = {"false", "False", "FALSE"}


def _looks_boolean(values: pd.Series) -> bool:
    if len(values) == 0:
        return False
    as_text = set(values.astype(str).unique())
    return as_text <= (_TRUE | _FALSE) and len(as_text) > 0


def _canonical_category(value: Any) -> Any:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    if isinstance(value, (bool, np.bool_)):
        return "True" if value else "False"
    text = str(value)
    if text in _TRUE:
        return "True"
    if text in _FALSE:
        return "False"
    # Whole floats from JSON or CSV ("3.0") and ints ("3") are the same category.
    if isinstance(value, (float, np.floating)) and float(value).is_integer():
        return str(int(value))
    return text
