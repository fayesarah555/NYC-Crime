"""Export the Python pipeline to compact static JSON for app/web (ticket 0038).

Reads data/warehouse.db + outputs/ and writes the six files named in the
ticket's rd.md to app/web/public/data/ (or --out). Numbers are copied from the
existing artefacts, never recomputed with a different definition.

Exits non-zero when an invariant breaks (per-park total vs type sum, city
series total, payload budget).

Run from the repository root:  python export/export_web.py
"""

import argparse
import json
import shutil
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "warehouse.db"
TABLE_DIR = ROOT / "outputs" / "tables"
METRIC_DIR = ROOT / "outputs" / "metrics"
DEFAULT_OUT = ROOT / "app" / "web" / "public" / "data"

MAX_PAYLOAD_BYTES = 2 * 1024 * 1024
# Boroughs with enough history to be modelled by analysis/model.py.
BOROUGH_SERIES = ["BRONX", "BROOKLYN", "MANHATTAN", "QUEENS"]
# French rendering of metrics["citywide"]["selection_caveat"]; the model keeps
# the English string as data, the UI shows this one.
SELECTION_CAVEAT_FR = (
    "Modèle choisi sur le MAE calculé sur les 8 mêmes trimestres de validation "
    "qu'il rapporte : son avantage est donc optimiste ; la comparaison avec la "
    "baseline naïve saisonnière récursive n'est pas affectée."
)
FILES = (
    "meta.json", "parks.json", "series.json",
    "borough_type.json", "forecast.json", "clusters.json",
)


def fail(message):
    """Abort the export with a non-zero exit code."""
    raise SystemExit(f"export_web: {message}")


def load():
    """Crime long table and park reference table from the warehouse."""
    if not DB_PATH.exists():
        fail(f"missing {DB_PATH}; run `make warehouse` first")
    with sqlite3.connect(DB_PATH) as conn:
        crimes = pd.read_sql(
            "SELECT quarter_label, period_start, park, borough, size_acres, "
            "crime_type, count FROM crimes_long",
            conn,
        )
        parks_ref = pd.read_sql("SELECT park, lat, lon FROM parks", conn)
    return crimes, parks_ref


def build_parks(crimes, parks_ref):
    """One row per park with at least one crime (792), type counts included."""
    per_type = (
        crimes.groupby(["park", "crime_type"])["count"].sum()
        .unstack(fill_value=0).sort_index(axis=1)
    )
    per_park = crimes.groupby("park").agg(
        total=("count", "sum"),
        borough=("borough", "first"),
        acres=("size_acres", "first"),
    )
    geo = parks_ref.drop_duplicates("park").set_index("park")
    clusters = pd.read_csv(TABLE_DIR / "park_clusters.csv")
    clusters = clusters.drop_duplicates("park").set_index("park")

    rows = []
    for park, meta in per_park.iterrows():
        total = int(meta["total"])
        if total <= 0:
            continue  # zero-crime parks stay out; the map filters them
        counts = {t: int(v) for t, v in per_type.loc[park].items()}
        if total != sum(counts.values()):
            fail(f"{park}: total {total} != sum of types {sum(counts.values())}")
        lat = geo.at[park, "lat"] if park in geo.index else None
        lon = geo.at[park, "lon"] if park in geo.index else None
        cluster = (
            int(clusters.at[park, "cluster"]) if park in clusters.index else None
        )
        rows.append({
            "park": park,
            "borough": meta["borough"],
            "lat": None if pd.isna(lat) else round(float(lat), 6),
            "lon": None if pd.isna(lon) else round(float(lon), 6),
            "acres": round(float(meta["acres"]), 3) if not pd.isna(meta["acres"]) else None,
            "total": total,
            "dominant_type": max(counts, key=counts.get),
            "cluster": cluster,
            "counts": counts,
        })
    rows.sort(key=lambda row: (-row["total"], row["park"]))
    return rows


