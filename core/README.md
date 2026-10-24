# sentinel-core

The statistics behind [Sentinel](../README.md): per-feature and multivariate drift, label-free
performance estimation (CBPE) with a concept-drift check, and slice-level root cause.

No web or database dependencies; NumPy, SciPy, pandas and scikit-learn only.

```python
from sentinel_core.drift import ColumnReference, PCAReconstructionDrift, detect_drift
from sentinel_core.performance import CBPE, check_concept_drift
from sentinel_core.slices import SliceBinner, explain_change
```

See the repository README for design notes and how the maths is verified.
