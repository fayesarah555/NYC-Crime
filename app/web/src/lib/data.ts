// Typed access to the seven static JSON files exported by export/export_web.py
// (ticket 0038). Consumers import datasets from here, never the JSON directly.
// The payloads are validated at load; a malformed file surfaces `dataError`
// instead of crashing a view later.

import metaJson from '../data/meta.json';
import parksJson from '../data/parks.json';
import seriesJson from '../data/series.json';
import boroughTypeJson from '../data/borough_type.json';
import forecastJson from '../data/forecast.json';
import clustersJson from '../data/clusters.json';
import cubesJson from '../data/cubes.json';

export interface Meta {
  generated_by: string;
  /** UTC ISO timestamp of the export run. */
  generated_at: string;
  /** Short HEAD sha of the export run, "unknown" when git was unavailable.
   * Suffixed "-dirty" when the worktree had uncommitted changes. */
  git_commit: string;
  /** True when the worktree was dirty at export time. */
  git_dirty: boolean;
  /** Present when dirty: the commit does not contain these artefacts. */
  git_commit_note?: {fr: string; en: string};
  pipeline_version: string;
  /** sha256 of data/raw/manifest.json, "unknown" when the file was absent. */
  source_manifest_sha256: string;
  /** Payload schema; 2 introduced cubes.json. */
  schema_version: number;
  quarters_total: number;
  missing_quarters: string[];
  /** Two-sided interval alpha used for the forecast bounds (0.05 -> 95 %). */
  ci_alpha: number;
  /** Clickable sources rendered by the Méthode tab (exported by the pipeline). */
  source_links?: {label: string; url: string}[];
  periods: {
    first: string;
    last: string;
    count: number;
    missing: string[];
    labels: string[];
  };
  totals: {
    crimes: number;
    park_quarters: number;
    parks: number;
    parks_with_crimes: number;
  };
  geo: {
    parks: number;
    matched: number;
    coverage_pct: number;
    weighted_coverage_pct: number;
  };
  /** Combined BROOKLYN/QUEENS label: source parks vs parks with crimes. */
  combined_borough: {
    label: string;
    parks_source: number;
    parks_with_crimes: number;
  };
  sources: string[];
  caveats: string[];
  /** French rendering of `caveats`, same order; what the UI displays. */
  caveats_fr: string[];
}

export interface Park {
  /** Stable NYC Parks property id; the cube is keyed by it, the name is display. */
  park_id: string;
  park: string;
  borough: string;
  lat: number | null;
  lon: number | null;
  acres: number | null;
  total: number;
  dominant_type: string;
  cluster: number | null;
  /** Crimes per 100 acres over the park's whole history; null without acres. */
  crimes_per_100_acres: number | null;
  /** Rank by crimes per 100 acres, 1 = highest; null without acres. */
  risk_rank: number | null;
  /** First–last quarter the park appears in the source. */
  coverage_era: string;
  counts: Record<string, number>;
}

export interface Series {
  quarters: string[];
  city: number[];
  /** Citywide quarterly totals per crime type; each array aligns with `quarters`. */
  city_by_type: Record<string, number[]>;
  boroughs: Record<string, number[]>;
}

export interface BoroughType {
  crime_types: string[];
  boroughs: {borough: string; total: number; counts: Record<string, number>}[];
}

export interface ForecastPoint {
  quarter: string;
  point: number;
  lower: number;
  upper: number;
}

/** Best non-baseline model, with its DM test against seasonal-naive. */
export interface ChallengerMetrics {
  model: string;
  mae: number;
  mae_sd: number;
  dm_p: number | null;
}

/** Pooled rolling-origin backtest metrics, one entry per candidate model. */
export interface BacktestModelMetrics {
  mae: number;
  mae_sd: number;
  rmse: number;
  mape: number | null;
  coverage_95: number;
  dm_p: number | null;
}

export interface BacktestOrigin {
  train_end: string;
  test_window: string[];
  metrics: {model: string; mae: number; rmse: number}[];
}