def build_series(crimes, total_crimes):
    """Quarter labels, city totals, per-type city totals and borough series."""
    totals = (
        crimes.groupby("quarter_label", as_index=False)
        .agg(period_start=("period_start", "min"), crimes=("count", "sum"))
        .sort_values("period_start")
    )
    labels = totals["quarter_label"].tolist()
    city = [int(v) for v in totals["crimes"]]
    if len(labels) != 46:
        fail(f"expected 46 quarter labels, got {len(labels)}")
    if sum(city) != total_crimes:
        fail(f"city series sums to {sum(city)}, expected {total_crimes}")
    by_type = (
        crimes.groupby(["crime_type", "quarter_label"])["count"].sum()
        .unstack(fill_value=0).reindex(columns=labels, fill_value=0)
        .sort_index()
    )
    city_by_type = {
        crime_type: [int(v) for v in row]
        for crime_type, row in by_type.iterrows()
    }
    for index, label in enumerate(labels):
        per_type = sum(values[index] for values in city_by_type.values())
        if per_type != city[index]:
            fail(f"{label}: per-type sum {per_type} != all-type {city[index]}")
    boroughs = {}
    for borough in BOROUGH_SERIES:
        series = (
            crimes[crimes["borough"] == borough]
            .groupby("quarter_label")["count"].sum()
            .reindex(labels, fill_value=0)
        )
        boroughs[borough] = [int(v) for v in series]
    return {
        "quarters": labels,
        "city": city,
        "city_by_type": city_by_type,
        "boroughs": boroughs,
    }


def build_borough_type(crimes):
    """Borough x crime-type counts, six borough labels kept as the source gives."""
    counts = (
        crimes.groupby(["borough", "crime_type"])["count"].sum()
        .unstack(fill_value=0).sort_index(axis=1)
    )
    rows = []
    for borough, row in counts.iterrows():
        by_type = {t: int(v) for t, v in row.items()}
        rows.append({
            "borough": borough,
            "total": int(row.sum()),
            "counts": by_type,
        })
    return {"crime_types": counts.columns.tolist(), "boroughs": rows}


def _points(frame):
    return [
        {
            "quarter": row.quarter_label,
            "point": float(row.point),
            "lower": float(row.lower),
            "upper": float(row.upper),
        }
        for row in frame.itertuples()
    ]


def build_forecast(metrics):
    """City and borough forecast points, intervals, model metrics, caveats."""
    city = pd.read_csv(TABLE_DIR / "forecast_city.csv")
    boroughs = pd.read_csv(TABLE_DIR / "forecast_boroughs.csv")
    keep = lambda block: {  # noqa: E731 - one-line projection
        key: value for key, value in block.items() if key != "forecast"
    }
    return {
        "city": _points(city),
        "boroughs": {
            b: _points(boroughs[boroughs["borough"] == b])
            for b in BOROUGH_SERIES
        },
        "metrics": {
            "city": {**keep(metrics["citywide"]), "selection_caveat_fr": SELECTION_CAVEAT_FR},
            "boroughs": {
                b: keep(block) for b, block in metrics["boroughs"].items()
            },
            "skipped_boroughs": metrics["skipped_boroughs"],
        },
        "caveats": metrics["caveats"],
    }


def build_clusters(metrics):
    """Cluster profiles and the per-park sample silhouette from the CSV."""
    profiles = pd.read_csv(TABLE_DIR / "cluster_profiles.csv")
    park_rows = pd.read_csv(TABLE_DIR / "park_clusters.csv")
    info = metrics["clustering"]
    return {
        "k": info["selected_k"],
        "silhouette": info["silhouette"],
        "features": info["features"],
        "profiles": [
            {
                "cluster": int(row.cluster),
                "n_parks": int(row.n_parks),
                "total_crimes": int(row.total_crimes),
                "mean_acres": round(float(row.mean_acres), 3),
                "mean_silhouette": round(float(row.mean_silhouette), 6),
                "top_type": row.top_type,
            }
            for row in profiles.itertuples()
        ],
        "parks": [
            {
                "park": row.park,
                "borough": row.borough,
                "cluster": int(row.cluster),
                "sample_silhouette": round(float(row.sample_silhouette), 6),
            }
            for row in park_rows.itertuples()
        ],
    }


