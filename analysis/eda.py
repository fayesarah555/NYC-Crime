"""Exploratory analysis of NYC park crime.

Figures, tables and headline statistics for the report. Figure labels are
French (the deliverable is for a French course); code and comments are English.

Run from the repository root:  python analysis/eda.py
"""

import json
import math
import sqlite3
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
FIG_DIR = ROOT / "outputs" / "figures"
TABLE_DIR = ROOT / "outputs" / "tables"
METRIC_DIR = ROOT / "outputs" / "metrics"

DPI = 150
FIGSIZE = (10, 6)

# Okabe-Ito colorblind-safe palette.
OKABE_ITO = [
    "#0072B2", "#E69F00", "#009E73", "#CC79A7",
    "#56B4E9", "#D55E00", "#000000", "#F0E442",
]

MONTHS_FR = {1: "Janvier", 4: "Avril", 7: "Juillet", 10: "Octobre"}
ANOMALY_NOTE = (
    "Anomalie source : Flushing Meadows, 2025Q4 — TOTAL 17 vs somme 18 ; "
    "la ligne est exclue du warehouse (outputs/tables/source_anomalies.csv)."
)


# --------------------------------------------------------------------------
# Data loading and helpers
# --------------------------------------------------------------------------

def load_crimes():
    """Load the long crime table from the warehouse, falling back to the CSV."""
    if DB_PATH.exists():
        with sqlite3.connect(DB_PATH) as conn:
            df = pd.read_sql(
                "SELECT quarter_label, period_start, period_end, park, borough, "
                "size_acres, category, crime_type, count FROM crimes_long",
                conn,
            )
    else:
        df = pd.read_csv(CSV_PATH)
    df["period_start"] = pd.to_datetime(df["period_start"])
    return df


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


