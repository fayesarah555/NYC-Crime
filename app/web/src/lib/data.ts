// Typed access to the six static JSON files exported by export/export_web.py
// (ticket 0038). Consumers import datasets from here, never the JSON directly.

import metaJson from '../../public/data/meta.json';
import parksJson from '../../public/data/parks.json';
import seriesJson from '../../public/data/series.json';
import boroughTypeJson from '../../public/data/borough_type.json';
import forecastJson from '../../public/data/forecast.json';
import clustersJson from '../../public/data/clusters.json';

export interface Meta {
  generated_by: string;
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
  sources: string[];
  caveats: string[];
  /** French rendering of `caveats`, same order; what the UI displays. */
  caveats_fr: string[];
}

export interface Park {
  park: string;
  borough: string;
  lat: number | null;
  lon: number | null;
  acres: number | null;
  total: number;
  dominant_type: string;
  cluster: number | null;
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

export interface Forecast {
  city: ForecastPoint[];
  boroughs: Record<string, ForecastPoint[]>;
  metrics: {
    city: Record<string, unknown>;
    boroughs: Record<string, Record<string, unknown>>;
    skipped_boroughs: Record<string, string>;
  };
  caveats: string[];
}

export interface ClusterProfile {
  cluster: number;
  n_parks: number;
  total_crimes: number;
  mean_acres: number;
  mean_silhouette: number;
  top_type: string;
}

export interface ClusterPark {
  park: string;
  borough: string;
  cluster: number;
  sample_silhouette: number;
}

export interface Clusters {
  k: number;
  silhouette: number;
  features: string[];
  profiles: ClusterProfile[];
  parks: ClusterPark[];
}

export const meta: Meta = metaJson;
export const parks: Park[] = parksJson;
export const series: Series = seriesJson;
export const boroughType: BoroughType = boroughTypeJson;
export const forecast: Forecast = forecastJson;
export const clusters: Clusters = clustersJson;
