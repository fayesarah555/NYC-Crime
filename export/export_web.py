"""Export the Python pipeline to compact static JSON for app/web (ticket 0038).

Reads data/warehouse.db + outputs/ and writes the seven files named in the
ticket's rd.md to app/web/src/data/ (or --out), bundled into the build so the
browser receives exactly one copy. Numbers are copied from the existing
artefacts, never recomputed with a different definition.

Exits non-zero when an invariant breaks (per-park total vs type sum, city
series total, cube sums, payload budget).

Run from the repository root:  python export/export_web.py
"""

import argparse
import hashlib
import json
import math
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pandas as pd

import sys
import palette_data  # noqa: E402  (single palette for web, Streamlit, matplotlib)

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "warehouse.db"
TABLE_DIR = ROOT / "outputs" / "tables"
METRIC_DIR = ROOT / "outputs" / "metrics"
MANIFEST_PATH = ROOT / "data" / "raw" / "manifest.json"
SCHEMA_DIR = ROOT / "export" / "schemas"
DEFAULT_OUT = ROOT / "app" / "web" / "src" / "data"

MAX_PAYLOAD_BYTES = 2 * 1024 * 1024
# Bumped when the export pipeline changes; the payload schema moved to 3
# when cube keys became park_id and cells may carry null (missing column).
PIPELINE_VERSION = "1.0.0"
SCHEMA_VERSION = 3
# French rendering of metrics["citywide"]["selection_caveat"]; the model keeps
# the English string as data, the UI shows this one. The held-out window size
# is injected from the metrics, never typed here.
SELECTION_CAVEAT_FR = (
    "Modèle choisi sur le MAE moyen de {backtest_quarters} prévisions issues "
    "d'origines glissantes, avec une tolérance de 1 % vers le modèle le plus "
    "simple ; le MAE rapporté est celui de ces mêmes prévisions, donc son "
    "avantage reste optimiste, mais la comparaison avec la baseline naïve "
    "saisonnière récursive n'est pas affectée."
)
FILES = (
    "meta.json", "parks.json", "series.json",
    "borough_type.json", "forecast.json", "clusters.json", "cubes.json",
    "palette.json",
)
# Clipping caveat rebuilt from ci_alpha: a typed interval level would lie if
# the interval level ever changed.
INTERVAL_CAVEAT = {
    "en": (
        "The lower bound of the {level} % interval is clipped at 0 because a "
        "crime count cannot be negative. On rows flagged clipped, the "
        "interval is therefore one-sided/asymmetric and the true lower bound "
        "is not shown."
    ),
    "fr": (
        "La borne basse de l'intervalle à {level} % est ramenée à 0 car un "
        "nombre de crimes ne peut pas être négatif. Sur les lignes marquées "
        "« clipped », l'intervalle est donc unilatéral/asymétrique et sa "
        "vraie borne basse n'est pas représentée."
    ),
}


def interval_caveat(metrics):
    """Clipping caveat (en, fr) whose level follows metrics["ci_alpha"]."""
    level = round((1 - metrics["ci_alpha"]) * 100)
    return {
        lang: text.format(level=level) for lang, text in INTERVAL_CAVEAT.items()
    }


def fail(message):
    """Abort the export with a non-zero exit code."""
    raise SystemExit(f"export_web: {message}")


def documented_missing(stats):
    """Quarter labels eda_stats documents as absent from the source."""
    labels = stats.get("missing_quarters")
    if labels is not None:
        return list(labels)
    label = stats.get("missing_quarter")
    return [label] if label else []


def quarter_grid(first, last):
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


def load():
    """Crime long table and park reference table from the warehouse."""
    if not DB_PATH.exists():
        fail(f"missing {DB_PATH}; run `make warehouse` first")
    with sqlite3.connect(DB_PATH) as conn:
        crimes = pd.read_sql(
            "SELECT quarter_label, period_start, park, borough, size_acres, "
            "crime_type, count, count_missing, total_mismatch FROM crimes_long",
            conn,
        )
        parks_ref = pd.read_sql(
            "SELECT park, borough, park_id, lat, lon FROM parks", conn
        )
    ids = parks_ref[["park", "borough", "park_id"]].drop_duplicates()
    return crimes.merge(ids, on=["park", "borough"], how="left"), parks_ref


