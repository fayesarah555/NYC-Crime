"""Attach coordinates and acreage to the park-crime parks via NYC Parks Properties.

Usage:
    python etl/geo.py            # fetch (cached), match, write CSV + warehouse table
    python etl/geo.py --refresh  # ignore the cache TTL and refetch from Socrata
    python etl/geo.py --report   # print unweighted and volume-weighted match coverage

Matching is a manual override, then exact signname, then exact name311, then a
difflib ratio within the same borough at cutoff 0.88. Fuzzy candidates must
agree on direction words and numeric tokens (NORTH != SOUTH, 5 != 6), must not
appear in data/geo_denylist.csv, and ties break deterministically on larger
acreage then centroid distance. Every fuzzy match gets a distance audit against
its runner-up candidate in outputs/tables/geo_fuzzy_audit.csv.

The raw properties JSON is cached in data/raw/ with a 30-day TTL and the
sha256 of the payload. Socrata is paged with $limit/$offset/$order until a
short page.
"""

import argparse
import difflib
import hashlib
import json
import math
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from shapely.errors import GEOSException
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):  # running as `python etl/geo.py`
    sys.path.insert(0, str(ROOT))
from etl import schema  # noqa: E402
RAW_DIR = ROOT / "data" / "raw"
CACHE_PATH = RAW_DIR / "parks_properties.json"
CRIME_CSV = ROOT / "data" / "processed" / "park_crime_long.csv"
GEO_CSV = ROOT / "data" / "processed" / "parks_geo.csv"
DB_PATH = ROOT / "data" / "warehouse.db"
COVERAGE_CSV = ROOT / "outputs" / "tables" / "geo_coverage.csv"
FALSE_POSITIVES_CSV = ROOT / "outputs" / "tables" / "geo_false_positives.csv"
FUZZY_AUDIT_CSV = ROOT / "outputs" / "tables" / "geo_fuzzy_audit.csv"
DENYLIST_CSV = ROOT / "data" / "geo_denylist.csv"
OVERRIDES_CSV = ROOT / "data" / "geo_overrides.csv"

PROPERTIES_URL = "https://data.cityofnewyork.us/resource/enfh-gkve.json"
PROPERTIES_SELECT = (
    "signname,name311,borough,acres,typecategory,gispropnum,omppropid,multipolygon"
)
PAGE_SIZE = 1000
MAX_OFFSET = 100_000  # hard cap: abort a pagination that never terminates
CACHE_TTL_DAYS = 30
BOROUGHS = {"M": "MANHATTAN", "B": "BROOKLYN", "X": "BRONX", "Q": "QUEENS", "R": "STATEN ISLAND"}
# Approximate borough centroids: only a deterministic tie-break reference.
BOROUGH_CENTROIDS = {
    "MANHATTAN": (40.783, -73.966),
    "BROOKLYN": (40.650, -73.949),
    "BRONX": (40.845, -73.865),
    "QUEENS": (40.728, -73.794),
    "STATEN ISLAND": (40.579, -74.150),
}
PARK_COLUMNS = [
    "park", "borough", "park_id", "canonical_name",
    "lat", "lon", "acres_geo", "typecategory", "match_type",
]
CUTOFF = 0.88
DIRECTIONS = {"NORTH", "SOUTH", "EAST", "WEST"}
NUMBER_RE = re.compile(r"\b\d+\b")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def cache_payload(properties, fetched_at):
    canonical = json.dumps(properties, sort_keys=True, ensure_ascii=False)
    return {
        "fetched_at": fetched_at,
        "sha256": sha256(canonical.encode("utf-8")),
        "count": len(properties),
        "properties": properties,
    }


