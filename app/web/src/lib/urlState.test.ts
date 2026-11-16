import {describe, expect, it} from 'vitest';
import {cube} from './data';
import {
  defaultFilters,
  isTabId,
  readUrlState,
  writeUrlState,
} from './urlState';

const quarters = cube.quarters;
const full: [number, number] = [0, quarters.length - 1];

describe('URL state', () => {
  it('reads the default view from an empty query string', () => {
    const state = readUrlState('', quarters);
    expect(state.tab).toBe('exploration');
    expect(state.filters).toEqual(defaultFilters(quarters));
  });

  it('restores the tab, borough, type, range and search', () => {
    const state = readUrlState(
      '?tab=previsions&borough=MANHATTAN&type=MURDER&from=2020Q2&to=2022Q4&q=central',
      quarters,
    );
    expect(state.tab).toBe('previsions');
    expect(state.filters.boroughs).toEqual(['MANHATTAN']);
    expect(state.filters.types).toEqual(['MURDER']);
    expect(state.filters.query).toBe('central');
    expect(quarters[state.filters.range[0]]).toBe('2020Q2');
    expect(quarters[state.filters.range[1]]).toBe('2022Q4');
  });

  it('ignores unknown values and a reversed range', () => {
    const state = readUrlState(
      '?tab=inconnu&borough=ATLANTIS&type=SPEEDING&from=2024Q4&to=2020Q2',
      quarters,
    );
    expect(state.tab).toBe('exploration');
    expect(state.filters.boroughs).toEqual([]);
    expect(state.filters.types).toEqual([]);
    expect(state.filters.range).toEqual(full);
  });

  it('writes only non-default parameters', () => {
    expect(writeUrlState(readUrlState('', quarters), quarters)).toBe('');
    const search = writeUrlState(
      readUrlState('?tab=previsions&borough=MANHATTAN', quarters),
      quarters,
    );
    expect(search).toBe('?tab=previsions&borough=MANHATTAN');
  });

  it('round-trips a full state', () => {
    const search =
      '?tab=methode&borough=QUEENS&type=RAPE&from=2021Q1&to=2023Q2&q=pelham';
    expect(writeUrlState(readUrlState(search, quarters), quarters)).toBe(search);
  });

  it('accepts only the three tab ids', () => {
    expect(isTabId('previsions')).toBe(true);
    expect(isTabId('forecast')).toBe(false);
  });
});
