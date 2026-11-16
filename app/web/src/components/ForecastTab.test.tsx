import {describe, expect, it} from 'vitest';
import {render, screen} from '@testing-library/react';
import ForecastTab from './ForecastTab';

describe('ForecastTab', () => {
  it('shows the model, its MAE/MAPE and the Central Park caveat', () => {
    render(<ForecastTab />);
    expect(screen.getByText('SARIMAX')).toBeTruthy();
    expect(screen.getByText('19.98')).toBeTruthy();
    expect(screen.getByText('9.62 %')).toBeTruthy();
    expect(screen.getAllByText(/Central Park/).length).toBeGreaterThan(0);
  });

  it('lists the forecast points with their intervals', () => {
    render(<ForecastTab />);
    expect(screen.getByText('2026Q3')).toBeTruthy();
    expect(screen.getByText('Borne basse')).toBeTruthy();
    expect(screen.getByText('Borne haute')).toBeTruthy();
  });
});
