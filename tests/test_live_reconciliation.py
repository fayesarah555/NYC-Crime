"""Reconciliation against the real data/ artefacts; skipped when absent.

Everything here is `live`: the numbers below are facts about the published
workbooks, not invariants of the code. CI runs `pytest -m "not live"`; a local
`make data warehouse geo eda model` makes these tests run again.
"""

import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

pytestmark = pytest.mark.live

DATA = ROOT / "data"


@pytest.fixture(autouse=True)
def require_live_data():
    if not (DATA / "warehouse.db").exists():
        pytest.skip(
            "data/warehouse.db absent; run `make data warehouse geo eda model` first"
        )


FILES = (
    "meta.json", "parks.json", "series.json",
    "borough_type.json", "forecast.json", "clusters.json", "cubes.json",
)


# ---------------------------------------------------------------- parsing ---

@pytest.mark.parametrize(
    "name, quarter",
    [
        ("nyc-park-crime-stats-q1-2015.xlsx", "2015Q1"),
        ("nyc-park-crime-stats-q1-2026.xlsx", "2026Q1"),
    ],
)
def test_real_workbooks_parse_cleanly(tmp_path, name, quarter):
    from etl.parse import CRIME_TYPES, parse_all

    source = DATA / "raw" / name
    if not source.exists():
        pytest.skip(f"{source} absent; run `make data` first")
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / name).write_bytes(source.read_bytes())

    parsed, records, violations = parse_all(raw)

    assert violations == []
    assert [workbook["quarter"] for workbook in parsed] == [quarter]
    assert len(records) == parsed[0]["source_rows"] * len(CRIME_TYPES)
    assert {record["quarter_label"] for record in records} == {quarter}
    assert {record["crime_type"] for record in records} == set(CRIME_TYPES)
    assert any(record["count"] == 0 for record in records)


# ----------------------------------------------------------------- export ---

@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    from export import export_web as ew

    if not (DATA / "warehouse.db").exists():
        pytest.skip("data/warehouse.db absent; run `make data ... eda model` first")
    out = tmp_path_factory.mktemp("live-web-data")
    ew.main(["--out", str(out)])
    return out


def load(out, name):
    return json.loads((out / name).read_text(encoding="utf-8"))


def test_meta_periods_totals_caveats(exported):
    meta = load(exported, "meta.json")
    assert meta["periods"]["count"] == 46
    assert meta["periods"]["first"] == "2014Q4"
    assert meta["periods"]["last"] == "2026Q2"
    assert meta["periods"]["missing"] == ["2020Q1"]
    assert meta["totals"]["crimes"] == 12544
    assert meta["totals"]["parks_with_crimes"] == 792
    assert meta["geo"]["matched"] == 1009
    assert meta["geo"]["coverage_pct"] == 87.4
    caveats = " ".join(meta["caveats"])
    assert "Central Park" in caveats
    assert "BROOKLYN/QUEENS" in caveats
    assert "2020Q1" in caveats


def test_meta_caveats_fr_parallel_and_french(exported):
    meta = load(exported, "meta.json")
    assert len(meta["caveats_fr"]) == len(meta["caveats"])
    fr = " ".join(meta["caveats_fr"])
    assert "artefact de couverture" in fr
    assert "jamais traité comme zéro" in fr
    assert "libellé combiné" in fr
    assert "5 parcs dans la source, 4 avec au moins un crime" in fr
    assert "Central Park" in fr
    assert "colonne MURDER" in fr


def test_meta_ci_alpha_and_murder_caveat(exported):
    meta = load(exported, "meta.json")
    assert meta["ci_alpha"] == 0.05
    caveats = " ".join(meta["caveats"])
    assert "MURDER" in caveats
    assert "2024Q2" in caveats and "2025Q1" in caveats
    assert "null (missing)" in caveats
    assert "excluded from sums" in caveats