def borough_rate_table(df):
    """Crime rate per 100 acres by borough.

    Acres are taken once per distinct park so summing over crime types or
    quarters does not double-count a park's acreage.
    """
    crimes = df.groupby("borough")["count"].sum()
    parks = df.groupby("borough")["park"].nunique()
    acres = (
        df.groupby(["borough", "park"])["size_acres"].first()
        .groupby("borough").sum()
    )
    table = pd.DataFrame({
        "total_crimes": crimes,
        "parks": parks,
        "acres": acres,
    }).dropna()
    table["rate_per_100_acres"] = [
        rate_per_100_acres(r.total_crimes, r.acres) for r in table.itertuples()
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
        index="quarter_label", columns="park", values="count", aggfunc="sum",
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

    first_seen = df.groupby("park")["period_start"].min()
    new_parks = sorted(first_seen[first_seen >= pd.Timestamp(latest, 1, 1)].index)
    latest_rows = df[df["period_start"].dt.year == latest]
    new_crimes = int(latest_rows.loc[latest_rows["park"].isin(new_parks), "count"].sum())
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
             f"{yoy['yoy_change_pct']:+.2f} %). 2020Q1 absent des données "
             "source. " + ANOMALY_NOTE,
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
    fig.text(0.01, 0.01,
             "Moyennes T1/T3 calculées sur 11 trimestres, T2/T4 sur 12 : "
             "2020Q1 est absent des données source.",
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
    totals = df.groupby(["park", "borough"])["count"].sum().reset_index()
    return totals.sort_values("count", ascending=False)


def coverage_gaps(df):
    """Parks whose first or last appearance is not the dataset boundary."""
    first_bound = df["period_start"].min()
    last_bound = df["period_start"].max()
    first = df.groupby("park")["period_start"].min()
    last = df.groupby("park")["period_start"].max()
    total = df.groupby("park")["count"].sum()
    parks = first.index[(first > first_bound) | (last < last_bound)]
    qmap = df.drop_duplicates("period_start").set_index("period_start")["quarter_label"]
    return pd.DataFrame({
        "park": parks,
        "first_quarter": [qmap[s] for s in first.loc[parks]],
        "last_quarter": [qmap[s] for s in last.loc[parks]],
        "total_crimes": [int(total[p]) for p in parks],
    }).sort_values("park").reset_index(drop=True)


def fig04_top_parks(df):
    top = park_totals(df).head(15)
    types = df.groupby(["park", "crime_type"])["count"].sum().unstack(fill_value=0)
    types = types.reindex(top["park"])
    top = top.iloc[::-1]
    types = types.iloc[::-1]
    fig, ax = plt.subplots(figsize=(10, 7))
    left = np.zeros(len(top))
    for i, crime_type in enumerate(types.columns):
        values = types[crime_type].values
        ax.barh(top["park"], values, left=left, label=crime_type,
                color=OKABE_ITO[i])
        left += values
    ax.set_xlabel("Nombre de crimes (2014Q4–2026Q2)")
    ax.set_title("Top 15 des parcs par nombre total de crimes")
    ax.legend(ncol=4, fontsize=7, loc="lower right")
    fig.text(0.01, 0.01, ANOMALY_NOTE, fontsize=6, color="#555555")
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
    fig.text(0.01, 0.01,
             "Taux = somme des crimes du borough / somme des acres des parcs "
             "distincts x 100. BROOKLYN/QUEENS (combiné) : 5 parcs dont la "
             "valeur de borough est partagée entre Brooklyn et Queens.",
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
    fig.text(0.01, 0.01,
             "Part calculée sur les parcs présents au trimestre. Segments "
             "absents en amont, donc exclus : Central Park avant 2025Q1, "
             "Corona Health Sanctuary 2022Q2, Flushing Meadows 2025Q4. "
             "2020Q1 absent des données source.",
             fontsize=7, color="#555555", wrap=True)
    _save(fig, "fig06_zero_share.png")


# --------------------------------------------------------------------------
# Tables and metrics
# --------------------------------------------------------------------------

def write_tables(df):
    top = park_totals(df).head(15)
    types = df.groupby(["park", "crime_type"])["count"].sum().unstack(fill_value=0)
    top = top.assign(
        **{t: top["park"].map(types[t]) for t in types.columns}
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
    rate["note"] = rate["borough"].map(
        lambda b: "5 parks; borough value split between Brooklyn and Queens"
        if b == "BROOKLYN/QUEENS" else ""
    )
    rate.to_csv(TABLE_DIR / "rate_by_borough.csv", index=False)

    coverage_gaps(df).to_csv(TABLE_DIR / "coverage_gaps.csv", index=False)

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

    park_sum = df.groupby("park")["count"].sum()
    parks_total = int(park_sum.size)
    parks_hit = int((park_sum > 0).sum())

    rows_total = int(len(df))
    zero_rows = int((df["count"] == 0).sum())

    stats = {
        "total_crimes": n,
        "peak_quarter": str(peak["quarter_label"]),
        "peak_quarter_crimes": int(peak["crimes"]),
        "chi2_statistic": round(statistic, 6),
        "chi2_dof": dof,
        "chi2_p_value": p_value,
        "chi2_p_display": "p < 1e-200",
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
        "zero_rows": zero_rows,
        "share_zero_rows_pct": round(zero_rows / rows_total * 100, 2),
        "zero_share_mean_pct": round(float(zero_share.mean()), 2),
        "quarters_total": int(len(totals)),
        "first_quarter": str(totals["quarter_label"].iloc[0]),
        "last_quarter": str(totals["quarter_label"].iloc[-1]),
        "missing_quarter": "2020Q1",
        "rate_per_100_acres_formula":
            "sum(count) / sum(size_acres of distinct parks) * 100",
        "source_anomaly":
            "q4-2025 FLUSHING MEADOWS CORONA PARK: TOTAL recorded 17 vs "
            "sum 18, row excluded from the warehouse "
            "(outputs/tables/source_anomalies.csv)",
    }
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