def _int_or_none(value):
    return None if pd.isna(value) else int(value)


def _type_cells(crimes, keys, crime_types):
    """Per-key type sums; min_count=1 keeps an all-NULL group NaN.

    Every source row emits all seven types, so NaN after the sum means the
    workbook had no such column: missing, never a silent 0.
    """
    sums = (
        crimes.groupby(keys + ["crime_type"])["count"].sum(min_count=1)
        .unstack("crime_type")
        .reindex(columns=crime_types)
        .sort_index(axis=1)
    )
    return sums


def load_park_risk():
    """Per-park risk table written by analysis/model.py, keyed by park_id."""
    path = TABLE_DIR / "park_risk.csv"
    if not path.exists():
        fail(f"missing {path}; run `make model` first")
    return pd.read_csv(path).drop_duplicates("park_id").set_index("park_id")


def _risk_fields(risk, park_id, park):
    """Risk columns copied verbatim; a park absent from the table is a bug."""
    if park_id not in risk.index:
        fail(f"{park}: absent from outputs/tables/park_risk.csv")
    row = risk.loc[park_id]
    rate = row["crimes_per_100_acres"]
    rank = row["risk_rank"]
    return {
        "crimes_per_100_acres": None if pd.isna(rate) else round(float(rate), 3),
        "risk_rank": None if pd.isna(rank) else int(rank),
        "coverage_era": str(row["coverage_era"]),
    }


def build_parks(crimes, parks_ref, risk):
    """One row per park_id with at least one crime, type counts included."""
    crime_types = sorted(crimes["crime_type"].unique())
    sums = _type_cells(crimes, ["park_id"], crime_types)
    per_park = crimes.groupby("park_id").agg(
        park=("park", "first"),
        total=("count", "sum"),
        borough=("borough", "first"),
        acres=("size_acres", "last"),
    )
    geo = parks_ref.drop_duplicates("park_id").set_index("park_id")
    clusters = pd.read_csv(TABLE_DIR / "park_clusters.csv")
    clusters = clusters.drop_duplicates("park_id").set_index("park_id")

    rows = []
    for park_id, meta in per_park.iterrows():
        total = int(meta["total"])
        if total <= 0:
            continue  # zero-crime parks stay out; the map filters them
        counts = {t: _int_or_none(sums.at[park_id, t]) for t in crime_types}
        rated = sum(value for value in counts.values() if value is not None)
        if total != rated:
            fail(f"{meta['park']}: total {total} != sum of types {rated}")
        lat = geo.at[park_id, "lat"] if park_id in geo.index else None
        lon = geo.at[park_id, "lon"] if park_id in geo.index else None
        cluster = (
            int(clusters.at[park_id, "cluster"])
            if park_id in clusters.index else None
        )
        rows.append({
            "park_id": park_id,
            "park": meta["park"],
            "borough": meta["borough"],
            "lat": None if pd.isna(lat) else round(float(lat), 6),
            "lon": None if pd.isna(lon) else round(float(lon), 6),
            "acres": round(float(meta["acres"]), 3) if not pd.isna(meta["acres"]) else None,
            "total": total,
            "dominant_type": max(
                counts, key=lambda t: counts[t] if counts[t] is not None else -1
            ),
            "cluster": cluster,
            "counts": counts,
            **_risk_fields(risk, park_id, meta["park"]),
        })
    rows.sort(key=lambda row: (-row["total"], row["park"]))
    return rows


