// Filters and the active tab live in the URL query string: a view is
// linkable, reload-safe and the browser's back/forward buttons work.

import {useCallback, useEffect, useState} from 'react';
import {BOROUGH_OPTIONS, CRIME_TYPES, type Filters} from './filters';

export type TabId = 'exploration' | 'previsions' | 'methode';

export interface UrlState {
  filters: Filters;
  tab: TabId;
}

const TABS: readonly string[] = ['exploration', 'previsions', 'methode'];

export function isTabId(value: string): value is TabId {
  return TABS.includes(value);
}

export function defaultFilters(quarters: string[]): Filters {
  return {
    boroughs: [],
    types: [],
    range: [0, Math.max(0, quarters.length - 1)],
    query: '',
  };
}

export function defaultUrlState(quarters: string[]): UrlState {
  return {filters: defaultFilters(quarters), tab: 'exploration'};
}

function quarterIndex(quarters: string[], label: string | null): number {
  return label === null ? -1 : quarters.indexOf(label);
}

/** Unknown or stale parameter values fall back to the default view. */
export function readUrlState(search: string, quarters: string[]): UrlState {
  const params = new URLSearchParams(search);
  const boroughs = [...new Set(params.getAll('borough'))].filter(borough =>
    BOROUGH_OPTIONS.includes(borough),
  );
  const types = [...new Set(params.getAll('type'))].filter(type =>
    CRIME_TYPES.includes(type),
  );
  const from = quarterIndex(quarters, params.get('from'));
  const to = quarterIndex(quarters, params.get('to'));
  const fallback = defaultFilters(quarters).range;
  const range: [number, number] =
    from >= 0 && to >= from ? [from, to] : fallback;
  const tabParam = params.get('tab') ?? '';
  const tab = TABS.includes(tabParam) ? (tabParam as TabId) : 'exploration';
  return {
    filters: {boroughs, types, range, query: params.get('q') ?? ''},
    tab,
  };
}

/** Serialized query string; only non-default values are written. */
export function writeUrlState(state: UrlState, quarters: string[]): string {
  const params = new URLSearchParams();
  if (state.tab !== 'exploration') params.set('tab', state.tab);
  for (const borough of state.filters.boroughs) {
    params.append('borough', borough);
  }
  for (const type of state.filters.types) params.append('type', type);
  const [from, to] = state.filters.range;
  if (from !== 0 || to !== quarters.length - 1) {
    params.set('from', quarters[from] ?? '');
    params.set('to', quarters[to] ?? '');
  }
  if (state.filters.query !== '') params.set('q', state.filters.query);
  const search = params.toString();
  return search === '' ? '' : `?${search}`;
}

/** Full URL for history.pushState. */
export function urlFor(state: UrlState, quarters: string[]): string {
  return `${window.location.pathname}${writeUrlState(state, quarters)}`;
}

/**
 * State synced both ways: writes push a history entry, popstate reads the URL
 * back so back/forward restore the filters and tab.
 */
export function useUrlState(
  quarters: string[],
): [UrlState, (next: UrlState) => void] {
  const [state, setState] = useState<UrlState>(() =>
    readUrlState(window.location.search, quarters),
  );
  useEffect(() => {
    const onPop = () => setState(readUrlState(window.location.search, quarters));
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, [quarters]);
  const update = useCallback(
    (next: UrlState) => {
      setState(next);
      window.history.pushState(null, '', urlFor(next, quarters));
    },
    [quarters],
  );
  return [state, update];
}
