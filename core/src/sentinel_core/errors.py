"""Exceptions raised by sentinel_core.

Every error the library raises on purpose derives from :class:`SentinelError`, so callers
(the API server, workers) can catch library failures without swallowing programming bugs.
"""

from __future__ import annotations


class SentinelError(Exception):
    """Base class for all errors raised deliberately by sentinel_core."""


class InsufficientDataError(SentinelError):
    """Not enough usable rows to compute a statistic reliably.

    Raised for empty windows, all-NaN columns, single-class reference labels and similar.
    The service layer treats this as "skip this window", not as a crash.
    """


class InvalidInputError(SentinelError, ValueError):
    """Input has the wrong shape, type or range (e.g. probabilities outside [0, 1])."""


class NotFittedError(SentinelError, RuntimeError):
    """A detector or estimator was used before ``fit`` was called."""
