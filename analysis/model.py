"""Forecasting and park clustering for NYC park crime (ticket 0035, 0052).

Forecast: citywide and per-borough quarterly totals. The Central Park 2025Q1
coverage break is handled by a SARIMAX step dummy (`post_coverage`, 1 from the
quarter the park enters the source), with a consistent-perimeter sensitivity
that drops Central Park. Models are selected on the mean MAE of three rolling
four-quarter origins (1 % tie tolerance toward the simpler model) against
seasonal-naive, Holt-Winters, Poisson-GLM and log-SARIMAX challengers;
Diebold-Mariano (HLN) tests the winner against seasonal-naive, and empirical
interval coverage at the configured level is measured on the same origins.
City and borough
forecasts are reconciled bottom-up (modelled boroughs + a seasonal-naive
residual for skipped boroughs) before publication. Clustering: shrinkage-
smoothed CLR shares, KMeans by silhouette, with ARI stability, GMM/HDBSCAN
comparison and PCA coordinates. A per-park risk table (crimes per 100 acres)
feeds the exports.

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
import statsmodels.api as sm  # noqa: E402
from scipy import stats  # noqa: E402
from sklearn.cluster import HDBSCAN, KMeans  # noqa: E402
from sklearn.decomposition import PCA  # noqa: E402
from sklearn.metrics import (  # noqa: E402
    adjusted_rand_score, silhouette_samples, silhouette_score,
)
from sklearn.mixture import GaussianMixture  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402
from statsmodels.stats.diagnostic import acorr_ljungbox  # noqa: E402
from statsmodels.tsa.holtwinters import ExponentialSmoothing  # noqa: E402
from statsmodels.tsa.statespace.sarimax import SARIMAX  # noqa: E402
from statsmodels.tsa.stattools import adfuller, kpss  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "warehouse.db"
CSV_PATH = ROOT / "data" / "processed" / "park_crime_long.csv"
GEO_CSV = ROOT / "data" / "processed" / "parks_geo.csv"
FIG_DIR = ROOT / "outputs" / "figures"
TABLE_DIR = ROOT / "outputs" / "tables"
METRIC_DIR = ROOT / "outputs" / "metrics"

SEED = 42
SEASON = 4
HORIZON = 4
BACKTEST = 8
# Rolling origins: three expanding-window origins, four quarters each.
ROLL_ORIGINS = 3
ROLL_HORIZON = 4
# Selection rule: a simpler model within 1 % of the best mean MAE wins.
TIE_TOLERANCE = 0.01
K_MIN, K_MAX = 2, 6
MIN_PARK_CRIMES = 20
# Shrinkage pseudo-count pulling each park's crime mix toward the citywide mix.
SHRINKAGE = 20.0
SUBSAMPLE_ARI = 20
ARI_SUBSAMPLE_FRACTION = 0.8
# A borough needs at least 4 years of history and real signal to model.
MIN_MEAN_CRIMES = 5.0
MIN_NONZERO_QUARTERS = 16
CI_ALPHA = 0.05
LEVEL_PCT = round((1 - CI_ALPHA) * 100)
INTERVAL_LABEL_FR = f"Intervalle à {LEVEL_PCT} %"
INTERVAL_NOTE_EN = (
    f"The lower bound of the {LEVEL_PCT} % interval is clipped at 0 because a "
    "crime count cannot be negative. On rows flagged clipped, the interval is "
    "therefore one-sided/asymmetric and the true lower bound is not shown."
)
INTERVAL_NOTE_FR = (
    f"La borne basse de l'intervalle à {LEVEL_PCT} % est ramenée à 0 car un "
    "nombre de crimes ne peut pas être négatif. Sur les lignes marquées "
    "« clipped », l'intervalle est donc unilatéral/asymétrique et sa vraie "
    "borne basse n'est pas représentée."
)

MODELS = ("seasonal_naive", "holt_winters", "glm_poisson", "sarimax", "sarimax_log")
# Lower is simpler; ties within TIE_TOLERANCE go to the simpler model.
COMPLEXITY = {
    "seasonal_naive": 0, "holt_winters": 1, "glm_poisson": 2,
    "sarimax": 3, "sarimax_log": 3,
}
DEFAULT_ORDER = (1, 1, 1)
DEFAULT_SEASONAL_ORDER = (1, 1, 0, SEASON)
HW_SIMULATIONS = 600
GLM_DRAWS = 400
QUARTER_FR = {
    "BURGLARY": "Cambriolage",
    "FELONY ASSAULT": "Agression",
    "GRAND LARCENY": "Larcin",
    "GRAND LARCENY AUTO": "Vol de véhicule",
    "MURDER": "Meurtre",
    "RAPE": "Viol",
    "ROBBERY": "Vol qualifié",
}

DPI = 150
OKABE_ITO = [
    "#0072B2", "#E69F00", "#009E73", "#CC79A7",
    "#56B4E9", "#D55E00", "#F0E442", "#000000",
]


def late_parks(crimes):
    """Parks whose first observed quarter is later than the dataset's first."""
    order = crimes.groupby("quarter_label")["period_start"].min().sort_values().index
    first = order[0]
    firsts = crimes.sort_values("period_start").groupby("park_id")["quarter_label"].first()
    names = crimes.groupby("park_id")["park"].first()
    return [
        (names[park_id], label)
        for park_id, label in firsts.items()
        if label != first
    ]


def coverage_onset(crimes):
    """First quarter at which any park newly enters the source, or None."""
    late = late_parks(crimes)
    if not late:
        return None
    return min(label for _, label in late)


def missing_column_entries(crimes):
    """(quarter, crime_type) cells that are NULL because the column is absent."""
    if "count_missing" not in crimes:
        return []
    rows = crimes[crimes["count_missing"].eq(1)]
    return sorted(set(zip(rows["quarter_label"], rows["crime_type"])))


def total_mismatch_entries(crimes):
    """Flagged TOTAL mismatches with the workbook TOTAL when the table exists."""
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


def build_caveats(crimes, interpolated):
    """Model caveats derived from the data and the EDA anomaly tables."""
    caveats = []
    late = late_parks(crimes)
    if late:
        names = ", ".join(name.title() for name, _ in late)
        first = late[0][1]
        previous = previous_quarters(first, 2)[0]
        caveats.append(
            f"{names} n'apparaît dans la source qu'à partir de {first} : la "
            f"croissance citywide {previous}→{first} est en partie un artefact "
            "de couverture (outputs/tables/coverage_gaps.csv)."
        )
    for entry in total_mismatch_entries(crimes):
        recorded = entry.get("total_recorded")
        total = (
            f"TOTAL {recorded} vs somme {entry['sum_computed']}"
            if recorded is not None
            else f"TOTAL enregistré vs somme {entry['sum_computed']}"
        )
        caveats.append(
            f"{entry['park'].title()} {entry['quarter']} : {total} ; ses "
            "composantes sont conservées (total_mismatch=1) et la ligne n'est "
            "exclue que des contrôles TOTAL "
            "(outputs/tables/source_anomalies.csv)."
        )
    entries = missing_column_entries(crimes)
    if entries:
        quarters = ", ".join(sorted({quarter for quarter, _ in entries}))
        types = ", ".join(sorted({crime for _, crime in entries}))
        caveats.append(
            f"Les classeurs {quarters} n'ont pas de colonne {types} : le "
            "compte est NULL, exclu des sommes, jamais imputé ni compté comme "
            "zéro."
        )
    if interpolated:
        caveats.append(
            f"{', '.join(interpolated)} est absent en amont : laissé NaN pour "
            "SARIMAX, interpolé saisonnièrement pour Holt-Winters et le GLM, "
            "jamais traité comme zéro."
        )
    return caveats


