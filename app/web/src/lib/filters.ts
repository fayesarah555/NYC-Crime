// Pure filter and aggregation helpers shared by every dashboard view.
// Every count derives from the park x quarter x type cube, so the quarter
// range and the type/borough filters mean the same thing in all four views.

import type {Cube} from './data';
import {fmtFixed} from './format'

export interface Filters {
  boroughs: string[];
  types: string[];
  /** Inclusive index range into `Cube.quarters`. */
  range: [number, number];
  query: string;
}

export interface ParkRow {
  park_id: string;
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

export const CRIME_TYPES = [
  'BURGLARY',
  'FELONY ASSAULT',
  'GRAND LARCENY',
  'GRAND LARCENY AUTO',
  'MURDER',
  'RAPE',
  'ROBBERY',
];

export const BOROUGH_OPTIONS = [
  'BRONX',
  'BROOKLYN',
  'BROOKLYN/QUEENS',
  'MANHATTAN',
  'QUEENS',
  'STATEN ISLAND',
];

export const SHORT_TYPE_LABELS: Record<string, string> = {
  BURGLARY: 'Cambriolage',
  'FELONY ASSAULT': 'Agression',
  'GRAND LARCENY': 'Larcin',
  'GRAND LARCENY AUTO': 'Vol de véhicule',
  MURDER: 'Meurtre',
  RAPE: 'Viol',
  ROBBERY: 'Vol qualifié',
};

export function typeLabel(type: string): string {
  return SHORT_TYPE_LABELS[type] ?? type;
}

/** Lowercase, accent-free text for park search. */
export function normalizeText(value: string): string {
  return value
    .normalize('NFKD')
    .replace(/\p{M}/gu, '')
    .toLowerCase();
}

/** "2026Q2" -> "2025Q2". */
export function yearAgo(quarter: string): string {
  const [year, q] = quarter.split('Q');
  return `${Number(year) - 1}Q${q}`;
}

/**
 * BROOKLYN/QUEENS is its own source label (4 parks), so selecting it returns
 * exactly those 4 parks and not BROOKLYN + QUEENS's 433: its own series (114
 * crimes) backs the label, and widening the park set would make the KPI
 * contradict the trend. BROOKLYN or QUEENS alone still keep the combined
 * parks, because the source files them under both; filtering once means no
 * duplicate when both are selected.
 */
export function matchesBorough(borough: string, selected: string[]): boolean {
  if (selected.length === 0) return true;
  if (borough === 'BROOKLYN/QUEENS') {
    return (
      selected.includes('BROOKLYN/QUEENS') ||
      selected.includes('BROOKLYN') ||
      selected.includes('QUEENS')
    );
  }
  return selected.includes(borough);
}

/** Crime count for a park under the selected types (all types when empty). */
export function selectedCount(park: ParkRow, types: string[]): number {
  if (types.length === 0) return park.total;
  return types.reduce((sum, type) => sum + (park.counts[type] ?? 0), 0);
}

/** Most frequent type inside the selection; deterministic ties by type order. */
export function dominantType(park: ParkRow, types: string[]): string {
  const pool = types.length ? types : Object.keys(park.counts);
  let best = park.dominant_type;
  let bestCount = -1;
  for (const type of pool) {
    const count = park.counts[type] ?? 0;
    if (count > bestCount) {
      best = type;
      bestCount = count;
    }
  }
  return best;
}

/** Quarter labels for the slider range, clamped to the shared index. */
export function quarterWindow(
  cube: Cube,
  range: [number, number],
): string[] {
  const max = cube.quarters.length - 1;
  const start = Math.max(0, Math.min(range[0], max));
  const end = Math.max(start, Math.min(range[1], max));
  return cube.quarters.slice(start, end + 1);
}

/** Per-type counts for one park_id inside the quarter window; null is missing. */
export function parkCounts(
  cube: Cube,
  parkId: string,
  window: string[],
): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const type of cube.crime_types) counts[type] = 0;
  const cells = cube.parks[parkId];
  if (cells === undefined) return counts;
  for (const quarter of window) {
    const cell = cells[quarter];
    if (cell === undefined) continue;
    cube.crime_types.forEach((type, index) => {
      const value = cell[index];
      if (value !== null && value !== undefined) {
        counts[type] = (counts[type] ?? 0) + value;
      }
    });
  }
  return counts;
}

