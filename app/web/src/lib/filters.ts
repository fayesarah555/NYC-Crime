// Pure filter and aggregation helpers shared by every dashboard view.
// The static export has all-period park totals only, so the quarter range
// filters the city/borough series; park-level views ignore it by necessity.

export interface Filters {
  boroughs: string[];
  types: string[];
  /** Inclusive index range into `SeriesData.quarters`. */
  range: [number, number];
  query: string;
}

export interface ParkRow {
  park: string;
  borough: string;
  lat: number | null;
  lon: number | null;
  total: number;
  dominant_type: string;
  cluster: number | null;
  counts: Record<string, number>;
}

export interface SeriesData {
  quarters: string[];
  city: number[];
  city_by_type: Record<string, number[]>;
  boroughs: Record<string, number[]>;
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
 * BROOKLYN/QUEENS rows belong to both boroughs, so either selection keeps
 * them; filtering once means no duplicate when both are selected.
 */
export function matchesBorough(borough: string, selected: string[]): boolean {
  if (selected.length === 0) return true;
  if (borough === 'BROOKLYN/QUEENS') {
    return selected.includes('BROOKLYN') || selected.includes('QUEENS');
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

export function filterParks(parks: ParkRow[], filters: Filters): ParkRow[] {
  const query = normalizeText(filters.query).trim();
  return parks.filter(
    park =>
      matchesBorough(park.borough, filters.boroughs) &&
      selectedCount(park, filters.types) > 0 &&
      (query === '' || normalizeText(park.park).includes(query)),
  );
}

/** Parks drawn on the map: coordinates present and a positive selected total. */
export function mapParks(parks: ParkRow[], filters: Filters): ParkRow[] {
  return filterParks(parks, filters).filter(
    park => park.lat !== null && park.lon !== null,
  );
}

/** Selected parks whose coordinates are missing; never silently dropped. */
export function parksWithoutCoordinates(
  parks: ParkRow[],
  filters: Filters,
): number {
  return filterParks(parks, filters).filter(
    park => park.lat === null || park.lon === null,
  ).length;
}

/**
 * Parks drawn nowhere because the selection leaves them at zero crimes.
 * The export only holds the 792 parks ever hit, so the 363 never-hit parks
 * cannot be counted here (no row, no coordinates).
 */
export function zeroCrimeParks(parks: ParkRow[], filters: Filters): number {
  const query = normalizeText(filters.query).trim();
  return parks.filter(
    park =>
      matchesBorough(park.borough, filters.boroughs) &&
      (query === '' || normalizeText(park.park).includes(query)) &&
      park.lat !== null &&
      park.lon !== null &&
      selectedCount(park, filters.types) === 0,
  ).length;
}

/** Inclusive quarter labels for the slider range, clamped to the series. */
export function quarterLabels(
  series: SeriesData,
  range: [number, number],
): string[] {
  const max = series.quarters.length - 1;
  const start = Math.max(0, Math.min(range[0], max));
  const end = Math.max(start, Math.min(range[1], max));
  return series.quarters.slice(start, end + 1);
}

/** Quarterly crimes for the city, or the sum of the selected borough series. */
export function trendData(
  series: SeriesData,
  filters: Filters,
): {quarter: string; crimes: number}[] {
  return quarterLabels(series, filters.range).map(quarter => {
    const index = series.quarters.indexOf(quarter);
    let crimes = series.city[index];
    if (filters.boroughs.length > 0) {
      crimes = filters.boroughs.reduce(
        (sum, borough) => sum + (series.boroughs[borough]?.[index] ?? 0),
        0,
      );
    }
    return {quarter, crimes};
  });
}

/**
 * Quarterly totals the change KPI compares: borough sums when boroughs are
 * selected, else the selected crime types, else the all-type city series.
 * shortcut: no borough x type x quarter export, so a borough selection wins
 * over the type selection; upgrade if the export gains that breakdown.
 */
export function changeSeries(
  series: SeriesData,
  filters: Filters,
): {quarter: string; crimes: number}[] {
  return quarterLabels(series, filters.range).map(quarter => {
    const index = series.quarters.indexOf(quarter);
    if (filters.boroughs.length > 0) {
      const crimes = filters.boroughs.reduce(
        (sum, borough) => sum + (series.boroughs[borough]?.[index] ?? 0),
        0,
      );
      return {quarter, crimes};
    }
    if (filters.types.length > 0) {
      const crimes = filters.types.reduce(
        (sum, type) => sum + (series.city_by_type[type]?.[index] ?? 0),
        0,
      );
      return {quarter, crimes};
    }
    return {quarter, crimes: series.city[index]};
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
  series: SeriesData,
): Kpis {
  const rows = filterParks(parks, filters);
  const total = rows.reduce(
    (sum, park) => sum + selectedCount(park, filters.types),
    0,
  );

  let topType: string | null = null;
  if (total > 0) {
    const pool = filters.types.length ? filters.types : Object.keys(rows[0].counts);
    const totals = new Map<string, number>();
    for (const type of pool) {
      const count = rows.reduce(
        (sum, park) => sum + (park.counts[type] ?? 0),
        0,
      );
      if (count > 0) totals.set(type, count);
    }
    const ranked = [...totals.entries()].sort((a, b) => b[1] - a[1]);
    topType = ranked.length > 0 ? ranked[0][0] : null;
  }

  const trend = changeSeries(series, filters);
  const latest = trend[trend.length - 1];
  let changePct: number | null = null;
  let changeBasis: Kpis['changeBasis'] = null;
  if (total > 0 && latest) {
    const previous = trend.find(point => point.quarter === yearAgo(latest.quarter));
    if (previous && previous.crimes > 0) {
      changePct = ((latest.crimes - previous.crimes) / previous.crimes) * 100;
      changeBasis = 'annuelle';
    } else if (
      filters.types.length === 0 &&
      trend.length >= 2 &&
      trend[trend.length - 2].crimes > 0
    ) {
      // Type-filtered series show — rather than a quarterly stand-in.
      const prior = trend[trend.length - 2].crimes;
      changePct = ((latest.crimes - prior) / prior) * 100;
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
  limit = 10,
): ParkRow[] {
  return [...filterParks(parks, filters)]
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
): {types: string[]; rows: BoroughRow[]} {
  const types = filters.types.length ? filters.types : CRIME_TYPES;
  const byBorough = new Map<string, Record<string, number>>();
  for (const park of filterParks(parks, filters)) {
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
  return `${value > 0 ? '+' : ''}${value.toFixed(1)} %`;
}