def build_footnote(crimes, interpolated):
    """Compact figure footnote with the same derived facts."""
    parts = []
    late = late_parks(crimes)
    if late:
        parts.append(
            f"{', '.join(name.title() for name, _ in late)} absent de la source avant "
            f"{late[0][1]}"
        )
    for entry in total_mismatch_entries(crimes):
        parts.append(
            f"{entry['park'].title()} {entry['quarter']} flaggé "
            "total_mismatch (composantes conservées)"
        )
    entries = missing_column_entries(crimes)
    if entries:
        parts.append(
            f"{', '.join(sorted({crime for _, crime in entries}))} NULL en "
            f"{', '.join(sorted({quarter for quarter, _ in entries}))}"
        )
    if interpolated:
        parts.append(
            f"{', '.join(interpolated)} absent (NaN pour SARIMAX, "
            "interpolation saisonnière sinon)"
        )
    return "Note : " + " ; ".join(parts) + "." if parts else "Note : aucune."


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------

def load_crimes():
    """Load the long crime table with its stable park_id.

    NULL counts (a crime column absent from a workbook) are excluded from every
    sum here and never imputed: pandas sums skip them by default.
    """
    if DB_PATH.exists():
        with sqlite3.connect(DB_PATH) as conn:
            df = pd.read_sql(
                "SELECT quarter_label, period_start, park, borough, "
                "size_acres, crime_type, count, count_missing, total_mismatch "
                "FROM crimes_long",
                conn,
            )
    else:
        df = pd.read_csv(CSV_PATH)
    df["period_start"] = pd.to_datetime(df["period_start"])
    ids = pd.read_csv(GEO_CSV)[["park", "borough", "park_id"]]
    return df.merge(ids, on=["park", "borough"], how="left")


def load_parks():
    """Park reference table keyed by park_id: coordinates from geography."""
    if not DB_PATH.exists():
        return pd.DataFrame(columns=["park_id", "lat", "lon"])
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql(
            "SELECT park_id, lat, lon FROM parks", conn
        )


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


def interpolate_seasonal(series):
    """Fill NaNs with the mean of the same quarter ±1 year; linear fallback."""
    out = series.copy()
    for position in [i for i, v in enumerate(series.to_numpy()) if pd.isna(v)]:
        neighbours = [
            out.iloc[j]
            for j in (position - SEASON, position + SEASON)
            if 0 <= j < len(out) and not pd.isna(out.iloc[j])
        ]
        if neighbours:
            out.iloc[position] = float(np.mean(neighbours))
    if out.isna().any():
        out = out.interpolate(method="linear")
    return out


def quarterly_series(df, label_col="quarter_label", method="linear"):
    """Continuous quarterly totals; absent quarters are interpolated.

    `method` controls the fill for downstream models: "linear" (default),
    "seasonal" (same quarter ±1 year) or None (left NaN for SARIMAX, which
    handles missing observations natively).

    Returns (series, interpolated_quarters). A quarter missing upstream is
    interpolated for modelling and reported, never filled with zero.
    """
    totals = df.groupby(label_col)["count"].sum()
    totals = totals[~totals.index.duplicated()]
    labels = quarter_range(totals.index.min(), totals.index.max())
    series = totals.reindex(labels).astype(float)
    missing = series[series.isna()].index.tolist()
    if missing:
        if method == "linear":
            series = series.interpolate(method="linear")
        elif method == "seasonal":
            series = interpolate_seasonal(series)
        elif method is not None:
            raise ValueError(f"unknown interpolation method: {method}")
    if pd.isna(series.iloc[0]) or pd.isna(series.iloc[-1]):
        raise ValueError(f"Leading/trailing missing quarters: {missing}")
    return series, missing


def fill_seasonal_values(values):
    """Seasonal fill used by models that cannot accept NaN endog."""
    return interpolate_seasonal(pd.Series(np.asarray(values, dtype=float))).to_numpy()


def mae(actual, predicted):
    """Mean absolute error."""
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    return float(np.nanmean(np.abs(actual - predicted)))


def rmse(actual, predicted):
    """Root mean squared error."""
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    return float(np.sqrt(np.nanmean((actual - predicted) ** 2)))


def mape(actual, predicted):
    """Mean absolute percentage error, ignoring zero actuals.

    Returns None when every actual is zero (percentage undefined).
    """
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    mask = (actual != 0) & ~np.isnan(actual)
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


def coverage_exog(labels, coverage_from):
    """Step dummy: 1 from the quarter new parks enter the source, else 0."""
    if not coverage_from:
        return None
    return np.array(
        [[1.0 if label >= coverage_from else 0.0] for label in labels]
    )


def _glm_design(labels, coverage_from):
    """Intercept + quarter dummies (+ coverage step) for the Poisson GLM.

    No linear trend: on a short quarterly sample a free trend extrapolates
    the level runaway, and the quarter dummies already carry the seasonal
    level.
    """
    quarter = np.array([parse_quarter(label)[1] for label in labels])
    columns = [
        np.ones((len(labels), 1)),
        np.column_stack([(quarter == q).astype(float) for q in (2, 3, 4)]),
    ]
    exog = coverage_exog(labels, coverage_from)
    if exog is not None:
        columns.append(exog)
    return np.column_stack(columns)


def _useful_exog(exog_history, exog_future):
    """Drop the dummy when it never moves: a constant column is rank-deficient."""
    if exog_history is None:
        return None, None
    stacked = np.vstack([exog_history, exog_future])
    if float(np.std(stacked)) == 0.0:
        return None, None
    return exog_history, exog_future


def _forecast_frame(labels, point, lower, upper):
    return pd.DataFrame({
        "quarter_label": list(labels),
        "point": np.asarray(point, dtype=float),
        "lower": np.asarray(lower, dtype=float),
        "upper": np.asarray(upper, dtype=float),
    })


def _fit_sarimax(values, exog, order, seasonal_order):
    """Converged SARIMAX fit; stationarity/invertibility left enforced."""
    if exog is not None:
        # A named frame keeps fitted parameters addressable in diagnostics.
        exog = pd.DataFrame(np.asarray(exog), columns=["post_coverage"])
    model = SARIMAX(
        values, exog=exog, order=order, seasonal_order=seasonal_order,
        trend="n",
    )
    fit = model.fit(disp=False, maxiter=200)
    if not fit.mle_retvals.get("converged", True):
        raise RuntimeError("SARIMAX optimization did not converge")
    return fit


