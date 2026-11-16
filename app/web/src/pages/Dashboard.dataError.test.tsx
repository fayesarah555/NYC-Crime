import {describe, expect, it, vi} from 'vitest';
import {render, screen} from '@testing-library/react';

// A rejected bundle: `cubes` is `{}`, so `cubes.quarters.length` throws.
// Any payload access before the dataError guard blanks the page.
vi.mock('../lib/data', () => ({
  dataError:
    'Données statiques invalides : parks: tableau attendu ; cubes.quarters: tableau de chaînes attendu.',
  parks: {},
  cube: {},
  meta: {},
  clusters: {},
  forecast: {},
  boroughType: {},
}));

import Dashboard from './Dashboard';

describe('Dashboard with a rejected payload', () => {
  it('renders the French error card when cubes.quarters is malformed', () => {
    expect(() => render(<Dashboard />)).not.toThrow();
    expect(screen.getByText('Chargement des données impossible')).toBeTruthy();
    expect(screen.getByText(/cubes\.quarters/)).toBeTruthy();
  });
});
