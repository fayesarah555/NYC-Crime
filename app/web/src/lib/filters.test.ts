import {describe, expect, it} from 'vitest';
import {boroughType, cube, meta, parks} from './data';
import {
  boroughTypeMatrix,
  computeKpis,
  filterParks,
  formatPct,
  mapParks,
  normalizeText,
  parksWithoutCoordinates,
  plural,
  quarterWindow,
  topParks,
  trendData,
  zeroCrimeParks,
  type Filters,
  type ParkRow,
} from './filters';

const base: Filters = {
  boroughs: [],
  types: [],
  range: [0, cube.quarters.length - 1],
  query: '',
};

const rows = parks as ParkRow[];

function synthetic(park: string, borough: string, counts: Record<string, number>): ParkRow {
  return {
    park_id: `TEST:${borough}:${park}`,
    park,
    borough,
    lat: null,
    lon: null,
    acres: null,
    total: Object.values(counts).reduce((sum, value) => sum + value, 0),
    dominant_type: 'GRAND LARCENY',
    cluster: null,
    counts,
  };
}

function trendSum(filters: Filters): number {
  return trendData(rows, filters, cube).reduce((sum, point) => sum + point.crimes, 0);
}

function matrixSum(filters: Filters): number {
  return boroughTypeMatrix(rows, filters, cube).rows.reduce(
    (sum, row) => sum + row.total,
    0,
  );
}

describe('computeKpis — reconciliation with the Streamlit app', () => {
  it('matches 12 544 crimes, 792 parks, Larcin and +2,7 %', () => {
    const kpis = computeKpis(rows, base, cube);
    expect(kpis.total).toBe(12544);
    expect(kpis.total).toBe(meta.totals.crimes);
    expect(kpis.parks).toBe(792);
    expect(kpis.parks).toBe(meta.totals.parks_with_crimes);
    expect(kpis.topType).toBe('GRAND LARCENY');
    expect(kpis.latestQuarter).toBe('2026Q2');
    expect(kpis.changeBasis).toBe('annuelle');
    expect(kpis.changePct).toBeCloseTo(2.72, 1);
    expect(formatPct(kpis.changePct)).toBe('+2,7 %');
  });

  it('returns 0 / 0 / — / — for an empty selection', () => {
    const kpis = computeKpis([], base, cube);
    expect(kpis.total).toBe(0);
    expect(kpis.parks).toBe(0);
    expect(kpis.topType).toBeNull();
    expect(kpis.changePct).toBeNull();
    expect(formatPct(kpis.changePct)).toBe('—');
  });

  it('returns 0 / 0 / — / — when the search matches nothing', () => {
    const kpis = computeKpis(rows, {...base, query: 'zzz-nowhere'}, cube);
    expect(kpis.total).toBe(0);
    expect(kpis.parks).toBe(0);
    expect(kpis.topType).toBeNull();
    expect(kpis.changePct).toBeNull();
  });

  it('sums park totals to the citywide total', () => {
    const total = rows.reduce((sum, park) => sum + park.total, 0);
    expect(total).toBe(12544);
  });
});

describe('annual change respects the crime-type filter', () => {
  it('computes BURGLARY 2026Q2 vs 2025Q2: 3 against 5 cases, -40,0 %', () => {
    const kpis = computeKpis(rows, {...base, types: ['BURGLARY']}, cube);
    expect(kpis.changeBasis).toBe('annuelle');
    expect(kpis.changePct).toBeCloseTo(-40, 6);
    expect(formatPct(kpis.changePct)).toBe('-40,0 %');
    // The cube backs those quarterly values: 5 in 2025Q2, 3 in 2026Q2.
    const trend = trendData(rows, {...base, types: ['BURGLARY']}, cube);
    const i2025 = cube.quarters.indexOf('2025Q2');
    const i2026 = cube.quarters.indexOf('2026Q2');
    expect(trend[i2025]!.crimes).toBe(5);
    expect(trend[i2026]!.crimes).toBe(3);
  });

  it('Larcin shows its own +4.4 %, not the all-type +2,7 %', () => {
    const kpis = computeKpis(rows, {...base, types: ['GRAND LARCENY']}, cube);
    expect(kpis.changePct).toBeCloseTo(4.4, 1);
  });

  it('shows — when the selected types have no year-ago quarter', () => {
    const kpis = computeKpis(rows, {...base, types: ['BURGLARY'], range: [0, 0]}, cube);
    expect(kpis.changeBasis).toBeNull();
    expect(formatPct(kpis.changePct)).toBe('—');
  });
});

