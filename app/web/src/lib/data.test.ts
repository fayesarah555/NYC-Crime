import {describe, expect, it} from 'vitest';
import {
  boroughType,
  clusters,
  cube,
  forecast,
  meta,
  parks,
  series,
  validateData,
} from './data';

// Raw JSON text of the bundled payloads, as shipped.
const RAW_PAYLOADS = import.meta.glob('../data/*.json', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

const encoder = new TextEncoder();

describe('payload budget', () => {
  it('ships eight JSON files under 2 MB in total', () => {
    const names = Object.keys(RAW_PAYLOADS).map(path =>
      path.slice(path.lastIndexOf('/') + 1),
    );
    expect(names.sort()).toEqual([
      'borough_type.json',
      'clusters.json',
      'cubes.json',
      'forecast.json',
      'meta.json',
      'palette.json',
      'parks.json',
      'series.json',
    ]);
    const total = Object.values(RAW_PAYLOADS).reduce(
      (sum, text) => sum + encoder.encode(text).length,
      0,
    );
    expect(total).toBeGreaterThan(0);
    expect(total).toBeLessThan(2 * 1024 * 1024);
  });
});

describe('cube sums', () => {
  const quarterIndex = new Map(cube.quarters.map((q, i) => [q, i]));

  function cubeTotals(): {byPark: Map<string, number>; byQuarter: number[]; byType: number[]} {
    const byPark = new Map<string, number>();
    const byQuarter = new Array<number>(cube.quarters.length).fill(0);
    const byType = new Array<number>(cube.crime_types.length).fill(0);
    for (const [parkId, cells] of Object.entries(cube.parks)) {
      let parkTotal = 0;
      for (const [quarter, counts] of Object.entries(cells)) {
        const index = quarterIndex.get(quarter)!;
        // null = missing column: it contributes nothing, and is never a 0.
        parkTotal += counts.reduce<number>(
          (sum, value) => sum + (value ?? 0),
          0,
        );
        counts.forEach((value, type) => {
          if (value !== null) {
            byQuarter[index]! += value;
            byType[type]! += value;
          }
        });
      }
      byPark.set(parkId, parkTotal);
    }
    return {byPark, byQuarter, byType};
  }

  it('per-park totals equal parks.json totals (0 tolerance)', () => {
    const {byPark} = cubeTotals();
    expect(Object.keys(cube.parks)).toHaveLength(parks.length);
    for (const park of parks) {
      expect(byPark.get(park.park_id), park.park).toBe(park.total);
    }
  });

  it('quarter sums equal the city series (0 tolerance)', () => {
    const {byQuarter} = cubeTotals();
    expect(byQuarter).toEqual(series.city);
  });

  it('type sums equal the city-by-type series (0 tolerance)', () => {
    const {byType} = cubeTotals();
    cube.crime_types.forEach((type, index) => {
      const expected = series.city_by_type[type]!.reduce((sum, value) => sum + value, 0);
      expect(byType[index], type).toBe(expected);
    });
    expect(byType.reduce((sum, value) => sum + value, 0)).toBe(meta.totals.crimes);
  });

  it('borough x type sums equal borough_type.json', () => {
    const boroughOf = new Map(parks.map(park => [park.park_id, park.borough]));
    for (const row of boroughType.boroughs) {
      const sums = new Array<number>(cube.crime_types.length).fill(0);
      for (const [parkId, cells] of Object.entries(cube.parks)) {
        if (boroughOf.get(parkId) !== row.borough) continue;
        for (const counts of Object.values(cells)) {
          counts.forEach((value, type) => {
            if (value !== null) sums[type]! += value;
          });
        }
      }
      cube.crime_types.forEach((type, index) => {
        expect(sums[index], `${row.borough} ${type}`).toBe(row.counts[type]);
      });
    }
  });
});

describe('load-time validation', () => {
  const good = {
    meta,
    parks,
    series,
    borough_type: boroughType,
    forecast,
    clusters,
    cubes: cube,
  };

  it('accepts the bundled payloads', () => {
    expect(validateData(good)).toEqual([]);
  });

  it('rejects an old schema_version', () => {
    const problems = validateData({...good, meta: {...meta, schema_version: 1}});
    expect(problems.join(' ')).toContain('schema_version');
  });

  it('rejects a cube that breaks the shared quarter index', () => {
    const problems = validateData({
      ...good,
      cubes: {...cube, quarters: cube.quarters.slice(1)},
    });
    expect(problems.join(' ')).toContain('doit égaler series.quarters');
  });

  it('rejects a cell with the wrong number of counts', () => {
    const firstPark = Object.keys(cube.parks)[0]!;
    const firstQuarter = Object.keys(cube.parks[firstPark]!)[0]!;
    const cells = {...cube.parks[firstPark]!, [firstQuarter]: [1, 2]};
    const problems = validateData({
      ...good,
      cubes: {...cube, parks: {...cube.parks, [firstPark]: cells}},
    });
    expect(problems.join(' ')).toContain('entiers attendus');
  });

  it('rejects a cell keyed by a quarter outside cubes.quarters', () => {
    const firstPark = Object.keys(cube.parks)[0]!;
    const cells = {
      ...cube.parks[firstPark]!,
      '2099Q1': new Array<number>(cube.crime_types.length).fill(0),
    };
    const problems = validateData({
      ...good,
      cubes: {...cube, parks: {...cube.parks, [firstPark]: cells}},
    });
    expect(problems.join(' ')).toContain('trimestre inconnu');
    expect(problems.join(' ')).toContain('2099Q1');
  });

  it('rejects a parks row with non-numeric counts', () => {
    const problems = validateData({
      ...good,
      parks: [{...parks[0]!, counts: {...parks[0]!.counts, MURDER: 'x'}}],
    });
    expect(problems.join(' ')).toContain('counts');
  });

  it('rejects a series whose city array is misaligned', () => {
    const problems = validateData({
      ...good,
      series: {...series, city: series.city.slice(1)},
    });
    expect(problems.join(' ')).toContain('series.city');
  });
});
