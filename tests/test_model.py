"""Network-free checks for the forecast and clustering helpers (ticket 0035)."""

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis import model  # noqa: E402
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


def _naive_only(monkeypatch, fail=()):
    """Route every model to the real seasonal-naive frame except `fail`."""
    real = model._model_forecast

    def fake(name, values, steps, history_labels, future_labels,
             coverage_from=None, order=None, seasonal_order=None):
        if name in fail:
            raise RuntimeError("no convergence")
        return real(
            "seasonal_naive", values, steps, history_labels, future_labels,
        )

    monkeypatch.setattr(model, "_model_forecast", fake)


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


def test_forecast_lower_bounds_never_negative():
    # Low counts with ordinary noise make the Gaussian interval dip below 0.
    rng = np.random.default_rng(3)
    values = rng.poisson(1.5, 40).astype(float)
    result = forecast_series(values, horizon=4, backtest=8)
    assert (result["forecast"]["lower"] >= 0).all()


def test_forecast_flags_clipped_lower_bound(monkeypatch):
    """A clipped row keeps the raw quantile and is flagged, not smoothed."""
    _naive_only(monkeypatch)
    rng = np.random.default_rng(3)
    values = rng.poisson(1.5, 40).astype(float)
    forecast = forecast_series(values, horizon=4, backtest=8)["forecast"]
    clipped = forecast[forecast["clipped"]]
    assert not clipped.empty
    assert (clipped["clipless_lower"] <= 0).all()
    assert (clipped["lower"] == 0).all()
    rest = forecast[~forecast["clipped"]]
    assert (rest["clipless_lower"] == rest["lower"]).all()


# --------------------------------------------------------------------------
# Series builders, metrics and selection rules
# --------------------------------------------------------------------------

def test_quarter_label_arithmetic():
    assert model.parse_quarter("2020Q3") == (2020, 3)
    assert model.quarter_range("2019Q4", "2020Q2") == [
        "2019Q4", "2020Q1", "2020Q2",
    ]
    assert model.next_quarters("2019Q4", 2) == ["2020Q1", "2020Q2"]
    assert model.previous_quarters("2020Q1", 2) == ["2019Q4", "2020Q1"]
    assert model.previous_quarters("2020Q2", 4) == [
        "2019Q3", "2019Q4", "2020Q1", "2020Q2",
    ]


def test_rmse_and_recursive_seasonal_naive_hand_checked():
    assert model.rmse([1, 2], [1, 3]) == pytest.approx(np.sqrt(0.5))
    # Each forecast reuses the value one season earlier, including the
    # forecasts it has just produced.
    assert list(model.seasonal_naive_forecast([1, 2, 3, 4], 3)) == [1, 2, 3]


def test_model_forecast_rejects_an_unknown_model():
    with pytest.raises(ValueError, match="nope"):
        model._model_forecast(
            "nope", np.arange(20, dtype=float), 2,
            [f"T{i}" for i in range(20)], ["T21", "T22"],
        )


def test_holt_winters_interval_brackets_its_point():
    frame = model._model_forecast(
        "holt_winters", _synthetic_series(n=24, seed=1), 2,
        [f"T{i}" for i in range(24)], ["2021Q1", "2021Q2"],
    )
    assert list(frame.columns) == ["quarter_label", "point", "lower", "upper"]
    assert (frame["lower"] <= frame["point"]).all()
    assert (frame["point"] <= frame["upper"]).all()


def test_model_selection_ties_go_to_the_seasonal_naive_baseline(monkeypatch):
    """The 1 % tie rule keeps the simplest model on a tie."""
    _naive_only(monkeypatch)
    result = model.forecast_series(
        _synthetic_series(), horizon=2, backtest=8, last_label="2020Q4",
    )
    assert result["selected_model"] == "seasonal_naive"
    assert result["baseline_wins"] is True
    assert result["improvement_pct"] == 0.0
    assert result["model_failures"] == {}


def test_challenger_failures_are_recorded_not_swallowed(monkeypatch):
    _naive_only(monkeypatch, fail={"holt_winters", "glm_poisson",
                                   "sarimax", "sarimax_log"})
    result = model.forecast_series(_synthetic_series(), horizon=2, backtest=8)
    assert set(result["model_failures"]) == {
        "holt_winters", "glm_poisson", "sarimax", "sarimax_log",
    }
    assert "RuntimeError" in result["model_failures"]["holt_winters"]
    assert result["selected_model"] == "seasonal_naive"
    # No last label: generic horizon labels, no backtest window.
    assert list(result["forecast"]["quarter_label"]) == ["T+1", "T+2"]
    assert len(result["backtest_window"]) == 12


