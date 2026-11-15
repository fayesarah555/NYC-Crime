import {describe, expect, it} from 'vitest';
import {meta, parks, series} from './data';
import {
  boroughTypeMatrix,
  computeKpis,
  filterParks,
  formatPct,
  mapParks,
  normalizeText,
  parksWithoutCoordinates,
  plural,
  quarterLabels,
  topParks,
  trendData,
  zeroCrimeParks,
  type Filters,
  type ParkRow,
} from './filters';

const base: Filters = {
  boroughs: [],
  types: [],
  range: [0, series.quarters.length - 1],
  query: '',
};

const rows = parks as ParkRow[];

function synthetic(park: string, borough: string, counts: Record<string, number>): ParkRow {
  return {
    park,
    borough,
    lat: null,
    lon: null,
    total: Object.values(counts).reduce((sum, value) => sum + value, 0),
    dominant_type: 'GRAND LARCENY',
    cluster: null,
    counts,
  };
}

describe('computeKpis — reconciliation with the Streamlit app', () => {
  it('matches 12 526 crimes, 792 parks, Larcin and +2.7 %', () => {
    const kpis = computeKpis(rows, base, series);
    expect(kpis.total).toBe(12526);
    expect(kpis.total).toBe(meta.totals.crimes);
    expect(kpis.parks).toBe(792);
    expect(kpis.parks).toBe(meta.totals.parks_with_crimes);
    expect(kpis.topType).toBe('GRAND LARCENY');
    expect(kpis.latestQuarter).toBe('2026Q2');
    expect(kpis.changeBasis).toBe('annuelle');
    expect(kpis.changePct).toBeCloseTo(2.72, 1);
    expect(formatPct(kpis.changePct)).toBe('+2.7 %');
  });

  it('returns 0 / 0 / — / — for an empty selection', () => {
    const kpis = computeKpis([], base, series);
    expect(kpis.total).toBe(0);
    expect(kpis.parks).toBe(0);
    expect(kpis.topType).toBeNull();
    expect(kpis.changePct).toBeNull();
    expect(formatPct(kpis.changePct)).toBe('—');
  });

  it('returns 0 / 0 / — / — when the search matches nothing', () => {
    const kpis = computeKpis(rows, {...base, query: 'zzz-nowhere'}, series);
    expect(kpis.total).toBe(0);
    expect(kpis.parks).toBe(0);
    expect(kpis.topType).toBeNull();
    expect(kpis.changePct).toBeNull();
  });

  it('sums park totals to the citywide total', () => {
    const total = rows.reduce((sum, park) => sum + park.total, 0);
    expect(total).toBe(12526);
  });
});

describe('annual change respects the crime-type filter', () => {
  it('computes BURGLARY 2026Q2 vs 2025Q2: 3 against 5 cases, -40.0 %', () => {
    const i2025 = series.quarters.indexOf('2025Q2');
    const i2026 = series.quarters.indexOf('2026Q2');
    expect(series.city_by_type.BURGLARY[i2025]).toBe(5);
    expect(series.city_by_type.BURGLARY[i2026]).toBe(3);
    const kpis = computeKpis(rows, {...base, types: ['BURGLARY']}, series);
    expect(kpis.changeBasis).toBe('annuelle');
    expect(kpis.changePct).toBeCloseTo(-40, 6);
    expect(formatPct(kpis.changePct)).toBe('-40.0 %');
  });

  it('Larcin shows its own +4.4 %, not the all-type +2.7 %', () => {
    const kpis = computeKpis(rows, {...base, types: ['GRAND LARCENY']}, series);
    expect(kpis.changePct).toBeCloseTo(4.4, 1);
  });

  it('shows — when the selected types have no year-ago quarter', () => {
    const kpis = computeKpis(rows, {...base, types: ['BURGLARY'], range: [0, 0]}, series);
    expect(kpis.changeBasis).toBeNull();
    expect(formatPct(kpis.changePct)).toBe('—');
  });
});