def build_meta(parks, series, stats):
    """Periods, totals, sources and caveats for the KPI header."""
    geo = pd.read_csv(TABLE_DIR / "geo_coverage.csv").set_index("metric")["value"]
    matched = int(float(geo["matched_parks"]))
    parks_total = int(float(geo["parks"]))
    combined_parks = sum(
        1 for park in parks if park["borough"] == "BROOKLYN/QUEENS"
    )
    return {
        "generated_by": "export/export_web.py",
        "periods": {
            "first": series["quarters"][0],
            "last": series["quarters"][-1],
            "count": len(series["quarters"]),
            "missing": [stats["missing_quarter"]],
            "labels": series["quarters"],
        },
        "totals": {
            "crimes": stats["total_crimes"],
            "park_quarters": stats["rows_total"],
            "parks": stats["parks_total"],
            "parks_with_crimes": len(parks),
        },
        "geo": {
            "parks": parks_total,
            "matched": matched,
            "coverage_pct": round(float(geo["unweighted_coverage"]) * 100, 1),
            "weighted_coverage_pct": round(float(geo["weighted_coverage"]) * 100, 2),
        },
        "sources": [
            "NYC Park Crime Statistics, quarterly XLSX workbooks",
            "NYC Parks properties (coordinates)",
        ],
        "caveats": [
            "2020Q1 is absent from the source; it is never treated as zero.",
            "Central Park appears in the source only from 2025Q1: the "
            "2024Q4-2025Q1 citywide jump is partly a coverage artefact.",
            "Flushing Meadows 2025Q4 is excluded (TOTAL 17 vs sum 18) — see "
            "outputs/tables/source_anomalies.csv.",
            f"Coordinates matched for {matched} of {parks_total} parks "
            f"({round(matched / parks_total * 100, 1)}%); unmatched parks have "
            "null coordinates.",
            f"BROOKLYN/QUEENS is a combined source label for {combined_parks} "
            "parks; it is kept as its own borough value.",
        ],
        "caveats_fr": [
            "2020Q1 est absent de la source ; il n'est jamais traité comme zéro.",
            "Central Park n'apparaît dans la source qu'à partir de 2025Q1 : le "
            "saut citywide 2024Q4-2025Q1 est en partie un artefact de couverture.",
            "Flushing Meadows 2025Q4 est exclu (TOTAL 17 vs somme 18) — voir "
            "outputs/tables/source_anomalies.csv.",
            f"Coordonnées rapprochées pour {matched} parcs sur {parks_total} "
            f"({round(matched / parks_total * 100, 1)} %) ; les parcs non "
            "rapprochés ont des coordonnées nulles.",
            f"BROOKLYN/QUEENS est un libellé combiné de la source pour "
            f"{combined_parks} parcs ; il est conservé comme valeur "
            "d'arrondissement à part entière.",
        ],
    }


def publish(out, blobs):
    """Swap the validated blobs into `out`; a failure leaves it untouched."""
    tmp = out.parent / (out.name + ".tmp")
    bak = out.parent / (out.name + ".bak")
    for stale in (tmp, bak):
        if stale.exists():
            shutil.rmtree(stale)
    tmp.mkdir(parents=True)
    for name, blob in blobs.items():
        (tmp / name).write_bytes(blob)
    if out.exists():
        out.rename(bak)
        try:
            tmp.rename(out)
        except BaseException:
            bak.rename(out)
            raise
        shutil.rmtree(bak)
    else:
        tmp.rename(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT,
        help=f"output directory (default: {DEFAULT_OUT})",
    )
    args = parser.parse_args(argv)

    stats = json.loads((METRIC_DIR / "eda_stats.json").read_text(encoding="utf-8"))
    crimes, parks_ref = load()
    metrics = json.loads(
        (METRIC_DIR / "model_metrics.json").read_text(encoding="utf-8")
    )

    series = build_series(crimes, stats["total_crimes"])
    parks = build_parks(crimes, parks_ref)
    if len(parks) != stats["parks_ever_hit"]:
        fail(f"{len(parks)} parks exported, expected {stats['parks_ever_hit']}")
    payloads = {
        "meta.json": build_meta(parks, series, stats),
        "parks.json": parks,
        "series.json": series,
        "borough_type.json": build_borough_type(crimes),
        "forecast.json": build_forecast(metrics),
        "clusters.json": build_clusters(metrics),
    }
    blobs = {
        name: json.dumps(
            payloads[name], ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        for name in FILES
    }
    sizes = {name: len(blob) for name, blob in blobs.items()}
    total = sum(sizes.values())
    if total >= MAX_PAYLOAD_BYTES:
        fail(f"payload {total} bytes exceeds the {MAX_PAYLOAD_BYTES}-byte budget")

    publish(args.out, blobs)
    print(json.dumps(
        {"out": str(args.out), "files": sizes, "total_bytes": total},
        indent=2,
    ))


if __name__ == "__main__":
    main()
