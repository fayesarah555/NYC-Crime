"""Network-free checks for the EDA helpers (ticket 0034, 0048)."""

import ast
import json
import shutil
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.eda import (  # noqa: E402
    chi_square, cramers_v, park_totals, rate_per_100_acres,
)


def test_chi_square_hand_checked_2x2():
    # [[10, 20], [30, 40]]: chi2 = 100 * (400 - 600)^2 / (30*70*40*60)
    statistic, p_value, dof, _ = chi_square([[10, 20], [30, 40]])
    assert statistic == pytest.approx(0.7936507936507937)
    assert p_value == pytest.approx(0.3730, abs=1e-3)
    assert dof == 1


def test_cramers_v_zero_on_independent_table():
    table = [[10, 20, 30], [20, 40, 60]]
    statistic, _, _, _ = chi_square(table)
    assert cramers_v(statistic, 180, (2, 3)) == pytest.approx(0.0, abs=1e-12)


def test_cramers_v_in_unit_interval():
    statistic, _, _, _ = chi_square([[10, 20], [30, 40]])
    value = cramers_v(statistic, 100, (2, 2))
    assert 0.0 <= value <= 1.0


def test_rate_per_100_acres():
    assert rate_per_100_acres(50, 200) == pytest.approx(25.0)
    assert rate_per_100_acres(0, 200) == 0.0
    assert rate_per_100_acres(5, 0) == 0.0


def fixture_crimes(fixture_warehouse, monkeypatch):
    from analysis import eda

    monkeypatch.setattr(eda, "DB_PATH", fixture_warehouse["db"])
    monkeypatch.setattr(eda, "CSV_PATH", fixture_warehouse["csv"])
    monkeypatch.setattr(eda, "GEO_CSV", fixture_warehouse["geo_csv"])
    return eda.load_crimes()


def test_null_murder_cells_stay_null_not_zero(fixture_warehouse, monkeypatch):
    df = fixture_crimes(fixture_warehouse, monkeypatch)
    murder = df[df["crime_type"] == "MURDER"]
    missing = murder[murder["count"].isna()]
    assert set(missing["quarter_label"]) == {"2019Q3"}
    assert missing["count_missing"].eq(1).all()
    assert not (missing["count"] == 0).any()


def test_total_mismatch_components_kept_and_flagged(fixture_warehouse, monkeypatch):
    df = fixture_crimes(fixture_warehouse, monkeypatch)
    cell = df[df["park"].eq("COMBO PARK") & df["quarter_label"].eq("2019Q2")]
    assert len(cell) == 7
    assert cell["total_mismatch"].eq(1).all()
    assert int(cell["count"].sum()) == 1


def test_duplicate_park_name_fixture_groups_once_per_park_id():
    frame = pd.DataFrame({
        "park_id": ["Q1", "M1", "Q1"],
        "park": ["ROSE PARK", "ROSE PARK", "ROSE PARK"],
        "borough": ["QUEENS", "MANHATTAN", "QUEENS"],
        "count": [3, 5, 4],
    })
    totals = park_totals(frame).set_index("park_id")
    assert len(totals) == 2
    assert totals.loc["Q1", "count"] == 7
    assert totals.loc["M1", "count"] == 5


def test_coverage_gaps_flag_the_total_mismatch(fixture_warehouse, monkeypatch):
    from analysis.eda import coverage_gaps

    df = fixture_crimes(fixture_warehouse, monkeypatch)
    gaps = coverage_gaps(df).set_index("park")
    combo = gaps.loc["COMBO PARK"]
    assert "2019Q2" in combo["missing_quarters"].split()


def test_rate_table_reconciles_perimeter_and_coverage(fixture_warehouse, monkeypatch):
    from analysis.eda import borough_rate_table

    df = fixture_crimes(fixture_warehouse, monkeypatch)
    rates = borough_rate_table(df)
    for column in (
        "parks_with_acreage", "crimes_with_acreage", "excluded_crimes",
        "crime_coverage_pct", "acres", "rate_per_100_acres",
        "rate_excl_central_park", "central_park_crimes", "central_park_acres",
    ):
        assert column in rates.columns, column
    for row in rates.itertuples():
        assert row.total_crimes == row.crimes_with_acreage + row.excluded_crimes