/** A park row whose counts and total cover the filter's quarter window. */
function windowRow(cube: Cube, park: ParkRow, window: string[]): ParkRow {
  const counts = parkCounts(cube, park.park_id, window);
  return {
    ...park,
    counts,
    total: Object.values(counts).reduce((sum, value) => sum + value, 0),
  };
}

function matchesQuery(park: ParkRow, query: string): boolean {
  return query === '' || normalizeText(park.park).includes(query);
}

/** Selected parks (window-scoped counts) with at least one selected crime. */
export function filterParks(
  parks: ParkRow[],
  filters: Filters,
  cube: Cube,
): ParkRow[] {
  const window = quarterWindow(cube, filters.range);
  const query = normalizeText(filters.query).trim();
  const rows: ParkRow[] = [];
  for (const park of parks) {
    if (!matchesBorough(park.borough, filters.boroughs)) continue;
    if (!matchesQuery(park, query)) continue;
    const row = windowRow(cube, park, window);
    if (selectedCount(row, filters.types) > 0) rows.push(row);
  }
  return rows;
}

/** Parks drawn on the map: coordinates present and a positive selected total. */
export function mapParks(
  parks: ParkRow[],
  filters: Filters,
  cube: Cube,
): ParkRow[] {
  return filterParks(parks, filters, cube).filter(
    park => park.lat !== null && park.lon !== null,
  );
}

/** Selected parks whose coordinates are missing; never silently dropped. */
export function parksWithoutCoordinates(
  parks: ParkRow[],
  filters: Filters,
  cube: Cube,
): number {
  return filterParks(parks, filters, cube).filter(
    park => park.lat === null || park.lon === null,
  ).length;
}

/**
 * Parks drawn nowhere because the selection leaves them at zero crimes in the
 * quarter window. The export only holds the 792 parks ever hit, so the 363
 * never-hit parks cannot be counted here (no row, no coordinates).
 */
export function zeroCrimeParks(
  parks: ParkRow[],
  filters: Filters,
  cube: Cube,
): number {
  const window = quarterWindow(cube, filters.range);
  const query = normalizeText(filters.query).trim();
  return parks.filter(
    park =>
      matchesBorough(park.borough, filters.boroughs) &&
      matchesQuery(park, query) &&
      park.lat !== null &&
      park.lon !== null &&
      selectedCount(windowRow(cube, park, window), filters.types) === 0,
  ).length;
}

export interface TrendPoint {
  quarter: string;
  crimes: number;
}

/**
 * Quarterly trend honouring every filter: borough x type x quarter derived
 * from the cube, so selecting types and boroughs together stays exact.
 */
export function trendData(
  parks: ParkRow[],
  filters: Filters,
  cube: Cube,
): TrendPoint[] {
  const window = quarterWindow(cube, filters.range);
  const selected = filterParks(parks, filters, cube).map(row => row.park_id);
  const typeIndexes = cube.crime_types
    .map((type, index) => (filters.types.includes(type) ? index : -1))
    .filter(index => index >= 0);
  return window.map(quarter => {
    let crimes = 0;
    for (const parkId of selected) {
      const cell = cube.parks[parkId]?.[quarter];
      if (cell === undefined) continue;
      const indexes = filters.types.length === 0
        ? cell.map((_, index) => index)
        : typeIndexes;
      for (const index of indexes) {
        const value = cell[index];
        if (value !== null && value !== undefined) crimes += value;
      }
    }
    return {quarter, crimes};
  });
}