def _model_forecast(name, values, steps, history_labels, future_labels,
                    coverage_from=None, order=DEFAULT_ORDER,
                    seasonal_order=DEFAULT_SEASONAL_ORDER):
    """Point forecast and configured-level interval; NaN endog for SARIMAX."""
    values = np.asarray(values, dtype=float)
    filled = fill_seasonal_values(values)
    if name == "seasonal_naive":
        point = seasonal_naive_forecast(filled, steps)
        # shortcut: constant-width interval from in-sample seasonal residuals;
        # upgrade to a bootstrapped path if intervals drive decisions.
        sd = float(np.nanstd(filled[SEASON:] - filled[:-SEASON]))
        return _forecast_frame(
            future_labels, point, point - 1.96 * sd, point + 1.96 * sd,
        )
    if name == "holt_winters":
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = ExponentialSmoothing(
                filled, trend="add", seasonal="add",
                seasonal_periods=SEASON, initialization_method="estimated",
            ).fit()
            if not fit.mle_retvals.get("converged", True):
                raise RuntimeError("Holt-Winters optimization did not converge")
            point = np.asarray(fit.forecast(steps))
            sims = fit.simulate(
                steps, repetitions=HW_SIMULATIONS, error="add",
                random_state=np.random.RandomState(SEED),
            )
        return _forecast_frame(
            future_labels, point,
            np.quantile(sims, CI_ALPHA / 2, axis=1),
            np.quantile(sims, 1 - CI_ALPHA / 2, axis=1),
        )
    exog_history, exog_future = _useful_exog(
        coverage_exog(history_labels, coverage_from),
        coverage_exog(future_labels, coverage_from),
    )
    if name == "glm_poisson":
        design = _glm_design(history_labels, coverage_from)
        future = _glm_design(future_labels, coverage_from)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = sm.GLM(filled, design, family=sm.families.Poisson()).fit()
        point = np.asarray(fit.predict(future))
        # Parametric bootstrap: coefficient draws, then Poisson predictive
        # draws — the interval stays on the count scale and never goes below 0.
        rng = np.random.default_rng(SEED)
        draws = rng.multivariate_normal(
            np.asarray(fit.params), np.asarray(fit.cov_params()),
            size=GLM_DRAWS, check_valid="ignore",
        )
        lam = np.exp(future @ draws.T)
        samples = rng.poisson(np.clip(lam, 0.0, None))
        return _forecast_frame(
            future_labels, point,
            np.quantile(samples, CI_ALPHA / 2, axis=1),
            np.quantile(samples, 1 - CI_ALPHA / 2, axis=1),
        )
    if name in ("sarimax", "sarimax_log"):
        data = values if name == "sarimax" else np.log1p(values)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = _fit_sarimax(data, exog_history, order, seasonal_order)
            frame = fit.get_forecast(steps, exog=exog_future).summary_frame(
                alpha=CI_ALPHA
            )
        point = np.asarray(frame["mean"])
        lower = np.asarray(frame["mean_ci_lower"])
        upper = np.asarray(frame["mean_ci_upper"])
        if name == "sarimax_log":
            point, lower, upper = np.expm1(point), np.expm1(lower), np.expm1(upper)
        return _forecast_frame(future_labels, point, lower, upper)
    raise ValueError(name)


def select_sarimax_order(values, history_labels, coverage_from,
                         p_max=2, q_max=2, P_max=1, Q_max=1, d=1, D=1):
    """Small AICc grid over (p,d,q)x(P,D,Q,4); returns the best order + rows."""
    exog = coverage_exog(history_labels, coverage_from)
    rows = []
    failures = 0
    for p in range(p_max + 1):
        for q in range(q_max + 1):
            for P in range(P_max + 1):
                for Q in range(Q_max + 1):
                    order = (p, d, q)
                    seasonal_order = (P, D, Q, SEASON)
                    try:
                        with warnings.catch_warnings():
                            warnings.simplefilter("ignore")
                            fit = _fit_sarimax(values, exog, order, seasonal_order)
                        rows.append({
                            "order": list(order),
                            "seasonal_order": list(seasonal_order),
                            "aicc": round(float(fit.aicc), 4),
                        })
                    except Exception:  # noqa: BLE001 - counted, not swallowed
                        failures += 1
    if not rows:
        return DEFAULT_ORDER, DEFAULT_SEASONAL_ORDER, [], failures
    rows.sort(key=lambda row: row["aicc"])
    best = rows[0]
    return tuple(best["order"]), tuple(best["seasonal_order"]), rows[:5], failures


def sarimax_diagnostics(values, labels, coverage_from, order, seasonal_order):
    """AICc, Ljung-Box, ADF/KPSS and fitted params for the selected order."""
    exog = coverage_exog(labels, coverage_from)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit = _fit_sarimax(values, exog, order, seasonal_order)
        residuals = pd.Series(np.asarray(fit.resid), index=labels)
        clean = pd.Series(np.asarray(values, dtype=float)).dropna()
        ljung_p = float(
            acorr_ljungbox(residuals.dropna(), lags=[2 * SEASON], return_df=True)
            .iloc[0]["lb_pvalue"]
        )
        adf_p = float(adfuller(clean, autolag="AIC")[1])
        kpss_p = float(kpss(clean, regression="c", nlags="auto")[1])
    return {
        "order": list(order),
        "seasonal_order": list(seasonal_order),
        "aicc": round(float(fit.aicc), 4),
        "ljung_box_p": round(ljung_p, 4),
        "adf_p": round(adf_p, 4),
        # KPSS p-value is bounded to [0.01, 0.10] by statsmodels' table.
        "kpss_p": round(kpss_p, 4),
        "params": [
            {"name": str(name), "value": round(float(value), 4)}
            for name, value in fit.params.items()
        ],
    }, residuals


def diebold_mariano(loss_model, loss_base, horizon):
    """Two-sided p-value, HLN small-sample correction, absolute-error loss."""
    d = np.asarray(loss_model, dtype=float) - np.asarray(loss_base, dtype=float)
    d = d[~np.isnan(d)]
    n = len(d)
    if n <= horizon or np.allclose(d, 0.0):
        return None
    dbar = float(d.mean())
    variance = float(np.mean((d - dbar) ** 2))
    for lag in range(1, horizon):
        gamma = float(np.mean((d[lag:] - dbar) * (d[:-lag] - dbar)))
        variance += 2 * (1 - lag / horizon) * gamma
    if variance <= 0:
        return None
    dm = dbar / np.sqrt(variance / n)
    correction = np.sqrt((n + 1 - 2 * horizon + horizon * (horizon - 1) / n) / n)
    return float(2 * stats.t.sf(abs(dm * correction), df=n - 1))