IDENTITY_COLUMN = "park_id"


def bare_park_groupbys(source):
    """Line numbers of groupby calls naming "park" without the park_id key."""
    offenders = []
    for node in ast.walk(ast.parse(source)):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "groupby"
        ):
            continue
        by = node.args[0] if node.args else next(
            (keyword.value for keyword in node.keywords if keyword.arg == "by"),
            None,
        )
        if isinstance(by, (ast.List, ast.Tuple)):
            names = [elt.value for elt in by.elts if isinstance(elt, ast.Constant)]
        elif isinstance(by, ast.Constant):
            names = [by.value]
        else:
            names = []
        if "park" in names and IDENTITY_COLUMN not in names:
            offenders.append(node.lineno)
    return offenders


def test_bare_park_groupby_gate_accepts_and_rejects_fixtures():
    assert bare_park_groupbys('df.groupby("park")') == [1]
    assert bare_park_groupbys("df.groupby('park', as_index=False)") == [1]
    assert bare_park_groupbys('df.groupby(["park", "borough"])') == [1]
    assert bare_park_groupbys('df.groupby(by="park")') == [1]
    assert bare_park_groupbys('df.groupby("park_id")') == []
    assert bare_park_groupbys('df.groupby(["park_id", "park", "borough"])') == []
    assert bare_park_groupbys('df.groupby("quarter_label", as_index=False)') == []


def test_no_bare_park_groupby_in_analysis_or_export():
    offenders = []
    for directory in ("analysis", "export"):
        for source in (ROOT / directory).glob("*.py"):
            offenders += [
                f"{source.name}:{number}"
                for number in bare_park_groupbys(
                    source.read_text(encoding="utf-8")
                )
            ]
    assert offenders == []


# --------------------------------------------------------------------------
# End-to-end: the real EDA pipeline on a two-year fixture world
# --------------------------------------------------------------------------

FIGURES = (
    "fig01_quarterly_trend.png", "fig02_seasonality.png",
    "fig03_borough_type_heatmap.png", "fig04_top_parks.png",
    "fig05_rate_per_100acres.png", "fig06_zero_share.png",
)
TABLES = (
    "top_parks.csv", "borough_type_share.csv", "rate_by_borough.csv",
    "coverage_gaps.csv", "source_anomaly_sensitivity.csv", "yoy_changes.csv",
)


def _relabelled(rows, year, quarter):
    out = rows.copy()
    out["quarter_label"] = f"{year}Q{quarter}"
    start = pd.Timestamp(year, (quarter - 1) * 3 + 1, 1)
    out["period_start"] = start
    out["period_end"] = start + pd.offsets.QuarterEnd()
    return out


def _two_year_frame(frame):
    """Fixture rows stretched over 2018-2019 so the YoY paths can run.

    2018Q2 is removed on purpose: it drives the missing-quarter grid, the
    internal-gap table and the coverage footnote. 2019Q4 copies the
    all-columns 2019Q1 rows so the last year is complete. LATE PARK appears
    only in 2019, which drives the late-park / YoY-artefact branches.
    """
    parts = []
    for year in (2018, 2019):
        for quarter in (1, 2, 3):
            if (year, quarter) == (2018, 2):
                continue
            rows = frame[frame["quarter_label"].str[-1].astype(int).eq(quarter)]
            parts.append(_relabelled(rows, year, quarter))
    q1 = frame[frame["quarter_label"].eq("2019Q1")]
    parts.append(_relabelled(q1, 2018, 4))
    parts.append(_relabelled(q1, 2019, 4))

    late_rows = []
    for quarter, month in ((1, 1), (2, 4), (3, 7), (4, 10)):
        for crime, count in (("ROBBERY", 2), ("BURGLARY", 1)):
            start = pd.Timestamp(2019, month, 1)
            late_rows.append({
                "quarter_label": f"2019Q{quarter}",
                "period_start": start,
                "period_end": start + pd.offsets.QuarterEnd(),
                "park": "LATE PARK", "borough": "QUEENS", "size_acres": 1.0,
                "category": "PLAYGROUND", "crime_type": crime,
                "count": float(count), "count_missing": 0, "total_mismatch": 0,
            })
    return pd.concat(parts + [pd.DataFrame(late_rows)], ignore_index=True)


