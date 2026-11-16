"""Exploratory analysis of NYC park crime.

Figures, tables and headline statistics for the report. Figure labels are
French (the deliverable is for a French course); code and comments are English.

Run from the repository root:  python analysis/eda.py
"""

import json
import math
import re
import sqlite3
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import chi2_contingency  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "warehouse.db"
CSV_PATH = ROOT / "data" / "processed" / "park_crime_long.csv"
GEO_CSV = ROOT / "data" / "processed" / "parks_geo.csv"
FIG_DIR = ROOT / "outputs" / "figures"
TABLE_DIR = ROOT / "outputs" / "tables"
METRIC_DIR = ROOT / "outputs" / "metrics"

DPI = 150
FIGSIZE = (10, 6)

# Okabe-Ito colourblind-safe palette, shared with the web dashboard and
# Streamlit through palette_data.py (the exporter serialises the same values).
from palette_data import CLUSTER_PALETTE, NEUTRAL_COLOR  # noqa: E402

OKABE_ITO = CLUSTER_PALETTE + ["#000000", "#F0E442", NEUTRAL_COLOR]

MONTHS_FR = {1: "Janvier", 4: "Avril", 7: "Juillet", 10: "Octobre"}


# --------------------------------------------------------------------------
# Data loading and helpers
# --------------------------------------------------------------------------

def load_crimes():
    """Load the long crime table and attach the stable park_id.

    NULL counts stay NULL (see NULL_RULE); every consumer aggregates with
    skipna so a missing column never enters a sum as a zero.
    """
    columns = (
        "quarter_label, period_start, period_end, park, borough, size_acres, "
        "category, crime_type, count, count_missing, total_mismatch"
    )
    if DB_PATH.exists():
        with sqlite3.connect(DB_PATH) as conn:
            df = pd.read_sql(f"SELECT {columns} FROM crimes_long", conn)
    else:
        df = pd.read_csv(CSV_PATH)
    df["period_start"] = pd.to_datetime(df["period_start"])
    ids = pd.read_csv(GEO_CSV)[["park", "borough", "park_id"]]
    return df.merge(ids, on=["park", "borough"], how="left")


def quarter_range(first, last):
    """Continuous quarter labels from first to last, inclusive."""
    year, quarter = (int(part) for part in first.split("Q"))
    last_year, last_quarter = (int(part) for part in last.split("Q"))
    labels = []
    while (year, quarter) <= (last_year, last_quarter):
        labels.append(f"{year}Q{quarter}")
        quarter += 1
        if quarter == 5:
            year, quarter = year + 1, 1
    return labels


def missing_quarters(df):
    """Quarter labels on the continuous grid with no row in the data."""
    order = df.groupby("quarter_label")["period_start"].min().sort_values().index
    seen = set(order)
    return [label for label in quarter_range(order[0], order[-1]) if label not in seen]


def missing_sentence(df):
    """Footnote fragment naming the dataset-wide absent quarter(s)."""
    missing = missing_quarters(df)
    if not missing:
        return ""
    return f"{', '.join(missing)} absent des données source. "


def quarter_from_workbook(name):
    """'...q4-2025.xlsx' -> '2025Q4'."""
    match = re.search(r"q(\d)-(\d{4})\.xlsx$", str(name))
    return f"{match.group(2)}Q{match.group(1)}" if match else ""


def source_anomaly_table():
    """Integrity flags written by etl/parse.py; empty when absent."""
    path = TABLE_DIR / "source_anomalies.csv"
    if not path.exists():
        return pd.DataFrame(
            columns=["workbook", "park", "total_recorded", "sum_computed", "kind"]
        )
    return pd.read_csv(path)


def source_anomaly_entries():
    """Structured TOTAL-mismatch entries for the metrics JSON."""
    flags = source_anomaly_table()
    if flags.empty or "kind" not in flags:
        return []
    return [
        {
            "park": row.park,
            "quarter": quarter_from_workbook(row.workbook),
            "total_recorded": int(row.total_recorded),
            "sum_computed": int(row.sum_computed),
        }
        for row in flags[flags["kind"].eq("total_mismatch")].itertuples()
    ]


