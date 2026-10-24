from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from sentinel_core.errors import InsufficientDataError, InvalidInputError
from sentinel_core.slices import (
    SliceBinner,
    correctness,
    expected_correctness,
    explain_change,
)


def traffic(
    rng: np.random.Generator, n: int, *, broken: bool = False
) -> tuple[pd.DataFrame, np.ndarray]:
    frame = pd.DataFrame(
        {
            "income": rng.lognormal(10, 0.6, n),
            "region": rng.choice(list("ABCD"), n),
            "channel": rng.choice(["web", "app"], n),
        }
    )
    accuracy = np.full(n, 0.88)
    if broken:
        low_income = frame["income"] < 14_000
        accuracy[(frame["region"] == "C").to_numpy() & low_income.to_numpy()] = 0.35
    return frame, rng.binomial(1, accuracy).astype(float)


def test_injected_segment_is_ranked_first(rng: np.random.Generator) -> None:
    ref, ref_scores = traffic(rng, 10_000)
    cur, cur_scores = traffic(rng, 4000, broken=True)
    binner = SliceBinner().fit(ref)
    report = explain_change(binner.transform(ref), ref_scores, binner.transform(cur), cur_scores)

    top = report.findings[0]
    assert set(top.features) == {"income", "region"}
    assert "region: C" in top.label
    assert top.metric_current < 0.5
    assert top.share_of_drop > 0.6
    assert report.delta < 0


def test_pure_mix_shift_is_not_blamed_on_the_model(rng: np.random.Generator) -> None:
    # Region D is always hard; the current window simply has more of it.
    n_ref, n_cur = 8000, 4000
    ref = pd.DataFrame({"region": rng.choice(list("ABCD"), n_ref, p=[0.3, 0.3, 0.3, 0.1])})
    cur = pd.DataFrame({"region": rng.choice(list("ABCD"), n_cur, p=[0.1, 0.1, 0.1, 0.7])})
    acc = {"A": 0.9, "B": 0.9, "C": 0.9, "D": 0.5}
    ref_s = rng.binomial(1, ref["region"].map(acc)).astype(float)
    cur_s = rng.binomial(1, cur["region"].map(acc)).astype(float)

    report = explain_change(ref, ref_s, cur, cur_s, include_pairs=False)
    (summary,) = report.partitions
    assert report.delta < -0.15
    assert summary.mix_effect == pytest.approx(report.delta, abs=0.03)
    assert abs(summary.performance_effect) < 0.03


def test_min_slice_size_filters_small_slices() -> None:
    ref = pd.DataFrame({"g": ["a"] * 100 + ["b"] * 100})
    cur = pd.DataFrame({"g": ["a"] * 100 + ["b"] * 10})
    ref_s = np.ones(200)
    cur_s = np.concatenate([np.ones(100), np.zeros(10)])
    report = explain_change(ref, ref_s, cur, cur_s, min_slice_size=50)
    assert report.findings == ()
    report = explain_change(ref, ref_s, cur, cur_s, min_slice_size=5)
    assert [f.values for f in report.findings] == [("b",)]


def test_no_drop_means_no_findings(rng: np.random.Generator) -> None:
    ref = pd.DataFrame({"g": rng.choice(list("ab"), 1000)})
    report = explain_change(ref, np.full(1000, 0.5), ref, np.full(1000, 0.9))
    assert report.findings == ()
    assert report.delta == pytest.approx(0.4)


def test_slice_new_in_current_window() -> None:
    ref = pd.DataFrame({"g": ["a"] * 100})
    cur = pd.DataFrame({"g": ["a"] * 100 + ["new"] * 100})
    report = explain_change(
        ref, np.ones(100), cur, np.r_[np.ones(100), np.zeros(100)], min_slice_size=1
    )
    (summary,) = report.partitions
    assert summary.performance_effect + summary.mix_effect == pytest.approx(report.delta)
    assert report.findings == ()  # "new" has no reference rows, so it cannot be ranked


def test_pairs_can_be_disabled(rng: np.random.Generator) -> None:
    ref, ref_s = traffic(rng, 3000)
    cur, cur_s = traffic(rng, 3000, broken=True)
    binner = SliceBinner().fit(ref)
    report = explain_change(
        binner.transform(ref), ref_s, binner.transform(cur), cur_s, include_pairs=False
    )
    assert all(len(p.features) == 1 for p in report.partitions)
    assert all(len(f.features) == 1 for f in report.findings)


def test_max_findings(rng: np.random.Generator) -> None:
    ref, ref_s = traffic(rng, 3000)
    cur, cur_s = traffic(rng, 3000, broken=True)
    binner = SliceBinner().fit(ref)
    report = explain_change(
        binner.transform(ref), ref_s, binner.transform(cur), cur_s, max_findings=2
    )
    assert len(report.findings) == 2
    assert report.findings[0].contribution <= report.findings[1].contribution