def forecast_series(values, horizon=HORIZON, backtest=BACKTEST, season=SEASON,
                    last_label=None, coverage_from=None, labels=None,
                    order=None, seasonal_order=None, origins=ROLL_ORIGINS):
    """Rolling-origin backtest over five models, then refit the winner.

    Each of `origins` expanding-window origins holds out ROLL_HORIZON quarters.
    Selection: mean MAE across origins, 1 % tie tolerance toward the simpler
    model. Diebold-Mariano (HLN) tests each challenger against seasonal-naive.
    """
    values = np.asarray(values, dtype=float)
    n = len(values)
    if labels is None:
        labels = (
            previous_quarters(last_label, n) if last_label
            else [f"T{index + 1}" for index in range(n)]
        )
    labels = list(labels)
    order = tuple(order or DEFAULT_ORDER)
    seasonal_order = tuple(seasonal_order or DEFAULT_SEASONAL_ORDER)
    if n < horizon + origins * ROLL_HORIZON + season:
        raise ValueError("Not enough quarters to backtest")

    pooled = {
        name: {"abs": [], "sq": [], "covered": [], "predicted": [], "actual": []}
        for name in MODELS
    }
    origin_rows = []
    failures = {}
    for origin_index in range(origins, 0, -1):
        cut = n - ROLL_HORIZON * origin_index
        train, test = values[:cut], values[cut:cut + ROLL_HORIZON]
        train_labels = labels[:cut]
        test_labels = labels[cut:cut + ROLL_HORIZON]
        per_model = []
        for name in MODELS:
            if name in failures:
                continue
            try:
                frame = _model_forecast(
                    name, train, len(test), train_labels, test_labels,
                    coverage_from, order, seasonal_order,
                )
            except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
                failures[name] = f"{type(exc).__name__}: {exc}"
                continue
            predicted = np.asarray(frame["point"], dtype=float)
            error = np.abs(test - predicted)
            lower = np.asarray(frame["lower"], dtype=float)
            upper = np.asarray(frame["upper"], dtype=float)
            pooled[name]["abs"].extend(error.tolist())
            pooled[name]["sq"].extend(((test - predicted) ** 2).tolist())
            pooled[name]["covered"].extend(
                ((test >= lower) & (test <= upper)).tolist()
            )
            pooled[name]["predicted"].extend(predicted.tolist())
            pooled[name]["actual"].extend(test.tolist())
            per_model.append({
                "model": name,
                "mae": round(mae(test, predicted), 4),
                "rmse": round(rmse(test, predicted), 4),
            })
        origin_rows.append({
            "train_end": train_labels[-1],
            "test_window": test_labels,
            "metrics": per_model,
        })

    metrics = {}
    for name, loss in pooled.items():
        if name in failures or not loss["abs"]:
            continue
        origin_maes = [
            row_metrics["mae"]
            for row in origin_rows
            for row_metrics in row["metrics"]
            if row_metrics["model"] == name
        ]
        entry = {
            "mae": round(float(np.nanmean(loss["abs"])), 4),
            "mae_sd": round(float(np.nanstd(origin_maes)), 4),
            "rmse": round(float(np.sqrt(np.nanmean(loss["sq"]))), 4),
            "mape": (
                None
                if mape(loss["actual"], loss["predicted"]) is None
                else round(mape(loss["actual"], loss["predicted"]), 2)
            ),
            "coverage_95": round(float(np.mean(loss["covered"])), 4),
            "dm_p": (
                None
                if name == "seasonal_naive"
                else diebold_mariano(
                    loss["abs"], pooled["seasonal_naive"]["abs"], ROLL_HORIZON,
                )
            ),
        }
        if entry["dm_p"] is not None:
            entry["dm_p"] = round(entry["dm_p"], 4)
        # A non-finite MAE (degenerate fit) disqualifies the candidate.
        if np.isfinite(entry["mae"]) and np.isfinite(entry["mae_sd"]):
            metrics[name] = entry

    if "seasonal_naive" not in metrics:
        raise RuntimeError("every candidate model failed")
    best = min(metrics, key=lambda name: metrics[name]["mae"])
    threshold = metrics[best]["mae"] * (1 + TIE_TOLERANCE)
    winner = min(
        (name for name in metrics if metrics[name]["mae"] <= threshold),
        key=lambda name: COMPLEXITY[name],
    )
    baseline_mae = metrics["seasonal_naive"]["mae"]
    improvement = (
        (baseline_mae - metrics[winner]["mae"]) / baseline_mae * 100.0
        if baseline_mae else 0.0
    )
    # The winner may be the baseline itself, whose DM test is undefined;
    # report the best challenger's test so a DM p-value is always visible.
    challengers = [
        name for name in metrics
        if name != "seasonal_naive" and metrics[name]["dm_p"] is not None
    ]
    best_challenger = (
        min(challengers, key=lambda name: metrics[name]["mae"])
        if challengers else None
    )

    # Textbook one-step seasonal rule over the last `backtest` quarters:
    # reference only; selection stays on the recursive rolling backtest above.
    rule_pred = np.asarray([
        values[position - season]
        for position in range(n - backtest, n)
    ])
    baseline_rule_mae = round(mae(values[-backtest:], rule_pred), 4)

    horizon_labels = (
        next_quarters(last_label, horizon) if last_label
        else [f"T+{h}" for h in range(1, horizon + 1)]
    )
    forecast = _model_forecast(
        winner, values, horizon, labels,
        horizon_labels, coverage_from, order, seasonal_order,
    )
    forecast["point"] = forecast["point"].round(2)
    # Crime counts cannot be negative, but a Gaussian interval below can.
    # Keep the raw quantile and flag the row before clipping: the clip makes
    # the interval one-sided where it bites, so it must stay visible instead
    # of passing for a symmetric interval.
    forecast["clipless_lower"] = forecast["lower"].round(2)
    forecast["clipped"] = forecast["lower"] < 0
    forecast["lower"] = forecast["lower"].clip(lower=0).round(2)
    forecast["upper"] = forecast["upper"].clip(lower=0).round(2)

    actual = [
        value
        for origin_index in range(origins, 0, -1)
        for value in values[n - ROLL_HORIZON * origin_index:
                            n - ROLL_HORIZON * (origin_index - 1)]
    ] if winner in pooled else []
    predicted = pooled.get(winner, {}).get("predicted", [])
    if len(predicted) != len(actual):
        predicted = []
    return {
        "selected_model": winner,
        "baseline_wins": winner == "seasonal_naive",
        "baseline_mae_seasonal_rule": baseline_rule_mae,
        "improvement_pct": round(float(improvement), 2),
        "backtest_quarters": origins * ROLL_HORIZON,
        "backtest_window": [
            label
            for origin_index in range(origins, 0, -1)
            for label in labels[n - ROLL_HORIZON * origin_index:
                                n - ROLL_HORIZON * (origin_index - 1)]
        ],
        "backtest_origins": origin_rows,
        "backtest_metrics": metrics,
        "best_challenger": (
            {
                "model": best_challenger,
                "mae": metrics[best_challenger]["mae"],
                "mae_sd": metrics[best_challenger]["mae_sd"],
                "dm_p": metrics[best_challenger]["dm_p"],
            }
            if best_challenger else None
        ),
        "backtest_fit": {
            "labels": [
                label
                for origin_index in range(origins, 0, -1)
                for label in labels[n - ROLL_HORIZON * origin_index:
                                    n - ROLL_HORIZON * (origin_index - 1)]
            ],
            "actual": [float(v) for v in actual],
            "predicted": [round(float(v), 4) for v in predicted],
        },
        "model_failures": failures,
        "forecast": forecast,
        "coverage_from": coverage_from,
        "order": list(order),
        "seasonal_order": list(seasonal_order),
    }


# --------------------------------------------------------------------------
# Clustering
# --------------------------------------------------------------------------

def park_feature_table(crimes, parks, min_crimes=MIN_PARK_CRIMES):
    """Feature table for parks with at least `min_crimes` major crimes.

    Crime mix: shares are shrunk toward the citywide mix (SHRINKAGE pseudo-
    counts) then CLR-transformed, so a park with 21 crimes cannot look as
    certain as one with 2,000. Raw shares stay alongside for the heatmap.
    """
    totals = crimes.groupby("park_id")["count"].sum()
    eligible = totals[totals >= min_crimes].index
    sub = crimes[crimes["park_id"].isin(eligible)]
    counts = sub.pivot_table(
        index="park_id", columns="crime_type", values="count",
        aggfunc="sum", fill_value=0,
    )
    counts = counts.reindex(columns=sorted(crimes["crime_type"].unique()),
                            fill_value=0)
    raw = counts.div(counts.sum(axis=1), axis=0)
    raw.columns = [f"share_{c.lower().replace(' ', '_')}" for c in raw.columns]
    city_shares = counts.sum() / counts.sum().sum()
    smoothed = counts.add(SHRINKAGE * city_shares, axis=1)
    smoothed = smoothed.div(smoothed.sum(axis=1), axis=0)
    clr = np.log(smoothed)
    clr = clr.sub(clr.mean(axis=1), axis=0)
    clr.columns = [f"clr_{c.lower().replace(' ', '_')}" for c in clr.columns]

    full = pd.DataFrame(index=counts.index)
    full["total_crimes"] = counts.sum(axis=1)
    full["log_total"] = np.log1p(full["total_crimes"])
    latest = sub.sort_values("period_start")
    acres = latest.groupby("park_id")["size_acres"].last()
    full["log_acres"] = np.log1p(acres)
    acres_missing = int(full["log_acres"].isna().sum())
    if acres_missing:
        full["log_acres"] = full["log_acres"].fillna(full["log_acres"].median())
    features = clr.join(raw).join(full[["total_crimes", "log_total", "log_acres"]])
    features["borough"] = sub.groupby("park_id")["borough"].first()
    features["park"] = sub.groupby("park_id")["park"].first()
    if not parks.empty:
        ref = parks.drop_duplicates("park_id").set_index("park_id")
        features = features.join(ref[["lat", "lon"]], how="left")
    else:
        features["lat"] = np.nan
        features["lon"] = np.nan
    features = features.sort_values("park")
    features.attrs["acres_missing"] = acres_missing
    return features


