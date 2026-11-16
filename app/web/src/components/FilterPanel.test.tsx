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
});
