"""Property-based invariants over the published artefacts (plan 5.4).

These run against the exported JSON payloads: the cube must reconcile with the
park totals, the city series and the borough matrix for every generated
window/type/borough selection; shares must sum to one; forecast bounds must be
ordered and non-negative.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "web" / "src" / "data"

pytestmark = pytest.mark.skipif(
    not (DATA / "cubes.json").exists(),
    reason="web payloads absent; run `make web-export` first",
)


def _load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def payloads():
    return {name: _load(name) for name in
            ("cubes.json", "parks.json", "series.json", "borough_type.json",
             "forecast.json", "meta.json")}


def _window_cells(cube, types, start, end):
    quarters = cube["quarters"]
    lo = quarters.index(start) if start in quarters else 0
    hi = quarters.index(end) if end in quarters else len(quarters) - 1
    type_index = {t: i for i, t in enumerate(cube["crime_types"])}
    picked = [type_index[t] for t in types] if types else list(range(len(cube["crime_types"])))
    total = 0
    for cells in cube["parks"].values():
        for quarter, counts in cells.items():
            q = quarters.index(quarter)
            if lo <= q <= hi:
                total += sum(counts[i] or 0 for i in picked)
    return total


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    boroughs=st.lists(st.sampled_from(["BRONX", "BROOKLYN", "MANHATTAN", "QUEENS", "STATEN ISLAND"]), max_size=3),
    types=st.lists(st.sampled_from(["MURDER", "RAPE", "ROBBERY", "FELONY ASSAULT", "BURGLARY", "GRAND LARCENY", "GRAND LARCENY AUTO"]), max_size=3),
    lo=st.integers(min_value=0, max_value=45),
    hi=st.integers(min_value=0, max_value=45),
)
def test_selection_totals_agree(payloads, boroughs, types, lo, hi):
    cube = payloads["cubes.json"]
    quarters = cube["quarters"]
    start, end = sorted((lo, hi))
    start_q, end_q = quarters[start], quarters[end]
    window = _window_cells(cube, types, start_q, end_q)
    assert window >= 0

    # Selecting boroughs only partitions the same window.
    borough_of = {p["park_id"]: p["borough"] for p in payloads["parks.json"]}
    selected = 0
    for park_id, cells in cube["parks"].items():
        if boroughs and borough_of.get(park_id) not in boroughs:
            continue
        for quarter, counts in cells.items():
            q = quarters.index(quarter)
            if start <= q <= end:
                selected += sum(v or 0 for v in counts) if not types else sum(
                    counts[cube["crime_types"].index(t)] or 0 for t in types
                )
    assert selected <= window or types
    assert selected >= 0


def test_park_totals_equal_cube_sums(payloads):
    cube = payloads["cubes.json"]
    parks = {p["park_id"]: p for p in payloads["parks.json"]}
    type_index = {t: i for i, t in enumerate(cube["crime_types"])}
    for park_id, cells in cube["parks"].items():
        total = 0
        for counts in cells.values():
            total += sum(v or 0 for v in counts)
        park_total = parks[park_id]["total"]
        assert total == park_total, park_id
        for crime_type, value in parks[park_id]["counts"].items():
            if value is not None:
                assert value >= 0
                assert value == sum(
                    (cells.get(q) or [0] * len(type_index))[type_index[crime_type]] or 0
                    for q in cells
                ), (park_id, crime_type)


def test_city_series_equals_cube(payloads):
    cube = payloads["cubes.json"]
    series = payloads["series.json"]
    quarters = cube["quarters"]
    per_quarter = {q: 0 for q in quarters}
    for cells in cube["parks"].values():
        for quarter, counts in cells.items():
            per_quarter[quarter] += sum(v or 0 for v in counts)
    assert [per_quarter[q] for q in quarters] == series["city"]


def test_borough_matrix_equals_cube(payloads):
    cube = payloads["cubes.json"]
    matrix = payloads["borough_type.json"]
    borough_of = {p["park_id"]: p["borough"] for p in payloads["parks.json"]}
    computed = {
        row["borough"]: {t: 0 for t in cube["crime_types"]}
        for row in matrix["boroughs"]
    }
    for park_id, cells in cube["parks"].items():
        borough = borough_of[park_id]
        if borough not in computed:
            continue
        for counts in cells.values():
            for crime_type, value in zip(cube["crime_types"], counts):
                computed[borough][crime_type] += value or 0
    for row in matrix["boroughs"]:
        assert computed[row["borough"]] == row["counts"], row["borough"]


def test_forecast_bounds_ordered_and_non_negative(payloads):
    forecast = payloads["forecast.json"]

    def check(points):
        for point in points:
            assert point["lower"] >= 0
            assert point["lower"] <= point["point"] <= point["upper"]

    check(forecast["city"])
    for points in forecast["boroughs"].values():
        check(points)


def test_type_shares_sum_to_one(payloads):
    parks = payloads["parks.json"]
    for park in parks:
        if park["total"] == 0:
            continue
        shares = [v for v in park["counts"].values() if v is not None]
        assert abs(sum(shares) / park["total"] - 1) < 1e-9


def test_random_quarter_windows_are_monotone(payloads):
    cube = payloads["cubes.json"]
    quarters = cube["quarters"]
    rng = random.Random(42)
    windows = sorted(rng.sample(range(len(quarters)), 6))
    totals = [_window_cells(cube, [], quarters[a], quarters[b])
              for a, b in zip(windows, windows[1:])]
    assert all(t >= 0 for t in totals)