def anomaly_note():
    """Figure footnote derived from the recorded TOTAL mismatches."""
    entries = source_anomaly_entries()
    if not entries:
        return "Aucune anomalie TOTAL signalée dans la source."
    details = " ; ".join(
        f"{entry['park'].title()}, {entry['quarter']} — TOTAL "
        f"{entry['total_recorded']} vs somme {entry['sum_computed']}"
        for entry in entries
    )
    return (
        f"Anomalie source : {details} ; les composantes sont conservées, la "
        "ligne est exclue des contrôles TOTAL seulement "
        "(outputs/tables/source_anomalies.csv)."
    )


def missing_column_rows(df):
    """Rows whose count is NULL because the workbook lacks that crime column."""
    if "count_missing" not in df:
        return df.iloc[0:0]
    return df[df["count_missing"].eq(1)]


def null_rule(df):
    """Logged exclusion rule, with the quarters/types read from the data."""
    missing = missing_column_rows(df)
    if missing.empty:
        return "No NULL count: every workbook carries all crime columns."
    quarters = ", ".join(sorted(missing["quarter_label"].unique()))
    types = ", ".join(sorted(missing["crime_type"].unique()))
    return (
        f"count=NULL when the workbook lacks the crime column ({quarters}: "
        f"{types}); NULLs are excluded from sums, rates and shares, never "
        "imputed, never treated as 0."
    )


def missing_column_anomaly(df):
    """English summary of the absent-column anomalies, derived from the data."""
    missing = missing_column_rows(df)
    if missing.empty:
        return "No workbook lacks a crime column."
    quarters = ", ".join(sorted(missing["quarter_label"].unique()))
    types = ", ".join(sorted(missing["crime_type"].unique()))
    return (
        f"{quarters} have no {types} column: count is NULL with "
        "count_missing=1, never 0 (outputs/tables/source_anomalies.csv)"
    )


def late_parks(df):
    """Parks whose first observed quarter is later than the dataset's first."""
    order = df.groupby("quarter_label")["period_start"].min().sort_values().index
    first = order[0]
    firsts = df.sort_values("period_start").groupby("park_id")["quarter_label"].first()
    names = df.groupby("park_id")["park"].first()
    return [
        {"park": names[park_id], "first_quarter": label}
        for park_id, label in firsts.items()
        if label != first
    ]


def p_value_display(p_value):
    """'p < 1e-N' with N the largest power of ten the value stays below."""
    if not p_value or p_value <= 0:
        return "p < 1e-300"
    return f"p < 1e-{math.floor(-math.log10(p_value))}"


def chi_square(table):
    """Chi-square test of independence on a count table.

    Returns (statistic, p_value, degrees_of_freedom, expected). No Yates
    correction: the helper is used on tables wider than 2x2 and in tests on a
    hand-checkable 2x2, where the uncorrected formula is the textbook one.
    """
    observed = np.asarray(table, dtype=float)
    statistic, p_value, dof, expected = chi2_contingency(observed, correction=False)
    return float(statistic), float(p_value), int(dof), expected


def cramers_v(statistic, n, shape):
    """Cramér's V for a chi-square statistic on a table of the given shape."""
    k = min(shape) - 1
    if k <= 0 or n <= 0:
        return 0.0
    return float(math.sqrt(statistic / (n * k)))


def rate_per_100_acres(total_crimes, acres):
    """Crimes per 100 acres; acres must be counted once per park."""
    if acres <= 0:
        return 0.0
    return float(total_crimes) / float(acres) * 100.0


def quarterly_totals(df):
    """Total crimes per quarter, ordered by period start."""
    totals = df.groupby("quarter_label", as_index=False).agg(
        period_start=("period_start", "min"),
        crimes=("count", "sum"),
    )
    return totals.sort_values("period_start").reset_index(drop=True)


def borough_type_counts(df):
    """Borough x crime-type count table."""
    return (
        df.groupby(["borough", "crime_type"])["count"]
        .sum()
        .unstack(fill_value=0)
        .sort_index()
    )