def fetch_properties(url=PROPERTIES_URL, cache_path=CACHE_PATH, refresh=False,
                     session=None, ttl_days=CACHE_TTL_DAYS):
    """Return the properties list, refetching when the cache is stale.

    The cache envelope carries fetched_at and the sha256 of the payload; a
    legacy bare-list cache is upgraded in place using its modification time.
    """
    if cache_path.exists() and not refresh:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if isinstance(cached, dict) and cached.get("properties") is not None:
            fetched_at = datetime.fromisoformat(cached["fetched_at"])
            if (datetime.now(timezone.utc) - fetched_at).days < ttl_days:
                return cached["properties"]
        elif isinstance(cached, list) and cached:
            fetched_at = datetime.fromtimestamp(
                cache_path.stat().st_mtime, tz=timezone.utc
            ).replace(microsecond=0)
            if (datetime.now(timezone.utc) - fetched_at).days < ttl_days:
                payload = cache_payload(cached, fetched_at.isoformat())
                cache_path.write_text(
                    json.dumps(payload, ensure_ascii=False), encoding="utf-8"
                )
                return cached

    session = session or requests.Session()
    properties, offset, seen_pages = [], 0, set()
    while True:
        if offset >= MAX_OFFSET:
            raise RuntimeError(
                f"pagination reached MAX_OFFSET={MAX_OFFSET} offset {offset} "
                "without a short page: the API never terminates"
            )
        response = session.get(
            url,
            params={
                "$select": PROPERTIES_SELECT,
                "$limit": PAGE_SIZE,
                "$offset": offset,
                "$order": ":id",
            },
            timeout=120,
        )
        response.raise_for_status()
        page = response.json()
        page_hash = sha256(json.dumps(page, sort_keys=True).encode("utf-8"))
        if page_hash in seen_pages:
            raise RuntimeError(
                f"duplicate page at offset {offset}: the API ignores $offset "
                "and repeats the same rows"
            )
        seen_pages.add(page_hash)
        properties.extend(page)
        if len(page) < PAGE_SIZE:  # short page: the dataset is exhausted
            break
        offset += PAGE_SIZE
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = cache_payload(properties, datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return properties


def normalize_name(value):
    """Uppercase, expand '&', drop apostrophes/periods, space other punctuation."""
    if value is None:
        return ""
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


def distance_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in kilometres."""
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    hav = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(hav))


def prepare(prop):
    signname = prop.get("signname")
    borough = BOROUGHS.get(prop.get("borough"))
    geometry = prop.get("multipolygon")
    if not isinstance(signname, str) or not signname.strip() or borough is None or not geometry:
        return None
    signname = signname.strip()
    try:
        lat, lon = centroid(geometry)
    except (GEOSException, KeyError, TypeError, ValueError):  # empty geometry
        return None
    if not (40.4 <= lat <= 41.0 and -74.3 <= lon <= -73.6):
        return None  # degenerate geometry outside NYC
    try:
        acres = float(prop.get("acres"))
    except (TypeError, ValueError):
        acres = None
    return {
        "signname": normalize_name(signname),
        "canonical_name": signname,
        "name311": normalize_name(prop.get("name311")),
        "borough": borough,
        "park_id": prop.get("gispropnum") or prop.get("omppropid"),
        "lat": lat,
        "lon": lon,
        "acres_geo": acres,
        "typecategory": prop.get("typecategory"),
    }


def build_index(properties):
    by_sign, by_311, by_borough = {}, {}, {}
    skipped = 0
    for prop in properties:
        prepared = prepare(prop)
        if prepared is None:
            skipped += 1
            continue
        by_sign.setdefault(prepared["signname"], []).append(prepared)
        if prepared["name311"]:
            by_311.setdefault(prepared["name311"], []).append(prepared)
        by_borough.setdefault(prepared["borough"], []).append(prepared)
    if skipped:
        print(f"skipped {skipped} malformed property row(s) (null name, borough "
              "or geometry)", file=sys.stderr)
    return {"signname": by_sign, "name311": by_311, "borough": by_borough}


def load_denylist(path=DENYLIST_CSV):
    """Curated (crime park, property) pairs that must never match."""
    if not path.exists():
        return frozenset()
    frame = pd.read_csv(path)
    return frozenset(
        (normalize_name(row.park), normalize_name(row.matched_property))
        for row in frame.itertuples()
    )


def load_overrides(path=OVERRIDES_CSV):
    """Curated (crime park, borough) -> property signname matches."""
    if not path.exists():
        return {}
    frame = pd.read_csv(path)
    return {
        (normalize_name(row.park), str(row.borough).strip()): normalize_name(row.property)
        for row in frame.itertuples()
    }


def direction_tokens(name):
    return {token for token in name.split() if token in DIRECTIONS}


def numeric_tokens(name):
    return set(NUMBER_RE.findall(name))


def fuzzy_guard(name, candidate):
    """Never fuzzy-match across a directional qualifier or a number."""
    return (
        direction_tokens(name) == direction_tokens(candidate)
        and numeric_tokens(name) == numeric_tokens(candidate)
    )


def pick_best(candidates):
    """Larger acreage first, then closest borough centroid, then name."""
    return min(
        candidates,
        key=lambda c: (
            -(c["acres_geo"] or 0.0),
            distance_km(*BOROUGH_CENTROIDS[c["borough"]], c["lat"], c["lon"]),
            c["signname"],
        ),
    )


def fuzzy_candidates(name, boroughs, index, cutoff=CUTOFF, denylist=frozenset()):
    """Ranked same-borough candidates that pass the guards and the denylist."""
    pool = [
        candidate
        for one in boroughs
        for candidate in index["borough"].get(one, [])
        if fuzzy_guard(name, candidate["signname"])
        and (name, candidate["signname"]) not in denylist
    ]
    scored = [
        (difflib.SequenceMatcher(None, name, candidate["signname"]).ratio(), candidate)
        for candidate in pool
    ]
    scored = [pair for pair in scored if pair[0] >= cutoff]
    scored.sort(
        key=lambda pair: (
            -pair[0],
            -(pair[1]["acres_geo"] or 0.0),
            distance_km(*BOROUGH_CENTROIDS[pair[1]["borough"]], pair[1]["lat"], pair[1]["lon"]),
            pair[1]["signname"],
        )
    )
    return [candidate for _, candidate in scored]


def match_park(park, borough, index, cutoff=CUTOFF, denylist=frozenset(), overrides=None):
    """Return (prepared property or None, match_type) for one crime-data park."""
    name = normalize_name(park)
    boroughs = [part.strip() for part in str(borough).split("/")]
    if overrides:
        for one in boroughs:
            target = overrides.get((name, one))
            if target:
                for candidate in index["signname"].get(target, []):
                    if candidate["borough"] == one:
                        return candidate, "override"
    for table, kind in ((index["signname"], "signname"), (index["name311"], "name311")):
        same_borough = [
            candidate
            for candidate in table.get(name, [])
            if candidate["borough"] in boroughs
            and (name, candidate["signname"]) not in denylist
        ]
        if same_borough:
            return pick_best(same_borough), kind
    ranked = fuzzy_candidates(name, boroughs, index, cutoff, denylist)
    if ranked:
        return ranked[0], "fuzzy"
    return None, "none"


def crime_parks(csv_path=CRIME_CSV):
    frame = pd.read_csv(csv_path)
    return frame.groupby(["park", "borough"], as_index=False)["count"].sum()


def park_identity(park, borough, matched, taken):
    """Stable park id: the GIS property number when it is unique.

    Unmatched parks (and two crime rows landing on one property) fall back to
    a deterministic borough:name id, so every crime park has its own key.
    """
    candidate = matched["park_id"] if matched and matched["park_id"] else None
    if candidate is None or candidate in taken:
        candidate = f"{borough}:{park}"
    taken.add(candidate)
    return candidate


def build_frame(parks, index, denylist=None, overrides=None):
    """Match every crime park; return (frame, fuzzy audit rows)."""
    denylist = load_denylist() if denylist is None else denylist
    overrides = load_overrides() if overrides is None else overrides
    rows, audit, taken = [], [], set()
    for record in parks.itertuples(index=False):
        matched, match_type = match_park(
            record.park, record.borough, index, denylist=denylist, overrides=overrides
        )
        rows.append(
            {
                "park": record.park,
                "borough": record.borough,
                "park_id": park_identity(record.park, record.borough, matched, taken),
                "canonical_name": matched["canonical_name"] if matched else None,
                "lat": matched["lat"] if matched else None,
                "lon": matched["lon"] if matched else None,
                "acres_geo": matched["acres_geo"] if matched else None,
                "typecategory": matched["typecategory"] if matched else None,
                "match_type": match_type,
                "count": record.count,
            }
        )
        if match_type == "fuzzy" and matched:
            # Distance audit: how far the runner-up candidate is from the pick.
            boroughs = [part.strip() for part in str(record.borough).split("/")]
            ranked = fuzzy_candidates(
                normalize_name(record.park), boroughs, index, denylist=denylist
            )
            runner_up = ranked[1] if len(ranked) > 1 else None
            audit.append(
                {
                    "park": record.park,
                    "borough": record.borough,
                    "matched_property": matched["canonical_name"],
                    "runner_up": runner_up["canonical_name"] if runner_up else None,
                    "distance_km": (
                        round(distance_km(matched["lat"], matched["lon"],
                                          runner_up["lat"], runner_up["lon"]), 3)
                        if runner_up else None
                    ),
                }
            )
    return pd.DataFrame(rows), audit


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


def write_warehouse(frame):
    """Rewrite the parks dimension and park ids in a temp DB, then swap."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DB_PATH.with_name(DB_PATH.name + ".tmp")
    try:
        if DB_PATH.exists():
            shutil.copyfile(DB_PATH, tmp)
        connection = schema.connect(tmp)
        try:
            schema.ensure_schema(connection)
            # Park ids are rewritten in place, so FK checks move to commit time.
            connection.execute("BEGIN")
            connection.execute("PRAGMA defer_foreign_keys = ON")
            connection.execute("DELETE FROM parks")
            connection.executemany(
                "INSERT INTO parks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        row.park_id, row.park, row.borough, row.canonical_name,
                        row.lat, row.lon, row.acres_geo, row.typecategory,
                        row.match_type,
                    )
                    for row in frame[PARK_COLUMNS].itertuples(index=False)
                ],
            )
            connection.executemany(
                "UPDATE crimes_long SET park_id = ? WHERE park = ? AND borough = ?",
                [
                    (row.park_id, row.park, row.borough)
                    for row in frame[["park", "borough", "park_id"]].itertuples(index=False)
                ],
            )
            connection.commit()
        finally:
            connection.close()
        os.replace(tmp, DB_PATH)
    finally:
        tmp.unlink(missing_ok=True)