def build_series(crimes, stats):
    """Quarter labels, city totals, per-type city totals and borough series."""
    totals = (
        crimes.groupby("quarter_label", as_index=False)
        .agg(period_start=("period_start", "min"), crimes=("count", "sum"))
        .sort_values("period_start")
    )
    labels = totals["quarter_label"].tolist()
    city = [int(v) for v in totals["crimes"]]
    expected = [
        label
        for label in quarter_grid(stats["first_quarter"], stats["last_quarter"])
        if label not in documented_missing(stats)
    ]
    if len(expected) != stats["quarters_total"]:
        fail(
            f"expected grid has {len(expected)} quarters, eda_stats says "
            f"{stats['quarters_total']}"
        )
    if labels != expected:
        absent = [label for label in expected if label not in set(labels)]
        extra = [label for label in labels if label not in set(expected)]
        fail(f"quarter labels break the grid: absent {absent}, unexpected {extra}")
    if sum(city) != stats["total_crimes"]:
        fail(f"city series sums to {sum(city)}, expected {stats['total_crimes']}")
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
    for borough in sorted(crimes["borough"].unique()):
        rows = crimes[crimes["borough"] == borough]
        # Validate the borough's own quarters before reindex(): reindex()
        # would relabel the result with `labels`, making a post-check vacuous.
        borough_quarters = sorted(rows["quarter_label"].unique())
        if borough_quarters != expected:
            absent = [label for label in expected if label not in set(borough_quarters)]
            extra = [label for label in borough_quarters if label not in set(expected)]
            fail(
                f"{borough}: quarter labels break the grid: absent {absent}, "
                f"unexpected {extra}"
            )
        series = (
            rows.groupby("quarter_label")["count"].sum()
            .reindex(labels, fill_value=0)
        )
        if int(series.sum()) != int(rows["count"].sum()):
            fail(
                f"{borough}: series sums to {int(series.sum())}, expected "
                f"{int(rows['count'].sum())}"
            )
        boroughs[borough] = [int(v) for v in series]
    return {
        "quarters": labels,
        "city": city,
        "city_by_type": city_by_type,
        "boroughs": boroughs,
    }


def build_cube(crimes, series, parks):
    """Sparse park_id x quarter x type cells; null means missing, not 0.

    Sums ignore null cells and are asserted at 0 tolerance.
    """
    crime_types = sorted(crimes["crime_type"].unique())
    if crime_types != sorted(series["city_by_type"]):
        fail(f"cube crime types {crime_types} != series types")
    quarter_order = {label: index for index, label in enumerate(series["quarters"])}
    wide = _type_cells(crimes, ["park_id", "quarter_label"], crime_types)
    cells = {}
    for (park_id, quarter), row in wide.iterrows():
        counts = [_int_or_none(row[crime_type]) for crime_type in crime_types]
        if any(counts):
            cells.setdefault(park_id, {})[quarter] = counts
    # Cell order follows the shared quarter index so the bundle is stable.
    parks_cube = {
        park_id: {
            quarter: quarter_cells[quarter]
            for quarter in sorted(quarter_cells, key=quarter_order.__getitem__)
        }
        for park_id, quarter_cells in cells.items()
    }

    totals = {row["park_id"]: row["total"] for row in parks}
    for park_id, quarter_cells in parks_cube.items():
        total = sum(
            value
            for counts in quarter_cells.values()
            for value in counts
            if value is not None
        )
        if total != totals.get(park_id):
            fail(f"cube {park_id}: {total} != parks.json total {totals.get(park_id)}")
    per_quarter = [0] * len(series["quarters"])
    per_type = dict.fromkeys(crime_types, 0)
    for quarter_cells in parks_cube.values():
        for quarter, counts in quarter_cells.items():
            per_quarter[quarter_order[quarter]] += sum(
                value for value in counts if value is not None
            )
            for crime_type, value in zip(crime_types, counts):
                if value is not None:
                    per_type[crime_type] += value
    if per_quarter != series["city"]:
        fail("cube quarter sums do not equal the city series")
    for crime_type, values in series["city_by_type"].items():
        if per_type[crime_type] != sum(values):
            fail(f"cube {crime_type} sum != city_by_type series")
    return {
        "quarters": series["quarters"],
        "crime_types": crime_types,
        "parks": parks_cube,
    }