def park_acres(df):
    """Latest non-null size_acres per park_id (not the first row's value)."""
    ordered = df.dropna(subset=["size_acres"]).sort_values("period_start")
    return ordered.groupby("park_id")["size_acres"].last()


def borough_rate_table(df):
    """Crime rate per 100 acres by borough, perimeter and coverage stated.

    The numerator and denominator are restricted to parks with acreage; the
    excluded crime volume is reported, never silently dropped. A second,
    consistent-perimeter rate excludes Central Park, whose crime series starts
    later than the rest while its acreage is counted in full.
    """
    park_rows = df.groupby(["park_id", "park", "borough"], as_index=False).agg(
        total_crimes=("count", "sum"),
    )
    park_rows["acres"] = park_rows["park_id"].map(park_acres(df))
    park_rows["has_acres"] = park_rows["acres"].notna()
    park_rows["is_central"] = park_rows["park"].eq("CENTRAL PARK")

    table = []
    for borough, group in park_rows.groupby("borough"):
        rated = group[group["has_acres"]]
        central = rated[rated["is_central"]]
        total = float(group["total_crimes"].sum())
        rated_crimes = float(rated["total_crimes"].sum())
        rated_acres = float(rated["acres"].sum())
        excl_crimes = rated_crimes - float(central["total_crimes"].sum())
        excl_acres = rated_acres - float(central["acres"].sum())
        table.append({
            "borough": borough,
            "parks": int(len(group)),
            "parks_with_crimes": int((group["total_crimes"] > 0).sum()),
            "parks_with_acreage": int(len(rated)),
            "total_crimes": int(total),
            "crimes_with_acreage": int(rated_crimes),
            "excluded_crimes": int(total - rated_crimes),
            "crime_coverage_pct": round(rated_crimes / total * 100, 2) if total else 0.0,
            "acres": round(rated_acres, 3),
            "rate_per_100_acres": round(rate_per_100_acres(rated_crimes, rated_acres), 3),
            "rate_excl_central_park": round(
                rate_per_100_acres(excl_crimes, excl_acres), 3
            ),
            "central_park_crimes": int(central["total_crimes"].sum()),
            "central_park_acres": round(float(central["acres"].sum()), 3),
        })
    table = pd.DataFrame(table).set_index("borough")
    table["note"] = [
        f"{int(row.parks)} parks in the source, {int(row.parks_with_crimes)} "
        "with at least one crime; borough value split between Brooklyn and "
        "Queens"
        if borough == "BROOKLYN/QUEENS" else ""
        for borough, row in table.iterrows()
    ]
    return table.sort_values("rate_per_100_acres", ascending=False)


def seasonal_means(df):
    """Mean quarterly crimes by quarter-of-year, and by period-start month."""
    totals = quarterly_totals(df)
    totals = totals.assign(
        quarter_of_year=totals["quarter_label"].str[-1].astype(int),
        month=totals["period_start"].dt.month,
    )
    by_quarter = totals.groupby("quarter_of_year")["crimes"].mean()
    by_month = totals.groupby("month")["crimes"].mean()
    return by_quarter, by_month


def zero_share_by_quarter(df):
    """Share of parks with zero major crimes in each quarter.

    Only park-quarter rows that exist are counted: an absent park is not a
    park with zero crimes (fill_value=0 used to invent those rows).
    """
    per_park = df.pivot_table(
        index="quarter_label", columns="park_id", values="count", aggfunc="sum",
    )
    order = df.groupby("quarter_label")["period_start"].min().sort_values().index
    per_park = per_park.reindex(order)
    present = per_park.notna()
    zero = (per_park == 0) & present
    return zero.sum(axis=1) / present.sum(axis=1) * 100