/** Bottom-up reconciliation block; citywide only. */
export interface Reconciliation {
  method: string;
  delta_mean: number;
  residual_mean: number;
  residual_sd: number;
}

/**
 * Backtest and selection metrics, typed instead of Record<string, unknown>.
 * Borough metrics share the shape but omit the city-only fields.
 */
export interface ForecastMetrics {
  selected_model: string;
  selected_mae: number;
  selected_mae_sd: number;
  selected_rmse: number;
  selected_mape: number | null;
  baseline_mae: number;
  baseline_mae_sd: number;
  /** Textbook one-step rule (same season a year back, observed values). */
  baseline_mae_seasonal_rule: number;
  baseline_wins: boolean;
  dm_p_vs_naive: number | null;
  best_challenger?: ChallengerMetrics | null;
  improvement_pct: number;
  backtest_quarters: number;
  backtest_window: string[];
  backtest_origins: BacktestOrigin[];
  backtest_metrics: Record<string, BacktestModelMetrics>;
  interval_coverage_95: number;
  tie_tolerance_pct: number;
  reconciliation?: Reconciliation | null;
  selection_caveat_fr?: string;
  forecast_footnote?: string;
}

export interface Forecast {
  city: ForecastPoint[];
  boroughs: Record<string, ForecastPoint[]>;
  metrics: {
    city: ForecastMetrics;
    boroughs: Record<string, ForecastMetrics>;
    skipped_boroughs: Record<string, string>;
  };
  caveats: string[];
  /** Clipping caveat for the interval bounds; the French one is displayed. */
  caveat: string;
  caveat_fr: string;
}

export interface ClusterProfile {
  cluster: number;
  n_parks: number;
  total_crimes: number;
  mean_acres: number;
  mean_silhouette: number;
  top_type: string;
  /** Honest French label: the two over-represented types vs the city mix. */
  name: string;
}

export interface ClusterPark {
  park: string;
  borough: string;
  cluster: number;
  sample_silhouette: number;
  crimes_per_100_acres: number | null;
}

export interface Clusters {
  k: number;
  silhouette: number;
  features: string[];
  profiles: ClusterProfile[];
  parks: ClusterPark[];
}

export interface Cube {
  /** Shared quarter index; every cell's quarters are keys into it. */
  quarters: string[];
  /** Shared crime-type order; every cell is one count per type. */
  crime_types: string[];
  /** park_id -> quarter label -> counts, only for nonzero park-quarters.
   * A null count means the workbook had no such column: missing, never 0. */
  parks: Record<string, Record<string, (number | null)[]>>;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(item => typeof item === 'string');
}

function isCount(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0;
}

function isCountArray(value: unknown): value is (number | null)[] {
  return Array.isArray(value) && value.every(item => item === null || isCount(item));
}

function isCountRecord(value: unknown): value is Record<string, number> {
  return (
    isObject(value) &&
    Object.values(value).every(
      count => typeof count === 'number' && Number.isFinite(count),
    )
  );
}

function isAlignedNumberArrays(
  value: unknown,
  length: number,
  label: string,
  add: (message: string) => void,
): void {
  if (!isObject(value)) {
    add(`${label}: objet attendu`);
    return;
  }
  for (const [key, series] of Object.entries(value)) {
    if (!Array.isArray(series) || series.length !== length) {
      add(`${label}.${key}: ${length} valeurs attendues`);
    } else if (!series.every(item => typeof item === 'number')) {
      add(`${label}.${key}: nombres attendus`);
    }
  }
}

/**
 * Shape checks for the seven payloads; returns one message per problem,
 * empty when the bundle is usable. Sum invariants belong to the exporter.
 */