def build_provenance():
    """generated_at, git_commit (dirty-marked) and the manifest digest."""
    digest = (
        hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest()
        if MANIFEST_PATH.exists()
        else "unknown"
    )
    dirty = False
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        commit = result.stdout.strip() or "unknown"
        status = subprocess.run(
            ["git", "-C", str(ROOT), "status", "--porcelain"],
            capture_output=True, text=True, check=True,
        )
        dirty = bool(status.stdout.strip())
        if dirty:
            commit = f"{commit}-dirty"
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
    provenance = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit": commit,
        "git_dirty": dirty,
        "source_manifest_sha256": digest,
    }
    if dirty:
        provenance["git_commit_note"] = {
            "fr": (
                "L'arbre de travail contenait des modifications non validées "
                "lors de l'export : ce commit ne contient pas ces artefacts."
            ),
            "en": (
                "The worktree had uncommitted changes at export time: this "
                "commit does not contain these artefacts."
            ),
        }
    return provenance


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


def check_cube_borough_type(cube, borough_type, parks):
    """Cube per-borough/type sums must equal borough_type.json (0 tolerance).

    Mirrors the browser-side assertion in app/web/src/lib/data.test.ts so a
    bad export fails here, before any file is written.
    """
    borough_of = {row["park_id"]: row["borough"] for row in parks}
    totals = {
        (row["borough"], crime_type): 0
        for row in borough_type["boroughs"]
        for crime_type in cube["crime_types"]
    }
    for park_id, cells in cube["parks"].items():
        borough = borough_of[park_id]
        for counts in cells.values():
            for crime_type, value in zip(cube["crime_types"], counts):
                if value is not None:
                    totals[(borough, crime_type)] += value
    for row in borough_type["boroughs"]:
        for crime_type in cube["crime_types"]:
            expected = row["counts"][crime_type]
            if totals[(row["borough"], crime_type)] != expected:
                fail(
                    f"cube {row['borough']} {crime_type} sums to "
                    f"{totals[(row['borough'], crime_type)]}, borough_type "
                    f"says {expected}"
                )


# JSON Schema's `number` accepts float("nan"), but JSON has no NaN and
# json.dumps would write a bare NaN that no browser can parse.
FINITE_NUMBER = jsonschema.Draft202012Validator.TYPE_CHECKER.redefine(
    "number",
    lambda checker, instance: (
        isinstance(instance, (int, float))
        and not isinstance(instance, bool)
        and math.isfinite(instance)
    ),
)
FINITE_VALIDATOR = jsonschema.validators.extend(
    jsonschema.Draft202012Validator, type_checker=FINITE_NUMBER
)


