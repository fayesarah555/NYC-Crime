"""Network-free: name normalization, centroid, borough-scoped fuzzy match, coverage."""

import sys
from pathlib import Path

import pandas as pd

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import etl.geo as geo  # noqa: E402
from etl.geo import (  # noqa: E402
    PAGE_SIZE,
    build_index,
    centroid,
    coverage,
    fetch_properties,
    match_park,
    normalize_name,
    park_identity,
)


def square(lon, lat):
    """A 0.1-degree MultiPolygon square around (lon, lat)."""
    ring = [
        [lon - 0.05, lat - 0.05],
        [lon + 0.05, lat - 0.05],
        [lon + 0.05, lat + 0.05],
        [lon - 0.05, lat + 0.05],
        [lon - 0.05, lat - 0.05],
    ]
    return {"type": "MultiPolygon", "coordinates": [[ring]]}


def property_(signname, name311, borough, lon=-73.95, lat=40.75):
    return {
        "signname": signname,
        "name311": name311,
        "borough": borough,
        "acres": "1.0",
        "typecategory": "Park",
        "multipolygon": square(lon, lat),
    }


def test_normalize_name_collapses_spelling_variants():
    assert normalize_name("  Central   Park ") == "CENTRAL PARK"
    assert normalize_name("St. Mary's Park") == normalize_name("ST MARYS PARK")
    assert normalize_name("BEACH & BOARDWALK") == normalize_name("Beach and Boardwalk")
    assert normalize_name("MATTHEWS - PALMER") == normalize_name("MATTHEWS PALMER")


def test_centroid_on_known_square():
    geometry = square(-73.95, 40.75)
    lat, lon = centroid(geometry)
    assert abs(lat - 40.75) < 1e-6
    assert abs(lon - (-73.95)) < 1e-6


def test_fuzzy_match_does_not_cross_boroughs():
    index = build_index(
        [
            property_("ROSE PARK", "Rose Park", "M"),
            property_("ROSE PARK", "Rose Park", "X", lon=-73.90, lat=40.85),
        ]
    )
    # Exact name: the same-borough candidate wins over the other borough.
    hit, kind = match_park("ROSE PARK", "BRONX", index)
    assert kind == "signname"
    assert (hit["lat"], hit["lon"]) != (40.75, -73.95)
    # Near-miss name: only fuzzy, so a match is allowed inside the borough...
    same, kind = match_park("ROSE PARKK", "MANHATTAN", index)
    assert kind == "fuzzy"
    assert abs(same["lat"] - 40.75) < 1e-6
    # ...and refused when the closest name lives in another borough.
    elsewhere, kind = match_park("ROSE PARKK", "QUEENS", index)
    assert elsewhere is None
    assert kind == "none"


def test_exact_match_in_another_borough_is_not_a_match():
    index = build_index([property_("ROSE PARK", "Rose Park", "M")])
    # The only ROSE PARK property is in Manhattan: no exact match for Queens.
    hit, kind = match_park("ROSE PARK", "QUEENS", index)
    assert hit is None
    assert kind == "none"
    # It falls through to the within-borough fuzzy tier instead.
    index = build_index(
        [
            property_("ROSE PARK", "Rose Park", "M"),
            property_("ROSE PARKK", "Rose Parkk", "Q", lon=-73.80, lat=40.70),
        ]
    )
    hit, kind = match_park("ROSE PARK", "QUEENS", index)
    assert kind == "fuzzy"
    assert abs(hit["lat"] - 40.70) < 1e-6


def test_coverage_weights_by_crime_volume():
    frame = pd.DataFrame(
        {
            "park": ["A", "B", "C", "D"],
            "match_type": ["signname", "fuzzy", "none", "none"],
            "lat": [40.7, 40.8, None, None],
            "lon": [-73.9, -73.8, None, None],
            "count": [10, 20, 5, 0],
        }
    )
    stats = coverage(frame)
    assert stats["parks"] == 4
    assert stats["matched_parks"] == 2
    assert stats["unweighted_coverage"] == 0.5
    assert abs(stats["weighted_coverage"] - 30 / 35) < 1e-9


def test_coverage_requires_both_coordinates():
    frame = pd.DataFrame(
        {
            "park": ["A", "B"],
            "match_type": ["signname", "signname"],
            "lat": [40.7, None],
            "lon": [-73.9, None],
            "count": [10, 5],
        }
    )
    stats = coverage(frame)
    assert stats["matched_parks"] == 1
    assert abs(stats["weighted_coverage"] - 10 / 15) < 1e-9


def test_empty_geometry_is_skipped_not_fatal():
    empty = property_("EMPTY", "Empty", "M")
    empty["multipolygon"] = {"type": "MultiPolygon", "coordinates": []}
    flat = property_("FLAT", "Flat", "M")
    flat["multipolygon"] = {
        "type": "MultiPolygon",
        "coordinates": [[[[0.0, 0.0], [0.0, 0.0], [0.0, 0.0], [0.0, 0.0]]]],
    }
    index = build_index([empty, flat, property_("ROSE PARK", "Rose Park", "M")])
    assert "EMPTY" not in index["signname"]
    assert "FLAT" not in index["signname"]
    hit, kind = match_park("ROSE PARK", "MANHATTAN", index)
    assert kind == "signname"
    assert hit is not None


def test_park_identity_prefers_gis_id_and_disambiguates_duplicates():
    taken = set()
    matched = {"park_id": "M110"}
    assert park_identity("ROSE PARK", "MANHATTAN", matched, taken) == "M110"
    # A second crime row landing on the same property gets its own key.
    assert park_identity("ROSE PARK NORTH", "MANHATTAN", matched, taken) == (
        "MANHATTAN:ROSE PARK NORTH"
    )
    # Unmatched parks still get a deterministic id.
    assert park_identity("ADMIRAL PARK", "QUEENS", None, taken) == (
        "QUEENS:ADMIRAL PARK"
    )


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeSession:
    """Socrata stand-in; `ignore_offset` models an API that drops $offset."""

    def __init__(self, rows, ignore_offset=False):
        self.rows = rows
        self.ignore_offset = ignore_offset

    def get(self, url, params, timeout):
        start = 0 if self.ignore_offset else params["$offset"]
        return FakeResponse(self.rows[start:start + PAGE_SIZE])


def test_fetch_properties_aborts_when_api_ignores_offset(tmp_path):
    rows = [{"name311": f"PARK {i}"} for i in range(PAGE_SIZE)]
    with pytest.raises(RuntimeError, match=r"ignores \$offset"):
        fetch_properties(
            url="fake",
            cache_path=tmp_path / "cache.json",
            refresh=True,
            session=FakeSession(rows, ignore_offset=True),
        )


def test_fetch_properties_reads_a_long_result_set_under_the_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(geo, "MAX_OFFSET", PAGE_SIZE * 5)
    rows = [{"name311": f"PARK {i}"} for i in range(PAGE_SIZE * 5 - 500)]
    got = fetch_properties(
        url="fake",
        cache_path=tmp_path / "cache.json",
        refresh=True,
        session=FakeSession(rows),
    )
    assert len(got) == len(rows)


def test_fetch_properties_aborts_at_max_offset(tmp_path, monkeypatch):
    monkeypatch.setattr(geo, "MAX_OFFSET", PAGE_SIZE * 2)
    rows = [{"name311": f"PARK {i}"} for i in range(PAGE_SIZE * 4)]
    with pytest.raises(RuntimeError, match="MAX_OFFSET"):
        fetch_properties(
            url="fake",
            cache_path=tmp_path / "cache.json",
            refresh=True,
            session=FakeSession(rows),
        )