export function validateData(raw: {
  meta: unknown;
  parks: unknown;
  series: unknown;
  borough_type: unknown;
  forecast: unknown;
  clusters: unknown;
  cubes: unknown;
}): string[] {
  const problems: string[] = [];
  const add = (message: string) => problems.push(message);

  const meta = raw.meta;
  if (!isObject(meta)) {
    add('meta: objet attendu');
  } else {
    for (const key of [
      'generated_at',
      'git_commit',
      'pipeline_version',
      'source_manifest_sha256',
    ] as const) {
      if (typeof meta[key] !== 'string') add(`meta.${key}: chaîne attendue`);
    }
    if (meta.schema_version !== 3) {
      add(`meta.schema_version: 3 attendu, reçu ${String(meta.schema_version)}`);
    }
    if (!isCount(meta.quarters_total)) {
      add('meta.quarters_total: entier attendu');
    }
    if (!isStringArray(meta.missing_quarters)) {
      add('meta.missing_quarters: tableau de chaînes attendu');
    }
    if (typeof meta.ci_alpha !== 'number') {
      add('meta.ci_alpha: nombre attendu');
    }
    if (!isObject(meta.periods) || !isStringArray(meta.periods.labels)) {
      add('meta.periods.labels: tableau de chaînes attendu');
    }
    if (!isObject(meta.totals) || typeof meta.totals.crimes !== 'number') {
      add('meta.totals.crimes: nombre attendu');
    }
  }

  const seriesRaw = raw.series;
  let quarters: string[] | null = null;
  if (!isObject(seriesRaw) || !isStringArray(seriesRaw.quarters)) {
    add('series.quarters: tableau de chaînes attendu');
  } else if (seriesRaw.quarters.length === 0) {
    add('series.quarters: vide');
  } else {
    quarters = seriesRaw.quarters;
    const series = seriesRaw;
    if (
      !Array.isArray(series.city) ||
      series.city.length !== quarters.length
    ) {
      add('series.city: une valeur par trimestre attendue');
    }
    isAlignedNumberArrays(
      series.city_by_type,
      quarters.length,
      'series.city_by_type',
      add,
    );
    isAlignedNumberArrays(
      series.boroughs,
      quarters.length,
      'series.boroughs',
      add,
    );
  }

  const parks = raw.parks;
  if (!Array.isArray(parks)) {
    add('parks: tableau attendu');
  } else {
    for (const row of parks) {
      if (!isObject(row) || typeof row.park !== 'string') {
        add('parks: ligne sans nom de parc');
        break;
      }
      if (typeof row.park_id !== 'string') {
        add(`parks.${row.park}: park_id attendu`);
        break;
      }
      if (typeof row.borough !== 'string' || typeof row.total !== 'number') {
        add(`parks.${row.park}: borough et total attendus`);
        break;
      }
      if (!isCountRecord(row.counts)) {
        add(`parks.${row.park}.counts: nombres attendus`);
        break;
      }
      if (
        (row.lat !== null && typeof row.lat !== 'number') ||
        (row.lon !== null && typeof row.lon !== 'number')
      ) {
        add(`parks.${row.park}: coordonnées nulles ou numériques attendues`);
        break;
      }
      if (
        (row.crimes_per_100_acres !== null &&
          typeof row.crimes_per_100_acres !== 'number') ||
        (row.risk_rank !== null && !isCount(row.risk_rank)) ||
        typeof row.coverage_era !== 'string'
      ) {
        add(`parks.${row.park}: risque par acre attendu`);
        break;
      }
    }
  }

  const boroughType = raw.borough_type;
  if (
    !isObject(boroughType) ||
    !isStringArray(boroughType.crime_types) ||
    !Array.isArray(boroughType.boroughs)
  ) {
    add('borough_type: crime_types et boroughs attendus');
  }

  const forecast = raw.forecast;
  if (
    !isObject(forecast) ||
    !Array.isArray(forecast.city) ||
    !isObject(forecast.boroughs) ||
    !isObject(forecast.metrics) ||
    !Array.isArray(forecast.caveats)
  ) {
    add('forecast: city, boroughs, metrics et caveats attendus');
  } else {
    for (const point of forecast.city) {
      if (
        !isObject(point) ||
        typeof point.quarter !== 'string' ||
        typeof point.point !== 'number' ||
        typeof point.lower !== 'number' ||
        typeof point.upper !== 'number'
      ) {
        add('forecast.city: points trimestre/point/bornes attendus');
        break;
      }
    }
  }
  // The UI reads these metric fields directly, so a malformed block must stop
  // the load instead of rendering "undefined" in a KPI.
  if (isObject(forecast) && isObject(forecast.metrics)) {
    const scopes: [string, unknown][] = [
      ['city', forecast.metrics.city],
      ...(isObject(forecast.metrics.boroughs)
        ? Object.entries(forecast.metrics.boroughs)
        : []),
    ];
    for (const [scope, metrics] of scopes) {
      const label = `forecast.metrics.${scope}`;
      if (!isObject(metrics)) {
        add(`${label}: objet attendu`);
        continue;
      }
      if (typeof metrics.selected_model !== 'string') {
        add(`${label}.selected_model: chaîne attendue`);
      }
      for (const key of [
        'selected_mae',
        'selected_mae_sd',
        'selected_rmse',
        'baseline_mae',
        'baseline_mae_seasonal_rule',
        'improvement_pct',
      ] as const) {
        if (typeof metrics[key] !== 'number') {
          add(`${label}.${key}: nombre attendu`);
        }
      }
      if (!isStringArray(metrics.backtest_window)) {
        add(`${label}.backtest_window: tableau de chaînes attendu`);
      }
      if (!isObject(metrics.backtest_metrics)) {
        add(`${label}.backtest_metrics: objet attendu`);
      }
    }
  }

  const clusters = raw.clusters;
  if (
    !isObject(clusters) ||
    typeof clusters.k !== 'number' ||
    !Array.isArray(clusters.profiles) ||
    !Array.isArray(clusters.parks)
  ) {
    add('clusters: k, profiles et parks attendus');
  }

  const cubes = raw.cubes;
  if (!isObject(cubes)) {
    add('cubes: objet attendu');
  } else {
    const cubeQuarters = cubes.quarters;
    const crimeTypes = cubes.crime_types;
    if (!isStringArray(cubeQuarters)) {
      add('cubes.quarters: tableau de chaînes attendu');
    } else if (
      quarters !== null &&
      JSON.stringify(cubeQuarters) !== JSON.stringify(quarters)
    ) {
      add("cubes.quarters: doit égaler series.quarters (index partagé)");
    }
    if (!isStringArray(crimeTypes) || crimeTypes.length === 0) {
      add('cubes.crime_types: ordre des types attendu');
    } else if (!isObject(cubes.parks)) {
      add('cubes.parks: objet attendu');
    } else {
      const width = crimeTypes.length;
      // A key outside cubes.quarters has no index in the shared grid.
      const knownQuarters = isStringArray(cubeQuarters)
        ? new Set(cubeQuarters)
        : null;
      outer: for (const [park, cells] of Object.entries(cubes.parks)) {
        if (!isObject(cells)) {
          add(`cubes.parks.${park}: objet trimestre attendu`);
          break;
        }
        for (const [quarter, counts] of Object.entries(cells)) {
          if (knownQuarters !== null && !knownQuarters.has(quarter)) {
            add(`cubes.parks.${park}.${quarter}: trimestre inconnu`);
            break outer;
          }
          if (!isCountArray(counts) || counts.length !== width) {
            add(`cubes.parks.${park}.${quarter}: ${width} entiers attendus`);
            break outer;
          }
        }
      }
    }
  }

  return problems;
}

const dataProblems = validateData({
  meta: metaJson,
  parks: parksJson,
  series: seriesJson,
  borough_type: boroughTypeJson,
  forecast: forecastJson,
  clusters: clustersJson,
  cubes: cubesJson,
});

/** Non-null when the bundled payloads fail validation; views show it. */
export const dataError: string | null =
  dataProblems.length === 0
    ? null
    : `Données statiques invalides : ${dataProblems.join(' ; ')}.`;

export const meta: Meta = metaJson;
export const parks: Park[] = parksJson;
export const series: Series = seriesJson;
export const boroughType: BoroughType = boroughTypeJson;
export const forecast: Forecast = forecastJson;
export const clusters: Clusters = clustersJson;
export const cube: Cube = cubesJson;
