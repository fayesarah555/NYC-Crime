// Map marker geometry: one marker per park, or a grid aggregate at low zoom.
// Radius scales with sqrt(crimes) and is capped so a single park cannot paint
// over the whole city.

import {selectedCount, type ParkRow} from './filters';

export interface MapMarker {
  /** Stable React key: park_id, or "latCell:lonCell" for a group. */
  key: string;
  lat: number;
  lon: number;
  count: number;
  /** The park for an individual marker; null for a grouped marker. */
  parkId: string | null;
  parkCount: number;
  /** Full park row for the tooltip (individual markers only). */
  park: ParkRow | null;
}

/** Group below this zoom; above it, one marker per park. */
export const GROUP_MAX_ZOOM = 11;
/** Grid cell size in degrees (~5.5 km at NYC's latitude). */
export const GROUP_CELL = 0.05;
/** Radius cap in pixels, shown in the size legend. */
export const RADIUS_MAX = 36;

export function markerRadius(count: number): number {
  return Math.min(RADIUS_MAX, 2 + 4 * Math.sqrt(count));
}

interface Positioned {
  park: ParkRow;
  lat: number;
  lon: number;
  count: number;
}

function positioned(parks: ParkRow[], types: string[]): Positioned[] {
  const rows: Positioned[] = [];
  for (const park of parks) {
    if (park.lat === null || park.lon === null) continue;
    rows.push({
      park,
      lat: park.lat,
      lon: park.lon,
      count: selectedCount(park, types),
    });
  }
  return rows;
}

export function mapMarkers(
  parks: ParkRow[],
  types: string[],
  group: boolean,
  zoom: number,
): MapMarker[] {
  const rows = positioned(parks, types);
  if (!group || zoom > GROUP_MAX_ZOOM) {
    return rows.map(row => ({
      key: row.park.park_id,
      lat: row.lat,
      lon: row.lon,
      count: row.count,
      parkId: row.park.park_id,
      parkCount: 1,
      park: row.park,
    }));
  }
  const cells = new Map<
    string,
    {lat: number; lon: number; count: number; parkCount: number}
  >();
  for (const row of rows) {
    const key = `${Math.round(row.lat / GROUP_CELL)}:${Math.round(row.lon / GROUP_CELL)}`;
    const cell = cells.get(key) ?? {lat: 0, lon: 0, count: 0, parkCount: 0};
    cell.lat += row.lat;
    cell.lon += row.lon;
    cell.count += row.count;
    cell.parkCount += 1;
    cells.set(key, cell);
  }
  return [...cells.entries()].map(([key, cell]) => ({
    key,
    lat: cell.lat / cell.parkCount,
    lon: cell.lon / cell.parkCount,
    count: cell.count,
    parkId: null,
    parkCount: cell.parkCount,
    park: null,
  }));
}
