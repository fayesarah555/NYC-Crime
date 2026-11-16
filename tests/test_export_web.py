"""Network-free checks for the static web data export (ticket 0038)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / "data" / "warehouse.db").exists():
    pytest.skip(
        "data/warehouse.db absent; run `make data` then `make warehouse` first",
        allow_module_level=True,
    )
FILES = (
    "meta.json", "parks.json", "series.json",
    "borough_type.json", "forecast.json", "clusters.json",
)


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    """Run the export into a scratch directory; fail loudly if it aborts."""
    out = tmp_path_factory.mktemp("web-data")
    result = subprocess.run(
        [sys.executable, str(ROOT / "export" / "export_web.py"), "--out", str(out)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    return out


def load(out, name):
    return json.loads((out / name).read_text(encoding="utf-8"))


def test_six_files_and_payload_budget(exported):
    assert all((exported / name).is_file() for name in FILES)
    total = sum((exported / name).stat().st_size for name in FILES)
    assert total < 2 * 1024 * 1024


def test_meta_periods_totals_caveats(exported):
    meta = load(exported, "meta.json")
    assert meta["periods"]["count"] == 46
    assert meta["periods"]["first"] == "2014Q4"
    assert meta["periods"]["last"] == "2026Q2"
    assert meta["periods"]["missing"] == ["2020Q1"]
    assert meta["totals"]["crimes"] == 12526
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
    assert "Central Park" in fr


def test_parks_rows_and_type_sums(exported):
    parks = load(exported, "parks.json")
    assert len(parks) == 792
    for row in parks:
        assert len(row["counts"]) == 7
        assert row["total"] == sum(row["counts"].values())
        assert row["dominant_type"] == max(row["counts"], key=row["counts"].get)
        assert (row["lat"] is None) == (row["lon"] is None)
        assert row["cluster"] is None or 0 <= row["cluster"] <= 3


def test_series_quarters_and_city_total(exported):
    series = load(exported, "series.json")
    assert len(series["quarters"]) == 46
    assert "2020Q1" not in series["quarters"]
    assert sum(series["city"]) == 12526
    assert set(series["boroughs"]) == {"BRONX", "BROOKLYN", "MANHATTAN", "QUEENS"}
    for values in series["boroughs"].values():
        assert len(values) == 46


def test_series_city_by_type_sums_to_city(exported):
    series = load(exported, "series.json")
    assert len(series["city_by_type"]) == 7
    for crime_type, values in series["city_by_type"].items():
        assert len(values) == len(series["quarters"]), crime_type
    for index, city_total in enumerate(series["city"]):
        per_type = sum(values[index] for values in series["city_by_type"].values())
        assert per_type == city_total, series["quarters"][index]


def test_borough_type_matrix(exported):
    table = load(exported, "borough_type.json")
    assert len(table["crime_types"]) == 7
    assert len(table["boroughs"]) == 6
    assert sum(row["total"] for row in table["boroughs"]) == 12526
    for row in table["boroughs"]:
        assert row["total"] == sum(row["counts"].values())


def test_forecast_points_and_metrics(exported):
    forecast = load(exported, "forecast.json")
    assert len(forecast["city"]) == 4
    assert set(forecast["boroughs"]) == {"BRONX", "BROOKLYN", "MANHATTAN", "QUEENS"}
    for point in forecast["city"]:
        assert point["lower"] <= point["point"] <= point["upper"]
    assert forecast["metrics"]["city"]["selected_model"]
    assert forecast["metrics"]["city"]["selection_caveat_fr"].startswith(
        "Modèle choisi sur le MAE"
    )
    assert forecast["caveats"]


def test_clusters_profiles_and_silhouettes(exported):
    clusters = load(exported, "clusters.json")
    assert clusters["k"] == 4
    assert len(clusters["profiles"]) == 4
    assert len(clusters["parks"]) == 337
    for row in clusters["parks"]:
        assert -1.0 <= row["sample_silhouette"] <= 1.0
        assert row["cluster"] in {p["cluster"] for p in clusters["profiles"]}


def test_combined_borough_caveat_counts_emitted_rows(exported):
    parks = load(exported, "parks.json")
    combined = [p for p in parks if p["borough"] == "BROOKLYN/QUEENS"]
    caveats = " ".join(load(exported, "meta.json")["caveats"])
    assert len(combined) == 4
    assert f"for {len(combined)} parks" in caveats


def test_failed_validation_leaves_previous_data(tmp_path, monkeypatch):
    """A validation failure must not overwrite or partially replace `out`."""
    from export import export_web as ew

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