def test_forecast_series_rejects_a_series_too_short_to_backtest():
    with pytest.raises(ValueError, match="Not enough quarters"):
        model.forecast_series(np.arange(10, dtype=float))


def test_series_metrics_summarise_the_selection(monkeypatch):
    _naive_only(monkeypatch)
    result = model.forecast_series(
        _synthetic_series(), horizon=2, backtest=8, last_label="2020Q4",
    )
    metrics = model._series_metrics(result)
    assert metrics["selected_model"] == "seasonal_naive"
    assert metrics["backtest_quarters"] == 12
    assert metrics["backtest_window"] == model.previous_quarters("2020Q4", 12)
    assert metrics["selected_mae_sd"] >= 0.0
    assert metrics["tie_tolerance_pct"] == 1.0
    assert "rolling" in metrics["selection_caveat"]
    assert len(metrics["forecast"]) == 2


# --------------------------------------------------------------------------
# Data loading and derived narrative
# --------------------------------------------------------------------------

def test_load_crimes_falls_back_to_the_csv(fixture_warehouse, monkeypatch,
                                           tmp_path):
    monkeypatch.setattr(model, "DB_PATH", tmp_path / "absent.db")
    monkeypatch.setattr(model, "CSV_PATH", fixture_warehouse["csv"])
    monkeypatch.setattr(model, "GEO_CSV", fixture_warehouse["geo_csv"])
    crimes = model.load_crimes()
    assert set(crimes["park_id"].unique()) == set(
        fixture_warehouse["parks"]["park_id"]
    )
    assert pd.api.types.is_datetime64_any_dtype(crimes["period_start"])


def test_load_parks_is_empty_without_a_warehouse(monkeypatch, tmp_path):
    monkeypatch.setattr(model, "DB_PATH", tmp_path / "absent.db")
    assert list(model.load_parks().columns) == ["park_id", "lat", "lon"]


def test_caveats_derive_every_source_anomaly(fixture_world, monkeypatch):
    monkeypatch.setattr(model, "DB_PATH", fixture_world["db"])
    monkeypatch.setattr(model, "GEO_CSV", fixture_world["geo_csv"])
    monkeypatch.setattr(model, "TABLE_DIR", fixture_world["tables"])
    crimes = model.load_crimes()
    interpolated = ["2019Q4"]

    caveats = "\n".join(model.build_caveats(crimes, interpolated))
    assert "Combo Park" in caveats
    assert "TOTAL 999 vs somme 1" in caveats
    assert "MURDER" in caveats
    assert "2019Q4" in caveats

    footnote = model.build_footnote(crimes, interpolated)
    assert "Combo Park" in footnote
    assert "MURDER NULL en 2019Q3" in footnote
    assert "2019Q4 absent" in footnote


def test_park_feature_table_filters_parks_below_the_crime_floor():
    crimes = pd.DataFrame({
        "park_id": ["A", "A", "B"],
        "park": ["ALPHA", "ALPHA", "BETA"],
        "borough": ["BRONX"] * 3,
        "size_acres": [2.0, 2.0, 1.0],
        "period_start": pd.to_datetime(
            ["2019-01-01", "2019-04-01", "2019-01-01"]
        ),
        "crime_type": ["ROBBERY", "MURDER", "ROBBERY"],
        "count": [60.0, 10.0, 3.0],
    })
    features = model.park_feature_table(
        crimes, pd.DataFrame(columns=["park_id", "lat", "lon"]),
    )
    assert list(features.index) == ["A"]  # BETA has 3 < MIN_PARK_CRIMES (20)
    assert features.loc["A", "log_total"] == pytest.approx(np.log1p(70))
    assert features.loc["A", "log_acres"] == pytest.approx(np.log1p(2.0))
    assert features.loc["A", "share_robbery"] == pytest.approx(60 / 70)
    # Shrinkage moves the CLR share off the raw log-ratio.
    assert features.loc["A", "clr_robbery"] > 0
    assert np.isnan(features.loc["A", "lat"])


