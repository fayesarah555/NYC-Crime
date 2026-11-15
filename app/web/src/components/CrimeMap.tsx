// Leaflet map: one CircleMarker per selected park with coordinates.
// Radius scales with sqrt(crimes); colour by dominant type or by cluster.
import 'leaflet/dist/leaflet.css';
import {AspectRatio} from '@astryxdesign/core/AspectRatio';
import {CircleMarker, MapContainer, TileLayer, Tooltip} from 'react-leaflet';
import {
  dominantType,
  formatInt,
  selectedCount,
  type ParkRow,
} from '../lib/filters';
import {CLUSTER_TOKENS, NEUTRAL_TOKEN, tokenColor, typeToken} from '../lib/tokens';

function clusterToken(cluster: number | null): string {
  return cluster === null
    ? NEUTRAL_TOKEN
    : CLUSTER_TOKENS[cluster % CLUSTER_TOKENS.length];
}

export default function CrimeMap({
  parks,
  types,
  clusterMode,
}: {
  parks: ParkRow[];
  types: string[];
  clusterMode: boolean;
}) {
  return (
    <AspectRatio
      ratio={16 / 9}
      role="region"
      aria-label="Carte des parcs"
      aria-describedby="carte-resume">
      <MapContainer
        center={[40.72, -73.95]}
        zoom={10}
        scrollWheelZoom
        style={{height: '100%', width: '100%'}}>
        <TileLayer
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution="&copy; OpenStreetMap contributors"
        />
        {parks.map(park => {
          const count = selectedCount(park, types);
          const token = clusterMode
            ? clusterToken(park.cluster)
            : typeToken(dominantType(park, types));
          const color = tokenColor(token);
          return (
            <CircleMarker
              key={park.park}
              center={[park.lat!, park.lon!]}
              radius={Math.min(36, 2 + 4 * Math.sqrt(count))}
              pathOptions={{
                color,
                fillColor: color,
                fillOpacity: 0.55,
                weight: 1,
              }}>
              <Tooltip>
                {park.park} — {formatInt(count)} crimes
              </Tooltip>
            </CircleMarker>
          );
        })}
      </MapContainer>
    </AspectRatio>
  );
}
