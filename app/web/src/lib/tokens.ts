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
  '--color-data-categorical-teal',
  '--color-data-categorical-red',
];

/**
 * Colour tokens for k clusters. Throws instead of wrapping when the export
 * grows past the palette, so new clusters are visible as bugs, not colours.
 */
export function clusterTokens(k: number): string[] {
  if (k > CLUSTER_TOKENS.length) {
    throw new Error(
      `Palette de ${CLUSTER_TOKENS.length} couleurs pour k = ${k} : étendre CLUSTER_TOKENS.`,
    );
  }
  return CLUSTER_TOKENS.slice(0, k);
}

export const NEUTRAL_TOKEN = '--color-data-neutral';

// Shared data palette (Okabe–Ito) exported by export_web.py; the same values
// feed Streamlit and matplotlib so a crime type keeps one colour everywhere.
import paletteJson from '../data/palette.json';

export const DATA_COLORS: Record<string, string> = paletteJson.colors;
export const NEUTRAL_COLOR = paletteJson.neutral;

export function typeColor(type: string): string {
  return DATA_COLORS[type] ?? NEUTRAL_COLOR;
}

export function clusterColor(cluster: number | null, k: number): string {
  if (cluster === null) return NEUTRAL_COLOR;
  const color = paletteJson.clusters[cluster];
  if (color === undefined || k > paletteJson.clusters.length) {
    throw new Error(
      `Cluster ${cluster} hors palette (k = ${k}, palette ${paletteJson.clusters.length}).`,
    );
  }
  return color;
}

export function typeToken(type: string): string {
  return TYPE_TOKENS[type] ?? NEUTRAL_TOKEN;
}
