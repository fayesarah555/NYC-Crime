// Recharts views and the token-styled borough × type heat grid.
import {AspectRatio} from '@astryxdesign/core/AspectRatio';
import {Card} from '@astryxdesign/core/Card';
import {Grid} from '@astryxdesign/core/Grid';
import {VStack} from '@astryxdesign/core/Layout';
import {Heading, Text} from '@astryxdesign/core/Text';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  formatInt,
  selectedCount,
  typeLabel,
  type BoroughRow,
  type ParkRow,
} from '../lib/filters';
import {tokenColor} from '../lib/tokens';

const AXIS_TICK = {fontSize: '0.75rem'};

function axisColor(): string {
  return tokenColor('--color-text-secondary');
}

export function TrendChart({
  data,
}: {
  data: {quarter: string; crimes: number}[];
}) {
  return (
    <Card>
      <VStack gap={3}>
        <Heading level={3}>Tendance trimestrielle</Heading>
        <AspectRatio ratio={2.6}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={data}
              margin={{top: 8, right: 16, bottom: 0, left: 0}}>
              <CartesianGrid
                stroke={tokenColor('--color-border')}
                vertical={false}
              />
              <XAxis
                dataKey="quarter"
                stroke={axisColor()}
                tick={AXIS_TICK}
                minTickGap={24}
              />
              <YAxis
                stroke={axisColor()}
                tick={AXIS_TICK}
                width={48}
              />
              <Tooltip />
              <Line
                type="monotone"
                dataKey="crimes"
                name="Crimes"
                stroke={tokenColor('--color-data-categorical-blue')}
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </AspectRatio>
      </VStack>
    </Card>
  );
}

export function BoroughTypeGrid({
  types,
  rows,
}: {
  types: string[];
  rows: BoroughRow[];
}) {
  const max = Math.max(
    1,
    ...rows.flatMap(row => types.map(type => row.counts[type] ?? 0)),
  );
  const level = (value: number) =>
    value === 0 ? 0 : Math.min(3, Math.max(1, Math.ceil((value / max) * 3)));
  return (
    <Card>
      <VStack gap={3}>
        <Heading level={3}>Arrondissement × type de délit</Heading>
        <Grid columns={types.length + 1} gap={1}>
          <Text type="label" color="secondary">
            Arrondissement
          </Text>
          {types.map(type => (
            <Text key={type} type="label" color="secondary">
              {typeLabel(type)}
            </Text>
          ))}
          {rows.flatMap(row => [
            <Text key={row.borough} type="body" weight="medium">
              {row.borough}
            </Text>,
            ...types.map(type => {
              const value = row.counts[type] ?? 0;
              const shade = level(value);
              return (
                <Text
                  key={row.borough + type}
                  as="div"
                  type="supporting"
                  style={{
                    padding: 'var(--spacing-2)',
                    borderRadius: 'var(--radius-inner)',
                    background:
                      shade === 0
                        ? 'transparent'
                        : `var(--color-data-blue-${shade})`,
                    color: 'var(--color-text-primary)',
                  }}>
                  {value === 0 ? '' : formatInt(value)}
                </Text>
              );
            }),
          ])}
        </Grid>
        <Text type="supporting" color="secondary">
          Intensité relative à la cellule maximale de la sélection.
        </Text>
      </VStack>
    </Card>
  );
}

export function TopParksChart({
  rows,
  types,
}: {
  rows: ParkRow[];
  types: string[];
}) {
  const data = rows.map(row => ({
    park: row.park.length > 26 ? `${row.park.slice(0, 25)}…` : row.park,
    crimes: selectedCount(row, types),
  }));
  return (
    <Card>
      <VStack gap={3}>
        <Heading level={3}>Top 10 des parcs</Heading>
        <AspectRatio ratio={2.6}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={data}
              layout="vertical"
              margin={{top: 4, right: 24, bottom: 4, left: 8}}>
              <CartesianGrid
                stroke={tokenColor('--color-border')}
                horizontal={false}
              />
              <XAxis type="number" stroke={axisColor()} tick={AXIS_TICK} />
              <YAxis
                type="category"
                dataKey="park"
                width={170}
                stroke={axisColor()}
                tick={AXIS_TICK}
              />
              <Tooltip />
              <Bar
                dataKey="crimes"
                name="Crimes"
                fill={tokenColor('--color-data-categorical-blue')}
              />
            </BarChart>
          </ResponsiveContainer>
        </AspectRatio>
      </VStack>
    </Card>
  );
}