FEATURE_COLUMNS = [
    "clr_burglary", "clr_felony_assault", "clr_grand_larceny",
    "clr_grand_larceny_auto", "clr_murder", "clr_rape", "clr_robbery",
    "log_total", "log_acres",
]


def cluster_parks(features, k_min=K_MIN, k_max=K_MAX, seed=SEED):
    """KMeans over standardized features; k chosen by silhouette.

    Returns (labels, per-park silhouette values, chosen k, best silhouette,
    per-k scores, scaled feature matrix).
    """
    x = StandardScaler().fit_transform(features[FEATURE_COLUMNS].to_numpy())
    k_max = min(k_max, len(features) - 1)
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


def cluster_names(profiles, share_columns):
    """Unique French names from the two crime types over-represented vs city."""
    weighted = profiles[share_columns].mul(
        profiles["total_crimes"], axis=0
    ).sum() / profiles["total_crimes"].sum()
    lift = profiles[share_columns].div(weighted, axis=1)
    names = []
    for cluster in profiles["cluster"]:
        order = lift.loc[cluster].sort_values(ascending=False).index
        top = [
            QUARTER_FR.get(
                column.replace("share_", "").replace("_", " ").upper(), column
            )
            for column in order[:2]
        ]
        names.append(f"{top[0]} dominant")
    counts = pd.Series(names).value_counts()
    for index, (cluster, name) in enumerate(zip(profiles["cluster"], names)):
        if counts[name] > 1:
            order = lift.loc[cluster].sort_values(ascending=False).index
            second = QUARTER_FR.get(
                order[1].replace("share_", "").replace("_", " ").upper(),
                order[1],
            )
            names[index] = f"{name} + {second.lower()}"
    if len(set(names)) < len(names):
        names = [f"{name} ({cluster})" for name, cluster
                 in zip(names, profiles["cluster"])]
    return names


def cluster_profiles(features, labels, sample_values):
    """One row per cluster: size, totals, mean crime-mix shares, top type."""
    table = features.copy()
    table["cluster"] = labels
    table["silhouette"] = sample_values
    table["acres"] = np.expm1(table["log_acres"])
    shares = [c for c in features.columns if c.startswith("share_")]
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
    profiles = profiles.reset_index()
    profiles["name"] = cluster_names(profiles, shares)
    table["dominant_type"] = (
        table[shares].idxmax(axis=1).str.replace("share_", "")
    )
    table = table.reset_index()
    return table, profiles


def cluster_stability(x, labels, k, seed=SEED):
    """ARI between the full solution and KMeans on 80 % park subsamples."""
    rng = np.random.default_rng(seed)
    size = max(k + 1, int(len(x) * ARI_SUBSAMPLE_FRACTION))
    scores = []
    for _ in range(SUBSAMPLE_ARI):
        index = np.sort(rng.choice(len(x), size=size, replace=False))
        sub_labels = KMeans(
            n_clusters=k, random_state=seed, n_init=10,
        ).fit_predict(x[index])
        scores.append(float(adjusted_rand_score(labels[index], sub_labels)))
    return {
        "subsamples": SUBSAMPLE_ARI,
        "fraction": ARI_SUBSAMPLE_FRACTION,
        "ari_mean": round(float(np.mean(scores)), 4),
        "ari_sd": round(float(np.std(scores)), 4),
    }