describe('borough filter, incl. BROOKLYN/QUEENS', () => {
  it('keeps the combined label for BROOKLYN and for QUEENS', () => {
    expect(filterParks(rows, {...base, boroughs: ['BROOKLYN']}, cube)).toHaveLength(253);
    expect(filterParks(rows, {...base, boroughs: ['QUEENS']}, cube)).toHaveLength(188);
  });

  it('counts combined parks once when both are selected', () => {
    const both = filterParks(rows, {...base, boroughs: ['BROOKLYN', 'QUEENS']}, cube);
    expect(both).toHaveLength(437);
    expect(new Set(both.map(park => park.park)).size).toBe(both.length);
  });

  it('selecting BROOKLYN/QUEENS returns its 4 combined parks, not its parents', () => {
    const combined = filterParks(rows, {...base, boroughs: ['BROOKLYN/QUEENS']}, cube);
    expect(combined).toHaveLength(4);
    expect(combined.every(park => park.borough === 'BROOKLYN/QUEENS')).toBe(true);
  });

  it('empty selection means no borough filter', () => {
    expect(filterParks(rows, base, cube)).toHaveLength(792);
  });
});

describe('trend series derived from the cube', () => {
  it("renders Staten Island's real series, which sums to 154", () => {
    const trend = trendData(rows, {...base, boroughs: ['STATEN ISLAND']}, cube);
    expect(trend.reduce((sum, point) => sum + point.crimes, 0)).toBe(154);
    expect(trend.some(point => point.crimes > 0)).toBe(true);
  });

  it('renders the combined BROOKLYN/QUEENS series, which sums to 114', () => {
    const trend = trendData(rows, {...base, boroughs: ['BROOKLYN/QUEENS']}, cube);
    expect(trend.reduce((sum, point) => sum + point.crimes, 0)).toBe(114);
  });

  it('with types and no borough, the trend equals the KPI total', () => {
    const filters = {...base, types: ['BURGLARY']};
    expect(trendSum(filters)).toBe(computeKpis(rows, filters, cube).total);
    expect(computeKpis(rows, filters, cube).total).toBe(311);
  });

  it('type + borough is exact: BRONX x BURGLARY matches the borough_type table', () => {
    const filters = {...base, boroughs: ['BRONX'], types: ['BURGLARY']};
    const bronx = boroughType.boroughs.find(row => row.borough === 'BRONX')!;
    expect(trendSum(filters)).toBe(bronx.counts.BURGLARY);
    expect(trendSum(filters)).toBe(53);
    const matrix = boroughTypeMatrix(rows, filters, cube);
    expect(matrix.rows[0]!.counts.BURGLARY).toBe(53);
  });
});

describe('quarter range drives every view', () => {
  const narrow: Filters = {...base, range: [44, 45]}; // 2026Q1-2026Q2
  const all = computeKpis(rows, base, cube);
  const cut = computeKpis(rows, narrow, cube);

  it('changes the KPIs', () => {
    expect(cut.total).toBe(441);
    expect(cut.total).toBeLessThan(all.total);
    expect(cut.parks).toBe(157);
    expect(cut.latestQuarter).toBe('2026Q2');
  });

  it('changes the map', () => {
    const full = mapParks(rows, base, cube);
    const cutMarkers = mapParks(rows, narrow, cube);
    expect(full).toHaveLength(693);
    expect(cutMarkers).toHaveLength(139);
    expect(cutMarkers.length).toBeLessThan(full.length);
    expect(parksWithoutCoordinates(rows, narrow, cube)).toBe(18);
    expect(zeroCrimeParks(rows, narrow, cube)).toBe(554);
  });

  it('changes the top 10', () => {
    const full = topParks(rows, base, cube, 3);
    const cutTop = topParks(rows, narrow, cube, 3);
    expect(full[0]!.park).toBe('FLUSHING MEADOWS CORONA PARK');
    expect(full[0]!.total).toBe(899);
    expect(cutTop[0]!.park).toBe('FLUSHING MEADOWS CORONA PARK');
    expect(cutTop[0]!.total).toBe(27);
    expect(cutTop[0]!.total).toBeLessThan(full[0]!.total);
  });

  it('changes the matrix', () => {
    const full = boroughTypeMatrix(rows, base, cube);
    const cutMatrix = boroughTypeMatrix(rows, narrow, cube);
    expect(full.rows.reduce((sum, row) => sum + row.total, 0)).toBe(12544);
    expect(cutMatrix.rows.reduce((sum, row) => sum + row.total, 0)).toBe(441);
  });
});

