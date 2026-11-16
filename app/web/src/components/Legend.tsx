// Map legend: crime-type or cluster colours from tokens, plus the size scale
// (radius ∝ √crimes, capped at RADIUS_MAX px — the cap is documented here).
import {Grid} from '@astryxdesign/core/Grid';
import {HStack, VStack} from '@astryxdesign/core/Layout';
import {Text} from '@astryxdesign/core/Text';
import {CRIME_TYPES, typeLabel} from '../lib/filters';
import {RADIUS_MAX, markerRadius} from '../lib/mapMarkers';
import {NEUTRAL_COLOR, clusterColor, typeColor} from '../lib/tokens';

const SIZE_SAMPLES = [1, 16, 100];

export default function Legend({
  clusterMode,
  types,
  k,
}: {
  clusterMode: boolean;
  types: string[];
  k: number;
}) {
  const items = clusterMode
    ? [
        ...Array.from({length: k}, (_, index) => ({
          color: clusterColor(index, k),
          label: `Cluster ${index}`,
        })),
        {color: NEUTRAL_COLOR, label: 'Hors cluster'},
      ]
    : (types.length ? types : CRIME_TYPES).map(type => ({
        color: typeColor(type),
        label: typeLabel(type),
      }));
  return (
    <VStack gap={2}>
      <Grid columns={{minWidth: 130, repeat: 'fit'}} gap={2}>
        {items.map(item => (
          <HStack key={item.label} gap={2} vAlign="center">
            <Text
              as="div"
              style={{
                width: '0.75rem',
                height: '0.75rem',
                borderRadius: 'var(--radius-full)',
                background: item.color,
              }}>
              {null}
            </Text>
            <Text type="supporting" color="secondary">
              {item.label}
            </Text>
          </HStack>
        ))}
      </Grid>
      <HStack gap={3} vAlign="center">
        <Text type="supporting" color="secondary">
          Taille : rayon ∝ √crimes, plafonné à {RADIUS_MAX} px.
        </Text>
        {SIZE_SAMPLES.map(count => (
          <HStack key={count} gap={1} vAlign="center">
            <Text
              as="div"
              role="img"
              aria-label={`${count} crimes`}
              style={{
                width: `${markerRadius(count)}px`,
                height: `${markerRadius(count)}px`,
                borderRadius: 'var(--radius-full)',
                border: '1px solid var(--color-border-emphasized)',
                background: 'var(--color-background-muted)',
              }}>
              {null}
            </Text>
            <Text type="supporting" color="secondary">
              {count}
            </Text>
          </HStack>
        ))}
        <Text type="supporting" color="secondary">
          crimes
        </Text>
      </HStack>
    </VStack>
  );
}
