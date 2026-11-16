// Series helpers for the forecast fan, the one-step backtest panel and the
// two data breaks the charts must annotate. Pure: no model recomputation.

import type {ForecastPoint, Meta} from './data';

export interface FanPoint {
  quarter: string;
  /** Observed total, null when the quarter is absent from the source. */
  history: number | null;
  /** Forecast point; the last history point repeats it to join the lines. */
  forecast: number | null;
  /** 95 % interval as a [lower, upper] range area. */
  interval: [number, number] | null;
}

export function fanSeries(
  quarters: string[],
  history: (number | null)[],
  points: ForecastPoint[],
): FanPoint[] {
  const rows: FanPoint[] = quarters.map((quarter, index) => ({
    quarter,
    history: history[index] ?? null,
    forecast: null,
    interval: null,
  }));
  const last = rows[rows.length - 1];
  if (last !== undefined) last.forecast = last.history;
  for (const point of points) {
    rows.push({
      quarter: point.quarter,
      history: null,
      forecast: point.point,
      interval: [point.lower, point.upper],
    });
  }
  return rows;
}

export interface RulePoint {
  quarter: string;
  actual: number | null;
  rule: number | null;
}

/**
 * One-step seasonal rule shown in the backtest panel: predict a quarter with
 * the observed value of the same quarter a year earlier. The exporter scores
 * this rule over its BACKTEST window (8 quarters, analysis/model.py), so the
 * panel uses the same window and cites `baseline_mae_seasonal_rule`.
 */
export const RULE_WINDOW = 8;

export function ruleBacktest(
  quarters: string[],
  history: (number | null)[],
  window = RULE_WINDOW,
): RulePoint[] {
  const rows: RulePoint[] = [];
  for (let index = Math.max(0, quarters.length - window); index < quarters.length; index++) {
    const quarter = quarters[index];
    if (quarter === undefined) continue;
    const previousIndex = index - 4;
    rows.push({
      quarter,
      actual: history[index] ?? null,
      rule: previousIndex >= 0 ? history[previousIndex] ?? null : null,
    });
  }
  return rows;
}

export interface GapAnnotation {
  /** The quarter absent from the source, e.g. 2020Q1. */
  missing: string;
  /** The first plotted quarter after the gap; the axis anchor. */
  anchor: string;
}

/** Anchor the missing-quarter marker on the axis, next to where it belongs. */
export function gapAnnotation(
  quarters: string[],
  missing: string[],
): GapAnnotation | null {
  const quarter = missing[0];
  if (quarter === undefined) return null;
  const anchor = quarters.find(label => label > quarter);
  return anchor === undefined ? null : {missing: quarter, anchor};
}

/**
 * Coverage-break quarter announced by the meta caveats (Central Park only
 * appears from 2025Q1, which inflates the jump). Read from the caveat text so
 * a regenerated export moves the annotation instead of hardcoding a year.
 */
export function coverageBreak(meta: Meta): string | null {
  for (const caveat of meta.caveats) {
    const namesPark = /central park/i.test(caveat);
    const namesBreak = /coverage|appears|only from/i.test(caveat);
    if (!namesPark || !namesBreak) continue;
    const match = caveat.match(/\b(\d{4}Q[1-4])\b/);
    if (match?.[1] !== undefined) return match[1];
  }
  return null;
}