def test_parks_rows_and_type_sums(exported):
    parks = load(exported, "parks.json")
    assert len(parks) == 792
    for row in parks:
        assert len(row["counts"]) == 7
        assert row["park_id"]
        assert row["total"] == sum(
            value for value in row["counts"].values() if value is not None
        )
        assert row["cluster"] is None or 0 <= row["cluster"] <= 3


def test_series_quarters_and_city_total(exported):
    series = load(exported, "series.json")
    assert len(series["quarters"]) == 46
    assert "2020Q1" not in series["quarters"]
    assert sum(series["city"]) == 12544
    assert set(series["boroughs"]) == {
        "BRONX", "BROOKLYN", "BROOKLYN/QUEENS", "MANHATTAN", "QUEENS",
        "STATEN ISLAND",
    }
    for values in series["boroughs"].values():
        assert len(values) == 46


def test_staten_island_series_kept_and_sums_to_154(exported):
    series = load(exported, "series.json")
    assert sum(series["boroughs"]["STATEN ISLAND"]) == 154
    assert sum(series["boroughs"]["BROOKLYN/QUEENS"]) == 114


def test_borough_type_matrix(exported):
    table = load(exported, "borough_type.json")
    assert len(table["crime_types"]) == 7
    assert len(table["boroughs"]) == 6
    assert sum(row["total"] for row in table["boroughs"]) == 12544


def test_forecast_points_and_metrics(exported):
    forecast = load(exported, "forecast.json")
    assert len(forecast["city"]) == 4
    assert set(forecast["boroughs"]) == {"BRONX", "BROOKLYN", "MANHATTAN", "QUEENS"}
    points = forecast["city"] + [
        point for block in forecast["boroughs"].values() for point in block
    ]
    assert all(isinstance(point["clipped"], bool) for point in points)
    assert any(point["clipped"] for point in points)
    assert forecast["caveat"] and forecast["caveat_fr"]
    meta = load(exported, "meta.json")
    level = round((1 - meta["ci_alpha"]) * 100)
    assert f"{level} %" in forecast["caveat"]
    assert f"à {level} %" in forecast["caveat_fr"]
    assert any("clipped at 0" in caveat for caveat in meta["caveats"])
    assert any("ramenée à 0" in caveat for caveat in meta["caveats_fr"])


def test_clusters_profiles_and_silhouettes(exported):
    clusters = load(exported, "clusters.json")
    metrics = json.loads(
        (ROOT / "outputs" / "metrics" / "model_metrics.json").read_text(
            encoding="utf-8"
        )
    )
    assert clusters["k"] == metrics["clustering"]["selected_k"]
    assert len(clusters["profiles"]) == clusters["k"]
    assert len(clusters["parks"]) == metrics["clustering"]["n_parks"]
    names = [profile["name"] for profile in clusters["profiles"]]
    assert len(set(names)) == len(names)  # honest, unique labels
    for row in clusters["parks"]:
        assert -1.0 <= row["sample_silhouette"] <= 1.0


def test_combined_borough_caveat_reports_source_and_emitted_rows(exported):
    meta = load(exported, "meta.json")
    parks = load(exported, "parks.json")
    combined = [p for p in parks if p["borough"] == "BROOKLYN/QUEENS"]
    assert len(combined) == 4
    assert meta["combined_borough"]["parks_source"] == 5
    assert meta["combined_borough"]["parks_with_crimes"] == len(combined)
    caveats = " ".join(meta["caveats"])
    assert "5 parks in the source, 4 with at least one crime" in caveats


def test_meta_park_quarters_and_long_rows_are_measured(exported):
    meta = load(exported, "meta.json")
    with sqlite3.connect(DATA / "warehouse.db") as conn:
        park_quarters = conn.execute(
            "SELECT COUNT(*) FROM ("
            "SELECT DISTINCT quarter_label, park FROM crimes_long)"
        ).fetchone()[0]
        long_rows = conn.execute("SELECT COUNT(*) FROM crimes_long").fetchone()[0]
    assert meta["totals"]["park_quarters"] == park_quarters
    assert meta["totals"]["long_rows"] == long_rows
    assert meta["totals"]["park_quarters"] < meta["totals"]["long_rows"]