def assert_finite(value, path):
    """Reject any non-finite float anywhere in the payload tree."""
    if isinstance(value, float) and not math.isfinite(value):
        fail(f"{path}: non-finite number {value!r}")
    if isinstance(value, dict):
        for key, item in value.items():
            assert_finite(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_finite(item, f"{path}[{index}]")


def validate_payloads(payloads):
    """Validate every payload against export/schemas/<name>.schema.json."""
    for name in FILES:
        assert_finite(payloads[name], name)
        schema_path = SCHEMA_DIR / name.replace(".json", ".schema.json")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = FINITE_VALIDATOR(schema)
        errors = sorted(
            validator.iter_errors(payloads[name]),
            key=lambda error: list(error.path),
        )
        if errors:
            fail(f"{name} violates {schema_path.name}: {errors[0].message}")


def _points(frame):
    points = [
        {
            "quarter": row.quarter_label,
            "point": float(row.point),
            "lower": float(row.lower),
            "upper": float(row.upper),
            "clipped": bool(getattr(row, "clipped", False)),
        }
        for row in frame.itertuples()
    ]
    for point in points:
        if point["lower"] < 0:
            fail(
                f"{point['quarter']}: lower bound {point['lower']} is negative"
            )
    return points


def build_forecast(metrics):
    """City and borough forecast points, intervals, model metrics, caveats."""
    city = pd.read_csv(TABLE_DIR / "forecast_city.csv")
    boroughs = pd.read_csv(TABLE_DIR / "forecast_boroughs.csv")
    keep = lambda block: {  # noqa: E731 - one-line projection
        key: value for key, value in block.items() if key != "forecast"
    }
    eligible = list(metrics["boroughs"])  # forecast-eligible, per the model
    forecast_boroughs = {}
    for borough in eligible:
        points = _points(boroughs[boroughs["borough"] == borough])
        if not points:
            fail(
                f"{borough}: forecast-eligible in model_metrics.json but no "
                "rows in forecast_boroughs.csv"
            )
        forecast_boroughs[borough] = points
    payload = {
        "city": _points(city),
        "boroughs": forecast_boroughs,
        "metrics": {
            "city": {
                **keep(metrics["citywide"]),
                "selection_caveat_fr": SELECTION_CAVEAT_FR.format(
                    backtest_quarters=metrics["citywide"]["backtest_quarters"]
                ),
            },
            "boroughs": {
                b: keep(block) for b, block in metrics["boroughs"].items()
            },
            "skipped_boroughs": metrics["skipped_boroughs"],
        },
        "caveats": metrics["caveats"],
    }
    if metrics.get("interval_clipped_rows"):
        note = interval_caveat(metrics)
        payload["caveat"] = note["en"]
        payload["caveat_fr"] = note["fr"]
    return payload


def build_clusters(metrics, risk):
    """Cluster profiles and the per-park sample silhouette from the CSV."""
    profiles = pd.read_csv(TABLE_DIR / "cluster_profiles.csv")
    park_rows = pd.read_csv(TABLE_DIR / "park_clusters.csv")
    info = metrics["clustering"]
    names = (
        profiles["name"] if "name" in profiles else profiles["top_type"]
    )
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
                "name": str(name),
            }
            for row, name in zip(profiles.itertuples(), names)
        ],
        "parks": [
            {
                "park": row.park,
                "borough": row.borough,
                "cluster": int(row.cluster),
                "sample_silhouette": round(float(row.sample_silhouette), 6),
                "crimes_per_100_acres": _park_rate(risk, row.park_id),
            }
            for row in park_rows.itertuples()
        ],
    }


def _park_rate(risk, park_id):
    """Rate copied from park_risk.csv; null when the park has no rate."""
    if park_id not in risk.index:
        return None
    value = risk.at[park_id, "crimes_per_100_acres"]
    return None if pd.isna(value) else round(float(value), 3)


def _late_parks(crimes, series):
    """Parks whose first observed quarter is later than the dataset's first."""
    first = series["quarters"][0]
    firsts = (
        crimes.sort_values("period_start")
        .groupby("park_id")["quarter_label"].first()
    )
    names = crimes.groupby("park_id")["park"].first()
    return [
        (names[park_id], label)
        for park_id, label in firsts.items()
        if label != first
    ]


def _missing_columns(crimes):
    """Quarter labels and crime types whose column is absent from a workbook."""
    if "count_missing" not in crimes:
        return None
    rows = crimes[crimes["count_missing"].eq(1)]
    if rows.empty:
        return None
    return sorted(rows["quarter_label"].unique()), sorted(rows["crime_type"].unique())


def _total_mismatches(crimes):
    """Flagged TOTAL mismatches, with the workbook TOTAL when the table exists."""
    if "total_mismatch" not in crimes:
        return []
    rows = crimes[crimes["total_mismatch"].eq(1)]
    entries = [
        {
            "park": park,
            "quarter": quarter,
            "sum_computed": int(group["count"].sum()),
        }
        for (_, park, quarter), group in rows.groupby(
            ["park_id", "park", "quarter_label"]
        )
    ]
    path = TABLE_DIR / "source_anomaly_sensitivity.csv"
    if path.exists() and entries:
        sensitivity = pd.read_csv(path)
        for entry in entries:
            match = sensitivity[
                sensitivity["park"].eq(entry["park"])
                & sensitivity["quarter"].eq(entry["quarter"])
            ]
            if not match.empty:
                entry["total_recorded"] = int(match.iloc[0]["total_recorded"])
    return entries