export interface Kpis {
  total: number;
  parks: number;
  topType: string | null;
  latestQuarter: string | null;
  changePct: number | null;
  changeBasis: 'annuelle' | 'trimestrielle' | null;
}

export function computeKpis(
  parks: ParkRow[],
  filters: Filters,
  cube: Cube,
): Kpis {
  const rows = filterParks(parks, filters, cube);
  const total = rows.reduce(
    (sum, park) => sum + selectedCount(park, filters.types),
    0,
  );

  let topType: string | null = null;
  const firstRow = rows[0];
  if (total > 0 && firstRow) {
    const pool = filters.types.length ? filters.types : Object.keys(firstRow.counts);
    const totals = new Map<string, number>();
    for (const type of pool) {
      const count = rows.reduce(
        (sum, park) => sum + (park.counts[type] ?? 0),
        0,
      );
      if (count > 0) totals.set(type, count);
    }
    const ranked = [...totals.entries()].sort((a, b) => b[1] - a[1]);
    const best = ranked[0];
    topType = best ? best[0] : null;
  }

  const trend = trendData(parks, filters, cube);
  const latest = trend[trend.length - 1];
  const prior = trend[trend.length - 2];
  let changePct: number | null = null;
  let changeBasis: Kpis['changeBasis'] = null;
  if (total > 0 && latest) {
    const previous = trend.find(point => point.quarter === yearAgo(latest.quarter));
    if (previous && previous.crimes > 0) {
      changePct = ((latest.crimes - previous.crimes) / previous.crimes) * 100;
      changeBasis = 'annuelle';
    } else if (
      filters.types.length === 0 &&
      prior !== undefined &&
      prior.crimes > 0
    ) {
      // Type-filtered series show — rather than a quarterly stand-in.
      changePct = ((latest.crimes - prior.crimes) / prior.crimes) * 100;
      changeBasis = 'trimestrielle';
    }
  }

  return {
    total,
    parks: rows.length,
    topType,
    latestQuarter: latest?.quarter ?? null,
    changePct,
    changeBasis,
  };
}

export function topParks(
  parks: ParkRow[],
  filters: Filters,
  cube: Cube,
  limit = 10,
): ParkRow[] {
  return [...filterParks(parks, filters, cube)]
    .sort(
      (a, b) =>
        selectedCount(b, filters.types) - selectedCount(a, filters.types),
    )
    .slice(0, limit);
}

export interface BoroughRow {
  borough: string;
  counts: Record<string, number>;
  total: number;
}

export function boroughTypeMatrix(
  parks: ParkRow[],
  filters: Filters,
  cube: Cube,
): {types: string[]; rows: BoroughRow[]} {
  const types = filters.types.length ? filters.types : cube.crime_types;
  const byBorough = new Map<string, Record<string, number>>();
  for (const park of filterParks(parks, filters, cube)) {
    const counts = byBorough.get(park.borough) ?? {};
    for (const type of types) {
      counts[type] = (counts[type] ?? 0) + (park.counts[type] ?? 0);
    }
    byBorough.set(park.borough, counts);
  }
  const rows = BOROUGH_OPTIONS.filter(borough => byBorough.has(borough)).map(
    borough => {
      const counts = byBorough.get(borough)!;
      return {
        borough,
        counts,
        total: types.reduce((sum, type) => sum + (counts[type] ?? 0), 0),
      };
    },
  );
  return {types, rows};
}

export function formatInt(value: number): string {
  return value.toLocaleString('fr-FR');
}

/** French plural: 0 and 1 stay singular, 2+ take the plural form. */
export function plural(
  count: number,
  singular: string,
  pluralForm = `${singular}s`,
): string {
  return count > 1 ? pluralForm : singular;
}

export function formatPct(value: number | null): string {
  if (value === null) return '—';
  return `${value > 0 ? '+' : ''}${fmtFixed(value, 1)} %`;
}
