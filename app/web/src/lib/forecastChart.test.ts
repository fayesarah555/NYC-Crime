import {describe, expect, it} from 'vitest';
import {forecast, meta, series} from './data';
import {
  RULE_WINDOW,
  coverageBreak,
  fanSeries,
  gapAnnotation,
  ruleBacktest,
} from './forecastChart';

describe('fanSeries', () => {
  it('joins history, forecast points and their interval on one axis', () => {
    const fan = fanSeries(
      ['2026Q1', '2026Q2'],
      [120, 331],
      [{quarter: '2026Q3', point: 388, lower: 300, upper: 476}],
    );
    expect(fan).toHaveLength(3);
    expect(fan[1]).toEqual({
      quarter: '2026Q2',
      history: 331,
      forecast: 331,
      interval: null,
    });
    expect(fan[2]).toEqual({
      quarter: '2026Q3',
      history: null,
      forecast: 388,
      interval: [300, 476],
    });
  });

  it('keeps a missing history quarter as null instead of zero', () => {
    const fan = fanSeries(['2020Q2'], [null], []);
    expect(fan[0]?.history).toBeNull();
  });
});

describe('one-step backtest rule', () => {
  it('uses the exporter rule window and reproduces the artifact MAE', () => {
    const points = ruleBacktest(series.quarters, series.city);
    expect(points).toHaveLength(RULE_WINDOW);
    const errors = points.flatMap(point =>
      point.actual === null || point.rule === null
        ? []
        : [Math.abs(point.actual - point.rule)],
    );
    const mae = errors.reduce((sum, value) => sum + value, 0) / errors.length;
    expect(mae).toBeCloseTo(
      forecast.metrics.city.baseline_mae_seasonal_rule,
      2,
    );
  });

  it('predicts with the same quarter a year earlier', () => {
    const points = ruleBacktest(['2025Q1', '2025Q2', '2025Q3', '2025Q4', '2026Q1'], [1, 2, 3, 4, 99]);
    expect(points[0]).toEqual({quarter: '2025Q1', actual: 1, rule: null});
    expect(points[4]).toEqual({quarter: '2026Q1', actual: 99, rule: 1});
  });
});

describe('data-break annotations', () => {
  it('anchors the missing 2020Q1 on the next plotted quarter', () => {
    expect(gapAnnotation(cubeQuarters(), ['2020Q1'])).toEqual({
      missing: '2020Q1',
      anchor: '2020Q2',
    });
  });

  it('reads the coverage break quarter from the meta caveats', () => {
    expect(coverageBreak(meta)).toBe('2025Q1');
  });

  it('returns null when meta announces nothing', () => {
    expect(gapAnnotation([], ['2020Q1'])).toBeNull();
    expect(coverageBreak({...meta, caveats: []})).toBeNull();
  });
});

function cubeQuarters(): string[] {
  return ['2019Q4', '2020Q2', '2020Q3'];
}
