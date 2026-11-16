import {describe, expect, it, vi} from 'vitest';
import {fireEvent, render, screen} from '@testing-library/react';
import {cube, parks} from '../lib/data';
import type {Park} from '../lib/data';
import ParkDetail, {parkHistory} from './ParkDetail';
import {fmtFixed} from '../lib/format'

const park = parks.find(row => row.park === 'WASHINGTON SQUARE PARK')!;

describe('ParkDetail', () => {
  it('shows acres, borough, cluster, coverage era and the risk rate', () => {
    render(<ParkDetail park={park} types={[]} onClose={() => {}} />);
    expect(screen.getByText(park.park)).toBeTruthy();
    expect(screen.getByText(park.borough)).toBeTruthy();
    expect(screen.getByText(`${fmtFixed(park.acres!, 2)} acres`)).toBeTruthy();
    expect(screen.getByText(park.coverage_era)).toBeTruthy();
    expect(screen.getByText(/677,6 \(rang 1\)/)).toBeTruthy();
  });

  it('lists the per-type breakdown over the whole period', () => {
    render(<ParkDetail park={park} types={[]} onClose={() => {}} />);
    expect(screen.getByText('Répartition par type (période complète)')).toBeTruthy();
    expect(screen.getByText('Larcin')).toBeTruthy();
  });

  it('sums the cube history to the park total', () => {
    const rows = parkHistory(cube, park.park_id, []);
    expect(rows).toHaveLength(cube.quarters.length);
    expect(rows.reduce((sum, point) => sum + point.crimes, 0)).toBe(park.total);
    expect(rows.some(point => point.quarter === '2020Q1')).toBe(false);
  });

  it('filters the history to the selected types', () => {
    const rows = parkHistory(cube, park.park_id, ['MURDER']);
    const murder = park.counts['MURDER'] ?? 0;
    expect(rows.reduce((sum, point) => sum + point.crimes, 0)).toBe(murder);
  });

  it('closes through the Fermer button', () => {
    const onClose = vi.fn();
    render(<ParkDetail park={park} types={[]} onClose={onClose} />);
    fireEvent.click(screen.getByRole('button', {name: 'Fermer'}));
    expect(onClose).toHaveBeenCalled();
  });

  it('renders a park without acreage with dashes, never NaN', () => {
    const noAcres: Park = {
      ...park,
      acres: null,
      crimes_per_100_acres: null,
      risk_rank: null,
    };
    render(<ParkDetail park={noAcres} types={[]} onClose={() => {}} />);
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });
});
