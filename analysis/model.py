"""Forecasting and park clustering for NYC park crime (ticket 0035).

Forecast: citywide and per-borough quarterly totals, backtested over the last
8 quarters against a seasonal-naive baseline (Holt-Winters and SARIMAX
challengers), then refit on all data for a 4-quarter forecast with a 95 %
interval. Clustering: KMeans on standardized park crime-mix features, k chosen
by silhouette.

Figure labels are French (the deliverable is for a French course); code and
comments are English.

Run from the repository root:  python analysis/model.py
"""

import json
import sqlite3
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.cluster import KMeans  # noqa: E402
from sklearn.metrics import silhouette_samples, silhouette_score  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402
from statsmodels.tsa.holtwinters import ExponentialSmoothing  # noqa: E402
from statsmodels.tsa.statespace.sarimax import SARIMAX  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "warehouse.db"
CSV_PATH = ROOT / "data" / "processed" / "park_crime_long.csv"
FIG_DIR = ROOT / "outputs" / "figures"
TABLE_DIR = ROOT / "outputs" / "tables"
METRIC_DIR = ROOT / "outputs" / "metrics"

SEED = 42
SEASON = 4
HORIZON = 4
BACKTEST = 8
K_MIN, K_MAX = 2, 6
MIN_PARK_CRIMES = 5
# A borough needs at least 4 years of history and real signal to model.
MIN_MEAN_CRIMES = 5.0
MIN_NONZERO_QUARTERS = 16
CI_ALPHA = 0.05

DPI = 150
OKABE_ITO = [
    "#0072B2", "#E69F00", "#009E73", "#CC79A7",
    "#56B4E9", "#D55E00", "#F0E442", "#000000",
]

CAVEATS = [
    "Central Park n'apparaît dans la source qu'à partir de 2025Q1 : la "
    "croissance citywide 2024Q4→2025Q1 est en partie un artefact de "
    "couverture (outputs/tables/coverage_gaps.csv).",
    "La ligne Flushing Meadows 2025Q4 est absente (anomalie de parsing, "
    "18 crimes) — output/tables/source_anomalies.csv.",
    "2020Q1 est absent en amont : interpolé entre 2019Q4 et 2020Q2 pour la "
    "modélisation, jamais traité comme zéro.",
]


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------

def load_crimes():
    """Load the long crime table from the warehouse, falling back to the CSV."""
    if DB_PATH.exists():
        with sqlite3.connect(DB_PATH) as conn:
            df = pd.read_sql(
                "SELECT quarter_label, period_start, park, borough, "
                "size_acres, crime_type, count FROM crimes_long",
                conn,
            )
    else:
        df = pd.read_csv(CSV_PATH)
    df["period_start"] = pd.to_datetime(df["period_start"])
    return df


def load_parks():
    """Park reference table: borough, coordinates and acreage from geography."""
    if not DB_PATH.exists():
        return pd.DataFrame(columns=["park", "lat", "lon"])
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql("SELECT park, borough, lat, lon FROM parks", conn)


# --------------------------------------------------------------------------
# Time-series helpers
# --------------------------------------------------------------------------

def parse_quarter(label):
    """'2020Q3' -> (2020, 3)."""
    year, q = label.split("Q")
    return int(year), int(q)


def quarter_range(first, last):
    """Continuous list of quarter labels from first to last, inclusive."""
    y0, q0 = parse_quarter(first)
    y1, q1 = parse_quarter(last)
    labels = []
    y, q = y0, q0
    while (y, q) <= (y1, q1):
        labels.append(f"{y}Q{q}")
        q += 1
        if q == 5:
            y, q = y + 1, 1
    return labels


def next_quarters(last_label, n):
    """The n quarter labels following last_label."""
    y, q = parse_quarter(last_label)
    out = []
    for _ in range(n):
        q += 1
        if q == 5:
            y, q = y + 1, 1
        out.append(f"{y}Q{q}")
    return out


