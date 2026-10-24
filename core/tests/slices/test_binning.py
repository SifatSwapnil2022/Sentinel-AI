from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sentinel_core.errors import InvalidInputError, NotFittedError
from sentinel_core.slices import MISSING_LABEL, OTHER_LABEL, SliceBinner, format_number


@pytest.fixture
def reference() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "income": np.linspace(0, 100_000, 1000),  # quartiles are exactly 25k, 50k, 75k
            "region": ["A"] * 500 + ["B"] * 300 + ["C"] * 150 + ["D"] * 50,
            "education": [1, 2, 3, 4] * 250,  # numeric codes, low cardinality
            "flag": [True, False] * 500,
        }
    )


def test_numeric_quartile_labels(reference: pd.DataFrame) -> None:
    binner = SliceBinner().fit(reference)
    bins = binner.bins("income")
    assert bins.is_numeric
    assert bins.labels == ("< 25k", "25k – 50k", "50k – 75k", "≥ 75k")


def test_values_on_edges_go_to_the_upper_bin(reference: pd.DataFrame) -> None:
    binner = SliceBinner().fit(reference)
    edge = binner.bins("income").edges
    assert edge is not None
    labels = binner.transform(reference.iloc[:3].assign(income=[edge[0] - 1, edge[0], edge[-1]]))
    assert labels["income"].tolist() == ["< 25k", "25k – 50k", "≥ 75k"]


def test_low_cardinality_numeric_is_categorical(reference: pd.DataFrame) -> None:
    bins = SliceBinner().fit(reference).bins("education")
    assert not bins.is_numeric
    assert set(bins.labels) == {"1", "2", "3", "4"}


def test_top_categories_and_other(reference: pd.DataFrame) -> None:
    binner = SliceBinner(max_categories=2).fit(reference)
    assert binner.bins("region").labels == ("A", "B", OTHER_LABEL)
    out = binner.transform(reference)
    assert out["region"].value_counts()[OTHER_LABEL] == 200


def test_unseen_and_missing_values(reference: pd.DataFrame) -> None:
    binner = SliceBinner().fit(reference)
    window = reference.iloc[:3].assign(region=["A", "Z", None], income=[np.nan, 5.0, 1e9])
    out = binner.transform(window)
    assert out["region"].tolist() == ["A", OTHER_LABEL, MISSING_LABEL]
    assert out["income"].tolist() == [MISSING_LABEL, "< 25k", "≥ 75k"]


def test_booleans_are_categories(reference: pd.DataFrame) -> None:
    out = SliceBinner().fit(reference).transform(reference)
    assert set(out["flag"]) == {"True", "False"}


def test_fit_on_feature_subset_and_index_preserved(reference: pd.DataFrame) -> None:
    binner = SliceBinner().fit(reference, features=["region"])
    window = reference.set_index(reference.index + 100)
    out = binner.transform(window)
    assert list(out.columns) == ["region"]
    assert out.index.equals(window.index)


def test_close_edges_keep_distinct_labels() -> None:
    frame = pd.DataFrame({"x": np.linspace(1.0001, 1.0009, 400)})
    labels = SliceBinner().fit(frame).bins("x").labels
    assert len(set(labels)) == len(labels)


def test_errors(reference: pd.DataFrame) -> None:
    with pytest.raises(NotFittedError):
        SliceBinner().transform(reference)
    with pytest.raises(NotFittedError):
        SliceBinner().bins("income")
    with pytest.raises(InvalidInputError, match="missing features"):
        SliceBinner().fit(reference, features=["nope"])
    with pytest.raises(InvalidInputError, match="missing features"):
        SliceBinner().fit(reference).transform(reference.drop(columns="region"))
    with pytest.raises(InvalidInputError):
        SliceBinner(n_bins=1)
    with pytest.raises(InvalidInputError):
        SliceBinner(max_categories=0)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.5, "0.5"),
        (950.0, "950"),
        (14_700.0, "14.7k"),
        (2_500_000.0, "2.5M"),
        (-3_000.0, "-3k"),
        (7.2e9, "7.2B"),
        (float("inf"), "inf"),
    ],
)
def test_format_number(value: float, expected: str) -> None:
    assert format_number(value) == expected
