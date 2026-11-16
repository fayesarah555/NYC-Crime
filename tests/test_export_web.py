"""Network-free checks for the static web data export (ticket 0038).

Every test runs on the synthetic fixture warehouse; assertions on the live
dataset's own numbers live in tests/test_live_reconciliation.py.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "meta.json", "parks.json", "series.json",
    "borough_type.json", "forecast.json", "clusters.json", "cubes.json",
)


@pytest.fixture(scope="session")
def exported(tmp_path_factory, fixture_world):
    """Run the export over the fixture world into a scratch directory."""
    from export import export_web as ew

    out = tmp_path_factory.mktemp("web-data")
    with pytest.MonkeyPatch.context() as patch:
        for name, value in fixture_world["export_paths"].items():
            patch.setattr(ew, name, value)
        ew.main(["--out", str(out)])
    return out


def load(out, name):
    return json.loads((out / name).read_text(encoding="utf-8"))


def test_seven_files_and_payload_budget(exported):
    assert all((exported / name).is_file() for name in FILES)
    total = sum((exported / name).stat().st_size for name in FILES)
    assert total < 2 * 1024 * 1024


def test_meta_provenance_fields(exported, fixture_world):
    meta = load(exported, "meta.json")
    assert meta["schema_version"] == 3
    assert meta["quarters_total"] == len(fixture_world["quarters"])
    assert meta["missing_quarters"] == []
    assert meta["pipeline_version"] == "1.0.0"
    assert meta["generated_at"].endswith("Z") and "T" in meta["generated_at"]
    assert len(meta["git_commit"]) >= 7 or meta["git_commit"] == "unknown"
    assert len(meta["source_manifest_sha256"]) == 64
    assert isinstance(meta["git_dirty"], bool)
    assert meta["git_commit"].endswith("-dirty") == meta["git_dirty"]
    if meta["git_dirty"]:
        assert meta["git_commit_note"]["fr"] and meta["git_commit_note"]["en"]


def test_cube_sums_match_parks_and_city_zero_tolerance(exported):
    cube = load(exported, "cubes.json")
    parks = load(exported, "parks.json")
    series = load(exported, "series.json")
    assert cube["quarters"] == series["quarters"]
    assert cube["crime_types"] == sorted(series["city_by_type"])
    quarter_index = {label: index for index, label in enumerate(cube["quarters"])}

    # A null cell is a missing column: it contributes nothing to any sum.
    by_park = {
        park_id: sum(
            value for counts in cells.values() for value in counts
            if value is not None
        )
        for park_id, cells in cube["parks"].items()
    }
    assert by_park == {row["park_id"]: row["total"] for row in parks}

    by_quarter = [0] * len(cube["quarters"])
    by_type = dict.fromkeys(cube["crime_types"], 0)
    for cells in cube["parks"].values():
        for quarter, counts in cells.items():
            by_quarter[quarter_index[quarter]] += sum(
                value for value in counts if value is not None
            )
            for crime_type, value in zip(cube["crime_types"], counts):
                if value is not None:
                    by_type[crime_type] += value
    assert by_quarter == series["city"]
    assert by_type == {
        crime_type: sum(values)
        for crime_type, values in series["city_by_type"].items()
    }
    assert all(counts for cells in cube["parks"].values() for counts in cells.values())


def test_meta_periods_totals_caveats(exported, fixture_world):
    meta = load(exported, "meta.json")
    quarters = fixture_world["quarters"]
    assert meta["periods"]["count"] == len(quarters)
    assert meta["periods"]["first"] == quarters[0]
    assert meta["periods"]["last"] == quarters[-1]
    assert meta["periods"]["missing"] == []
    assert meta["totals"]["crimes"] == int(fixture_world["frame"]["count"].sum())
    assert meta["totals"]["parks_with_crimes"] == int(
        (fixture_world["frame"]["count"].groupby(
            fixture_world["frame"]["park"]).sum() > 0).sum()
    )
    assert meta["geo"]["matched"] == len(fixture_world["parks"])
    assert meta["geo"]["coverage_pct"] == 100.0
    caveats = " ".join(meta["caveats"])
    assert "BROOKLYN/QUEENS" in caveats
    assert "MURDER" in caveats  # the q3 workbook has no MURDER column


def test_meta_caveats_fr_parallel_and_french(exported):
    meta = load(exported, "meta.json")
    assert len(meta["caveats_fr"]) == len(meta["caveats"])
    fr = " ".join(meta["caveats_fr"])
    assert "libellé combiné" in fr
    assert "colonne MURDER" in fr


def test_meta_ci_alpha_and_murder_caveat(exported):
    meta = load(exported, "meta.json")
    assert meta["ci_alpha"] == 0.05
    caveats = " ".join(meta["caveats"])
    assert "MURDER" in caveats
    assert "2019Q3" in caveats
    assert "null (missing)" in caveats
    assert "excluded from sums" in caveats


def test_parks_rows_and_type_sums(exported, fixture_world):
    parks = load(exported, "parks.json")
    assert len(parks) == int(
        (fixture_world["frame"]["count"].groupby(
            fixture_world["frame"]["park"]).sum() > 0).sum()
    )
    for row in parks:
        assert len(row["counts"]) == 7
        assert row["park_id"]
        assert row["total"] == sum(
            value for value in row["counts"].values() if value is not None
        )
        assert row["dominant_type"] == max(row["counts"], key=row["counts"].get)
        assert (row["lat"] is None) == (row["lon"] is None)
        assert row["cluster"] is None or row["cluster"] == 0


def test_series_quarters_and_city_total(exported, fixture_world):
    series = load(exported, "series.json")
    assert series["quarters"] == fixture_world["quarters"]
    assert sum(series["city"]) == int(fixture_world["frame"]["count"].sum())
    assert set(series["boroughs"]) == {"BRONX", "BROOKLYN/QUEENS", "MANHATTAN"}
    for values in series["boroughs"].values():
        assert len(values) == len(series["quarters"])


def test_series_city_by_type_sums_to_city(exported):
    series = load(exported, "series.json")
    assert len(series["city_by_type"]) == 7
    for crime_type, values in series["city_by_type"].items():
        assert len(values) == len(series["quarters"]), crime_type
    for index, city_total in enumerate(series["city"]):
        per_type = sum(values[index] for values in series["city_by_type"].values())
        assert per_type == city_total, series["quarters"][index]


def test_borough_type_matrix(exported, fixture_world):
    table = load(exported, "borough_type.json")
    assert len(table["crime_types"]) == 7
    assert len(table["boroughs"]) == 3
    assert sum(row["total"] for row in table["boroughs"]) == int(
        fixture_world["frame"]["count"].sum()
    )
    for row in table["boroughs"]:
        assert row["total"] == sum(row["counts"].values())


def test_forecast_points_and_metrics(exported):
    forecast = load(exported, "forecast.json")
    assert len(forecast["city"]) == 1
    assert set(forecast["boroughs"]) == {"BRONX", "MANHATTAN"}
    assert "BROOKLYN/QUEENS" in forecast["metrics"]["skipped_boroughs"]
    for point in forecast["city"]:
        assert point["lower"] <= point["point"] <= point["upper"]
        assert point["lower"] >= 0
    for points in forecast["boroughs"].values():
        assert all(point["lower"] >= 0 for point in points)
    assert forecast["metrics"]["city"]["selected_model"]
    assert forecast["metrics"]["city"]["selection_caveat_fr"].startswith(
        "Modèle choisi sur le MAE"
    )
    points = forecast["city"] + [
        point for block in forecast["boroughs"].values() for point in block
    ]
    assert all(isinstance(point["clipped"], bool) for point in points)
    assert "caveat" not in forecast  # fixture metrics report no clipped rows


def test_interval_caveat_is_generated_from_ci_alpha():
    sys.path.insert(0, str(ROOT))
    from export.export_web import INTERVAL_CAVEAT, interval_caveat

    assert "95" not in str(INTERVAL_CAVEAT)
    note = interval_caveat({"ci_alpha": 0.10})
    assert "90 %" in note["en"] and "90 %" in note["fr"]
    assert "95" not in str(note)


def test_exporter_has_no_quarter_literal_or_fixed_borough_list():
    source = (ROOT / "export" / "export_web.py").read_text(encoding="utf-8")
    assert "!= 46" not in source
    assert "BOROUGH_SERIES" not in source


def test_clusters_profiles_and_silhouettes(exported):
    clusters = load(exported, "clusters.json")
    assert clusters["k"] == 1
    assert len(clusters["profiles"]) == 1
    for row in clusters["parks"]:
        assert -1.0 <= row["sample_silhouette"] <= 1.0
        assert row["cluster"] in {p["cluster"] for p in clusters["profiles"]}


def test_combined_borough_caveat_reports_source_and_emitted_rows(exported):
    meta = load(exported, "meta.json")
    parks = load(exported, "parks.json")
    combined = [p for p in parks if p["borough"] == "BROOKLYN/QUEENS"]
    assert len(combined) == 1
    assert meta["combined_borough"]["parks_source"] == 1
    assert meta["combined_borough"]["parks_with_crimes"] == len(combined)
    caveats = " ".join(meta["caveats"])
    assert "1 parks in the source, 1 with at least one crime" in caveats


def _fake_git(porcelain):
    """subprocess.run stand-in: fixed HEAD sha and the given status output."""
    def run(argv, **kwargs):
        output = "abc1234\n" if "rev-parse" in argv else porcelain
        return subprocess.CompletedProcess(argv, 0, output, "")
    return run


def test_provenance_clean_worktree(monkeypatch):
    sys.path.insert(0, str(ROOT))
    from export import export_web

    monkeypatch.setattr(export_web.subprocess, "run", _fake_git(""))
    provenance = export_web.build_provenance()
    assert provenance["git_commit"] == "abc1234"
    assert provenance["git_dirty"] is False
    assert "git_commit_note" not in provenance


def test_provenance_dirty_worktree_is_marked(monkeypatch):
    sys.path.insert(0, str(ROOT))
    from export import export_web

    monkeypatch.setattr(
        export_web.subprocess, "run", _fake_git(" M export/export_web.py\n")
    )
    provenance = export_web.build_provenance()
    assert provenance["git_commit"] == "abc1234-dirty"
    assert provenance["git_dirty"] is True
    note = provenance["git_commit_note"]
    assert "commit ne contient pas" in note["fr"]
    assert "does not contain" in note["en"]


def test_cube_borough_type_cross_check():
    sys.path.insert(0, str(ROOT))
    from export.export_web import check_cube_borough_type

    parks = [{"park_id": "X1", "park": "A", "borough": "BRONX"}]
    cube = {"crime_types": ["ASSAULT"], "parks": {"X1": {"2024Q1": [5]}}}
    good = {
        "crime_types": ["ASSAULT"],
        "boroughs": [
            {"borough": "BRONX", "total": 5, "counts": {"ASSAULT": 5}}
        ],
    }
    check_cube_borough_type(cube, good, parks)

    bad = {
        "crime_types": ["ASSAULT"],
        "boroughs": [
            {"borough": "BRONX", "total": 6, "counts": {"ASSAULT": 6}}
        ],
    }
    with pytest.raises(SystemExit, match="borough_type"):
        check_cube_borough_type(cube, bad, parks)


def test_failed_validation_leaves_previous_data(tmp_path, monkeypatch, fixture_world):
    """A validation failure must not overwrite or partially replace `out`."""
    from export import export_web as ew

    for name, value in fixture_world["export_paths"].items():
        monkeypatch.setattr(ew, name, value)
    out = tmp_path / "data"
    out.mkdir()
    sentinels = {name: f'{{"sentinel":"{name}"}}' for name in ew.FILES}
    for name, text in sentinels.items():
        (out / name).write_text(text, encoding="utf-8")

    monkeypatch.setattr(ew, "MAX_PAYLOAD_BYTES", 1)  # force budget failure
    with pytest.raises(SystemExit):
        ew.main(["--out", str(out)])

    for name, text in sentinels.items():
        assert (out / name).read_text(encoding="utf-8") == text
    assert not (out.parent / (out.name + ".tmp")).exists()
    assert not (out.parent / (out.name + ".bak")).exists()


def _synthetic_inputs(tmp_path, drop_quarter=None, drop_borough=None):
    """A 47-quarter warehouse and the artefacts the exporter reads."""
    import sqlite3

    import pandas as pd
    from export import export_web as ew

    quarters = ew.quarter_grid("2015Q1", "2026Q3")
    assert len(quarters) == 47
    rows = []
    for index, label in enumerate(quarters):
        for park, borough, crime_type in (
            ("ALPHA PARK", "BRONX", "ROBBERY"),
            ("BETA PARK", "MANHATTAN", "BURGLARY"),
        ):
            if label == drop_quarter and drop_borough in (None, borough):
                continue
            rows.append({
                "quarter_label": label,
                "period_start": None,
                "park": park,
                "borough": borough,
                "size_acres": 10.0,
                "crime_type": crime_type,
                "count": index % 2,
                "count_missing": 0,
                "total_mismatch": 0,
            })
    frame = pd.DataFrame(rows)
    frame["period_start"] = pd.PeriodIndex(
        frame["quarter_label"], freq="Q"
    ).to_timestamp().astype(str)

    db = tmp_path / "warehouse.db"
    with sqlite3.connect(db) as conn:
        frame.to_sql("crimes_long", conn, index=False)
        pd.DataFrame({
            "park": ["ALPHA PARK", "BETA PARK"],
            "borough": ["BRONX", "MANHATTAN"],
            "park_id": ["X1", "M1"],
            "lat": [40.0, 40.1],
            "lon": [-73.0, -73.1],
        }).to_sql("parks", conn, index=False)

    tables = tmp_path / "tables"
    tables.mkdir()
    pd.DataFrame({
        "park_id": ["X1", "M1"],
        "park": ["ALPHA PARK", "BETA PARK"],
        "borough": ["BRONX", "MANHATTAN"],
        "cluster": [0, 0],
        "dominant_type": ["ROBBERY", "BURGLARY"],
        "total_crimes": [23, 23],
        "silhouette": [0.5, 0.5],
        "sample_silhouette": [0.4, 0.6],
    }).to_csv(tables / "park_clusters.csv", index=False)
    pd.DataFrame({
        "cluster": [0],
        "n_parks": [2],
        "total_crimes": [46],
        "mean_acres": [10.0],
        "mean_silhouette": [0.5],
        "top_type": ["ROBBERY"],
        "name": ["Vol qualifié dominant"],
    }).to_csv(tables / "cluster_profiles.csv", index=False)
    pd.DataFrame({
        "park_id": ["X1", "M1"],
        "park": ["ALPHA PARK", "BETA PARK"],
        "borough": ["BRONX", "MANHATTAN"],
        "crimes": [23, 23],
        "acres": [10.0, 10.0],
        "crimes_per_100_acres": [230.0, 230.0],
        "risk_rank": [1, 1],
        "coverage_first": ["2015Q1", "2015Q1"],
        "coverage_era": ["2015Q1–2026Q3", "2015Q1–2026Q3"],
        "cluster": [0, 0],
    }).to_csv(tables / "park_risk.csv", index=False)
    pd.DataFrame({
        "metric": ["matched_parks", "parks", "unweighted_coverage",
                   "weighted_coverage"],
        "value": [2, 2, 1.0, 1.0],
    }).to_csv(tables / "geo_coverage.csv", index=False)
    forecast = {"quarter_label": ["2026Q4"], "point": [3.0],
                "lower": [0.0], "upper": [6.0]}
    pd.DataFrame({"scope": ["CITYWIDE"], **forecast}).to_csv(
        tables / "forecast_city.csv", index=False,
    )
    pd.DataFrame({"borough": ["BRONX"], **forecast}).to_csv(
        tables / "forecast_boroughs.csv", index=False,
    )

    metrics = tmp_path / "metrics"
    metrics.mkdir()
    stats = {
        "total_crimes": int(frame["count"].sum()),
        "parks_total": 2,
        "parks_ever_hit": 2,
        "rows_total": len(frame),
        "first_quarter": quarters[0],
        "last_quarter": quarters[-1],
        "quarters_total": 47,
        "missing_quarter": None,
    }
    (metrics / "eda_stats.json").write_text(json.dumps(stats), encoding="utf-8")
    (metrics / "model_metrics.json").write_text(json.dumps({
        "ci_alpha": 0.05,
        "citywide": {
            "forecast": [],
            "selected_model": "seasonal_naive",
            "backtest_quarters": 8,
        },
        "boroughs": {"BRONX": {"forecast": []}},
        "skipped_boroughs": {},
        "caveats": [],
        "clustering": {"selected_k": 1, "silhouette": 0.5, "features": []},
    }), encoding="utf-8")

    monkeypatch_targets = {"DB_PATH": db, "TABLE_DIR": tables, "METRIC_DIR": metrics}
    return ew, monkeypatch_targets


def test_47_quarter_fixture_exports(tmp_path, monkeypatch):
    ew, paths = _synthetic_inputs(tmp_path)
    for name, value in paths.items():
        monkeypatch.setattr(ew, name, value)
    out = tmp_path / "out"
    ew.main(["--out", str(out)])
    series = json.loads((out / "series.json").read_text(encoding="utf-8"))
    assert len(series["quarters"]) == 47
    assert series["quarters"][0] == "2015Q1"
    assert series["quarters"][-1] == "2026Q3"
    assert set(series["boroughs"]) == {"BRONX", "MANHATTAN"}
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert meta["periods"]["count"] == 47
    assert meta["periods"]["missing"] == []
    cube = json.loads((out / "cubes.json").read_text(encoding="utf-8"))
    assert cube["quarters"] == series["quarters"]
    parks = json.loads((out / "parks.json").read_text(encoding="utf-8"))
    assert {
        park_id: sum(
            value for counts in cells.values() for value in counts
            if value is not None
        )
        for park_id, cells in cube["parks"].items()
    } == {row["park_id"]: row["total"] for row in parks}


def test_quarter_gap_fails_continuity_check(tmp_path, monkeypatch):
    ew, paths = _synthetic_inputs(tmp_path, drop_quarter="2020Q1")
    for name, value in paths.items():
        monkeypatch.setattr(ew, name, value)
    with pytest.raises(SystemExit, match="quarter labels break the grid"):
        ew.main(["--out", str(tmp_path / "out")])


def test_borough_quarter_gap_fails_continuity_check(tmp_path, monkeypatch):
    """A gap in one borough fails even when the city grid stays intact."""
    ew, paths = _synthetic_inputs(
        tmp_path, drop_quarter="2020Q1", drop_borough="MANHATTAN",
    )
    for name, value in paths.items():
        monkeypatch.setattr(ew, name, value)
    with pytest.raises(SystemExit, match="MANHATTAN: quarter labels break the grid"):
        ew.main(["--out", str(tmp_path / "out")])


def test_exporter_validates_every_payload_against_its_schema(exported):
    """Each exported file passes the schema in export/schemas/."""
    import jsonschema

    for name in FILES:
        schema_path = ROOT / "export" / "schemas" / name.replace(
            ".json", ".schema.json"
        )
        assert schema_path.is_file(), schema_path
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(load(exported, name))


def test_meta_park_quarters_and_long_rows_are_measured(exported, fixture_world):
    """park_quarters counts park x quarter, long_rows counts every CSV row."""
    import sqlite3

    meta = load(exported, "meta.json")
    with sqlite3.connect(fixture_world["db"]) as conn:
        park_quarters = conn.execute(
            "SELECT COUNT(*) FROM ("
            "SELECT DISTINCT quarter_label, park FROM crimes_long)"
        ).fetchone()[0]
        long_rows = conn.execute("SELECT COUNT(*) FROM crimes_long").fetchone()[0]
    assert meta["totals"]["park_quarters"] == park_quarters
    assert meta["totals"]["long_rows"] == long_rows
    assert meta["totals"]["park_quarters"] < meta["totals"]["long_rows"]


def test_finite_type_checker_rejects_nan_under_number_schema():
    """Plain JSON Schema accepts NaN; the exporter's checker must not."""
    import jsonschema
    import math

    from export import export_web as ew

    schema = json.loads(
        (ROOT / "export" / "schemas" / "forecast.schema.json").read_text(
            encoding="utf-8"
        )
    )
    payload = {
        "city": [{
            "quarter": "2026Q3", "point": math.nan, "lower": 0.0,
            "upper": 1.0, "clipped": False,
        }],
        "boroughs": {},
        "metrics": {"city": {}, "boroughs": {}, "skipped_boroughs": {}},
        "caveats": [],
    }
    assert jsonschema.Draft202012Validator(schema).is_valid(payload)
    assert not ew.FINITE_VALIDATOR(schema).is_valid(payload)


def test_nan_forecast_point_fails_before_publish(tmp_path, monkeypatch):
    """A NaN point must abort the export before any file is written."""
    ew, paths = _synthetic_inputs(tmp_path)
    for name, value in paths.items():
        monkeypatch.setattr(ew, name, value)

    real = ew.build_forecast

    def build_with_nan(metrics):
        payload = real(metrics)
        payload["city"][0]["point"] = float("nan")
        return payload

    monkeypatch.setattr(ew, "build_forecast", build_with_nan)
    out = tmp_path / "out"
    with pytest.raises(SystemExit, match="non-finite"):
        ew.main(["--out", str(out)])
    assert not out.exists()
    assert not (tmp_path / "out.tmp").exists()
    assert not (tmp_path / "out.bak").exists()
