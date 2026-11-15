// Resolve Astryx CSS custom properties to concrete rgb() values. SVG
// attributes (Leaflet paths, recharts strokes) do not understand var(), so the
// token is resolved once through a probe element and cached.

const cache = new Map<string, string>();

export function tokenColor(name: string): string {
  const cached = cache.get(name);
  if (cached !== undefined) return cached;
  const probe = document.createElement('div');
  probe.style.color = `var(${name})`;
  document.documentElement.appendChild(probe);
  const resolved = getComputedStyle(probe).color;
  probe.remove();
  cache.set(name, resolved);
  return resolved;
}

export const TYPE_TOKENS: Record<string, string> = {
  BURGLARY: '--color-data-categorical-purple',
  'FELONY ASSAULT': '--color-data-categorical-red',
  'GRAND LARCENY': '--color-data-categorical-blue',
  'GRAND LARCENY AUTO': '--color-data-categorical-cyan',
  MURDER: '--color-data-categorical-pink',
  RAPE: '--color-data-categorical-teal',
  ROBBERY: '--color-data-categorical-orange',
};

export const CLUSTER_TOKENS = [
  '--color-data-categorical-blue',
  '--color-data-categorical-orange',
  '--color-data-categorical-purple',
  '--color-data-categorical-green',
];

export const NEUTRAL_TOKEN = '--color-data-neutral';

export function typeToken(type: string): string {
  return TYPE_TOKENS[type] ?? NEUTRAL_TOKEN;
}