# -------------------------------------------------------------------- EDA ---

def test_stats_json_values_in_range():
    path = ROOT / "outputs" / "metrics" / "eda_stats.json"
    if not path.exists():
        pytest.skip("run analysis/eda.py first")
    stats = json.loads(path.read_text(encoding="utf-8"))
    for key in ("chi2_p_value", "cramers_v", "total_crimes", "peak_quarter",
                "chi2_p_display", "chi2_min_expected", "chi2_assumption",
                "coverage_artifact", "yoy_excluding_new_parks_pct"):
        assert key in stats
    assert 0.0 <= stats["cramers_v"] <= 1.0
    assert 0.0 <= stats["chi2_p_value"] <= 1.0
    assert stats["coverage_artifact"] is True
    assert stats["yoy_excluding_new_parks_pct"] < stats["yoy_change_pct"]


def test_central_park_first_quarter_is_2025q1():
    from analysis.eda import load_crimes

    df = load_crimes()
    first = df.loc[df["park"] == "CENTRAL PARK", "quarter_label"].min()
    assert first == "2025Q1"


def test_null_murder_cells_stay_null_not_zero():
    from analysis.eda import load_crimes

    df = load_crimes()
    murder = df[df["crime_type"] == "MURDER"]
    missing = murder[murder["count"].isna()]
    assert set(missing["quarter_label"]) == {"2024Q2", "2025Q1"}
    assert missing["count_missing"].eq(1).all()
    assert not (missing["count"] == 0).any()


def test_flushing_2025q4_components_kept_and_flagged():
    from analysis.eda import load_crimes

    df = load_crimes()
    cell = df[
        df["park"].eq("FLUSHING MEADOWS CORONA PARK")
        & df["quarter_label"].eq("2025Q4")
    ]
    assert len(cell) == 7
    assert cell["total_mismatch"].eq(1).all()
    assert int(cell["count"].sum()) == 18
    sensitivity = pd.read_csv(
        ROOT / "outputs" / "tables" / "source_anomaly_sensitivity.csv"
    )
    row = sensitivity[
        sensitivity["park"] == "FLUSHING MEADOWS CORONA PARK"
    ].iloc[0]
    assert row["total_recorded"] == 17
    assert row["sum_components"] == 18
    assert (
        row["city_total_from_components"]
        - row["city_total_using_recorded_total"] == 1
    )


def test_coverage_gaps_list_known_internal_gaps():
    path = ROOT / "outputs" / "tables" / "coverage_gaps.csv"
    if not path.exists():
        pytest.skip("run analysis/eda.py first")
    gaps = pd.read_csv(path).set_index("park")
    flushing = gaps.loc["FLUSHING MEADOWS CORONA PARK"]
    assert "2025Q4" in flushing["missing_quarters"].split()
    assert "total_mismatch" in flushing["gap_reasons"]
    corona = gaps.loc["CORONA HEALTH SANCTUARY"]
    assert "2022Q2" in corona["missing_quarters"].split()
    assert "no_rows" in corona["gap_reasons"]


# ------------------------------------------------------------------ model ---

def test_model_metrics_artefact_has_ci_alpha_and_clean_bounds():
    path = ROOT / "outputs" / "metrics" / "model_metrics.json"
    if not path.exists():
        pytest.skip("run `make model` first")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["ci_alpha"] == 0.05
    for block in [data["citywide"], *data["boroughs"].values()]:
        assert all(row["lower"] >= 0 for row in block["forecast"])


# -------------------------------------------------------------------- app ---

def test_forecast_interval_level_derived_from_metrics():
    metrics = ROOT / "outputs" / "metrics" / "model_metrics.json"
    if not metrics.exists():
        pytest.skip("run `make model` first")
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "app" / "app.py")).run(timeout=120)
    assert not at.exception
    captions = [element.value for element in at.caption]
    assert any("intervalle à 95 %" in caption for caption in captions), captions