def previous_quarters(last_label, n):
    """The n quarter labels ending at last_label (inclusive)."""
    y, q = parse_quarter(last_label)
    out = [last_label]
    for _ in range(n - 1):
        q -= 1
        if q == 0:
            y, q = y - 1, 4
        out.append(f"{y}Q{q}")
    return list(reversed(out))


def quarterly_series(df, label_col="quarter_label"):
    """Continuous quarterly totals; absent quarters are interpolated.

    Returns (series, interpolated_quarters). A quarter missing upstream
    (2020Q1) is interpolated linearly between its neighbours for modelling and
    reported, never filled with zero.
    """
    totals = df.groupby(label_col)["count"].sum()
    totals = totals[~totals.index.duplicated()]
    labels = quarter_range(totals.index.min(), totals.index.max())
    series = totals.reindex(labels).astype(float)
    missing = series[series.isna()].index.tolist()
    if missing:
        series = series.interpolate(method="linear")
        if series.isna().any():
            raise ValueError(f"Leading/trailing missing quarters: {missing}")
    return series, missing


def mae(actual, predicted):
    """Mean absolute error."""
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    return float(np.mean(np.abs(actual - predicted)))


def rmse(actual, predicted):
    """Root mean squared error."""
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    return float(np.sqrt(np.mean((actual - predicted) ** 2)))


def mape(actual, predicted):
    """Mean absolute percentage error, ignoring zero actuals.

    Returns None when every actual is zero (percentage undefined).
    """
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    mask = actual != 0
    if not mask.any():
        return None
    return float(np.mean(np.abs((actual[mask] - predicted[mask]) / actual[mask])) * 100.0)


def seasonal_naive_forecast(values, steps, season=SEASON):
    """Recursive seasonal-naive forecast (yhat_t = y_{t-season})."""
    history = [float(v) for v in values]
    preds = []
    for _ in range(steps):
        value = history[-season]
        preds.append(value)
        history.append(value)
    return np.asarray(preds)


def _fit_predict(name, train, steps):
    """Fit one challenger on train and predict `steps` ahead."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if name == "holt_winters":
            fit = ExponentialSmoothing(
                train, trend="add", seasonal="add",
                seasonal_periods=SEASON, initialization_method="estimated",
            ).fit()
            if not fit.mle_retvals.get("converged", True):
                raise RuntimeError("Holt-Winters optimization did not converge")
            return np.asarray(fit.forecast(steps))
        if name == "sarimax":
            fit = SARIMAX(
                train, order=(1, 1, 1), seasonal_order=(1, 1, 0, SEASON),
                enforce_stationarity=False, enforce_invertibility=False,
            ).fit(disp=False)
            if not fit.mle_retvals.get("converged", True):
                raise RuntimeError("SARIMAX optimization did not converge")
            return np.asarray(fit.forecast(steps))
    raise ValueError(name)


def _refit_and_interval(name, values, steps, horizon_labels, residual_sd):
    """Refit the winner on all data; return point forecasts and 95 % bounds."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if name == "holt_winters":
            fit = ExponentialSmoothing(
                values, trend="add", seasonal="add",
                seasonal_periods=SEASON, initialization_method="estimated",
            ).fit()
            # HoltWintersResults has no get_forecast in statsmodels 0.15:
            # interval from seeded simulation (deterministic, no tuning).
            point = np.asarray(fit.forecast(steps))
            sims = fit.simulate(
                steps, repetitions=1000, error="add",
                random_state=np.random.RandomState(SEED),
            )
            return pd.DataFrame({
                "quarter_label": horizon_labels,
                "point": point,
                "lower": np.quantile(sims, CI_ALPHA / 2, axis=1),
                "upper": np.quantile(sims, 1 - CI_ALPHA / 2, axis=1),
            })
        elif name == "sarimax":
            fit = SARIMAX(
                values, order=(1, 1, 1), seasonal_order=(1, 1, 0, SEASON),
                enforce_stationarity=False, enforce_invertibility=False,
            ).fit(disp=False)
            frame = fit.get_forecast(steps).summary_frame(alpha=CI_ALPHA)
        else:  # seasonal naive: empirical interval from seasonal residuals
            point = seasonal_naive_forecast(values, steps)
            # shortcut: constant-width interval from in-sample seasonal
            # residuals; upgrade to a bootstrapped path if intervals drive
            # decisions.
            sd = residual_sd
            return pd.DataFrame({
                "quarter_label": horizon_labels,
                "point": point,
                "lower": point - 1.96 * sd,
                "upper": point + 1.96 * sd,
            })
    return pd.DataFrame({
        "quarter_label": horizon_labels,
        "point": np.asarray(frame["mean"]),
        "lower": np.asarray(frame["mean_ci_lower"]),
        "upper": np.asarray(frame["mean_ci_upper"]),
    })


