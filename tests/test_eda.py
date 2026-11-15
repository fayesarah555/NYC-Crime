"""Network-free checks for the EDA helpers (ticket 0034)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.eda import (  # noqa: E402
    chi_square, cramers_v, load_crimes, rate_per_100_acres,
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


def test_stats_json_values_in_range():
    path = Path(__file__).resolve().parents[1] / "outputs" / "metrics" / "eda_stats.json"
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
    root = Path(__file__).resolve().parents[1]
    if not (root / "data" / "warehouse.db").exists() and not (
        root / "data" / "processed" / "park_crime_long.csv"
    ).exists():
        pytest.skip("no local data")
    df = load_crimes()
    first = df.loc[df["park"] == "CENTRAL PARK", "quarter_label"].min()
    assert first == "2025Q1"
