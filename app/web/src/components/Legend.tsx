// Map legend: crime-type colours or cluster colours, straight from tokens.
import {Grid} from '@astryxdesign/core/Grid';
import {HStack} from '@astryxdesign/core/Layout';
import {Text} from '@astryxdesign/core/Text';
import {CRIME_TYPES, typeLabel} from '../lib/filters';
import {
  CLUSTER_TOKENS,
  NEUTRAL_TOKEN,
  typeToken,
} from '../lib/tokens';

export default function Legend({
  clusterMode,
  types,
}: {
  clusterMode: boolean;
  types: string[];
}) {
  const items = clusterMode
    ? [
        ...CLUSTER_TOKENS.map((token, index) => ({
          token,
          label: `Cluster ${index}`,
        })),
        {token: NEUTRAL_TOKEN, label: 'Hors cluster'},
      ]
    : (types.length ? types : CRIME_TYPES).map(type => ({
        token: typeToken(type),
        label: typeLabel(type),
      }));
  return (
    <Grid columns={{minWidth: 130, repeat: 'fit'}} gap={2}>
      {items.map(item => (
        <HStack key={item.label} gap={2} vAlign="center">
          <Text
            as="div"
            style={{
              width: '0.75rem',
              height: '0.75rem',
              borderRadius: 'var(--radius-full)',
              background: `var(${item.token})`,
            }}>
            {null}
          </Text>
          <Text type="supporting" color="secondary">
            {item.label}
          </Text>
        </HStack>
      ))}
    </Grid>
  );
}