def test_score_helpers() -> None:
    np.testing.assert_array_equal(correctness([1, 0, 1], [1, 1, 1]), [1.0, 0.0, 1.0])
    np.testing.assert_allclose(expected_correctness([0.9, 0.9, 0.2], [1, 0, 0]), [0.9, 0.1, 0.8])
    with pytest.raises(InvalidInputError):
        correctness([1, 0], [1])
    with pytest.raises(InvalidInputError):
        expected_correctness([0.5], [1, 0])


def test_input_validation() -> None:
    frame = pd.DataFrame({"g": ["a", "b"]})
    with pytest.raises(InvalidInputError, match="same columns"):
        explain_change(frame, [1, 1], frame.rename(columns={"g": "h"}), [1, 1])
    with pytest.raises(InvalidInputError, match="no slice features"):
        explain_change(pd.DataFrame(index=[0]), [1], pd.DataFrame(index=[0]), [1])
    with pytest.raises(InvalidInputError, match="2 slice rows but 3 scores"):
        explain_change(frame, [1, 1, 1], frame, [1, 1])
    with pytest.raises(InvalidInputError, match="finite"):
        explain_change(frame, [1, np.nan], frame, [1, 1])
    with pytest.raises(InsufficientDataError):
        explain_change(frame.iloc[:0], [], frame, [1, 1])


@given(
    ref=st.lists(
        st.tuples(st.sampled_from("abc"), st.sampled_from("xy"), st.floats(0, 1)),
        min_size=1,
        max_size=60,
    ),
    cur=st.lists(
        st.tuples(st.sampled_from("abcd"), st.sampled_from("xy"), st.floats(0, 1)),
        min_size=1,
        max_size=60,
    ),
)
def test_decomposition_always_adds_up(
    ref: list[tuple[str, str, float]], cur: list[tuple[str, str, float]]
) -> None:
    def split(rows: list[tuple[str, str, float]]) -> tuple[pd.DataFrame, np.ndarray]:
        frame = pd.DataFrame({"f1": [r[0] for r in rows], "f2": [r[1] for r in rows]})
        return frame, np.array([r[2] for r in rows])

    ref_frame, ref_s = split(ref)
    cur_frame, cur_s = split(cur)
    report = explain_change(ref_frame, ref_s, cur_frame, cur_s, min_slice_size=1)
    for summary in report.partitions:
        total = summary.performance_effect + summary.mix_effect
        assert total == pytest.approx(report.delta, abs=1e-9)
    for finding in report.findings:
        assert finding.contribution < 0


def test_parent_slices_explained_by_a_pair_are_dropped(rng: np.random.Generator) -> None:
    ref, ref_s = traffic(rng, 10_000)
    cur, cur_s = traffic(rng, 4000, broken=True)
    binner = SliceBinner().fit(ref)
    args = (binner.transform(ref), ref_s, binner.transform(cur), cur_s)

    labels = [f.label for f in explain_change(*args).findings]
    assert "region: C" not in labels

    lenient = [f.label for f in explain_change(*args, specificity=1.0).findings]
    assert "region: C" in lenient  # with this seed no pair explains all of the parent


def test_specificity_must_be_a_fraction() -> None:
    frame = pd.DataFrame({"g": ["a"]})
    with pytest.raises(InvalidInputError, match="specificity"):
        explain_change(frame, [1], frame, [1], specificity=0)


def test_dominant_slice_is_not_reported_as_a_cause(rng: np.random.Generator) -> None:
    # 95% of rows share flag=False; the drop is spread evenly, except one small segment.
    n = 8000
    ref = pd.DataFrame({"flag": rng.random(n) < 0.05, "seg": rng.choice(list("abcd"), n)})
    cur = pd.DataFrame({"flag": rng.random(n) < 0.05, "seg": rng.choice(list("abcd"), n)})
    ref_s = rng.binomial(1, 0.9, n).astype(float)
    acc = np.where(cur["seg"] == "d", 0.5, 0.85)
    cur_s = rng.binomial(1, acc).astype(float)

    labels = [f.label for f in explain_change(ref, ref_s, cur, cur_s).findings]
    assert labels[0] == "seg: d"
    assert "flag: False" not in labels
    unfiltered = explain_change(
        ref, ref_s, cur, cur_s, min_concentration=0, specificity=1.0, include_pairs=False
    )
    assert "flag: False" in [f.label for f in unfiltered.findings]


def test_min_concentration_must_be_non_negative() -> None:
    frame = pd.DataFrame({"g": ["a"]})
    with pytest.raises(InvalidInputError, match="min_concentration"):
        explain_change(frame, [1], frame, [1], min_concentration=-1)