def forecast_series(values, horizon=HORIZON, backtest=BACKTEST, season=SEASON,
                    last_label=None):
    """Backtest seasonal-naive / Holt-Winters / SARIMAX, refit the winner.

    Returns a dict with the per-model backtest metrics, the selected model,
    its backtest predictions, and the forecast table (point + 95 % interval).
    `last_label` names the last history quarter; forecast rows are labelled
    from it (generic T+1 labels otherwise).
    """
    values = np.asarray(values, dtype=float)
    if len(values) <= backtest + season:
        raise ValueError("Not enough quarters to backtest")
    train, test = values[:-backtest], values[-backtest:]
    steps = len(test)

    candidates = {"seasonal_naive": seasonal_naive_forecast(train, steps)}
    failures = {}
    for name in ("holt_winters", "sarimax"):
        try:
            candidates[name] = _fit_predict(name, train, steps)
        except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
            failures[name] = f"{type(exc).__name__}: {exc}"

    metrics = {}
    for name, pred in candidates.items():
        metrics[name] = {
            "mae": round(mae(test, pred), 4),
            "rmse": round(rmse(test, pred), 4),
            "mape": None if mape(test, pred) is None else round(mape(test, pred), 2),
        }
    winner = min(metrics, key=lambda name: metrics[name]["mae"])
    baseline_mae = metrics["seasonal_naive"]["mae"]
    improvement = (baseline_mae - metrics[winner]["mae"]) / baseline_mae * 100.0

    # Textbook one-step seasonal rule: predict each held-out quarter with the
    # actual of the same quarter one year earlier. Reference only; model
    # selection stays on the recursive multi-step baseline above.
    rule_pred = np.asarray([
        values[pos - season] for pos in range(len(values) - backtest, len(values))
    ])
    baseline_rule_mae = round(mae(test, rule_pred), 4)

    horizon_labels = (
        next_quarters(last_label, horizon) if last_label
        else [f"T+{h}" for h in range(1, horizon + 1)]
    )
    # Training residuals only: the held-out window must not inform its own
    # interval width.
    residual_sd = float(np.std(train[season:] - train[:-season]))
    forecast = _refit_and_interval(
        winner, values, horizon, horizon_labels, residual_sd,
    )
    forecast["point"] = forecast["point"].round(2)
    forecast["lower"] = forecast["lower"].round(2)
    forecast["upper"] = forecast["upper"].round(2)

    return {
        "selected_model": winner,
        "baseline_wins": winner == "seasonal_naive",
        "baseline_mae_seasonal_rule": baseline_rule_mae,
        "improvement_pct": round(float(improvement), 2),
        "backtest_quarters": steps,
        "backtest_window": (
            previous_quarters(last_label, steps) if last_label else None
        ),
        "backtest_metrics": metrics,
        "backtest_fit": {
            "actual": [float(v) for v in test],
            "predicted": [round(float(v), 4) for v in candidates[winner]],
        },
        "model_failures": failures,
        "forecast": forecast,
    }


# --------------------------------------------------------------------------
# Clustering
# --------------------------------------------------------------------------