def test_coverage_onset_flags_a_park_entering_late():
    frame = _world_frame()
    frame["park_id"] = frame["park"]  # the warehouse adds park_id at ETL time
    # The frame has one park absent from the first 18 quarters.
    assert model.coverage_onset(frame) == "2018Q3"
    assert model.coverage_onset(frame[~frame["park"].eq("LATE PARK")]) is None


def test_diebold_mariano_is_null_when_losses_match():
    losses = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert model.diebold_mariano(losses, losses, horizon=4) is None
    worse = losses * 2.0
    p_value = model.diebold_mariano(worse, losses, horizon=4)
    assert p_value is not None and 0.0 <= p_value <= 1.0


def test_park_risk_table_guards_missing_acreage():
    crimes = pd.DataFrame({
        "park_id": ["A", "A", "B", "B"],
        "park": ["ALPHA", "ALPHA", "BETA", "BETA"],
        "borough": ["BRONX"] * 4,
        "size_acres": [10.0, 10.0, np.nan, np.nan],
        "period_start": pd.to_datetime(
            ["2019-01-01", "2019-04-01", "2019-01-01", "2019-04-01"]
        ),
        "quarter_label": ["2019Q1", "2019Q2", "2019Q1", "2019Q2"],
        "crime_type": ["ROBBERY"] * 4,
        "count": [5.0, 5.0, 1.0, 1.0],
    })
    clusters = pd.DataFrame({
        "park_id": ["A", "B"], "cluster": [0, 1],
    })
    risk = model.park_risk_table(crimes, clusters).set_index("park_id")
    assert risk.loc["A", "crimes_per_100_acres"] == pytest.approx(100.0)
    assert np.isnan(risk.loc["B", "crimes_per_100_acres"])
    assert np.isnan(risk.loc["B", "risk_rank"])
    assert risk.loc["A", "coverage_era"] == "2019Q1–2019Q2"
    assert risk.loc["A", "risk_rank"] == 1.0


# --------------------------------------------------------------------------
# End-to-end: the real pipeline on a short synthetic world
# --------------------------------------------------------------------------

CRIME_TYPES = sorted([
    "BURGLARY", "FELONY ASSAULT", "GRAND LARCENY", "GRAND LARCENY AUTO",
    "MURDER", "RAPE", "ROBBERY",
])
GAP_QUARTER = "2016Q2"


def _quarter_labels(start_year, count):
    labels = []
    year, quarter = start_year, 1
    for _ in range(count):
        labels.append(f"{year}Q{quarter}")
        quarter += 1
        if quarter == 5:
            year, quarter = year + 1, 1
    return labels


def _quarter_start(label):
    return pd.Timestamp(int(label[:4]), (int(label[-1]) - 1) * 3 + 1, 1)


def _row(label, park, borough, acres, crime, count, missing=0, mismatch=0):
    start = _quarter_start(label)
    return {
        "quarter_label": label, "period_start": start,
        "period_end": start + pd.offsets.QuarterEnd(),
        "park": park, "borough": borough, "size_acres": acres,
        "category": "PARK", "crime_type": crime, "count": count,
        "count_missing": missing, "total_mismatch": mismatch,
    }


def _world_frame():
    """20 quarters, 8 parks over two boroughs, one late park, one dataset-wide
    gap, one absent-column cell and one flagged TOTAL mismatch."""
    labels = _quarter_labels(2014, 20)
    rows = []
    for park_index in range(8):
        borough = "BRONX" if park_index < 4 else "MANHATTAN"
        park = f"PARK {park_index + 1:02d}"
        for position, label in enumerate(labels):
            if label == GAP_QUARTER:
                continue
            for type_index, crime in enumerate(CRIME_TYPES):
                # Not seasonal with period 4: the seasonal-naive baseline must
                # not be a perfect predictor (its MAE would be 0).
                count = float(
                    1 + (park_index * 11 + position * 7 + type_index * 3) % 5
                )
                missing = mismatch = 0
                if park_index == 0 and label == "2015Q1" and crime == "MURDER":
                    count, missing = np.nan, 1
                if park_index == 1 and label == "2016Q3" and crime == "RAPE":
                    mismatch = 1
                rows.append(_row(label, park, borough, 1.0 + park_index,
                                 crime, count, missing, mismatch))
    for label in labels[-2:]:
        for crime in CRIME_TYPES:
            rows.append(_row(label, "LATE PARK", "BROOKLYN/QUEENS", 2.0,
                             crime, 3.0))
    return pd.DataFrame(rows)


