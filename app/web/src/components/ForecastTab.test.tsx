import {describe, expect, it} from 'vitest';
import {fireEvent, render, screen} from '@testing-library/react';
import ForecastTab from './ForecastTab';
import {forecast, meta} from '../lib/data';
import type {Forecast} from '../lib/data';
import {fmtFixed} from '../lib/format'

describe('ForecastTab', () => {
  it('shows the model, its MAE ± sd and the Central Park caveat', () => {
    render(<ForecastTab />);
    expect(screen.getByText('SEASONAL_NAIVE')).toBeTruthy();
    expect(screen.getByText('30,17 ± 7,68')).toBeTruthy();
    expect(screen.getByText('12,94 %')).toBeTruthy();
    expect(screen.getAllByText(/Central Park/).length).toBeGreaterThan(0);
  });

  it('reports the reconciled forecast and the Diebold-Mariano test', () => {
    render(<ForecastTab />);
    expect(screen.getByText(/Prévisions citywide réconciliées/)).toBeTruthy();
    expect(screen.getByText(/Diebold-Mariano \(HLN\)/)).toBeTruthy();
  });

  it('lists the forecast points with their intervals', () => {
    render(<ForecastTab />);
    expect(screen.getByText('2026Q3')).toBeTruthy();
    expect(screen.getByText('Borne basse')).toBeTruthy();
    expect(screen.getByText('Borne haute')).toBeTruthy();
  });

  it('takes the interval level from meta.ci_alpha', () => {
    const level = Math.round((1 - meta.ci_alpha) * 100);
    render(<ForecastTab />);
    expect(
      screen.getByText(new RegExp(`Intervalle à ${level} %`)),
    ).toBeTruthy();
  });

  it('takes the interval level from the meta prop, not the module', () => {
    render(<ForecastTab meta={{...meta, ci_alpha: 0.1}} />);
    expect(screen.getByText(/Intervalle à 90 %/)).toBeTruthy();
  });

  it('lists the skipped boroughs and the clipping caveat from the artefacts', () => {
    render(<ForecastTab />);
    expect(screen.getByText(/STATEN ISLAND — non prévu/)).toBeTruthy();
    expect(screen.getByText(/BROOKLYN\/QUEENS — non prévu/)).toBeTruthy();
    expect(screen.getByText(/La borne basse de l'intervalle/)).toBeTruthy();
  });

  it('renders the model name from the fixture, never a hardcoded one', () => {
    const fixture: Forecast = {
      ...forecast,
      metrics: {
        ...forecast.metrics,
        city: {...forecast.metrics.city, selected_model: 'prophet'},
      },
    };
    render(<ForecastTab data={fixture} />);
    expect(screen.getByText('PROPHET')).toBeTruthy();
    // Exact match: the challenger sentence may legitimately name SARIMAX.
    expect(screen.queryByText('SARIMAX')).toBeNull();
  });

  it('draws the fan chart from history plus the reconciled forecast', () => {
    render(<ForecastTab />);
    expect(screen.getByText(/historique et éventail/)).toBeTruthy();
    expect(screen.getByText(/Backtest : réel vs règle naïve à un pas/)).toBeTruthy();
  });

  it('cites the one-step seasonal rule and its artifact MAE', () => {
    render(<ForecastTab />);
    expect(screen.getByText(/Règle à un pas/)).toBeTruthy();
    const ruleMae = fmtFixed(forecast.metrics.city.baseline_mae_seasonal_rule, 2);
    expect(screen.getAllByText(new RegExp(ruleMae)).length).toBeGreaterThan(0);
  });

  it('reports the DM test as without object when the baseline wins', () => {
    render(<ForecastTab />);
    expect(screen.getByText(/sans objet/)).toBeTruthy();
  });

  it('guards a null MAPE instead of printing NaN', () => {
    const fixture: Forecast = {
      ...forecast,
      metrics: {
        ...forecast.metrics,
        city: {...forecast.metrics.city, selected_mape: null},
      },
    };
    render(<ForecastTab data={fixture} />);
    expect(screen.getByText('n.d.')).toBeTruthy();
  });

  it('switches series and metrics through the borough selector', () => {
    render(<ForecastTab />);
    // The trigger and the open list both name the current option; the first
    // match is the trigger.
    fireEvent.click(screen.getAllByText('Ville entière (citywide)')[0]!);
    fireEvent.click(screen.getByRole('option', {name: 'MANHATTAN'}));
    expect(screen.getByText('10,35 ± 0,90')).toBeTruthy();
    expect(screen.getAllByText(/Prévisions MANHATTAN/).length).toBeGreaterThan(0);
    // Winner and best challenger coincide here: the DM test prints once.
    expect(screen.getAllByText(/Diebold-Mariano/)).toHaveLength(1);
  });

  it('names the selected scope in the fan heading', () => {
    render(<ForecastTab />);
    expect(
      screen.getByText(/Prévisions citywide : historique et éventail/),
    ).toBeTruthy();
  });
});