describe('KPI total == trend sum == matrix sum', () => {
  const boroughSets = [
    [],
    ['BRONX'],
    ['BROOKLYN'],
    ['QUEENS'],
    ['BROOKLYN', 'QUEENS'],
    ['BROOKLYN/QUEENS'],
    ['MANHATTAN'],
    ['STATEN ISLAND'],
  ];
  const typeSets = [
    [],
    ['BURGLARY'],
    ['GRAND LARCENY'],
    ['MURDER'],
    ['ROBBERY', 'RAPE'],
    ['BURGLARY', 'MURDER', 'RAPE'],
  ];
  const ranges: [number, number][] = [
    [0, cube.quarters.length - 1],
    [44, 45],
    [40, 45],
    [10, 20],
  ];
  const combinations: Filters[] = [];
  boroughSets.forEach((boroughs, b) =>
    typeSets.forEach((types, t) =>
      combinations.push({
        boroughs,
        types,
        range: ranges[(b + t) % ranges.length]!,
        query: '',
      }),
    ),
  );

  it('holds for at least 20 sampled filter combinations', () => {
    expect(combinations.length).toBeGreaterThanOrEqual(20);
    for (const filters of combinations) {
      const kpis = computeKpis(rows, filters, cube);
      expect(trendSum(filters), JSON.stringify(filters)).toBe(kpis.total);
      expect(matrixSum(filters), JSON.stringify(filters)).toBe(kpis.total);
    }
  });

  it('still holds with a park search in the mix', () => {
    for (const range of ranges) {
      const filters: Filters = {
        boroughs: [],
        types: ['GRAND LARCENY'],
        range,
        query: 'central',
      };
      expect(trendSum(filters)).toBe(computeKpis(rows, filters, cube).total);
      expect(matrixSum(filters)).toBe(computeKpis(rows, filters, cube).total);
    }
  });
});

describe('accent-insensitive park search', () => {
  it('normalises case and accents', () => {
    expect(normalizeText('Café Léon')).toBe('cafe leon');
  });

  it('matches an accented park name from an unaccented query', () => {
    const sample = [synthetic('PARC LÉON', 'BRONX', {'GRAND LARCENY': 3})];
    const sampleCube = {
      ...cube,
      parks: {
        ...cube.parks,
        [sample[0]!.park_id]: {'2026Q2': [0, 0, 3, 0, 0, 0, 0]},
      },
    };
    expect(filterParks(sample, {...base, query: 'leon'}, sampleCube)).toHaveLength(1);
    expect(filterParks(sample, {...base, query: 'LÉON'}, sampleCube)).toHaveLength(1);
    expect(filterParks(sample, {...base, query: 'central'}, sampleCube)).toHaveLength(0);
  });

  it('matches real parks case-insensitively', () => {
    const found = filterParks(rows, {...base, query: 'pelham'}, cube);
    expect(found.length).toBeGreaterThan(0);
    expect(found.every(park => park.park.includes('PELHAM'))).toBe(true);
  });
});

describe('quarter bounds', () => {
  it('keeps both endpoints, inclusive', () => {
    const labels = quarterWindow(cube, [44, 45]);
    expect(labels).toEqual(['2026Q1', '2026Q2']);
    expect(trendData(rows, {...base, range: [44, 45]}, cube)).toHaveLength(2);
  });

  it('clamps a reversed or out-of-range selection', () => {
    expect(quarterWindow(cube, [45, 44])).toEqual(['2026Q2']);
    expect(quarterWindow(cube, [-3, 500])).toHaveLength(46);
  });

  it('never treats the missing 2020Q1 as a zero', () => {
    expect(cube.quarters).not.toContain('2020Q1');
    expect(
      trendData(rows, base, cube).some(point => point.quarter === '2020Q1'),
    ).toBe(false);
  });
});

describe('totals and grouping', () => {
  it('crime-type filter restricts totals to that type', () => {
    const kpis = computeKpis(rows, {...base, types: ['BURGLARY']}, cube);
    expect(kpis.total).toBe(311);
    expect(kpis.parks).toBe(123);
    expect(kpis.topType).toBe('BURGLARY');
  });

  it('matrix totals equal the selected total per borough', () => {
    const matrix = boroughTypeMatrix(rows, base, cube);
    const total = matrix.rows.reduce((sum, row) => sum + row.total, 0);
    expect(total).toBe(12544);
    expect(matrix.types).toHaveLength(7);
    expect(matrix.rows.map(row => row.borough)).toContain('BROOKLYN/QUEENS');
  });

  it('top parks are ranked by selected count', () => {
    const top = topParks(rows, base, cube, 3);
    expect(top[0]!.park).toBe('FLUSHING MEADOWS CORONA PARK');
    expect(top[0]!.total).toBe(899);
    expect(top).toHaveLength(3);
  });

  it('map keeps only parks with coordinates; the rest are counted', () => {
    expect(mapParks(rows, base, cube)).toHaveLength(693);
    expect(parksWithoutCoordinates(rows, base, cube)).toBe(99);
  });

  it('zero-crime count follows the selection and needs coordinates', () => {
    expect(zeroCrimeParks(rows, base, cube)).toBe(0);
    const withCoords = rows.filter(
      park => park.lat !== null && park.lon !== null,
    ).length;
    expect(zeroCrimeParks(rows, {...base, types: ['MURDER']}, cube)).toBeGreaterThan(0);
    expect(zeroCrimeParks(rows, {...base, types: ['MURDER']}, cube)).toBeLessThan(
      withCoords,
    );
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