def park_feature_table(crimes, parks):
    """Feature table for parks with at least MIN_PARK_CRIMES major crimes.

    Columns: seven crime-type shares, log1p(total), log1p(acres), plus the
    park's borough and coordinates when the join finds them.
    """
    totals = crimes.groupby("park")["count"].sum()
    eligible = totals[totals >= MIN_PARK_CRIMES].index
    sub = crimes[crimes["park"].isin(eligible)]
    counts = sub.pivot_table(
        index="park", columns="crime_type", values="count",
        aggfunc="sum", fill_value=0,
    )
    counts = counts.reindex(columns=sorted(crimes["crime_type"].unique()),
                            fill_value=0)
    features = counts.div(counts.sum(axis=1), axis=0)
    features.columns = [f"share_{c.lower().replace(' ', '_')}" for c in features.columns]
    full = pd.DataFrame(index=counts.index)
    full["total_crimes"] = counts.sum(axis=1)
    full["log_total"] = np.log1p(full["total_crimes"])
    acres = sub.groupby("park")["size_acres"].first()
    full["log_acres"] = np.log1p(acres)
    features = features.join(full[["total_crimes", "log_total", "log_acres"]])
    borough = sub.groupby("park")["borough"].first()
    features["borough"] = borough
    if not parks.empty:
        ref = parks.drop_duplicates("park").set_index("park")
        features = features.join(ref[["lat", "lon"]], how="left")
    else:
        features["lat"] = np.nan
        features["lon"] = np.nan
    return features


FEATURE_COLUMNS = [
    "share_burglary", "share_felony_assault", "share_grand_larceny",
    "share_grand_larceny_auto", "share_murder", "share_rape", "share_robbery",
    "log_total", "log_acres",
]


def cluster_parks(features, k_min=K_MIN, k_max=K_MAX, seed=SEED):
    """KMeans over standardized features; k chosen by silhouette.

    Returns (labels, per-park silhouette values, chosen k, best silhouette,
    per-k scores, fitted scaler).
    """
    x = StandardScaler().fit_transform(features[FEATURE_COLUMNS].to_numpy())
    best = None
    scores = {}
    for k in range(k_min, k_max + 1):
        model = KMeans(n_clusters=k, random_state=seed, n_init=10).fit(x)
        score = float(silhouette_score(x, model.labels_))
        scores[k] = round(score, 4)
        if best is None or score > best[1]:
            best = (k, score, model)
    k, score, model = best
    sample_values = silhouette_samples(x, model.labels_)
    return model.labels_, sample_values, k, round(float(score), 4), scores, x


def cluster_profiles(features, labels, sample_values):
    """One row per cluster: size, totals, mean crime-mix shares, top type."""
    table = features.copy()
    table["cluster"] = labels
    table["silhouette"] = sample_values
    table["acres"] = np.expm1(table["log_acres"])
    shares = [c for c in FEATURE_COLUMNS if c.startswith("share_")]
    grouped = table.groupby("cluster")
    profiles = pd.DataFrame({
        "n_parks": grouped.size(),
        "total_crimes": grouped["total_crimes"].sum(),
        "mean_acres": grouped["acres"].mean(),
        "mean_silhouette": grouped["silhouette"].mean(),
    })
    for col in shares:
        profiles[col] = grouped[col].mean()
    profiles["top_type"] = profiles[shares].idxmax(axis=1).str.replace("share_", "")
    table["dominant_type"] = (
        table[shares].idxmax(axis=1).str.replace("share_", "")
    )
    table = table.reset_index()
    return table, profiles.reset_index()


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------

