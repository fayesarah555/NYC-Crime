import {beforeEach, describe, expect, it} from 'vitest';
import {act, fireEvent, render, screen, within} from '@testing-library/react';
import {parks} from '../lib/data';
import Dashboard from './Dashboard';
import {fmtFixed} from '../lib/format'

// Each test starts from a bare URL: the dashboard reads location.search.
beforeEach(() => window.history.replaceState(null, '', '/'));

describe('Dashboard trend caption', () => {
  it('renders the citywide caption with the trend', () => {
    render(<Dashboard />);
    expect(screen.getByText('Tendance citywide.')).toBeTruthy();
  });

  it('drops the "Toutes périodes" badges now the cube backs the filters', () => {
    render(<Dashboard />);
    expect(screen.queryByText(/Toutes périodes/)).toBeNull();
  });

  it('keeps the trend when types and boroughs combine', () => {
    render(<Dashboard />);
    fireEvent.click(screen.getByText('Arrondissements'));
    fireEvent.click(screen.getByRole('option', {name: 'BRONX'}));
    fireEvent.click(screen.getByText('Types de délit'));
    fireEvent.click(screen.getByRole('option', {name: 'Cambriolage'}));
    expect(screen.queryByText(/Types non disponibles/)).toBeNull();
    expect(
      screen.getByText(/Somme des séries trimestrielles/),
    ).toBeTruthy();
  });

  it('shows the per-acre risk ranking with the coverage era', () => {
    render(<Dashboard />);
    expect(screen.getByText(/Parcs les plus à risque/)).toBeTruthy();
    expect(screen.getAllByText('WASHINGTON SQUARE PARK').length).toBeGreaterThan(
      0,
    );
    expect(screen.getAllByText(/–2026Q2/).length).toBeGreaterThan(0);
  });

  it('marks the 2020Q1 gap and the 2025Q1 coverage break', () => {
    render(<Dashboard />);
    expect(screen.getByText(/2020Q1 est absent de la source/)).toBeTruthy();
    expect(
      screen.getByText(/rupture de couverture en 2025Q1/i),
    ).toBeTruthy();
  });
});

describe('park drill-down', () => {
  it('opens the detail panel from the keyboard park list', () => {
    render(<Dashboard />);
    fireEvent.click(
      screen.getByRole('button', {name: /WASHINGTON SQUARE PARK/}),
    );
    const panel = screen.getByRole('region', {name: 'Détail du parc'});
    const wash = parks.find(row => row.park === 'WASHINGTON SQUARE PARK')!;
    expect(within(panel).getByText('Superficie')).toBeTruthy();
    expect(
      within(panel).getByText(`${fmtFixed(wash.acres!, 2)} acres`),
    ).toBeTruthy();
    expect(
      within(panel).getByText('Répartition par type (période complète)'),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole('button', {name: 'Fermer'}));
    expect(screen.queryByRole('region', {name: 'Détail du parc'})).toBeNull();
  });

  it('shows the same park when its row is selected from the list twice', () => {
    render(<Dashboard />);
    fireEvent.click(
      screen.getByRole('button', {name: /WASHINGTON SQUARE PARK/}),
    );
    fireEvent.click(
      screen.getByRole('button', {name: /WASHINGTON SQUARE PARK/}),
    );
    expect(screen.getAllByRole('region', {name: 'Détail du parc'})).toHaveLength(
      1,
    );
  });
});

describe('URL state', () => {
  it('restores ?tab=previsions&borough=MANHATTAN on load', () => {
    window.history.replaceState(null, '', '/?tab=previsions&borough=MANHATTAN');
    render(<Dashboard />);
    expect(screen.getByText('SEASONAL_NAIVE')).toBeTruthy();
    expect(window.location.search).toBe('?tab=previsions&borough=MANHATTAN');
  });

  it('writes filters to the URL as they change', () => {
    render(<Dashboard />);
    fireEvent.click(screen.getByText('Arrondissements'));
    fireEvent.click(screen.getByRole('option', {name: 'BRONX'}));
    expect(window.location.search).toContain('borough=BRONX');
  });

  it('writes the tab to the URL', () => {
    render(<Dashboard />);
    fireEvent.click(screen.getByRole('tab', {name: 'Prévisions'}));
    expect(window.location.search).toBe('?tab=previsions');
  });

  it('clears the URL through Réinitialiser', () => {
    render(<Dashboard />);
    fireEvent.click(screen.getByText('Arrondissements'));
    fireEvent.click(screen.getByRole('option', {name: 'BRONX'}));
    fireEvent.click(screen.getByRole('button', {name: 'Réinitialiser'}));
    expect(window.location.search).toBe('');
  });

  it('restores the view from the URL on back/forward (popstate)', () => {
    render(<Dashboard />);
    window.history.replaceState(null, '', '/?q=zzzzzz');
    act(() => {
      window.dispatchEvent(new PopStateEvent('popstate'));
    });
    expect(screen.getByText('Aucune donnée pour ces filtres')).toBeTruthy();
  });
});

describe('empty states', () => {
  it('explains an empty selection instead of drawing empty charts', () => {
    window.history.replaceState(null, '', '/?q=zzzzzz');
    render(<Dashboard />);
    expect(screen.getByText('Aucune donnée pour ces filtres')).toBeTruthy();
    expect(
      screen.getByRole('button', {name: 'Réinitialiser'}),
    ).toBeTruthy();
    expect(screen.queryByText('Carte des parcs')).toBeNull();
  });
});
