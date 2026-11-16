"""Shared fixtures: the committed synthetic workbooks and the world they build.

Unit tests read this fixture set, never `data/` (ticket 0050). The real-data
checks live in tests/test_live_reconciliation.py behind the `live` marker.
"""

import hashlib
import json
import shutil
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKBOOK_DIR = Path(__file__).resolve().parent / "fixtures" / "workbooks"
sys.path.insert(0, str(ROOT))

GEO_COLUMNS = [
    "park", "borough", "park_id", "canonical_name",
    "lat", "lon", "acres_geo", "typecategory", "match_type",
]


@pytest.fixture(scope="session")
def fixture_raw(tmp_path_factory):
    """Copied fixture workbooks plus the manifest `etl/download.py` writes."""
    from etl.parse import QUARTER_RE

    raw = tmp_path_factory.mktemp("fixture-raw")
    entries = []
    for path in sorted(WORKBOOK_DIR.glob("*.xlsx")):
        shutil.copyfile(path, raw / path.name)
        data = (raw / path.name).read_bytes()
        match = QUARTER_RE.search(path.name)
        entries.append({
            "url": f"fixture://{path.name}",
            "filename": path.name,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "quarter": int(match.group(1)),
            "year": int(match.group(2)),
        })
    (raw / "manifest.json").write_text(
        json.dumps({"workbooks": entries}, indent=2) + "\n", encoding="utf-8"
    )
    return raw


@pytest.fixture(scope="session")
def fixture_warehouse(tmp_path_factory, fixture_raw):
    """The fixture workbooks parsed into the CSV + warehouse the ETL writes."""
    from etl.parse import OUTPUT_COLUMNS, parse_all

    root = tmp_path_factory.mktemp("fixture-world")
    processed = root / "processed"
    processed.mkdir()
    _, records, violations = parse_all(fixture_raw)
    frame = pd.DataFrame(records, columns=OUTPUT_COLUMNS)
    csv_path = processed / "park_crime_long.csv"
    frame.to_csv(csv_path, index=False)

    db_path = root / "warehouse.db"
    with sqlite3.connect(db_path) as connection:
        frame.to_sql("crimes_long", connection, index=False)
        connection.execute(
            "CREATE INDEX idx_crimes_quarter_park_crime "
            "ON crimes_long (quarter_label, park, crime_type)"
        )

    # Deterministic geography: no network, one stable id per (park, borough).
    parks = (
        frame.groupby(["park", "borough"], as_index=False)["size_acres"].last()
        .sort_values(["borough", "park"], ignore_index=True)
    )
    parks["park_id"] = [f"F{index:03d}" for index in range(1, len(parks) + 1)]
    parks["canonical_name"] = parks["park"]
    parks["lat"] = 40.70 + parks.index / 1000
    parks["lon"] = -73.90 - parks.index / 1000
    parks["acres_geo"] = parks["size_acres"]
    parks["typecategory"] = "Park"
    parks["match_type"] = "signname"
    geo_csv = processed / "parks_geo.csv"
    parks[GEO_COLUMNS].to_csv(geo_csv, index=False)
    with sqlite3.connect(db_path) as connection:
        parks[["park", "borough", "park_id", "lat", "lon"]].to_sql(
            "parks", connection, index=False
        )

    return {
        "root": root,
        "raw": fixture_raw,
        "db": db_path,
        "csv": csv_path,
        "geo_csv": geo_csv,
        "parks": parks,
        "violations": violations,
        "frame": frame,
    }