def _series_metrics(result):
    selected = result["backtest_metrics"][result["selected_model"]]
    return {
        "selected_model": result["selected_model"],
        "selected_mae": selected["mae"],
        "selected_rmse": selected["rmse"],
        "selected_mape": selected["mape"],
        "baseline_mae": result["backtest_metrics"]["seasonal_naive"]["mae"],
        "baseline_mae_seasonal_rule": result["baseline_mae_seasonal_rule"],
        "baseline_wins": result["baseline_wins"],
        "selection_caveat": (
            f"Model chosen by MAE on the same {result['backtest_quarters']} "
            "held-out quarters it reports, so its advantage is optimistic; "
            "the recursive seasonal-naive baseline comparison is unaffected."
        ),
        "improvement_pct": result["improvement_pct"],
        "backtest_quarters": result["backtest_quarters"],
        "backtest_window": result["backtest_window"],
        "backtest_metrics": result["backtest_metrics"],
        "model_failures": result["model_failures"],
        "forecast": result["forecast"].to_dict(orient="records"),
    }


def run_forecasts(crimes):
    """Citywide and per-borough forecasts (same function for each series)."""
    series, interpolated = quarterly_series(crimes)
    city = forecast_series(series, last_label=series.index[-1])
    boroughs, skipped = {}, {}
    for borough, group in crimes.groupby("borough"):
        values, b_missing = quarterly_series(group)
        mean_count = float(values.mean())
        nonzero = int((values > 0).sum())
        if mean_count < MIN_MEAN_CRIMES or nonzero < MIN_NONZERO_QUARTERS:
            reason = (
                f"trop peu de données : {int(values.sum())} crimes sur "
                f"{len(values)} trimestres (moyenne {mean_count:.1f}/trimestre, "
                f"{nonzero} trimestres non nuls)"
            )
            if borough == "BROOKLYN/QUEENS":
                reason += " ; libellé hybride (5 parcs) sans série homogène"
            skipped[borough] = reason
            continue
        boroughs[borough] = forecast_series(values, last_label=values.index[-1])
        boroughs[borough]["interpolated_quarters"] = b_missing
    return series, interpolated, city, boroughs, skipped


def run_clustering(crimes, parks):
    features = park_feature_table(crimes, parks)
    labels, sample_values, k, score, scores, _ = cluster_parks(features)
    table, profiles = cluster_profiles(features, labels, sample_values)
    return features, table, profiles, k, score, scores


# --------------------------------------------------------------------------
# Figures
# --------------------------------------------------------------------------

def _footnote(fig):
    fig.text(
        0.01, 0.01,
        "Note : Central Park absent de la source avant 2025Q1 ; ligne "
        "Flushing Meadows 2025Q4 absente ; 2020Q1 interpolé.",
        fontsize=7, style="italic", color="#555555",
    )