def latest_complete_yoy(df, totals):
    """Year-over-year change for the latest year with all four quarters.

    Parks first seen in the latest year (Central Park, absent upstream before
    2025) inflate the headline; their counts are removed for the exclusive
    figure rather than dropped from the dataset.
    """
    years = totals.assign(year=totals["period_start"].dt.year)
    counts = years.groupby("year").agg(
        crimes=("crimes", "sum"),
        quarters=("quarter_label", "nunique"),
    )
    complete = counts[counts["quarters"] == 4].index
    latest = int(complete.max())
    previous = latest - 1
    cur = float(counts.loc[latest, "crimes"])
    prev = float(counts.loc[previous, "crimes"])

    first_seen = df.groupby("park_id")["period_start"].min()
    names = df.groupby("park_id")["park"].first()
    new_ids = first_seen[first_seen >= pd.Timestamp(latest, 1, 1)].index
    new_parks = sorted(names[new_ids])
    latest_rows = df[df["period_start"].dt.year == latest]
    new_crimes = int(latest_rows.loc[latest_rows["park_id"].isin(new_ids), "count"].sum())
    cur_excl = cur - new_crimes
    yoy_excl = (cur_excl - prev) / prev * 100.0 if prev else 0.0
    names = ", ".join(new_parks) if new_parks else "aucun parc"
    return {
        "latest_complete_year": latest,
        "latest_complete_year_crimes": int(cur),
        "previous_year": previous,
        "previous_year_crimes": int(prev),
        "yoy_change_pct": (cur - prev) / prev * 100.0 if prev else 0.0,
        "new_parks": new_parks,
        "new_parks_latest_year_crimes": new_crimes,
        "latest_complete_year_excluding_new_parks_crimes": int(cur_excl),
        "yoy_excluding_new_parks_pct": yoy_excl,
        "coverage_artifact": bool(new_parks),
        "yoy_note": (
            f"{names} absent des workbooks source avant {latest}Q1 ; "
            f"hors ce parc, {latest} ({int(cur_excl)}) vs {previous} "
            f"({int(prev)}) = {yoy_excl:+.2f} % — le chiffre inclusif "
            f"({(cur - prev) / prev * 100.0:+.2f} %) est gonflé par cet "
            "artefact de couverture." if new_parks else
            "aucun parc nouveau dans l'année de référence"
        ),
    }


# --------------------------------------------------------------------------
# Figures
# --------------------------------------------------------------------------

def _save(fig, name):
    # Bottom margin keeps the footnote clear of the rotated x tick labels.
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(FIG_DIR / name, dpi=DPI)
    plt.close(fig)


def fig01_quarterly_trend(df):
    totals = quarterly_totals(df)
    boroughs = (
        df.groupby(["borough", "quarter_label"])["count"].sum()
        .unstack(fill_value=0)
        .reindex(columns=totals["quarter_label"], fill_value=0)
    )
    x = np.arange(len(totals))
    fig, ax = plt.subplots(figsize=FIGSIZE)
    for i, (borough, series) in enumerate(boroughs.iterrows()):
        ax.plot(x, series.values, label=borough, color=OKABE_ITO[i], linewidth=1.2)
    ax.plot(x, totals["crimes"].values, label="Total", color="#333333",
            linewidth=2.2, linestyle="--")
    ticks = x[::4]
    ax.set_xticks(ticks)
    ax.set_xticklabels(totals["quarter_label"].iloc[ticks], rotation=45, ha="right")
    ax.set_xlabel("Trimestre")
    ax.set_ylabel("Nombre de crimes")
    ax.set_title("Évolution trimestrielle des crimes dans les parcs "
                 f"({totals['quarter_label'].iloc[0]}–{totals['quarter_label'].iloc[-1]})")
    ax.set_ylim(bottom=0)
    ax.legend(ncol=3, fontsize=8)
    yoy = latest_complete_yoy(df, totals)
    fig.text(0.01, 0.01,
             f"Artefact de couverture : {', '.join(yoy['new_parks'])} absent "
             f"des workbooks avant {yoy['latest_complete_year']}Q1. Hors ce "
             f"parc, {yoy['latest_complete_year']} "
             f"({yoy['latest_complete_year_excluding_new_parks_crimes']}) vs "
             f"{yoy['previous_year']} ({yoy['previous_year_crimes']}) = "
             f"{yoy['yoy_excluding_new_parks_pct']:+.2f} % (chiffre inclusif "
             f"{yoy['yoy_change_pct']:+.2f} %). " + missing_sentence(df)
             + anomaly_note(),
             fontsize=6, color="#555555", wrap=True)
    _save(fig, "fig01_quarterly_trend.png")


