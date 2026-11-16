import {describe, expect, it, vi} from 'vitest';
import {fireEvent, render, screen} from '@testing-library/react';
import FilterPanel from './FilterPanel';
import type {Filters} from '../lib/filters';

const quarters = ['2025Q1', '2025Q2', '2025Q3'];
const filters: Filters = {
  boroughs: [],
  types: [],
  range: [0, quarters.length - 1],
  query: '',
};

describe('FilterPanel', () => {
  it('exposes the four controls: borough, crime type, quarter range, park search', () => {
    render(
      <FilterPanel filters={filters} quarters={quarters} onChange={() => {}} />,
    );
    expect(screen.getByText('Arrondissements')).toBeTruthy();
    expect(screen.getByText('Types de délit')).toBeTruthy();
    expect(screen.getByText('Période')).toBeTruthy();
    expect(screen.getByLabelText('Rechercher un parc')).toBeTruthy();
    expect(screen.getAllByRole('slider').length).toBeGreaterThan(0);
  });

  it('no longer annotates an all-periods fallback', () => {
    const {container} = render(
      <FilterPanel filters={filters} quarters={quarters} onChange={() => {}} />,
    );
    expect(container.textContent).not.toMatch(/Toutes périodes/);
    expect(container.textContent).not.toMatch(/ne les filtre pas/);
  });

  it('drives the filter range from the period slider', () => {
    const onChange = vi.fn();
    render(
      <FilterPanel filters={filters} quarters={quarters} onChange={onChange} />,
    );
    const thumbs = screen.getAllByRole('slider');
    fireEvent.keyDown(thumbs[0]!, {key: 'ArrowRight'});
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({range: [1, 2]}),
    );
  });

  it('reports a park query through onChange', () => {
    const onChange = vi.fn();
    render(
      <FilterPanel filters={filters} quarters={quarters} onChange={onChange} />,
    );
    fireEvent.change(screen.getByLabelText('Rechercher un parc'), {
      target: {value: 'central'},
    });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({query: 'central'}),
    );
  });

  it('offers Réinitialiser when a reset handler is provided', () => {
    const onReset = vi.fn();
    render(
      <FilterPanel
        filters={filters}
        quarters={quarters}
        onChange={() => {}}
        onReset={onReset}
      />,
    );
    fireEvent.click(screen.getByRole('button', {name: 'Réinitialiser'}));
    expect(onReset).toHaveBeenCalled();
  });
});