def _write_world(frame, root):
    processed = root / "processed"
    processed.mkdir(parents=True)
    db = root / "warehouse.db"
    with sqlite3.connect(db) as connection:
        frame.to_sql("crimes_long", connection, index=False)
    parks = frame.groupby(["park", "borough"], as_index=False)["size_acres"].last()
    parks["park_id"] = [f"P{index:03d}" for index in range(1, len(parks) + 1)]
    parks["lat"] = 40.70 + parks.index / 1000
    parks["lon"] = -73.90 - parks.index / 1000
    geo = processed / "parks_geo.csv"
    parks[["park", "borough", "park_id"]].to_csv(geo, index=False)
    with sqlite3.connect(db) as connection:
        parks[["park_id", "lat", "lon"]].to_sql("parks", connection, index=False)
    return db, geo


def test_main_writes_forecast_and_cluster_artefacts(tmp_path, monkeypatch):
    frame = _world_frame()
    db, geo = _write_world(frame, tmp_path / "world")
    figures = tmp_path / "outputs" / "figures"
    tables = tmp_path / "outputs" / "tables"
    metrics = tmp_path / "outputs" / "metrics"
    for directory in (figures, tables, metrics):
        directory.mkdir(parents=True)
    pd.DataFrame({
        "park": ["PARK 02"], "quarter": ["2016Q3"],
        "total_recorded": [999], "sum_components": [4],
        "city_total_from_components": [int(frame["count"].sum())],
        "city_total_using_recorded_total": [int(frame["count"].sum()) + 995],
    }).to_csv(tables / "source_anomaly_sensitivity.csv", index=False)
    for attribute, value in (
        ("DB_PATH", db), ("GEO_CSV", geo), ("FIG_DIR", figures),
        ("TABLE_DIR", tables), ("METRIC_DIR", metrics),
    ):
        monkeypatch.setattr(model, attribute, value)
    monkeypatch.setattr(model, "CSV_PATH", tmp_path / "absent.csv")

    model.main()

    for name in ("fig07_forecast.png", "fig08_clusters.png",
                 "fig09_forecast_boroughs.png", "fig10_residuals.png"):
        assert (figures / name).stat().st_size > 0, name
    city = pd.read_csv(tables / "forecast_city.csv")
    assert list(city["scope"]) == ["CITYWIDE"] * 4
    assert (city["lower"] >= 0).all()
    boroughs = pd.read_csv(tables / "forecast_boroughs.csv")
    assert set(boroughs["borough"]) == {"BRONX", "MANHATTAN"}
    clusters = pd.read_csv(tables / "park_clusters.csv")
    assert len(clusters) >= 8
    assert (tables / "cluster_profiles.csv").is_file()
    risk = pd.read_csv(tables / "park_risk.csv")
    assert {"crimes_per_100_acres", "coverage_era", "cluster"} <= set(risk.columns)
    sensitivity = pd.read_csv(tables / "interpolation_sensitivity.csv")
    assert set(sensitivity["interpolation"]) == {"linear", "seasonal"}

    payload = json.loads(
        (metrics / "model_metrics.json").read_text(encoding="utf-8")
    )
    assert payload["citywide"]["n_quarters"] == 20
    assert len(payload["citywide"]["backtest_origins"]) == 3
    assert payload["citywide"]["diagnostics"]["aicc"] is not None or (
        "error" in payload["citywide"]["diagnostics"]
    )
    skipped = payload["skipped_boroughs"]
    assert "BROOKLYN/QUEENS" in skipped
    assert "libellé hybride" in skipped["BROOKLYN/QUEENS"]
    assert 2 <= payload["clustering"]["selected_k"] <= 6
    names = payload["clustering"]["cluster_names"].values()
    assert len(set(names)) == len(names)  # honest, unique labels
    caveats = "\n".join(payload["caveats"])
    assert "Late Park" in caveats
    assert "TOTAL 999 vs somme" in caveats
    assert "MURDER" in caveats
    assert "interpolé" in caveats