def fig02_seasonality(df):
    by_quarter, by_month = seasonal_means(df)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=FIGSIZE)
    bars = ax1.bar([f"T{q}" for q in by_quarter.index], by_quarter.values,
                   color=OKABE_ITO[0])
    ax1.bar_label(bars, fmt="%.1f", fontsize=8)
    ax1.set_title("Moyenne par trimestre de l'année")
    ax1.set_xlabel("Trimestre")
    ax1.set_ylabel("Crimes moyens par trimestre")
    ax1.set_ylim(bottom=0)

    labels = [MONTHS_FR.get(m, str(m)) for m in by_month.index]
    bars = ax2.bar(labels, by_month.values, color=OKABE_ITO[1])
    ax2.bar_label(bars, fmt="%.1f", fontsize=8)
    ax2.set_title("Moyenne par mois de début de trimestre")
    ax2.set_xlabel("Mois de début")
    ax2.set_ylabel("Crimes moyens par trimestre")
    ax2.set_ylim(bottom=0)
    fig.suptitle("Saisonnalité des crimes dans les parcs")
    per_season = (
        quarterly_totals(df)["quarter_label"].str[-1].value_counts().sort_index()
    )
    span = ", ".join(
        f"T{quarter} sur {int(quarters)} trimestres"
        for quarter, quarters in per_season.items()
    )
    fig.text(0.01, 0.01,
             f"Moyennes calculées avec {span}. " + missing_sentence(df),
             fontsize=7, color="#555555")
    _save(fig, "fig02_seasonality.png")


def fig03_borough_type_heatmap(df):
    counts = borough_type_counts(df)
    share = counts.div(counts.sum(axis=1), axis=0) * 100
    fig, ax = plt.subplots(figsize=FIGSIZE)
    image = ax.imshow(share.values, cmap="viridis", aspect="auto")
    ax.set_xticks(np.arange(share.shape[1]))
    ax.set_xticklabels(share.columns, rotation=30, ha="right")
    ax.set_yticks(np.arange(share.shape[0]))
    ax.set_yticklabels(share.index)
    for i in range(share.shape[0]):
        for j in range(share.shape[1]):
            value = share.values[i, j]
            color = "white" if value < share.values.max() * 0.55 else "black"
            ax.text(j, i, f"{value:.1f}", ha="center", va="center",
                    fontsize=8, color=color)
    fig.colorbar(image, ax=ax, label="Part des crimes du borough (%)")
    ax.set_title("Répartition des types de crimes par borough")
    _save(fig, "fig03_borough_type_heatmap.png")


def park_totals(df):
    totals = (
        df.groupby(["park_id", "park", "borough"])["count"].sum().reset_index()
    )
    return totals.sort_values("count", ascending=False)


def coverage_gaps(df):
    """Per-park gaps against the expected quarter grid.

    A park-quarter is covered only when a row carries a non-NULL count and
    total_mismatch = 0, so the flagged Flushing Meadows 2025Q4 row is a gap
    even though its components are kept. Internal gaps and boundary gaps are
    both listed; a quarter absent dataset-wide is reported separately.
    """
    order = (
        df.groupby("quarter_label")["period_start"].min().sort_values().index
    )
    grid = list(order)
    index = {label: i for i, label in enumerate(grid)}
    dataset_first, dataset_last = grid[0], grid[-1]

    rows = []
    for (_, park, borough), group in df.groupby(["park_id", "park", "borough"]):
        usable = group.loc[
            group["total_mismatch"].eq(0) & group["count"].notna(), "quarter_label"
        ]
        covered = set(usable)
        seen = set(group["quarter_label"])
        first = min(seen, key=index.__getitem__)
        last = max(seen, key=index.__getitem__)
        missing = [
            (label, "total_mismatch" if label in seen else "no_rows")
            for label in grid[index[first] : index[last] + 1]
            if label not in covered
        ]
        boundary = first != dataset_first or last != dataset_last
        if not missing and not boundary:
            continue
        rows.append({
            "park": park,
            "borough": borough,
            "first_quarter": first,
            "last_quarter": last,
            "missing_quarters": " ".join(label for label, _ in missing),
            "gap_reasons": "; ".join(f"{label}: {why}" for label, why in missing),
            "n_missing": len(missing),
            "total_crimes": int(group["count"].sum()),
        })
    return (
        pd.DataFrame(rows)
        .sort_values("park")
        .reset_index(drop=True)
    )


