"""Attach coordinates and acreage to the park-crime parks via NYC Parks Properties.

Usage:
    python etl/geo.py            # fetch (cached), match, write CSV + warehouse table
    python etl/geo.py --report   # print unweighted and volume-weighted match coverage

The raw properties JSON is cached in data/raw/ so a rerun needs no network.
Matching is exact signname, then exact name311, then difflib within the same
borough at cutoff 0.88 -- no match ever crosses boroughs.
"""

import argparse
import difflib
import json
import re
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import requests
from shapely.errors import GEOSException
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
CACHE_PATH = RAW_DIR / "parks_properties.json"
CRIME_CSV = ROOT / "data" / "processed" / "park_crime_long.csv"
GEO_CSV = ROOT / "data" / "processed" / "parks_geo.csv"
DB_PATH = ROOT / "data" / "warehouse.db"
COVERAGE_CSV = ROOT / "outputs" / "tables" / "geo_coverage.csv"
FALSE_POSITIVES_CSV = ROOT / "outputs" / "tables" / "geo_false_positives.csv"

PROPERTIES_URL = (
    "https://data.cityofnewyork.us/resource/enfh-gkve.json"
    "?$select=signname,name311,borough,acres,typecategory,multipolygon&$limit=5000"
)
BOROUGHS = {"M": "MANHATTAN", "B": "BROOKLYN", "X": "BRONX", "Q": "QUEENS", "R": "STATEN ISLAND"}
PARK_COLUMNS = ["park", "borough", "lat", "lon", "acres_geo", "typecategory", "match_type"]
CUTOFF = 0.88
# Curated audit of the 0.88 fuzzy tier (2026-11): park, matched property, distance in km.
FALSE_POSITIVES = [
    ("ST. NICHOLAS PLAYGROUND NORTH", "ST NICHOLAS PLAYGROUND SOUTH", 0.18),
    ("DUGAN PLAYGROUND", "DONGAN PLAYGROUND", 2.96),
]


def fetch_properties(url=PROPERTIES_URL, cache_path=CACHE_PATH):
    """Return the properties list, downloading it once into the cache."""
    if cache_path.exists():
        with cache_path.open(encoding="utf-8") as handle:
            return json.load(handle)
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    properties = response.json()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.open("w", encoding="utf-8") as handle:
        json.dump(properties, handle, ensure_ascii=False)
    return properties


def normalize_name(value):
    """Uppercase, expand '&', drop apostrophes/periods, space other punctuation."""
    text = str(value).upper().replace("&", " AND ")
    text = re.sub(r"['’`.]", "", text)
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", text).split())


def centroid(geometry):
    """(lat, lon) from a GeoJSON MultiPolygon; a point guaranteed inside it."""
    polygon = shape(geometry)
    point = polygon.representative_point()
    if point.is_empty:  # degenerate geometry: fall back to the centroid
        point = polygon.centroid
    return round(point.y, 7), round(point.x, 7)


def prepare(prop):
    try:
        lat, lon = centroid(prop["multipolygon"])
    except GEOSException:  # empty geometry: skip the property, keep the run going
        return None
    if not (40.4 <= lat <= 41.0 and -74.3 <= lon <= -73.6):
        return None  # degenerate geometry outside NYC
    try:
        acres = float(prop["acres"])
    except (KeyError, TypeError, ValueError):
        acres = None
    return {
        "signname": normalize_name(prop["signname"]),
        "name311": normalize_name(prop["name311"]),
        "borough": BOROUGHS[prop["borough"]],
        "lat": lat,
        "lon": lon,
        "acres_geo": acres,
        "typecategory": prop.get("typecategory"),
    }


def build_index(properties):
    by_sign, by_311, by_borough = {}, {}, {}
    for prepared in map(prepare, properties):
        if prepared is None:
            continue
        by_sign.setdefault(prepared["signname"], []).append(prepared)
        by_311.setdefault(prepared["name311"], []).append(prepared)
        by_borough.setdefault(prepared["borough"], {}).setdefault(
            prepared["signname"], []
        ).append(prepared)
    return {"signname": by_sign, "name311": by_311, "borough": by_borough}


