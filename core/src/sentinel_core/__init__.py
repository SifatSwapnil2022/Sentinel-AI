"""Sentinel core: the monitoring maths behind Sentinel, with no web or database dependencies.

Subpackages:
    drift: per-feature and multivariate drift detection.
    performance: label-free performance estimation (CBPE) and concept-drift checks.
    slices: slice binning and root-cause decomposition of metric changes.
"""

from sentinel_core.errors import (
    InsufficientDataError,
    InvalidInputError,
    NotFittedError,
    SentinelError,
)

__version__ = "0.1.0"

__all__ = [
    "InsufficientDataError",
    "InvalidInputError",
    "NotFittedError",
    "SentinelError",
    "__version__",
]