def coverage_gap_sentence(df):
    """Footnote describing the gaps listed in coverage_gaps.csv."""
    gaps = coverage_gaps(df)
    order = df.groupby("quarter_label")["period_start"].min().sort_values().index
    first = order[0]
    boundary, internal, mismatch = [], [], []
    for row in gaps.itertuples():
        if row.first_quarter != first:
            boundary.append(f"{row.park.title()} avant {row.first_quarter}")
        for label, why in re.findall(r"(\S+): (\S+)", row.gap_reasons):
            if why == "no_rows":
                internal.append(f"{row.park.title()} {label}")
            elif why == "total_mismatch":
                mismatch.append(f"{row.park.title()} {label}")
    parts = ["Part calculée sur les parcs présents au trimestre."]
    if boundary:
        parts.append(
            "Segments absents en amont, donc exclus : "
            + ", ".join(boundary) + "."
        )
    if internal:
        parts.append("Trous internes exclus : " + ", ".join(internal) + ".")
    if mismatch:
        parts.append(
            "Conservés via leurs composantes (total_mismatch) : "
            + ", ".join(mismatch) + "."
        )
    missing = missing_sentence(df).strip()
    if missing:
        parts.append(missing)
    return " ".join(parts)


def fig04_top_parks(df):
    top = park_totals(df).head(15)
    types = df.groupby(["park_id", "crime_type"])["count"].sum().unstack(fill_value=0)
    types = types.reindex(top["park_id"])
    top = top.iloc[::-1]
    types = types.iloc[::-1]
    fig, ax = plt.subplots(figsize=(10, 7))
    left = np.zeros(len(top))
    for i, crime_type in enumerate(types.columns):
        values = types[crime_type].values
        ax.barh(top["park"], values, left=left, label=crime_type,
                color=OKABE_ITO[i])
        left += values
    totals = quarterly_totals(df)
    ax.set_xlabel(
        f"Nombre de crimes ({totals['quarter_label'].iloc[0]}–"
        f"{totals['quarter_label'].iloc[-1]})"
    )
    ax.set_title(f"Top {len(top)} des parcs par nombre total de crimes")
    ax.legend(ncol=4, fontsize=7, loc="lower right")
    fig.text(0.01, 0.01, anomaly_note(), fontsize=6, color="#555555")
    _save(fig, "fig04_top_parks.png")


def fig05_rate_per_100acres(df):
    table = borough_rate_table(df).iloc[::-1]
    labels = [
        f"{b} (combiné)" if b == "BROOKLYN/QUEENS" else b for b in table.index
    ]
    fig, ax = plt.subplots(figsize=FIGSIZE)
    bars = ax.barh(labels, table["rate_per_100_acres"], color=OKABE_ITO[0])
    for bar, (_, row) in zip(bars, table.iterrows()):
        ax.text(bar.get_width(), bar.get_y() + bar.get_height() / 2,
                f" {row['rate_per_100_acres']:.1f} pour 100 acres "
                f"({int(row['total_crimes'])} crimes)",
                va="center", fontsize=8)
    ax.set_xlabel("Crimes pour 100 acres")
    ax.set_title("Taux de criminalité par borough pour 100 acres")
    ax.set_xlim(0, table["rate_per_100_acres"].max() * 1.35)
    combined = table.loc["BROOKLYN/QUEENS"]
    fig.text(0.01, 0.01,
             "Taux = crimes des parcs dotés d'une surface / somme de leurs "
             "acres (dernière valeur connue) x 100 ; les crimes des parcs sans "
             "surface sont exclus et comptés à part (rate_by_borough.csv). "
             f"BROOKLYN/QUEENS (combiné) : {int(combined['parks'])} parcs dans "
             f"la source, {int(combined['parks_with_crimes'])} avec au moins "
             "un crime.",
             fontsize=7, color="#555555")
    _save(fig, "fig05_rate_per_100acres.png")


