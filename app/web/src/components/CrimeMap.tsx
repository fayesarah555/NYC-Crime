// Leaflet map: one CircleMarker per selected park with coordinates, with a
// 0.05° grid aggregate below zoom 11 (see GROUP_MAX_ZOOM in lib/mapMarkers).
// The view fits the selection, scroll zoom needs Ctrl, and a marker or the
// keyboard park list opens the drill-down panel.
import {useEffect, useMemo, useState} from 'react';
import 'leaflet/dist/leaflet.css';
import {latLngBounds} from 'leaflet';
import {AspectRatio} from '@astryxdesign/core/AspectRatio';
import {CircleMarker, MapContainer, TileLayer, Tooltip, useMap, useMapEvents} from 'react-leaflet';
import {
  dominantType,
  formatInt,
  selectedCount,
  typeLabel,
  type ParkRow,
} from '../lib/filters';
import {mapMarkers, markerRadius} from '../lib/mapMarkers';
import {NEUTRAL_COLOR, clusterColor, typeColor} from '../lib/tokens';
import {fmtFixed} from '../lib/format'

function markerColor(
  park: ParkRow | null,
  clusterMode: boolean,
  k: number,
  types: string[],
): string {
  if (park === null) return NEUTRAL_COLOR;
  return clusterMode
    ? clusterColor(park.cluster, k)
    : typeColor(dominantType(park, types));
}

/** Refit only when the selection changes; refitting on every render loops. */
function FitSelection({
  parks,
  types,
  selectionKey,
}: {
  parks: ParkRow[];
  types: string[];
  selectionKey: string;
}) {
  const map = useMap();
  useEffect(() => {
    const points = parks.flatMap(park =>
      park.lat === null || park.lon === null
        ? []
        : [[park.lat, park.lon] as [number, number]],
    );
    if (points.length === 0) return;
    map.fitBounds(latLngBounds(points), {padding: [24, 24], maxZoom: 14});
    // selectionKey is the dependency that represents `parks`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, selectionKey, types]);
  return null;
}

/** Ctrl-gated wheel zoom: plain wheel scrolls the page, Ctrl zooms the map. */
function CtrlScrollZoom() {
  const map = useMap();
  useEffect(() => {
    const container = map.getContainer();
    map.scrollWheelZoom.disable();
    // Capture phase: run before Leaflet's own wheel handler so enabling here
    // takes effect for the same event.
    const onWheel = (event: WheelEvent) => {
      if (event.ctrlKey) map.scrollWheelZoom.enable();
      else map.scrollWheelZoom.disable();
    };
    container.addEventListener('wheel', onWheel, {capture: true, passive: true});
    return () => container.removeEventListener('wheel', onWheel, {capture: true});
  }, [map]);
  return null;
}

function ZoomWatcher({onZoom}: {onZoom: (zoom: number) => void}) {
  useMapEvents({
    zoomend(event) {
      onZoom(event.target.getZoom());
    },
  });
  return null;
}

export default function CrimeMap({
  parks,
  types,
  clusterMode,
  k,
  groupMode,
  selectedParkId,
  onSelect,
}: {
  parks: ParkRow[];
  types: string[];
  clusterMode: boolean;
  k: number;
  groupMode: boolean;
  selectedParkId: string | null;
  onSelect: (parkId: string) => void;
}) {
  const [zoom, setZoom] = useState(10);
  const selectionKey = useMemo(
    () => parks.map(park => park.park_id).join('|'),
    [parks],
  );
  const markers = useMemo(
    () => mapMarkers(parks, types, groupMode, zoom),
    [parks, types, groupMode, zoom],
  );
  return (
    <AspectRatio
      ratio={16 / 9}
      role="region"
      aria-label="Carte des parcs"
      aria-describedby="carte-resume">
      <MapContainer
        center={[40.72, -73.95]}
        zoom={10}
        scrollWheelZoom={false}
        style={{height: '100%', width: '100%'}}>
        <TileLayer
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution="&copy; OpenStreetMap contributors"
        />
        <FitSelection parks={parks} types={types} selectionKey={selectionKey} />
        <CtrlScrollZoom />
        <ZoomWatcher onZoom={setZoom} />
        {markers.map(marker => {
          const park = marker.park;
          const count = marker.count;
          const color = markerColor(park, clusterMode, k, types);
          const isSelected =
            marker.parkId !== null && marker.parkId === selectedParkId;
          return (
            <CircleMarker
              key={marker.key}
              center={[marker.lat, marker.lon]}
              radius={markerRadius(count)}
              pathOptions={{
                color,
                fillColor: color,
                fillOpacity: isSelected ? 0.85 : 0.55,
                weight: isSelected ? 3 : 1,
              }}
              eventHandlers={{
                click: () => {
                  if (marker.parkId !== null) onSelect(marker.parkId);
                },
              }}>
              <Tooltip>
                {park === null ? (
                  <>
                    {marker.parkCount} parcs regroupés ·{' '}
                    {formatInt(count)} crimes. Zoomez (Ctrl + molette) pour le
                    détail par parc.
                  </>
                ) : (
                  <>
                    <strong>{park.park}</strong>
                    <br />
                    {park.borough} · {typeLabel(dominantType(park, types))} ·{' '}
                    {formatInt(selectedCount(park, types))} crimes
                    <br />
                    {park.acres === null
                      ? 'Superficie inconnue'
                      : `${fmtFixed(park.acres, 2)} acres`}
                  </>
                )}
              </Tooltip>
            </CircleMarker>
          );
        })}
      </MapContainer>
    </AspectRatio>
  );
}
