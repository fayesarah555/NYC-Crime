// Park drill-down: quarterly history from the cube, type breakdown, acres,
// cluster, borough, coverage era and risk rate. Opened by a marker or the
// keyboard park list; the panel is a region, not a modal.
import {AspectRatio} from '@astryxdesign/core/AspectRatio';
import {Button} from '@astryxdesign/core/Button';
import {Card} from '@astryxdesign/core/Card';
import {Grid} from '@astryxdesign/core/Grid';
import {HStack, VStack} from '@astryxdesign/core/Layout';
import {
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
} from '@astryxdesign/core/Table';
import {Heading, Text} from '@astryxdesign/core/Text';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type {Cube, Park} from '../lib/data';
import {cube} from '../lib/data';
import {formatInt, typeLabel} from '../lib/filters';
import {tokenColor} from '../lib/tokens';
import {ChartTooltip} from './Charts';
import {fmtFixed} from '../lib/format'

/** Quarterly totals from the cube; the export omits zero park-quarters. */
export function parkHistory(
  source: Cube,
  parkId: string,
  types: string[],
): {quarter: string; crimes: number}[] {
  const typeIndexes = source.crime_types
    .map((type, index) => (types.includes(type) ? index : -1))
    .filter(index => index >= 0);
  return source.quarters.map(quarter => {
    const cell = source.parks[parkId]?.[quarter];
    let crimes = 0;
    if (cell !== undefined) {
      const indexes =
        types.length === 0 ? cell.map((_, index) => index) : typeIndexes;
      for (const index of indexes) {
        const value = cell[index];
        if (value !== null && value !== undefined) crimes += value;
      }
    }
    return {quarter, crimes};
  });
}

function Fact({label, value}: {label: string; value: string}) {
  return (
    <VStack gap={1}>
      <Text type="supporting" color="secondary">
        {label}
      </Text>
      <Text type="body">{value}</Text>
    </VStack>
  );
}

export default function ParkDetail({
  park,
  types,
  onClose,
}: {
  park: Park;
  types: string[];
  onClose: () => void;
}) {
  const history = parkHistory(cube, park.park_id, types);
  const breakdown = Object.entries(park.counts).sort((a, b) => b[1] - a[1]);
  return (
    <Card>
      <VStack gap={4} role="region" aria-label="Détail du parc">
        <HStack hAlign="between" vAlign="center">
          <Heading level={3}>{park.park}</Heading>
          <Button variant="ghost" size="sm" label="Fermer" onClick={onClose} />
        </HStack>
        <Grid columns={{minWidth: 150, repeat: 'fit'}} gap={3}>
          <Fact label="Arrondissement" value={park.borough} />
          <Fact
            label="Superficie"
            value={park.acres === null ? '—' : `${fmtFixed(park.acres, 2)} acres`}
          />
          <Fact
            label="Cluster"
            value={park.cluster === null ? '—' : String(park.cluster)}
          />
          <Fact label="Couverture" value={park.coverage_era} />
          <Fact
            label="Risque (crimes / 100 acres)"
            value={
              park.crimes_per_100_acres === null
                ? '—'
                : `${fmtFixed(park.crimes_per_100_acres, 1)} (rang ${park.risk_rank ?? '—'})`
            }
          />
          <Fact
            label={
              types.length === 0 ? 'Crimes (période complète)' : 'Crimes (types filtrés)'
            }
            value={formatInt(
              types.length === 0
                ? park.total
                : types.reduce((sum, type) => sum + (park.counts[type] ?? 0), 0),
            )}
          />
        </Grid>
        <AspectRatio ratio={3}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={history}
              margin={{top: 8, right: 16, bottom: 8, left: 8}}>
              <CartesianGrid
                stroke={tokenColor('--color-border')}
                vertical={false}
              />
              <XAxis
                dataKey="quarter"
                tick={{fontSize: '0.75rem'}}
                stroke={tokenColor('--color-text-secondary')}
                minTickGap={32}
                label={{
                  value: 'Trimestre',
                  position: 'insideBottom',
                  offset: -4,
                  style: {
                    fontSize: '0.7rem',
                    fill: tokenColor('--color-text-secondary'),
                  },
                }}
              />
              <YAxis
                width={56}
                tick={{fontSize: '0.75rem'}}
                stroke={tokenColor('--color-text-secondary')}
                label={{
                  value: 'Crimes',
                  angle: -90,
                  position: 'insideLeft',
                  style: {
                    fontSize: '0.7rem',
                    fill: tokenColor('--color-text-secondary'),
                  },
                }}
              />
              <Tooltip content={<ChartTooltip />} />
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
        <Text type="supporting" color="secondary">
          Historique trimestriel issu du cube ; 2020Q1 absent de la source.
        </Text>
        <VStack gap={2}>
          <Heading level={4}>Répartition par type (période complète)</Heading>
          <Table density="compact">
            <TableHeader>
              <TableRow>
                <TableHeaderCell>Type</TableHeaderCell>
                <TableHeaderCell>Crimes</TableHeaderCell>
              </TableRow>
            </TableHeader>
            <TableBody>
              {breakdown.map(([type, count]) => (
                <TableRow key={type}>
                  <TableCell>{typeLabel(type)}</TableCell>
                  <TableCell>{formatInt(count)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </VStack>
      </VStack>
    </Card>
  );
}