def fig06_zero_share(df):
    share = zero_share_by_quarter(df)
    x = np.arange(len(share))
    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax.plot(x, share.values, color=OKABE_ITO[0], linewidth=1.5, marker="o",
            markersize=2.5)
    ticks = x[::4]
    ax.set_xticks(ticks)
    ax.set_xticklabels(share.index[ticks], rotation=45, ha="right")
    ax.set_xlabel("Trimestre")
    ax.set_ylabel("Parcs sans crime (%)")
    ax.set_title("Part des parcs sans aucun crime majeur par trimestre")
    ax.set_ylim(0, 100)
    fig.text(0.01, 0.01, coverage_gap_sentence(df),
             fontsize=7, color="#555555", wrap=True)
    _save(fig, "fig06_zero_share.png")


# --------------------------------------------------------------------------
# Tables and metrics
# --------------------------------------------------------------------------

def source_sensitivity(df):
    """Both city totals for each flagged TOTAL mismatch.

    city_total_from_components counts the seven kept components (what the
    pipeline publishes); city_total_using_recorded_total would follow the
    workbook's own TOTAL line instead.
    """
    columns = [
        "park", "quarter", "total_recorded", "sum_components",
        "city_total_from_components", "city_total_using_recorded_total",
    ]
    path = TABLE_DIR / "source_anomalies.csv"
    if not path.exists():
        return pd.DataFrame(columns=columns)
    flags = pd.read_csv(path)
    city = int(df["count"].sum())
    rows = []
    for entry in flags[flags["kind"] == "total_mismatch"].itertuples():
        quarter = re.search(r"q(\d)-(\d{4})\.xlsx$", entry.workbook)
        label = f"{quarter.group(2)}Q{quarter.group(1)}"
        cell = df[df["park"].eq(entry.park) & df["quarter_label"].eq(label)]
        components = int(cell["count"].sum())
        recorded = int(entry.total_recorded)
        rows.append({
            "park": entry.park,
            "quarter": label,
            "total_recorded": recorded,
            "sum_components": components,
            "city_total_from_components": city,
            "city_total_using_recorded_total": city - components + recorded,
        })
    return pd.DataFrame(rows, columns=columns)


def write_tables(df):
    top = park_totals(df).head(15)
    types = df.groupby(["park_id", "crime_type"])["count"].sum().unstack(fill_value=0)
    top = top.assign(
        **{t: top["park_id"].map(types[t]) for t in types.columns}
    ).rename(columns={"count": "total"})
    top.to_csv(TABLE_DIR / "top_parks.csv", index=False)

    counts = borough_type_counts(df)
    share = counts.div(counts.sum(axis=1), axis=0) * 100
    long = (
        counts.stack().rename("crimes").reset_index()
        .merge(share.stack().rename("share_pct").reset_index(),
               on=["borough", "crime_type"])
        .sort_values(["borough", "crime_type"])
    )
    long.to_csv(TABLE_DIR / "borough_type_share.csv", index=False)

    rate = borough_rate_table(df).reset_index()
    rate.to_csv(TABLE_DIR / "rate_by_borough.csv", index=False)

    coverage_gaps(df).to_csv(TABLE_DIR / "coverage_gaps.csv", index=False)
    source_sensitivity(df).to_csv(
        TABLE_DIR / "source_anomaly_sensitivity.csv", index=False
    )

    totals = quarterly_totals(df)
    totals["year"] = totals["period_start"].dt.year
    totals["quarter_of_year"] = totals["quarter_label"].str[-1].astype(int)
    prior = totals.set_index(["year", "quarter_of_year"])["crimes"]
    rows = []
    for row in totals.itertuples():
        key = (row.year - 1, row.quarter_of_year)
        if key in prior.index:
            previous = float(prior.loc[key])
            rows.append({
                "quarter": row.quarter_label,
                "crimes": int(row.crimes),
                "prior_year_crimes": int(previous),
                "yoy_change": int(row.crimes - previous),
                "yoy_pct": (row.crimes - previous) / previous * 100.0
                if previous else 0.0,
            })
    pd.DataFrame(rows).to_csv(TABLE_DIR / "yoy_changes.csv", index=False)