@pytest.fixture(scope="session")
def fixture_world(fixture_warehouse):
    """The fixture warehouse plus the artefact tables the web exporter reads."""
    root = fixture_warehouse["root"]
    frame = fixture_warehouse["frame"]
    parks = fixture_warehouse["parks"]
    quarters = sorted(frame["quarter_label"].unique())
    next_quarter = "2019Q4"

    tables = root / "outputs" / "tables"
    tables.mkdir(parents=True)
    metrics = root / "outputs" / "metrics"
    metrics.mkdir(parents=True)

    totals = (
        frame.merge(
            parks[["park", "borough", "park_id"]], on=["park", "borough"]
        )
        .groupby("park_id")["count"].sum()
    )
    clusters = parks.assign(
        cluster=0,
        dominant_type="ROBBERY",
        silhouette=0.5,
        sample_silhouette=0.5,
    )
    clusters["total_crimes"] = parks["park_id"].map(totals).fillna(0).astype(int)
    clusters[
        ["park_id", "park", "borough", "cluster", "dominant_type",
         "total_crimes", "silhouette", "sample_silhouette"]
    ].to_csv(tables / "park_clusters.csv", index=False)
    pd.DataFrame({
        "cluster": [0],
        "n_parks": [len(parks)],
        "total_crimes": [int(clusters["total_crimes"].sum())],
        "mean_acres": [float(parks["size_acres"].mean())],
        "mean_silhouette": [0.5],
        "top_type": ["ROBBERY"],
        "name": ["Vol qualifié dominant"],
    }).to_csv(tables / "cluster_profiles.csv", index=False)
    risk = clusters[["park_id", "park", "borough", "total_crimes"]].rename(
        columns={"total_crimes": "crimes"}
    )
    risk["acres"] = parks["size_acres"].to_numpy()
    risk["crimes_per_100_acres"] = risk["crimes"] / risk["acres"] * 100.0
    risk["risk_rank"] = risk["crimes_per_100_acres"].rank(
        ascending=False, method="min"
    )
    risk["coverage_first"] = quarters[0]
    risk["coverage_era"] = f"{quarters[0]}–{quarters[-1]}"
    risk["cluster"] = 0
    risk.sort_values("crimes_per_100_acres", ascending=False).to_csv(
        tables / "park_risk.csv", index=False,
    )
    pd.DataFrame({
        "metric": ["park_quarters", "parks", "matched_parks", "unweighted_coverage", "weighted_coverage"],
        "value": [len(frame), len(parks), len(parks), 1.0, 1.0],
    }).to_csv(tables / "geo_coverage.csv", index=False)
    forecast = {
        "quarter_label": [next_quarter],
        "point": [3.0],
        "lower": [0.0],
        "upper": [6.0],
        "clipped": [False],
    }
    pd.DataFrame({"scope": ["CITYWIDE"], **forecast}).to_csv(
        tables / "forecast_city.csv", index=False,
    )
    boroughs = ["BRONX", "MANHATTAN"]
    pd.DataFrame({
        "borough": boroughs,
        "quarter_label": [next_quarter] * len(boroughs),
        "point": [3.0] * len(boroughs),
        "lower": [0.0] * len(boroughs),
        "upper": [6.0] * len(boroughs),
        "clipped": [False] * len(boroughs),
    }).to_csv(tables / "forecast_boroughs.csv", index=False)
    mismatch = frame[frame["total_mismatch"].eq(1)]
    sensitivity = pd.DataFrame({
        "park": mismatch["park"].unique(),
        "quarter": mismatch["quarter_label"].unique(),
        "total_recorded": [999],
        "sum_components": [1],
        "city_total_from_components": [int(frame["count"].sum())],
        "city_total_using_recorded_total": [int(frame["count"].sum()) + 998],
    })
    sensitivity.to_csv(tables / "source_anomaly_sensitivity.csv", index=False)
    pd.DataFrame(fixture_warehouse["violations"]).to_csv(
        tables / "source_anomalies.csv", index=False
    )

    parks_ever_hit = int((clusters["total_crimes"] > 0).sum())
    (metrics / "eda_stats.json").write_text(json.dumps({
        "total_crimes": int(frame["count"].sum()),
        "parks_total": len(parks),
        "parks_ever_hit": parks_ever_hit,
        "first_quarter": quarters[0],
        "last_quarter": quarters[-1],
        "quarters_total": len(quarters),
    }), encoding="utf-8")
    (metrics / "model_metrics.json").write_text(json.dumps({
        "ci_alpha": 0.05,
        "citywide": {
            "forecast": [],
            "selected_model": "seasonal_naive",
            "backtest_quarters": 2,
        },
        "boroughs": {
            borough: {"forecast": [], "selected_model": "seasonal_naive"}
            for borough in boroughs
        },
        "skipped_boroughs": {"BROOKLYN/QUEENS": "fixture: too little history"},
        "caveats": [],
        "clustering": {"selected_k": 1, "silhouette": 0.5, "features": []},
    }), encoding="utf-8")

    return {
        **fixture_warehouse,
        "tables": tables,
        "metrics": metrics,
        "quarters": quarters,
        "export_paths": {
            "DB_PATH": fixture_warehouse["db"],
            "TABLE_DIR": tables,
            "METRIC_DIR": metrics,
            "MANIFEST_PATH": fixture_warehouse["raw"] / "manifest.json",
        },
    }