describe('borough filter, incl. BROOKLYN/QUEENS', () => {
  it('keeps the combined label for BROOKLYN and for QUEENS', () => {
    expect(filterParks(rows, {...base, boroughs: ['BROOKLYN']})).toHaveLength(253);
    expect(filterParks(rows, {...base, boroughs: ['QUEENS']})).toHaveLength(188);
  });

  it('counts combined parks once when both are selected', () => {
    const both = filterParks(rows, {...base, boroughs: ['BROOKLYN', 'QUEENS']});
    expect(both).toHaveLength(437);
    expect(new Set(both.map(park => park.park)).size).toBe(both.length);
  });

  it('empty selection means no borough filter', () => {
    expect(filterParks(rows, base)).toHaveLength(792);
  });
});

describe('accent-insensitive park search', () => {
  it('normalises case and accents', () => {
    expect(normalizeText('Café Léon')).toBe('cafe leon');
  });

  it('matches an accented park name from an unaccented query', () => {
    const sample = [synthetic('PARC LÉON', 'BRONX', {'GRAND LARCENY': 3})];
    expect(filterParks(sample, {...base, query: 'leon'})).toHaveLength(1);
    expect(filterParks(sample, {...base, query: 'LÉON'})).toHaveLength(1);
    expect(filterParks(sample, {...base, query: 'central'})).toHaveLength(0);
  });

  it('matches real parks case-insensitively', () => {
    const found = filterParks(rows, {...base, query: 'pelham'});
    expect(found.length).toBeGreaterThan(0);
    expect(found.every(park => park.park.includes('PELHAM'))).toBe(true);
  });
});

describe('quarter bounds', () => {
  it('keeps both endpoints, inclusive', () => {
    const labels = quarterLabels(series, [44, 45]);
    expect(labels).toEqual(['2026Q1', '2026Q2']);
    expect(trendData(series, {...base, range: [44, 45]})).toHaveLength(2);
  });

  it('clamps a reversed or out-of-range selection', () => {
    expect(quarterLabels(series, [45, 44])).toEqual(['2026Q2']);
    expect(quarterLabels(series, [-3, 500])).toHaveLength(46);
  });

  it('never treats the missing 2020Q1 as a zero', () => {
    expect(series.quarters).not.toContain('2020Q1');
    expect(trendData(series, base).some(point => point.quarter === '2020Q1')).toBe(false);
  });
});

describe('totals and grouping', () => {
  it('crime-type filter restricts totals to that type', () => {
    const kpis = computeKpis(rows, {...base, types: ['BURGLARY']}, series);
    expect(kpis.total).toBe(311);
    expect(kpis.parks).toBe(123);
    expect(kpis.topType).toBe('BURGLARY');
  });

  it('matrix totals equal the selected total per borough', () => {
    const matrix = boroughTypeMatrix(rows, base);
    const total = matrix.rows.reduce((sum, row) => sum + row.total, 0);
    expect(total).toBe(12526);
    expect(matrix.types).toHaveLength(7);
    expect(matrix.rows.map(row => row.borough)).toContain('BROOKLYN/QUEENS');
  });

  it('top parks are ranked by selected count', () => {
    const top = topParks(rows, base, 3);
    expect(top[0].park).toBe('FLUSHING MEADOWS CORONA PARK');
    expect(top[0].total).toBe(881);
    expect(top).toHaveLength(3);
  });

  it('map keeps only parks with coordinates; the rest are counted', () => {
    expect(mapParks(rows, base)).toHaveLength(693);
    expect(parksWithoutCoordinates(rows, base)).toBe(99);
  });

  it('zero-crime count follows the selection and needs coordinates', () => {
    expect(zeroCrimeParks(rows, base)).toBe(0);
    const murders = rows.filter(
      park => park.lat !== null && park.lon !== null && !park.counts.MURDER,
    );
    expect(zeroCrimeParks(rows, {...base, types: ['MURDER']})).toBe(murders.length);
  });

  it('plural keeps 0 and 1 singular, 2 or more plural', () => {
    expect(plural(0, 'parc')).toBe('parc');
    expect(plural(1, 'parc')).toBe('parc');
    expect(plural(2, 'parc')).toBe('parcs');
    expect(plural(112, 'parc')).toBe('parcs');
    expect(plural(1, 'géolocalisé', 'géolocalisés')).toBe('géolocalisé');
    expect(plural(693, 'géolocalisé', 'géolocalisés')).toBe('géolocalisés');
  });
});
