// Recharts views and the token-styled borough × type heat grid.
// Gaps and coverage breaks are annotated from meta, tooltips are token-styled
// and every axis carries its unit.
import type {CSSProperties} from 'react';
import {AspectRatio} from '@astryxdesign/core/AspectRatio';
import {Card} from '@astryxdesign/core/Card';
import {Grid} from '@astryxdesign/core/Grid';
import {ScrollableArea} from '@astryxdesign/core/ScrollableArea';
import {VStack} from '@astryxdesign/core/Layout';
import {Heading, Text} from '@astryxdesign/core/Text';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
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
  type TrendPoint,
} from '../lib/filters';
import type {GapAnnotation} from '../lib/forecastChart';
import {tokenColor} from '../lib/tokens';

const AXIS_TICK = {fontSize: '0.75rem'};
const AXIS_LABEL = {fontSize: '0.7rem'};

function axisColor(): string {
  return tokenColor('--color-text-secondary');
}

const TOOLTIP_STYLE: CSSProperties = {
  background: 'var(--color-background-popover)',
  border: '1px solid var(--color-border)',
  borderRadius: 'var(--radius-inner)',
  boxShadow: 'var(--shadow-med)',
  color: 'var(--color-text-primary)',
  padding: 'var(--spacing-2)',
  fontSize: '0.8rem',
};

interface TooltipEntry {
  value?: number | string;
  payload?: unknown;
}

interface TooltipContentProps {
  active?: boolean;
  payload?: TooltipEntry[];
  label?: string | number;
}

export function ChartTooltip({active, payload, label}: TooltipContentProps) {
  const entry = payload?.[0];
  if (!active || entry === undefined) return null;
  return (
    <Text as="div" type="supporting" style={TOOLTIP_STYLE}>
      {String(label)} : {formatInt(Number(entry.value))} crimes
    </Text>
  );
}

interface ParkDatum {
  full: string;
  crimes: number;
}

function isParkDatum(value: unknown): value is ParkDatum {
  return (
    typeof value === 'object' &&
    value !== null &&
    'full' in value &&
    'crimes' in value
  );
}

function ParkTooltip({active, payload}: TooltipContentProps) {
  const datum = payload?.[0]?.payload;
  if (!active || !isParkDatum(datum)) return null;
  return (
    <Text as="div" type="supporting" style={TOOLTIP_STYLE}>
      {datum.full} : {formatInt(datum.crimes)} crimes
    </Text>
  );
}

export function TrendChart({
  data,
  gap = null,
  breakQuarter = null,
}: {
  data: TrendPoint[];
  /** 2020Q1-style missing quarter, anchored on the first quarter after it. */
  gap?: GapAnnotation | null;
  /** Coverage-break quarter read from the meta caveats (2025Q1). */
  breakQuarter?: string | null;
}) {
  return (
    <Card>
      <VStack gap={3}>
        <Heading level={3}>Tendance trimestrielle</Heading>
        <AspectRatio ratio={2.6}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={data}
              margin={{top: 12, right: 16, bottom: 8, left: 8}}>
              <CartesianGrid
                stroke={tokenColor('--color-border')}
                vertical={false}
              />
              <XAxis
                dataKey="quarter"
                stroke={axisColor()}
                tick={AXIS_TICK}
                minTickGap={24}
                label={{
                  value: 'Trimestre',
                  position: 'insideBottom',
                  offset: -4,
                  style: {...AXIS_LABEL, fill: axisColor()},
                }}
              />
              <YAxis
                stroke={axisColor()}
                tick={AXIS_TICK}
                width={56}
                label={{
                  value: 'Crimes',
                  angle: -90,
                  position: 'insideLeft',
                  style: {...AXIS_LABEL, fill: axisColor()},
                }}
              />
              <Tooltip content={<ChartTooltip />} />
              {gap !== null && (
                <ReferenceLine
                  x={gap.anchor}
                  stroke={tokenColor('--color-text-secondary')}
                  strokeDasharray="4 4"
                  label={{
                    value: `${gap.missing} absent`,
                    position: 'insideTopRight',
                    style: {...AXIS_LABEL, fill: axisColor()},
                  }}
                />
              )}
              {breakQuarter !== null && (
                <ReferenceLine
                  x={breakQuarter}
                  stroke={tokenColor('--color-text-warning')}
                  strokeDasharray="6 3"
                  label={{
                    value: 'Rupture de couverture',
                    position: 'insideTopLeft',
                    style: {...AXIS_LABEL, fill: axisColor()},
                  }}
                />
              )}
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
        {gap !== null && (
          <Text type="supporting" color="secondary">
            Lecture : {gap.missing} est absent de la source (jamais traité
            comme zéro) ; la ligne relie les trimestres voisins.
          </Text>
        )}
        {breakQuarter !== null && (
          <Text type="supporting" color="secondary">
            Lecture : rupture de couverture en {breakQuarter}, quand Central
            Park entre dans la source ; le saut n'est pas un pic de
            criminalité.
          </Text>
        )}
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
        {/* Inline scroll on small screens: the grid keeps a readable minimum
            width and the viewport scrolls instead of squeezing every label. */}
        <ScrollableArea axis="inline" label="Tableau arrondissement par type de délit">
          <Grid
            columns={types.length + 1}
            gap={1}
            style={{minWidth: `${(types.length + 1) * 5}rem`}}>
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
        </ScrollableArea>
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
  onSelect,
}: {
  rows: ParkRow[];
  types: string[];
  onSelect?: (parkId: string) => void;
}) {
  const data = rows.map(row => ({
    park: row.park.length > 26 ? `${row.park.slice(0, 25)}…` : row.park,
    full: row.park,
    crimes: selectedCount(row, types),
  }));
  return (
    <Card>
      <VStack gap={3}>
        <Heading level={3}>Top 10 des parcs</Heading>
        <Text type="supporting" color="secondary">
          Classement sur la période et les filtres sélectionnés.{' '}
          {onSelect !== undefined
            ? 'Cliquez une barre pour ouvrir le détail du parc.'
            : null}
        </Text>
        <AspectRatio ratio={2.6}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={data}
              layout="vertical"
              margin={{top: 4, right: 24, bottom: 16, left: 8}}>
              <CartesianGrid
                stroke={tokenColor('--color-border')}
                horizontal={false}
              />
              <XAxis
                type="number"
                stroke={axisColor()}
                tick={AXIS_TICK}
                label={{
                  value: 'Crimes',
                  position: 'insideBottom',
                  offset: -8,
                  style: {...AXIS_LABEL, fill: axisColor()},
                }}
              />
              <YAxis
                type="category"
                dataKey="park"
                width={170}
                stroke={axisColor()}
                tick={AXIS_TICK}
              />
              <Tooltip content={<ParkTooltip />} />
              <Bar
                dataKey="crimes"
                name="Crimes"
                cursor={onSelect === undefined ? 'default' : 'pointer'}
                fill={tokenColor('--color-data-categorical-blue')}
                onClick={(_item, index) => {
                  const row = rows[index];
                  if (row !== undefined) onSelect?.(row.park_id);
                }}
              />
            </BarChart>
          </ResponsiveContainer>
        </AspectRatio>
      </VStack>
    </Card>
  );
}
