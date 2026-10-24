# 1. Monorepo with a dependency-free core

Date: 2026-10-24 · Status: accepted

## Context

Sentinel has statistics (drift, estimation, root cause), a web API, background workers and a
dashboard. The statistics are the part most likely to be wrong in subtle ways and the part
worth testing hardest.

## Decision

All monitoring maths lives in `core/` as the `sentinel_core` package. It depends only on NumPy,
SciPy, pandas and scikit-learn: no web framework, no database, no I/O. The server and workers
will import it; it never imports them.

One repository holds every component, managed as a uv workspace.

## Consequences

- The maths can be tested in milliseconds without a database or server.
- Parity tests against Evidently and NannyML run against the exact code the service uses.
- The package could be published to PyPI on its own.
- Cost: an extra package boundary to maintain, and changes that span core and server need two
  sets of tests.
