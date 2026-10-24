"""JSON helpers shared by the analysis documents."""

from __future__ import annotations

from typing import Any

import numpy as np

SCHEMA_VERSION = 1
"""Version of the document shapes served to the dashboard (``web/src/data/schema.ts``)."""


def r(x: float | None, digits: int = 4) -> float | None:
    """Round for JSON, mapping NaN and infinities to null."""
    if x is None:
        return None
    value = float(x)
    if not np.isfinite(value):
        return None
    return round(value, digits)


def jsonable(value: Any) -> Any:
    """A feature value as JSON: bools and ints kept, floats rounded, everything else text."""
    if value is None:
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return r(float(value), 3)
    return str(value)