def _write_world(frame, root):
    """Warehouse DB + geography CSV, the two files eda.load_crimes reads."""
    root.mkdir(parents=True)
    db = root / "warehouse.db"
    with sqlite3.connect(db) as connection:
        frame.to_sql("crimes_long", connection, index=False)
    parks = frame.groupby(["park", "borough"], as_index=False)["size_acres"].last()
    parks["park_id"] = [f"F{index:03d}" for index in range(1, len(parks) + 1)]
    geo = root / "parks_geo.csv"
    parks[["park", "borough", "park_id"]].to_csv(geo, index=False)
    return db, geo


def test_main_writes_every_figure_table_and_stat(tmp_path, fixture_warehouse,
                                                 fixture_world, monkeypatch):
    from analysis import eda

    frame = _two_year_frame(fixture_warehouse["frame"])
    db, geo = _write_world(frame, tmp_path / "world")
    figures, tables, metrics = (
        tmp_path / "outputs" / "figures",
        tmp_path / "outputs" / "tables",
        tmp_path / "outputs" / "metrics",
    )
    for directory in (figures, tables, metrics):
        directory.mkdir(parents=True)
    shutil.copyfile(
        fixture_world["tables"] / "source_anomalies.csv",
        tables / "source_anomalies.csv",
    )
    monkeypatch.setattr(eda, "DB_PATH", db)
    monkeypatch.setattr(eda, "CSV_PATH", tmp_path / "absent.csv")
    monkeypatch.setattr(eda, "GEO_CSV", geo)
    monkeypatch.setattr(eda, "FIG_DIR", figures)
    monkeypatch.setattr(eda, "TABLE_DIR", tables)
    monkeypatch.setattr(eda, "METRIC_DIR", metrics)

    eda.main()

    for name in FIGURES:
        assert (figures / name).stat().st_size > 0, name
    for name in TABLES:
        assert (tables / name).is_file(), name

    stats = json.loads((metrics / "eda_stats.json").read_text(encoding="utf-8"))
    assert stats["first_quarter"] == "2018Q1"
    assert stats["last_quarter"] == "2019Q4"
    assert stats["quarters_total"] == 7
    assert stats["missing_quarter"] == "2018Q2"
    assert stats["total_crimes"] > 0
    assert stats["coverage_artifact"] is True
    assert [entry["park"] for entry in stats["late_parks"]] == ["LATE PARK"]
    assert [entry["quarter"] for entry in stats["source_anomalies"]] == ["2019Q2"]
    assert stats["source_anomalies"][0]["total_recorded"] == 999
    assert stats["source_anomalies"][0]["sum_computed"] == 1
    assert stats["missing_column_types"] == ["MURDER"]
    assert stats["null_count_rows"] > 0
    assert stats["chi2_dof"] >= 1

    yoy = pd.read_csv(tables / "yoy_changes.csv")
    assert set(yoy["quarter"]) == {"2019Q1", "2019Q3", "2019Q4"}
    gaps = pd.read_csv(tables / "coverage_gaps.csv")
    assert "LATE PARK" in set(gaps["park"])
    sensitivity = pd.read_csv(tables / "source_anomaly_sensitivity.csv")
    assert sensitivity.iloc[0]["city_total_using_recorded_total"] == (
        sensitivity.iloc[0]["city_total_from_components"] + 998
    )