def denylist_rows(path=DENYLIST_CSV):
    """Curated false-positive audit, carried in the denylist itself."""
    if not path.exists():
        return []
    frame = pd.read_csv(path)
    if "distance_km" not in frame.columns:
        return []
    return [
        (row.park, row.matched_property, float(row.distance_km))
        for row in frame.itertuples()
        if pd.notna(row.distance_km)
    ]


def write_outputs(frame, audit):
    GEO_CSV.parent.mkdir(parents=True, exist_ok=True)
    frame[PARK_COLUMNS].to_csv(GEO_CSV, index=False)
    write_warehouse(frame)
    stats = coverage(frame)
    COVERAGE_CSV.parent.mkdir(parents=True, exist_ok=True)
    metrics = {"metric": list(stats), "value": [str(v) for v in stats.values()]}
    for park, matched, distance in denylist_rows():
        metrics["metric"].append("fuzzy_false_positive")
        metrics["value"].append(f"{park} -> {matched} ({distance} km)")
    pd.DataFrame(metrics).to_csv(COVERAGE_CSV, index=False)
    pd.DataFrame(
        denylist_rows(), columns=["park", "matched_property", "distance_km"]
    ).to_csv(FALSE_POSITIVES_CSV, index=False)
    pd.DataFrame(
        audit,
        columns=["park", "borough", "matched_property", "runner_up", "distance_km"],
    ).to_csv(FUZZY_AUDIT_CSV, index=False)
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        action="store_true",
        help="print unweighted and volume-weighted match coverage",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="ignore the properties cache TTL and refetch from Socrata",
    )
    args = parser.parse_args()

    if not CRIME_CSV.exists():
        print(f"error: {CRIME_CSV} missing; run etl/parse.py first", file=sys.stderr)
        return 2

    index = build_index(fetch_properties(refresh=args.refresh))
    frame, audit = build_frame(crime_parks(), index)
    stats = write_outputs(frame, audit)
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
    print(f"wrote {FUZZY_AUDIT_CSV.relative_to(ROOT)} ({len(audit)} fuzzy match(es) audited)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