def compute_stats(df):
    totals = quarterly_totals(df)
    peak = totals.loc[totals["crimes"].idxmax()]

    counts = borough_type_counts(df)
    statistic, p_value, dof, expected = chi_square(counts.values)
    n = int(counts.values.sum())

    yoy = latest_complete_yoy(df, totals)
    zero_share = zero_share_by_quarter(df)

    park_sum = df.groupby("park_id")["count"].sum()
    parks_total = int(park_sum.size)
    parks_hit = int((park_sum > 0).sum())

    rows_total = int(len(df))
    zero_rows = int((df["count"] == 0).sum())
    missing = missing_quarters(df)
    park_quarters = int(df[["quarter_label", "park"]].drop_duplicates().shape[0])
    missing_columns = missing_column_rows(df)

    stats = {
        "total_crimes": n,
        "peak_quarter": str(peak["quarter_label"]),
        "peak_quarter_crimes": int(peak["crimes"]),
        "chi2_statistic": round(statistic, 6),
        "chi2_dof": dof,
        "chi2_p_value": p_value,
        "chi2_p_display": p_value_display(p_value),
        "chi2_min_expected": round(float(expected.min()), 6),
        "chi2_assumption":
            "expected counts below 5 in some cells; interpret V as descriptive",
        "cramers_v": round(cramers_v(statistic, n, counts.shape), 6),
        **{k: (round(v, 6) if isinstance(v, float) else v)
           for k, v in yoy.items()},
        "parks_total": parks_total,
        "parks_ever_hit": parks_hit,
        "share_parks_ever_hit_pct": round(parks_hit / parks_total * 100, 2),
        "rows_total": rows_total,
        "park_quarters": park_quarters,
        "zero_rows": zero_rows,
        "share_zero_rows_pct": round(zero_rows / rows_total * 100, 2),
        "zero_share_mean_pct": round(float(zero_share.mean()), 2),
        "quarters_total": int(len(totals)),
        "first_quarter": str(totals["quarter_label"].iloc[0]),
        "last_quarter": str(totals["quarter_label"].iloc[-1]),
        "missing_quarter": missing[0] if missing else None,
        "missing_quarters": missing,
        "crime_types": sorted(df["crime_type"].unique()),
        "missing_column_quarters": sorted(
            missing_columns["quarter_label"].unique()
        ),
        "missing_column_types": sorted(missing_columns["crime_type"].unique()),
        "late_parks": late_parks(df),
        "source_anomalies": source_anomaly_entries(),
        "null_count_rule": null_rule(df),
        "null_count_rows": int(df["count"].isna().sum()),
        "rate_per_100_acres_formula":
            "sum(count of parks with acreage) / sum(latest size_acres of "
            "those parks) * 100; excluded crime volume reported",
        "source_anomaly": " ; ".join(
            f"{entry['quarter']} {entry['park']}: TOTAL recorded "
            f"{entry['total_recorded']} vs sum of components "
            f"{entry['sum_computed']}; components are kept and the row is "
            "excluded from TOTAL-based checks only"
            for entry in source_anomaly_entries()
        ) or "no TOTAL mismatch recorded",
        "missing_column_anomaly": missing_column_anomaly(df),
    }
    stats["source_anomaly"] += (
        " (outputs/tables/source_anomalies.csv, "
        "outputs/tables/source_anomaly_sensitivity.csv)"
    )
    return stats


# --------------------------------------------------------------------------

def main():
    for directory in (FIG_DIR, TABLE_DIR, METRIC_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    df = load_crimes()

    fig01_quarterly_trend(df)
    fig02_seasonality(df)
    fig03_borough_type_heatmap(df)
    fig04_top_parks(df)
    fig05_rate_per_100acres(df)
    fig06_zero_share(df)

    write_tables(df)

    stats = compute_stats(df)
    (METRIC_DIR / "eda_stats.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(stats, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