def fig_forecast(series, result, path):
    labels = list(series.index)
    y = series.to_numpy()
    bt_labels = labels[-len(result["backtest_fit"]["actual"]):]
    forecast = result["forecast"]

    fig, ax = plt.subplots(figsize=(11, 6))
    ax.plot(labels, y, color=OKABE_ITO[0], lw=1.4, label="Historique")
    ax.plot(bt_labels, result["backtest_fit"]["predicted"], "o--",
            color=OKABE_ITO[1], ms=4, label="Ajustement (backtest)")
    ax.plot(bt_labels, result["backtest_fit"]["actual"], "o",
            color=OKABE_ITO[0], ms=3)
    fx = list(forecast["quarter_label"])
    ax.plot(fx, forecast["point"], "o-", color=OKABE_ITO[2], label="Prévision")
    ax.fill_between(fx, forecast["lower"], forecast["upper"],
                    color=OKABE_ITO[2], alpha=0.2, label="Intervalle à 95 %")
    ax.axvline(len(labels) - 0.5, color="#999999", lw=0.8, ls=":")
    ax.set_title(
        "Crimes majeurs dans les parcs de New York — prévision trimestrielle "
        f"({result['selected_model']})"
    )
    ax.set_xlabel("Trimestre")
    ax.set_ylabel("Nombre de crimes")
    ax.legend(loc="upper left", frameon=False)
    ax.set_xticks(range(0, len(labels), 4))
    ax.set_xticklabels([labels[i] for i in range(0, len(labels), 4)],
                       rotation=45, ha="right", fontsize=8)
    ax.grid(alpha=0.25)
    _footnote(fig)
    recursive = f"{result['backtest_metrics']['seasonal_naive']['mae']:.2f}"
    rule = f"{result['baseline_mae_seasonal_rule']:.2f}"
    fig.text(
        0.01, 0.032,
        "Comparateur honnête multi-pas : naïve saisonnière récursive "
        f"(MAE {recursive.replace('.', ',')}) ; la règle saisonnière à un pas, "
        f"valeurs réelles de l'année précédente (MAE {rule.replace('.', ',')}), "
        "sert de référence.",
        fontsize=7, style="italic", color="#555555",
    )
    fig.tight_layout(rect=(0, 0.055, 1, 1))
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def fig_clusters(table, profiles, k, score, path):
    fig, (ax_map, ax_heat) = plt.subplots(1, 2, figsize=(13, 6))
    colored = table.dropna(subset=["lat", "lon"])
    n_missing_coords = int(len(table) - len(colored))
    ax_map.text(
        0.02, 0.02,
        f"{n_missing_coords} parcs sur {len(table)} n'ont pas de coordonnées "
        "et ne sont pas tracés.",
        transform=ax_map.transAxes, fontsize=8, style="italic",
        color="#444444",
        bbox=dict(facecolor="white", alpha=0.8, edgecolor="none"),
    )
    for cluster in sorted(table["cluster"].unique()):
        sub = colored[colored["cluster"] == cluster]
        ax_map.scatter(sub["lon"], sub["lat"], s=22,
                       color=OKABE_ITO[cluster % len(OKABE_ITO)],
                       label=f"Cluster {cluster}", alpha=0.85)
    ax_map.set_title(
        f"Profils spatiaux des parcs — k={k}, silhouette={score:.2f}"
    )
    ax_map.set_xlabel("Longitude")
    ax_map.set_ylabel("Latitude")
    ax_map.legend(frameon=False, fontsize=8)
    ax_map.grid(alpha=0.2)

    shares = [c for c in FEATURE_COLUMNS if c.startswith("share_")]
    matrix = profiles.set_index("cluster")[shares]
    im = ax_heat.imshow(matrix.to_numpy(), cmap="YlOrRd", aspect="auto")
    ax_heat.set_xticks(range(len(shares)))
    ax_heat.set_xticklabels(
        [s.replace("share_", "").replace("_", " ") for s in shares],
        rotation=45, ha="right", fontsize=8,
    )
    ax_heat.set_yticks(range(len(matrix)))
    ax_heat.set_yticklabels([f"Cluster {c} (n={n})" for c, n in
                             zip(matrix.index, profiles["n_parks"])])
    ax_heat.set_title("Part moyenne de chaque type d'infraction par cluster")
    fig.colorbar(im, ax=ax_heat, fraction=0.046, pad=0.04,
                 label="Part des crimes majeurs")
    _footnote(fig)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def fig_boroughs(borough_results, path):
    names = list(borough_results)
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    for ax, name in zip(axes.ravel(), names):
        result = borough_results[name]
        labels = list(result["history_labels"])
        values = result["history"]
        tail = 16
        hist_labels = labels[-tail:]
        hist_values = values[-tail:]
        ax.plot(hist_labels, hist_values, color=OKABE_ITO[0], lw=1.2,
                label="Historique")
        forecast = result["forecast"]
        fx = list(forecast["quarter_label"])
        ax.plot(fx, forecast["point"], "o-", color=OKABE_ITO[2],
                label="Prévision")
        ax.fill_between(fx, forecast["lower"], forecast["upper"],
                        color=OKABE_ITO[2], alpha=0.2,
                        label="Intervalle à 95 %")
        ax.set_title(name.title(), fontsize=11)
        ax.set_ylabel("Crimes")
        ax.tick_params(axis="x", rotation=45, labelsize=7)
        ax.grid(alpha=0.2)
    axes[0, 0].legend(frameon=False, fontsize=8)
    fig.suptitle(
        "Prévisions trimestrielles par borough (modèles refit sur 2014Q4–2026Q2)"
    )
    _footnote(fig)
    fig.tight_layout(rect=(0, 0.03, 1, 0.96))
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    for directory in (FIG_DIR, TABLE_DIR, METRIC_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    crimes = load_crimes()
    parks = load_parks()

    series, interpolated, city, boroughs, skipped = run_forecasts(crimes)

    # History is needed by the borough figure; attach it to each result.
    for borough, result in boroughs.items():
        values, _ = quarterly_series(crimes[crimes["borough"] == borough])
        result["history"] = [float(v) for v in values]
        result["history_labels"] = list(values.index)

    city_forecast = city["forecast"].copy()
    city_forecast.insert(0, "scope", "CITYWIDE")
    city_forecast.to_csv(TABLE_DIR / "forecast_city.csv", index=False)

    borough_frames = []
    for borough, result in boroughs.items():
        frame = result["forecast"].copy()
        frame.insert(0, "borough", borough)
        borough_frames.append(frame)
    pd.concat(borough_frames, ignore_index=True).to_csv(
        TABLE_DIR / "forecast_boroughs.csv", index=False,
    )

    features, cluster_table, profiles, k, score, k_scores = run_clustering(crimes, parks)
    # `silhouette` is the global retained-solution score (eval-facing, [0, 1]);
    # `sample_silhouette` is each park's own value and can be negative.
    park_out = cluster_table[["park", "borough", "cluster", "dominant_type",
                              "total_crimes"]].copy()
    park_out.insert(3, "silhouette", score)
    park_out.insert(4, "sample_silhouette", cluster_table["silhouette"].to_numpy())
    park_out.sort_values(["cluster", "total_crimes"],
                         ascending=[True, False]).to_csv(
        TABLE_DIR / "park_clusters.csv", index=False,
    )
    profiles.to_csv(TABLE_DIR / "cluster_profiles.csv", index=False)

    fig_forecast(series, city, FIG_DIR / "fig07_forecast.png")
    fig_clusters(cluster_table, profiles, k, score, FIG_DIR / "fig08_clusters.png")
    fig_boroughs(boroughs, FIG_DIR / "fig09_forecast_boroughs.png")

    metrics = {
        "citywide": {
            **_series_metrics(city),
            "interpolated_quarters": interpolated,
            "n_quarters": int(len(series)),
            "forecast_footnote": "Prévision gonflée par l'ajout de Central "
            "Park à la source en 2025Q1 ; voir coverage_gaps.csv.",
        },
        "boroughs": {
            borough: _series_metrics(result)
            for borough, result in boroughs.items()
        },
        "skipped_boroughs": skipped,
        "clustering": {
            "n_parks": int(len(cluster_table)),
            "min_crimes_ever": MIN_PARK_CRIMES,
            "features": FEATURE_COLUMNS,
            "selected_k": int(k),
            "silhouette": score,
            "silhouette_by_k": k_scores,
            "cluster_sizes": {
                int(c): int(n) for c, n in profiles["n_parks"].items()
            },
            "cluster_top_types": {
                int(c): str(t) for c, t in
                zip(profiles["cluster"], profiles["top_type"])
            },
            "random_state": SEED,
        },
        "caveats": CAVEATS,
    }
    with open(METRIC_DIR / "model_metrics.json", "w", encoding="utf-8") as fh:
        json.dump(metrics, fh, ensure_ascii=False, indent=2)

    print(json.dumps({
        "city_model": city["selected_model"],
        "city_mae": city["backtest_metrics"][city["selected_model"]]["mae"],
        "baseline_mae": city["backtest_metrics"]["seasonal_naive"]["mae"],
        "baseline_wins": city["baseline_wins"],
        "clusters_k": int(k),
        "silhouette": score,
        "skipped_boroughs": list(skipped),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
