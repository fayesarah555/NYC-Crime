"""Tests des helpers purs de l'application Streamlit (ticket 0036)."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from app import (  # noqa: E402
    SHORT_TYPE_LABELS,
    count_label,
    dominant_type,
    filter_dataframe,
    kpis,
    normalize_text,
    park_totals,
    top_parks,
    totals_by,
    year_ago,
)


def sample():
    return pd.DataFrame(
        {
            "quarter_label": ["2024Q4", "2024Q4", "2025Q1", "2025Q1"],
            "park": [
                "Parc des Églises",
                "Pelham Bay Park",
                "Parc des Églises",
                "Pelham Bay Park",
            ],
            "borough": ["MANHATTAN", "BRONX", "MANHATTAN", "BRONX"],
            "crime_type": ["ROBBERY", "BURGLARY", "ROBBERY", "MURDER"],
            "count": [2, 5, 4, 2],
        }
    )


def test_borough_filter_keeps_only_selected():
    out = filter_dataframe(sample(), boroughs=["BRONX"])
    assert set(out["borough"]) == {"BRONX"}
    assert int(out["count"].sum()) == 7


def test_empty_borough_selection_means_no_filter():
    out = filter_dataframe(sample(), boroughs=[])
    assert len(out) == len(sample())


def test_park_search_ignores_case_and_accents():
    out = filter_dataframe(sample(), park_query="eglises")
    assert out["park"].unique().tolist() == ["Parc des Églises"]
    assert normalize_text("ÉGLISE") == "eglise"


def test_quarter_range_boundaries_inclusive():
    only = filter_dataframe(sample(), quarter_range=("2024Q4", "2024Q4"))
    assert only["quarter_label"].unique().tolist() == ["2024Q4"]
    both = filter_dataframe(sample(), quarter_range=("2024Q4", "2025Q1"))
    assert len(both) == len(sample())


def test_empty_result_kpis_are_zeroed():
    out = filter_dataframe(sample(), park_query="introuvable")
    assert out.empty
    summary = kpis(out)
    assert summary["total_crimes"] == 0
    assert summary["parks"] == 0
    assert summary["latest_change_pct"] is None


def test_category_totals_per_crime_type():
    totals = totals_by(sample(), "crime_type").set_index("crime_type")["count"]
    assert int(totals["ROBBERY"]) == 6
    assert int(totals["BURGLARY"]) == 5


def test_kpis_latest_change_and_top_type():
    summary = kpis(sample())
    assert summary["top_type"] == "ROBBERY"
    assert summary["latest_quarter"] == "2025Q1"
    assert summary["latest_change_pct"] == pytest.approx((6 - 7) / 7 * 100)


def test_dominant_type_and_top_parks():
    dominant = dominant_type(sample()).set_index("park")["crime_type"]
    assert dominant["Parc des Églises"] == "ROBBERY"
    assert dominant["Pelham Bay Park"] == "BURGLARY"
    top = top_parks(sample(), n=1)
    assert top.iloc[0]["park"] == "Pelham Bay Park"
    assert int(top.iloc[0]["count"]) == 7


def combined_sample():
    return pd.DataFrame(
        {
            "quarter_label": ["2026Q2"] * 3,
            "park": ["Prospect Park", "Flushing Meadows", "Combo Park"],
            "borough": ["BROOKLYN", "QUEENS", "BROOKLYN/QUEENS"],
            "crime_type": ["ROBBERY"] * 3,
            "count": [10, 20, 7],
        }
    )


def test_combined_borough_counts_for_either_borough():
    brooklyn = filter_dataframe(combined_sample(), boroughs=["BROOKLYN"])
    assert brooklyn["park"].tolist() == ["Prospect Park", "Combo Park"]
    queens = filter_dataframe(combined_sample(), boroughs=["QUEENS"])
    assert queens["park"].tolist() == ["Flushing Meadows", "Combo Park"]


def test_combined_borough_not_duplicated_when_both_selected():
    both = filter_dataframe(combined_sample(), boroughs=["BROOKLYN", "QUEENS"])
    assert len(both) == 3
    assert both["park"].is_unique
    assert int(both["count"].sum()) == 37


def test_map_totals_drop_zero_crime_parks():
    df = pd.DataFrame(
        {
            "park": ["A", "A", "B"],
            "count": [0, 3, 0],
            "quarter_label": ["2026Q2"] * 3,
            "crime_type": ["ROBBERY"] * 3,
        }
    )
    totals, zero = park_totals(df)
    assert totals["park"].tolist() == ["A"]
    assert zero == 1
    assert kpis(df)["parks"] == 1


def test_zero_crime_selection_has_no_top_type_or_change():
    df = pd.DataFrame(
        {
            "park": ["A", "B"],
            "count": [0, 0],
            "quarter_label": ["2026Q2", "2026Q1"],
            "crime_type": ["ROBBERY", "MURDER"],
        }
    )
    summary = kpis(df)
    assert summary["top_type"] is None
    assert summary["latest_change_pct"] is None
    assert summary["change_basis"] is None


def test_change_uses_same_quarter_previous_year():
    df = pd.DataFrame(
        {
            "park": ["A"] * 3,
            "count": [100, 300, 150],
            "quarter_label": ["2025Q2", "2026Q1", "2026Q2"],
            "crime_type": ["ROBBERY"] * 3,
        }
    )
    summary = kpis(df)
    assert summary["change_basis"] == "annuelle"
    assert summary["latest_change_pct"] == pytest.approx((150 - 100) / 100 * 100)
    assert year_ago("2026Q2") == "2025Q2"


def test_change_falls_back_to_previous_quarter():
    df = pd.DataFrame(
        {
            "park": ["A"] * 2,
            "count": [10, 15],
            "quarter_label": ["2026Q1", "2026Q2"],
            "crime_type": ["ROBBERY"] * 2,
        }
    )
    summary = kpis(df)
    assert summary["change_basis"] == "trimestrielle"
    assert summary["latest_change_pct"] == pytest.approx(50.0)


def test_count_label_agrees_in_number():
    assert count_label(0, "parc", "parcs") == "0 parc"
    assert count_label(1, "parc", "parcs") == "1 parc"
    assert count_label(2, "parc", "parcs") == "2 parcs"
    assert count_label(1, "parc géolocalisé", "parcs géolocalisés") == "1 parc géolocalisé"


def test_short_labels_cover_every_crime_type():
    assert set(SHORT_TYPE_LABELS) == {
        "BURGLARY",
        "FELONY ASSAULT",
        "GRAND LARCENY",
        "GRAND LARCENY AUTO",
        "MURDER",
        "RAPE",
        "ROBBERY",
    }
    assert SHORT_TYPE_LABELS["GRAND LARCENY"] == "Larcin"


def test_missing_metrics_shows_make_all_error():
    from streamlit.testing.v1 import AppTest

    def script():
        import app as appmod

        appmod.METRICS_FILE = appmod.ROOT / "outputs" / "metrics" / "absent.json"
        appmod.render_forecast()

    at = AppTest.from_function(script).run(timeout=60)
    assert not at.exception
    assert at.error, "missing artefact must surface st.error"
    assert "make all" in at.error[0].value
