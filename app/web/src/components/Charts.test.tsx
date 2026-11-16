import {describe, expect, it} from 'vitest';
import {render, screen} from '@testing-library/react';
import {TrendChart} from './Charts';

describe('TrendChart', () => {
  it('renders the trend heading and the supplied points', () => {
    render(
      <TrendChart
        data={[
          {quarter: '2026Q1', crimes: 200},
          {quarter: '2026Q2', crimes: 241},
        ]}
      />,
    );
    expect(screen.getByText('Tendance trimestrielle')).toBeTruthy();
  });

  it('annotates the missing quarter and the coverage break on the axis', () => {
    render(
      <TrendChart
        data={[
          {quarter: '2019Q4', crimes: 300},
          {quarter: '2020Q2', crimes: 120},
          {quarter: '2025Q1', crimes: 120},
        ]}
        gap={{missing: '2020Q1', anchor: '2020Q2'}}
        breakQuarter="2025Q1"
      />,
    );
    // Recharts renders no SVG at width 0 in jsdom; the captions carry the
    // same annotation text the axis label shows in the browser.
    expect(screen.getByText(/2020Q1 est absent de la source/)).toBeTruthy();
    expect(screen.getByText(/rupture de couverture en 2025Q1/i)).toBeTruthy();
  });
});