def match_park(park, borough, index, cutoff=CUTOFF):
    """Return (prepared property or None, match_type) for one crime-data park."""
    name = normalize_name(park)
    boroughs = [part.strip() for part in str(borough).split("/")]
    for table, kind in ((index["signname"], "signname"), (index["name311"], "name311")):
        same_borough = [c for c in table.get(name, []) if c["borough"] in boroughs]
        if same_borough:
            return same_borough[0], kind
    pool = {}
    for one in boroughs:
        pool.update(index["borough"].get(one, {}))
    close = difflib.get_close_matches(name, list(pool), n=1, cutoff=cutoff)
    if close:
        return pool[close[0]][0], "fuzzy"
    return None, "none"


def crime_parks(csv_path=CRIME_CSV):
    frame = pd.read_csv(csv_path)
    return frame.groupby(["park", "borough"], as_index=False)["count"].sum()


def build_frame(parks, index):
    rows = []
    for record in parks.itertuples(index=False):
        matched, match_type = match_park(record.park, record.borough, index)
        rows.append(
            {
                "park": record.park,
                "borough": record.borough,
                "lat": matched["lat"] if matched else None,
                "lon": matched["lon"] if matched else None,
                "acres_geo": matched["acres_geo"] if matched else None,
                "typecategory": matched["typecategory"] if matched else None,
                "match_type": match_type,
                "count": record.count,
            }
        )
    return pd.DataFrame(rows)


def coverage(frame):
    """Unweighted (by park) and crime-volume-weighted match coverage."""
    matched = (
        frame["match_type"].ne("none")
        & frame["lat"].notna()
        & frame["lon"].notna()
    )
    total = float(frame["count"].sum())
    return {
        "parks": int(len(frame)),
        "matched_parks": int(matched.sum()),
        "unweighted_coverage": float(matched.mean()) if len(frame) else 0.0,
        "weighted_coverage": float(frame.loc[matched, "count"].sum()) / total if total else 0.0,
    }


def write_outputs(frame):
    GEO_CSV.parent.mkdir(parents=True, exist_ok=True)
    frame[PARK_COLUMNS].to_csv(GEO_CSV, index=False)
    connection = sqlite3.connect(DB_PATH)
    try:
        frame[PARK_COLUMNS].to_sql("parks", connection, if_exists="replace", index=False)
        connection.commit()
    finally:
        connection.close()
    stats = coverage(frame)
    COVERAGE_CSV.parent.mkdir(parents=True, exist_ok=True)
    metrics = {"metric": list(stats), "value": [str(v) for v in stats.values()]}
    for park, matched, distance in FALSE_POSITIVES:
        metrics["metric"].append("fuzzy_false_positive")
        metrics["value"].append(f"{park} -> {matched} ({distance} km)")
    pd.DataFrame(metrics).to_csv(COVERAGE_CSV, index=False)
    pd.DataFrame(
        FALSE_POSITIVES, columns=["park", "matched_property", "distance_km"]
    ).to_csv(FALSE_POSITIVES_CSV, index=False)
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        action="store_true",
        help="print unweighted and volume-weighted match coverage",
    )
    args = parser.parse_args()

    if not CRIME_CSV.exists():
        print(f"error: {CRIME_CSV} missing; run etl/parse.py first", file=sys.stderr)
        return 2

    index = build_index(fetch_properties())
    frame = build_frame(crime_parks(), index)
    stats = write_outputs(frame)
    print(
        f"parks: {stats['parks']}, matched: {stats['matched_parks']}"
        f" ({stats['unweighted_coverage']:.2%} unweighted,"
        f" {stats['weighted_coverage']:.2%} volume-weighted)"
    )
    if args.report:
        print(f"unweighted coverage: {stats['unweighted_coverage']:.2%}")
        print(f"volume-weighted coverage: {stats['weighted_coverage']:.2%}")
    print(f"wrote {GEO_CSV.relative_to(ROOT)}")
    print(f"wrote {DB_PATH.relative_to(ROOT)} (table parks)")
    print(f"wrote {COVERAGE_CSV.relative_to(ROOT)}")
    print(f"wrote {FALSE_POSITIVES_CSV.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