def build_meta(parks, series, stats, metrics, provenance, parks_ref, crimes):
    """Periods, totals, provenance, sources and caveats for the KPI header."""
    geo = pd.read_csv(TABLE_DIR / "geo_coverage.csv").set_index("metric")["value"]
    matched = int(float(geo["matched_parks"]))
    parks_total = int(float(geo["parks"]))
    combined_source = int((parks_ref["borough"] == "BROOKLYN/QUEENS").sum())
    combined_with_crimes = sum(
        1 for park in parks if park["borough"] == "BROOKLYN/QUEENS"
    )
    missing = documented_missing(stats)
    late = _late_parks(crimes, series)
    mismatches = _total_mismatches(crimes)
    missing_columns = _missing_columns(crimes)

    caveats = []
    caveats_fr = []
    if missing:
        joined = ", ".join(missing)
        caveats.append(
            f"{joined} is absent from the source; it is never treated as zero."
        )
        caveats_fr.append(
            f"{joined} est absent de la source ; il n'est jamais traité comme "
            "zéro."
        )
    for name, label in late:
        index = series["quarters"].index(label)
        previous = series["quarters"][index - 1] if index else label
        caveats.append(
            f"{name.title()} appears in the source only from {label}: the "
            f"{previous}-{label} citywide jump is partly a coverage artefact."
        )
        caveats_fr.append(
            f"{name.title()} n'apparaît dans la source qu'à partir de {label} "
            f": le saut citywide {previous}-{label} est en partie un artefact "
            "de couverture."
        )
    for entry in mismatches:
        recorded = entry.get("total_recorded")
        total_en = (
            f"TOTAL {recorded} vs sum {entry['sum_computed']}"
            if recorded is not None
            else f"recorded TOTAL vs sum {entry['sum_computed']}"
        )
        total_fr = (
            f"TOTAL {recorded} vs somme {entry['sum_computed']}"
            if recorded is not None
            else f"TOTAL enregistré vs somme {entry['sum_computed']}"
        )
        caveats.append(
            f"{entry['park'].title()} {entry['quarter']}: {total_en}; its "
            "components are kept and flagged total_mismatch, excluded from "
            "TOTAL-based checks only: see outputs/tables/source_anomalies.csv."
        )
        caveats_fr.append(
            f"{entry['park'].title()} {entry['quarter']} : {total_fr} ; ses "
            "composantes sont conservées et flaggées total_mismatch, la ligne "
            "n'est exclue que des contrôles TOTAL : voir "
            "outputs/tables/source_anomalies.csv."
        )
    caveats.append(
        f"Coordinates matched for {matched} of {parks_total} parks "
        f"({round(matched / parks_total * 100, 1)}%); unmatched parks have "
        "null coordinates."
    )
    caveats_fr.append(
        f"Coordonnées rapprochées pour {matched} parcs sur {parks_total} "
        f"({round(matched / parks_total * 100, 1)} %) ; les parcs non "
        "rapprochés ont des coordonnées nulles."
    )
    caveats.append(
        f"BROOKLYN/QUEENS is a combined source label: {combined_source} "
        f"parks in the source, {combined_with_crimes} with at least one "
        "crime; it is kept as its own borough value."
    )
    caveats_fr.append(
        f"BROOKLYN/QUEENS est un libellé combiné de la source : "
        f"{combined_source} parcs dans la source, "
        f"{combined_with_crimes} avec au moins un crime ; il est conservé "
        "comme valeur d'arrondissement à part entière."
    )
    if missing_columns:
        quarters, types = missing_columns
        quarters_text = ", ".join(quarters)
        types_text = ", ".join(types)
        caveats.append(
            f"Workbooks {quarters_text} have no {types_text} column: those "
            "cells are null (missing), excluded from sums, never a measured "
            "zero."
        )
        caveats_fr.append(
            f"Les classeurs {quarters_text} n'ont pas de colonne {types_text} : "
            "ces cellules sont nulles (manquantes), exclues des sommes, jamais "
            "un zéro mesuré."
        )
    if metrics.get("interval_clipped_rows"):
        note = interval_caveat(metrics)
        caveats.append(note["en"])
        caveats_fr.append(note["fr"])
    meta = {
        "generated_by": "export/export_web.py",
        "generated_at": provenance["generated_at"],
        "git_commit": provenance["git_commit"],
        "git_dirty": provenance["git_dirty"],
        "pipeline_version": PIPELINE_VERSION,
        "source_manifest_sha256": provenance["source_manifest_sha256"],
        "schema_version": SCHEMA_VERSION,
        "quarters_total": len(series["quarters"]),
        "missing_quarters": documented_missing(stats),
        "ci_alpha": metrics["ci_alpha"],
        "periods": {
            "first": series["quarters"][0],
            "last": series["quarters"][-1],
            "count": len(series["quarters"]),
            "missing": documented_missing(stats),
            "labels": series["quarters"],
        },
        "totals": {
            "crimes": stats["total_crimes"],
            "park_quarters": int(
                crimes[["quarter_label", "park"]].drop_duplicates().shape[0]
            ),
            "long_rows": int(len(crimes)),
            "parks": stats["parks_total"],
            "parks_with_crimes": len(parks),
        },
        "geo": {
            "parks": parks_total,
            "matched": matched,
            "coverage_pct": round(float(geo["unweighted_coverage"]) * 100, 1),
            "weighted_coverage_pct": round(float(geo["weighted_coverage"]) * 100, 2),
        },
        "combined_borough": {
            "label": "BROOKLYN/QUEENS",
            "parks_source": combined_source,
            "parks_with_crimes": combined_with_crimes,
        },
        "sources": [
            "NYC Park Crime Statistics, quarterly XLSX workbooks",
            "NYC Parks properties (coordinates)",
        ],
        "source_links": [
            {
                "label": "NYPD, Park Crime Statistics",
                "url": "https://www.nyc.gov/site/nypd/stats/crime-statistics/park-crime-stats.page",
            },
            {
                "label": "NYC Parks Properties (Socrata)",
                "url": "https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve",
            },
            {
                "label": "Dépôt GitHub",
                "url": "https://github.com/youcisla/NYC-Crime",
            },
        ],
        "caveats": caveats,
        "caveats_fr": caveats_fr,
    }
    if "git_commit_note" in provenance:
        meta["git_commit_note"] = provenance["git_commit_note"]
    return meta


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

    series = build_series(crimes, stats)
    risk = load_park_risk()
    parks = build_parks(crimes, parks_ref, risk)
    if len(parks) != stats["parks_ever_hit"]:
        fail(f"{len(parks)} parks exported, expected {stats['parks_ever_hit']}")
    payloads = {
        "meta.json": build_meta(
            parks, series, stats, metrics, build_provenance(), parks_ref, crimes
        ),
        "parks.json": parks,
        "series.json": series,
        "borough_type.json": build_borough_type(crimes),
        "forecast.json": build_forecast(metrics),
        "clusters.json": build_clusters(metrics, risk),
        "cubes.json": build_cube(crimes, series, parks),
        "palette.json": palette_data.payload(),
    }
    check_cube_borough_type(
        payloads["cubes.json"], payloads["borough_type.json"], parks
    )
    validate_payloads(payloads)
    blobs = {
        name: json.dumps(
            payloads[name], ensure_ascii=False, separators=(",", ":"),
            allow_nan=False,
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