def cluster_comparison(x, labels, k, seed=SEED):
    """GMM (BIC by k, ARI vs KMeans) and HDBSCAN compared to the KMeans fit."""
    gmm_bic = {}
    gmm_labels = {}
    components_max = max(K_MIN, min(K_MAX, len(x) // 10))
    for components in range(K_MIN, components_max + 1):
        gmm = GaussianMixture(
            n_components=components, covariance_type="diag",
            n_init=2, random_state=seed,
        ).fit(x)
        gmm_bic[components] = round(float(gmm.bic(x)), 2)
        gmm_labels[components] = gmm.predict(x)
    gmm_best_k = min(gmm_bic, key=gmm_bic.get)
    gmm_at_k = gmm_labels.get(k)
    if gmm_at_k is None:
        gmm_at_k = GaussianMixture(
            n_components=k, covariance_type="diag", n_init=2,
            random_state=seed,
        ).fit_predict(x)
    hdbscan = HDBSCAN(
        min_cluster_size=max(5, len(x) // 10), min_samples=5, copy=True,
    ).fit(x)
    noise = float(np.mean(hdbscan.labels_ == -1))
    return {
        "gmm_bic_by_k": {int(key): value for key, value in gmm_bic.items()},
        "gmm_best_k": int(gmm_best_k),
        "gmm_ari_vs_kmeans": round(
            float(adjusted_rand_score(labels, gmm_at_k)), 4
        ),
        "hdbscan_clusters": int(len(set(hdbscan.labels_)) - (1 if -1 in hdbscan.labels_ else 0)),
        "hdbscan_noise_fraction": round(noise, 4),
        "hdbscan_ari_vs_kmeans": round(
            float(adjusted_rand_score(labels, hdbscan.labels_)), 4
        ),
    }


def pca_coordinates(x, seed=SEED):
    """2-D PCA projection and its explained-variance ratios."""
    pca = PCA(n_components=2, random_state=seed)
    coords = pca.fit_transform(x)
    return coords, [round(float(v), 4) for v in pca.explained_variance_ratio_]


def park_risk_table(crimes, cluster_table):
    """Per-park risk: crimes, acres, crimes per 100 acres and coverage era."""
    totals = crimes.groupby("park_id")["count"].sum().rename("crimes")
    meta = crimes.groupby("park_id").agg(
        park=("park", "first"), borough=("borough", "first"),
    )
    acres = (
        crimes.sort_values("period_start")
        .groupby("park_id")["size_acres"].last().rename("acres")
    )
    nonzero = crimes[crimes["count"] > 0].sort_values("period_start")
    first = nonzero.groupby("park_id")["quarter_label"].first().rename(
        "coverage_first"
    )
    last_label = crimes.sort_values("period_start")["quarter_label"].iloc[-1]
    table = meta.join(totals).join(acres)
    table = table[table["crimes"] > 0].copy()
    table["coverage_first"] = first.reindex(table.index).fillna(last_label)
    table["coverage_era"] = (
        table["coverage_first"].astype(str) + "–" + last_label
    )
    # A park with no usable acreage gets a null rate, never a divide-by-zero.
    usable = table["acres"].notna() & (table["acres"] > 0)
    table["crimes_per_100_acres"] = np.nan
    table.loc[usable, "crimes_per_100_acres"] = (
        table.loc[usable, "crimes"] / table.loc[usable, "acres"] * 100.0
    )
    clusters = cluster_table.set_index("park_id")["cluster"]
    table["cluster"] = clusters.reindex(table.index)
    table["risk_rank"] = (
        table["crimes_per_100_acres"].rank(ascending=False, method="min")
    )
    table = table.reset_index().rename(columns={"index": "park_id"})
    table = table.sort_values(
        ["crimes_per_100_acres", "crimes"], ascending=[False, False],
        na_position="last",
    )
    return table[[
        "park_id", "park", "borough", "crimes", "acres",
        "crimes_per_100_acres", "risk_rank", "coverage_first", "coverage_era",
        "cluster",
    ]]


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------

def _series_metrics(result):
    selected = result["backtest_metrics"][result["selected_model"]]
    return {
        "selected_model": result["selected_model"],
        "selected_mae": selected["mae"],
        "selected_mae_sd": selected["mae_sd"],
        "selected_rmse": selected["rmse"],
        "selected_mape": selected["mape"],
        "baseline_mae": result["backtest_metrics"]["seasonal_naive"]["mae"],
        "baseline_mae_sd": result["backtest_metrics"]["seasonal_naive"]["mae_sd"],
        "baseline_mae_seasonal_rule": result["baseline_mae_seasonal_rule"],
        "baseline_wins": result["baseline_wins"],
        "dm_p_vs_naive": selected["dm_p"],
        "best_challenger": result["best_challenger"],
        "interval_coverage_95": selected["coverage_95"],
        "tie_tolerance_pct": round(TIE_TOLERANCE * 100, 2),
        "selection_caveat": (
            f"Model chosen on the mean MAE over {ROLL_ORIGINS} rolling "
            f"{ROLL_HORIZON}-quarter origins with a {TIE_TOLERANCE * 100:.0f} % "
            "tie tolerance toward the simpler model; the reported MAE is the "
            "mean of those same forecasts, so its advantage remains optimistic, "
            "while the comparison with the recursive seasonal-naive baseline "
            "is unaffected."
        ),
        "improvement_pct": result["improvement_pct"],
        "backtest_quarters": result["backtest_quarters"],
        "backtest_window": result["backtest_window"],
        "backtest_origins": result["backtest_origins"],
        "backtest_metrics": result["backtest_metrics"],
        "model_failures": result["model_failures"],
        "interval_clipped_rows": int(result["forecast"]["clipped"].sum()),
        "forecast": result["forecast"].to_dict(orient="records"),
    }


def forecast_bundle(group, coverage_from, scope):
    """One series end to end: AICc order, backtest, diagnostics, refit."""
    values, missing = quarterly_series(group, method=None)
    labels = list(values.index)
    order, seasonal_order, grid_top, grid_failures = select_sarimax_order(
        values.to_numpy(), labels, coverage_from,
    )
    result = forecast_series(
        values, last_label=labels[-1], coverage_from=coverage_from,
        labels=labels, order=order, seasonal_order=seasonal_order,
    )
    try:
        diagnostics, residuals = sarimax_diagnostics(
            values.to_numpy(), labels, coverage_from, order, seasonal_order,
        )
    except Exception:  # noqa: BLE001 - fall back to the default order
        order, seasonal_order = DEFAULT_ORDER, DEFAULT_SEASONAL_ORDER
        try:
            diagnostics, residuals = sarimax_diagnostics(
                values.to_numpy(), labels, coverage_from, order, seasonal_order,
            )
        except Exception as exc:  # noqa: BLE001 - recorded in the metrics
            diagnostics = {
                "order": list(order), "seasonal_order": list(seasonal_order),
                "aicc": None, "ljung_box_p": None, "adf_p": None,
                "kpss_p": None, "params": [], "error": str(exc),
            }
            residuals = pd.Series(dtype=float)
    diagnostics["aicc_grid_top"] = grid_top
    diagnostics["grid_failures"] = grid_failures
    diagnostics["scope"] = scope
    result["diagnostics"] = diagnostics
    result["residuals"] = residuals
    result["history"] = [float(v) for v in values]
    result["history_labels"] = labels
    result["interpolated_quarters"] = missing
    return result


def run_forecasts(crimes):
    """Citywide and per-borough forecasts (same function for each series)."""
    onset = coverage_onset(crimes)
    series, interpolated = quarterly_series(crimes, method=None)
    city = forecast_bundle(crimes, onset, "CITYWIDE")
    boroughs, skipped = {}, {}
    for borough, group in crimes.groupby("borough"):
        values, _ = quarterly_series(group, method=None)
        mean_count = float(values.mean())
        nonzero = int((values > 0).sum())
        if mean_count < MIN_MEAN_CRIMES or nonzero < MIN_NONZERO_QUARTERS:
            reason = (
                f"trop peu de données : {int(values.sum())} crimes sur "
                f"{len(values)} trimestres (moyenne {mean_count:.1f}/trimestre, "
                f"{nonzero} trimestres non nuls)"
            )
            if borough == "BROOKLYN/QUEENS":
                source_parks = int(group["park_id"].nunique())
                hit_parks = int(
                    (group.groupby("park_id")["count"].sum() > 0).sum()
                )
                reason += (
                    f" ; libellé hybride ({source_parks} parcs dans la source, "
                    f"{hit_parks} avec au moins un crime) sans série homogène"
                )
            skipped[borough] = reason
            continue
        boroughs[borough] = forecast_bundle(group, onset, borough)
    return series, interpolated, city, boroughs, skipped


def consistent_perimeter(crimes, coverage_from, excluded="CENTRAL PARK"):
    """City forecast on a perimeter that excludes the late-coverage park."""
    subset = crimes[~crimes["park"].str.upper().eq(excluded)]
    result = forecast_bundle(subset, coverage_from, f"WITHOUT {excluded}")
    return {
        "excluded_parks": [excluded],
        "selected_model": result["selected_model"],
        "selected_mae": result["backtest_metrics"][result["selected_model"]]["mae"],
        "selected_mae_sd": result["backtest_metrics"][result["selected_model"]]["mae_sd"],
        "points": result["forecast"][[
            "quarter_label", "point", "lower", "upper",
        ]].to_dict(orient="records"),
    }


def interpolation_sensitivity(crimes, coverage_from, order=None,
                              seasonal_order=None):
    """Same pipeline on a linearly vs seasonally filled city series.

    Both fills reuse the citywide AICc order so the table isolates the fill,
    not model selection.
    """
    rows = []
    for method in ("linear", "seasonal"):
        values, _ = quarterly_series(crimes, method=method)
        labels = list(values.index)
        result = forecast_series(
            values, last_label=labels[-1], coverage_from=coverage_from,
            labels=labels, order=order, seasonal_order=seasonal_order,
        )
        selected = result["backtest_metrics"][result["selected_model"]]
        for row in result["forecast"].itertuples():
            rows.append({
                "interpolation": method,
                "model": result["selected_model"],
                "mae": selected["mae"],
                "mae_sd": selected["mae_sd"],
                "quarter_label": row.quarter_label,
                "point": float(row.point),
                "lower": float(row.lower),
                "upper": float(row.upper),
            })
    return rows


def reconcile_forecasts(city, boroughs):
    """Bottom-up reconciled city forecast.

    Sum the modelled borough forecasts and add a seasonal-naive forecast of
    the residual (city minus modelled boroughs), which carries the skipped
    boroughs. Bounds add in quadrature with the residual's seasonal sd.
    """
    labels = city["history_labels"]
    total = np.zeros(len(labels))
    for result in boroughs.values():
        total += np.asarray(result["history"], dtype=float)
    residual = np.asarray(city["history"], dtype=float) - total
    residual_point = seasonal_naive_forecast(residual, HORIZON)
    residual_sd = float(np.nanstd(residual[SEASON:] - residual[:-SEASON]))
    horizons = list(city["forecast"]["quarter_label"])
    point = np.zeros(HORIZON)
    lower = np.zeros(HORIZON)
    upper = np.zeros(HORIZON)
    for result in boroughs.values():
        point += np.asarray(result["forecast"]["point"], dtype=float)
        lower += np.asarray(result["forecast"]["lower"], dtype=float)
        upper += np.asarray(result["forecast"]["upper"], dtype=float)
    point += residual_point
    lower += residual_point - 1.96 * residual_sd
    upper += residual_point + 1.96 * residual_sd
    frame = pd.DataFrame({
        "quarter_label": horizons,
        "point": np.round(point, 2),
        "lower": np.round(lower, 2),
        "upper": np.round(upper, 2),
    })
    frame["clipless_lower"] = frame["lower"]
    frame["clipped"] = frame["lower"] < 0
    frame["lower"] = frame["lower"].clip(lower=0)
    base = city["forecast"]["point"].to_numpy(dtype=float)
    return {
        "forecast": frame,
        "base_points": [
            {"quarter": label, "point": float(value)}
            for label, value in zip(horizons, base)
        ],
        "delta_by_quarter": [
            {"quarter": label, "delta": round(float(value - base_value), 2)}
            for label, value, base_value in zip(horizons, point, base)
        ],
        "delta_mean": round(float(np.mean(point - base)), 2),
        "residual_mean": round(float(np.nanmean(residual)), 2),
        "residual_sd": round(residual_sd, 2),
    }


def run_clustering(crimes, parks):
    features = park_feature_table(crimes, parks)
    labels, sample_values, k, score, scores, x = cluster_parks(features)
    table, profiles = cluster_profiles(features, labels, sample_values)
    stability = cluster_stability(x, labels, k)
    comparison = cluster_comparison(x, labels, k)
    coords, explained = pca_coordinates(x)
    table["pc1"] = coords[:, 0]
    table["pc2"] = coords[:, 1]
    return {
        "features": features,
        "table": table,
        "profiles": profiles,
        "k": k,
        "score": score,
        "scores": scores,
        "stability": stability,
        "comparison": comparison,
        "pca_explained": explained,
        "acres_missing": int(features.attrs.get("acres_missing", 0)),
    }


# --------------------------------------------------------------------------
# Figures
# --------------------------------------------------------------------------

def _footnote(fig, text):
    fig.text(0.01, 0.01, text, fontsize=7, style="italic", color="#555555")


def fig_forecast(series, result, path, footnote):
    labels = list(series.index)
    y = series.to_numpy()
    bt_labels = result["backtest_fit"]["labels"]
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
                    color=OKABE_ITO[2], alpha=0.2, label=INTERVAL_LABEL_FR)
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
    _footnote(fig, footnote)
    recursive = f"{result['backtest_metrics']['seasonal_naive']['mae']:.2f}"
    rule = f"{result['baseline_mae_seasonal_rule']:.2f}"
    fig.text(
        0.01, 0.032,
        "Comparateur honnête multi-pas : naïve saisonnière récursive "
        f"(MAE moyenne {recursive.replace('.', ',')}) ; la règle saisonnière à "
        f"un pas, valeurs réelles de l'année précédente (MAE {rule.replace('.', ',')}), "
        "sert de référence.",
        fontsize=7, style="italic", color="#555555",
    )
    fig.tight_layout(rect=(0, 0.055, 1, 1))
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def fig_clusters(table, profiles, k, score, explained, path, footnote):
    fig, (ax_map, ax_pca, ax_heat) = plt.subplots(1, 3, figsize=(17, 6))
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
    names = dict(zip(profiles["cluster"], profiles["name"]))
    for cluster in sorted(table["cluster"].unique()):
        sub = colored[colored["cluster"] == cluster]
        ax_map.scatter(sub["lon"], sub["lat"], s=22,
                       color=OKABE_ITO[cluster % len(OKABE_ITO)],
                       label=f"Cluster {cluster} : {names.get(cluster, '')}",
                       alpha=0.85)
    ax_map.set_title(
        f"Profils spatiaux des parcs — k={k}, silhouette={score:.2f}"
    )
    ax_map.set_xlabel("Longitude")
    ax_map.set_ylabel("Latitude")
    ax_map.legend(frameon=False, fontsize=7)
    ax_map.grid(alpha=0.2)

    for cluster in sorted(table["cluster"].unique()):
        sub = table[table["cluster"] == cluster]
        ax_pca.scatter(sub["pc1"], sub["pc2"], s=22,
                       color=OKABE_ITO[cluster % len(OKABE_ITO)],
                       label=f"Cluster {cluster}", alpha=0.85)
    ax_pca.set_title(
        "Projection PCA 2-D "
        f"({explained[0] * 100:.0f} % + {explained[1] * 100:.0f} % de variance)"
    )
    ax_pca.set_xlabel("PC1")
    ax_pca.set_ylabel("PC2")
    ax_pca.grid(alpha=0.2)

    shares = [c for c in profiles.columns if c.startswith("share_")]
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
    _footnote(fig, footnote)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def fig_residuals(residuals, diagnostics, path, footnote):
    clean = residuals.dropna()
    fig, (ax_series, ax_acf) = plt.subplots(1, 2, figsize=(13, 5))
    if clean.empty:
        ax_series.text(
            0.5, 0.5, "Résidus indisponibles (ajustement SARIMAX non convergé)",
            ha="center", va="center", transform=ax_series.transAxes,
        )
        ax_series.set_axis_off()
        ax_acf.set_axis_off()
        _footnote(fig, footnote)
        fig.tight_layout(rect=(0, 0.04, 1, 1))
        fig.savefig(path, dpi=DPI)
        plt.close(fig)
        return
    ax_series.plot(list(clean.index), clean.to_numpy(), color=OKABE_ITO[0], lw=1.0)
    ax_series.axhline(0, color="#999999", lw=0.8)
    ax_series.set_title(
        "Résidus du SARIMAX "
        f"({diagnostics['order']}×{diagnostics['seasonal_order']}), "
        f"Ljung-Box p = {diagnostics['ljung_box_p']:.3f}"
    )
    ax_series.set_xlabel("Trimestre")
    ax_series.set_ylabel("Résidu")
    ax_series.set_xticks(range(0, len(clean), 4))
    ax_series.set_xticklabels(
        [list(clean.index)[i] for i in range(0, len(clean), 4)],
        rotation=45, ha="right", fontsize=7,
    )
    ax_series.grid(alpha=0.25)

    lags = range(1, 2 * SEASON + 1)
    values = clean.to_numpy()
    centre = values - values.mean()
    denominator = float(np.sum(centre ** 2))
    acf = [
        float(np.sum(centre[lag:] * centre[:-lag]) / denominator)
        for lag in lags
    ]
    ax_acf.bar(list(lags), acf, color=OKABE_ITO[0])
    ax_acf.axhline(0, color="#999999", lw=0.8)
    bound = 1.96 / np.sqrt(len(values))
    ax_acf.axhline(bound, color=OKABE_ITO[1], lw=0.8, ls="--")
    ax_acf.axhline(-bound, color=OKABE_ITO[1], lw=0.8, ls="--")
    ax_acf.set_title(
        f"Autocorrélation des résidus (IC {LEVEL_PCT} % en pointillés)"
    )
    ax_acf.set_xlabel("Décalage (trimestres)")
    ax_acf.grid(alpha=0.25)
    _footnote(fig, footnote)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def fig_boroughs(borough_results, path, footnote):
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
                        label=INTERVAL_LABEL_FR)
        ax.set_title(name.title(), fontsize=11)
        ax.set_ylabel("Crimes")
        ax.tick_params(axis="x", rotation=45, labelsize=7)
        ax.grid(alpha=0.2)
    axes[0, 0].legend(frameon=False, fontsize=8)
    history = borough_results[names[0]]["history_labels"]
    fig.suptitle(
        "Prévisions trimestrielles par borough (modèles refit sur "
        f"{history[0]}–{history[-1]})"
    )
    _footnote(fig, footnote)
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
    onset = city["coverage_from"]
    late = late_parks(crimes)

    reconciled = reconcile_forecasts(city, boroughs)
    reconciled_frame = reconciled["forecast"]
    city["forecast"] = reconciled_frame.copy()
    city["forecast"].assign(scope="CITYWIDE")[[
        "scope", "quarter_label", "point", "lower", "upper",
        "clipless_lower", "clipped",
    ]].to_csv(TABLE_DIR / "forecast_city.csv", index=False)

    borough_frames = []
    for borough, result in boroughs.items():
        frame = result["forecast"].copy()
        frame.insert(0, "borough", borough)
        borough_frames.append(frame)
    pd.concat(borough_frames, ignore_index=True).to_csv(
        TABLE_DIR / "forecast_boroughs.csv", index=False,
    )

    sensitivity = interpolation_sensitivity(
        crimes, onset, city["order"], city["seasonal_order"],
    )
    pd.DataFrame(sensitivity).to_csv(
        TABLE_DIR / "interpolation_sensitivity.csv", index=False,
    )
    perimeter = consistent_perimeter(crimes, onset)
    pd.DataFrame(perimeter["points"]).assign(
        excluded=", ".join(perimeter["excluded_parks"]),
    ).to_csv(TABLE_DIR / "forecast_city_without_central_park.csv", index=False)

    clustering = run_clustering(crimes, parks)
    cluster_table = clustering["table"]
    profiles = clustering["profiles"]
    k = clustering["k"]
    score = clustering["score"]
    # `silhouette` is the global retained-solution score (eval-facing, [0, 1]);
    # `sample_silhouette` is each park's own value and can be negative.
    park_out = cluster_table[["park_id", "park", "borough", "cluster",
                              "dominant_type", "total_crimes"]].copy()
    park_out.insert(4, "silhouette", score)
    park_out.insert(5, "sample_silhouette", cluster_table["silhouette"].to_numpy())
    park_out.sort_values(["cluster", "total_crimes"],
                         ascending=[True, False]).to_csv(
        TABLE_DIR / "park_clusters.csv", index=False,
    )
    profiles.to_csv(TABLE_DIR / "cluster_profiles.csv", index=False)

    risk = park_risk_table(crimes, cluster_table)
    risk.to_csv(TABLE_DIR / "park_risk.csv", index=False)

    caveats = build_caveats(crimes, interpolated)
    footnote = build_footnote(crimes, interpolated)
    if onset:
        forecast_footnote = (
            footnote + f" Couverture : dummy post-{onset} (parcs ajoutés à la "
            "source) dans le SARIMAX ; l'artefact de sensibilité exclut "
            "Central Park."
        )
    else:
        forecast_footnote = footnote

    fig_forecast(series, city, FIG_DIR / "fig07_forecast.png", forecast_footnote)
    fig_clusters(
        cluster_table, profiles, k, score, clustering["pca_explained"],
        FIG_DIR / "fig08_clusters.png", footnote,
    )
    fig_boroughs(boroughs, FIG_DIR / "fig09_forecast_boroughs.png", footnote)
    fig_residuals(
        city["residuals"], city["diagnostics"],
        FIG_DIR / "fig10_residuals.png", footnote,
    )

    interval_clipped_rows = int(
        city["forecast"]["clipped"].sum()
        + sum(result["forecast"]["clipped"].sum() for result in boroughs.values())
    )
    city_metrics = {
        **_series_metrics(city),
        "interpolated_quarters": interpolated,
        "n_quarters": int(len(series)),
        "forecast_footnote": forecast_footnote,
        "diagnostics": city["diagnostics"],
        "coverage_handling": {
            "method": (
                "SARIMAX step dummy post_coverage = 1 from the quarter new "
                "parks enter the source; consistent-perimeter sensitivity "
                "excludes Central Park."
            ),
            "coverage_from": onset,
            "n_late_parks": len(late),
            "consistent_perimeter": perimeter,
        },
        "reconciliation": {
            "method": (
                "bottom-up: modelled borough forecasts + seasonal-naive "
                "residual (city minus modelled boroughs) for skipped boroughs"
            ),
            "base_forecast": reconciled["base_points"],
            "delta_by_quarter": reconciled["delta_by_quarter"],
            "delta_mean": reconciled["delta_mean"],
            "residual_mean": reconciled["residual_mean"],
            "residual_sd": reconciled["residual_sd"],
        },
        "interpolation_sensitivity": sensitivity,
    }
    metrics = {
        "ci_alpha": CI_ALPHA,
        "interval_clipped_rows": interval_clipped_rows,
        "interval_note": {"en": INTERVAL_NOTE_EN, "fr": INTERVAL_NOTE_FR},
        "tie_tolerance_pct": round(TIE_TOLERANCE * 100, 2),
        "citywide": city_metrics,
        "boroughs": {
            borough: _series_metrics(result)
            for borough, result in boroughs.items()
        },
        "skipped_boroughs": skipped,
        "clustering": {
            "n_parks": int(len(cluster_table)),
            "min_crimes_ever": MIN_PARK_CRIMES,
            "shrinkage_pseudocount": SHRINKAGE,
            "features": FEATURE_COLUMNS,
            "selected_k": int(k),
            "silhouette": score,
            "silhouette_by_k": clustering["scores"],
            "cluster_sizes": {
                int(c): int(n) for c, n in profiles["n_parks"].items()
            },
            "cluster_names": {
                int(c): str(name) for c, name in
                zip(profiles["cluster"], profiles["name"])
            },
            "stability": clustering["stability"],
            "comparison": clustering["comparison"],
            "pca_explained": clustering["pca_explained"],
            "acres_missing": clustering["acres_missing"],
            "random_state": SEED,
        },
        "park_risk": {
            "n_parks": int(len(risk)),
            "top": [
                {
                    "park": row.park,
                    "borough": row.borough,
                    "crimes_per_100_acres": (
                        None if pd.isna(row.crimes_per_100_acres)
                        else round(float(row.crimes_per_100_acres), 2)
                    ),
                }
                for row in risk.head(10).itertuples()
            ],
        },
        "caveats": caveats,
    }
    with open(METRIC_DIR / "model_metrics.json", "w", encoding="utf-8") as fh:
        json.dump(metrics, fh, ensure_ascii=False, indent=2)

    print(json.dumps({
        "city_model": city["selected_model"],
        "city_mae": city["backtest_metrics"][city["selected_model"]]["mae"],
        "city_mae_sd": city["backtest_metrics"][city["selected_model"]]["mae_sd"],
        "dm_p": city["backtest_metrics"][city["selected_model"]]["dm_p"],
        "baseline_mae": city["backtest_metrics"]["seasonal_naive"]["mae"],
        "baseline_wins": city["baseline_wins"],
        "reconciled_delta_mean": reconciled["delta_mean"],
        "clusters_k": int(k),
        "silhouette": score,
        "ari_mean": clustering["stability"]["ari_mean"],
        "parks_at_floor": int(len(cluster_table)),
        "skipped_boroughs": list(skipped),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
