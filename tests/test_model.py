"""Network-free checks for the forecast and clustering helpers (ticket 0035)."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.model import (  # noqa: E402
    FEATURE_COLUMNS, cluster_parks, forecast_series, mae, mape,
    quarterly_series,
)

K_BOUNDS = (2, 6)


def test_quarterly_aggregation_and_interpolation():
    df = pd.DataFrame({
        "quarter_label": ["2019Q4", "2019Q4", "2020Q2", "2020Q2"],
        "count": [4, 6, 10, 20],
    })
    series, interpolated = quarterly_series(df)
    assert list(series.index) == ["2019Q4", "2020Q1", "2020Q2"]
    assert series["2019Q4"] == 10
    assert series["2020Q1"] == 20  # linear between 10 and 30
    assert series["2020Q2"] == 30
    assert interpolated == ["2020Q1"]


def test_mae_and_mape_hand_checked():
    assert mae([10, 20], [12, 18]) == pytest.approx(2.0)
    assert mape([10, 20], [12, 18]) == pytest.approx(15.0)
    assert mape([0, 20], [5, 18]) == pytest.approx(10.0)  # zero ignored
    assert mape([0, 0], [5, 5]) is None


def _synthetic_series(n=40, seed=0):
    t = np.arange(n)
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, 3.0, n)
    return (100 + 0.5 * t + 20 * np.sin(2 * np.pi * t / 4)
            + 5 * np.cos(2 * np.pi * t / 2) + noise)


def test_forecast_horizon_and_interval_ordering():
    result = forecast_series(
        _synthetic_series(), horizon=3, backtest=8, last_label="2020Q4",
    )
    forecast = result["forecast"]
    assert len(forecast) == 3
    assert list(forecast["quarter_label"]) == ["2021Q1", "2021Q2", "2021Q3"]
    assert (forecast["lower"] < forecast["point"]).all()
    assert (forecast["point"] < forecast["upper"]).all()
    assert result["baseline_wins"] == (result["selected_model"] == "seasonal_naive")
    # Textbook one-step seasonal rule is reported separately from the
    # recursive baseline that drives selection.
    assert result["baseline_mae_seasonal_rule"] >= 0.0


def _synthetic_features(n_per_blob=20, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for blob in range(3):
        base = rng.dirichlet(np.ones(7))
        for _ in range(n_per_blob):
            shares = rng.dirichlet(base * 20)
            rows.append({**dict(zip(FEATURE_COLUMNS[:7], shares)),
                         "log_total": 1.0 + blob,
                         "log_acres": 0.5 + 0.1 * blob})
    return pd.DataFrame(rows)


def test_clustering_silhouette_range_and_deterministic_seed():
    features = _synthetic_features()
    first = cluster_parks(features)
    second = cluster_parks(features)
    labels, _, k, score, scores, _ = first
    assert 0.0 <= score <= 1.0
    assert K_BOUNDS[0] <= k <= K_BOUNDS[1]
    assert len(labels) == len(features)
    assert np.array_equal(labels, second[0])
    assert score == second[3]
    assert k == second[2]
