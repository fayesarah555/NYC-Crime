import {describe, expect, it} from 'vitest';
import type {ParkRow} from './filters';
import {
  GROUP_MAX_ZOOM,
  RADIUS_MAX,
  mapMarkers,
  markerRadius,
} from './mapMarkers';

function park(parkId: string, lat: number | null, lon: number | null, total: number): ParkRow {
  return {
    park_id: parkId,
    park: parkId,
    borough: 'MANHATTAN',
    lat,
    lon,
    acres: 10,
    total,
    dominant_type: 'GRAND LARCENY',
    cluster: 0,
    counts: {'GRAND LARCENY': total},
  };
}

const rows = [
  park('A', 40.7, -73.9, 10),
  park('B', 40.701, -73.901, 5),
  park('C', 40.9, -73.9, 2),
  park('D', null, null, 7),
];

describe('mapMarkers', () => {
  it('draws one marker per geolocated park and drops the rest', () => {
    const markers = mapMarkers(rows, [], false, 12);
    expect(markers).toHaveLength(3);
    expect(markers.map(marker => marker.parkId)).toEqual(['A', 'B', 'C']);
  });

  it('groups nearby parks on the grid below the zoom threshold', () => {
    const markers = mapMarkers(rows, [], true, GROUP_MAX_ZOOM);
    expect(markers).toHaveLength(2);
    const group = markers.find(marker => marker.parkCount === 2);
    expect(group?.parkId).toBeNull();
    expect(group?.count).toBe(15);
  });

  it('stops grouping above the zoom threshold', () => {
    expect(mapMarkers(rows, [], true, GROUP_MAX_ZOOM + 1)).toHaveLength(3);
  });

  it('caps the radius so one park cannot cover the city', () => {
    expect(markerRadius(1)).toBe(6);
    expect(markerRadius(10_000)).toBe(RADIUS_MAX);
  });

  it('sums only the selected types into the marker count', () => {
    const markers = mapMarkers(rows, ['GRAND LARCENY'], false, 12);
    expect(markers[0]?.count).toBe(10);
  });
});
