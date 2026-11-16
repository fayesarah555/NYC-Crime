// Prévisions tab — static artefacts only, no model recomputation.
// The fan chart joins observed history to the reconciled forecast points and
// their interval; the backtest panel illustrates the exporter's one-step rule.
import {useState} from 'react';
import {AspectRatio} from '@astryxdesign/core/AspectRatio';
import {Card} from '@astryxdesign/core/Card';
import {Grid} from '@astryxdesign/core/Grid';
import {VStack} from '@astryxdesign/core/Layout';
import {Selector} from '@astryxdesign/core/Selector';
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
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {forecast, meta, series} from '../lib/data';
import type {Forecast, ForecastMetrics, Meta, Series} from '../lib/data';
import {
  fanSeries,
  ruleBacktest,
  type FanPoint,
  type RulePoint,
} from '../lib/forecastChart';
import {formatInt} from '../lib/filters';
import {tokenColor} from '../lib/tokens';
import {fmtFixed} from '../lib/format'

const VILLE = 'VILLE';

function Metric({label, value}: {label: string; value: string}) {
  return (
    <Card>
      <VStack gap={2}>
        <Text type="supporting" color="secondary">
          {label}
        </Text>
        <Heading level={2}>{value}</Heading>
      </VStack>
    </Card>
  );
}

/** 0.05 -> "95": the interval level the artefacts were fitted with. */
function intervalLevel(alpha: number): number {
  return Math.round((1 - alpha) * 100);
}

/** DM test of the best challenger vs seasonal-naive, when one was run. */
function challengerNote(metrics: ForecastMetrics): string | null {
  const challenger = metrics.best_challenger;
  if (!challenger?.model || challenger.dm_p === null) return null;
  return `Diebold-Mariano (HLN) du meilleur challenger, ${challenger.model}, contre la naïve saisonnière : p = ${fmtFixed(challenger.dm_p, 2)}.`;
}

function isFanPoint(value: unknown): value is FanPoint {
  return typeof value === 'object' && value !== null && 'quarter' in value;
}

function FanTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: {payload?: unknown}[];
  label?: string | number;
}) {
  const point = payload?.[0]?.payload;
  if (!active || !isFanPoint(point)) return null;
  const style = {
    background: 'var(--color-background-popover)',
    border: '1px solid var(--color-border)',
    borderRadius: 'var(--radius-inner)',
    boxShadow: 'var(--shadow-med)',
    color: 'var(--color-text-primary)',
    padding: 'var(--spacing-2)',
    fontSize: '0.8rem',
  };
  return (
    <Text as="div" type="supporting" style={style}>
      {String(label ?? point.quarter)}
      {point.history !== null && (
        <>
          <br />
          Observé : {formatInt(point.history)} crimes
        </>
      )}
      {point.forecast !== null && (
        <>
          <br />
          Prévision : {fmtFixed(point.forecast, 1)} crimes
        </>
      )}
      {point.interval !== null && (
        <>
          <br />
          Intervalle : {fmtFixed(point.interval[0], 1)} –{' '}
          {fmtFixed(point.interval[1], 1)}
        </>
      )}
    </Text>
  );
}

function isRulePoint(value: unknown): value is RulePoint {
  return typeof value === 'object' && value !== null && 'rule' in value;
}

function RuleTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: {payload?: unknown}[];
  label?: string | number;
}) {
  const point = payload?.[0]?.payload;
  if (!active || !isRulePoint(point)) return null;
  return (
    <Text
      as="div"
      type="supporting"
      style={{
        background: 'var(--color-background-popover)',
        border: '1px solid var(--color-border)',
        borderRadius: 'var(--radius-inner)',
        boxShadow: 'var(--shadow-med)',
        color: 'var(--color-text-primary)',
        padding: 'var(--spacing-2)',
        fontSize: '0.8rem',
      }}>
      {String(label ?? point.quarter)}
      {point.actual !== null && (
        <>
          <br />
          Réel : {formatInt(point.actual)} crimes
        </>
      )}
      {point.rule !== null && (
        <>
          <br />
          Règle : {formatInt(point.rule)} crimes
        </>
      )}
    </Text>
  );
}

const AXIS_STYLE = {fontSize: '0.75rem'};

function axisColor(): string {
  return tokenColor('--color-text-secondary');
}

export default function ForecastTab({
  data = forecast,
  meta: metaData = meta,
  seriesData = series,
}: {
  data?: Forecast;
  meta?: Meta;
  seriesData?: Series;
}) {
  const [scope, setScope] = useState<string>(VILLE);
  const isCity = scope === VILLE;
  const metrics = (isCity ? data.metrics.city : data.metrics.boroughs[scope]) ??
    data.metrics.city;
  const points = (isCity ? data.city : data.boroughs[scope]) ?? data.city;
  const history = (isCity ? seriesData.city : seriesData.boroughs[scope]) ??
    seriesData.city;
  const level = intervalLevel(metaData.ci_alpha);
  const gapQuarter = metaData.missing_quarters[0] ?? null;
  const fan = fanSeries(seriesData.quarters, history, points);
  const backtest = ruleBacktest(seriesData.quarters, history);
  const scopeLabel = isCity ? 'citywide' : scope;
  const options = [
    {value: VILLE, label: 'Ville entière (citywide)'},
    ...Object.keys(data.boroughs).map(borough => ({
      value: borough,
      label: borough,
    })),
  ];

  return (
    <VStack gap={6}>
      <Selector
        label="Territoire de la prévision"
        options={options}
        value={scope}
        onChange={setScope}
      />
      <Grid columns={{minWidth: 200, repeat: 'fit'}} gap={4}>
        <Metric
          label="Modèle retenu"
          value={String(metrics.selected_model).toUpperCase()}
        />
        <Metric
          label="MAE (backtest, moyenne ± écart-type)"
          value={`${fmtFixed(metrics.selected_mae, 2)} ± ${fmtFixed(metrics.selected_mae_sd, 2)}`}
        />
        <Metric
          label="RMSE (backtest)"
          value={fmtFixed(metrics.selected_rmse, 2)}
        />
        <Metric
          label="MAPE (backtest)"
          value={
            metrics.selected_mape === null
              ? 'n.d.'
              : `${fmtFixed(metrics.selected_mape, 2)} %`
          }
        />
      </Grid>

      {metrics.selection_caveat_fr !== undefined && (
        <Text type="supporting" color="secondary">
          Avertissement (texte du modèle) : {metrics.selection_caveat_fr}
        </Text>
      )}
      <Text type="body">
        Baseline naïve saisonnière récursive : MAE{' '}
        {fmtFixed(metrics.baseline_mae, 2)} ± {fmtFixed(metrics.baseline_mae_sd, 2)},
        soit une amélioration de {fmtFixed(metrics.improvement_pct, 1)} % sur{' '}
        {metrics.backtest_quarters} prévisions de backtest (origines
        glissantes).
      </Text>
      <Text type="body">
        Règle à un pas (valeur observée du même trimestre un an plus tôt,
        référence sur {backtest.length} trimestres) : MAE{' '}
        {fmtFixed(metrics.baseline_mae_seasonal_rule, 2)}. La sélection reste sur
        le backtest glissant, pas sur cette règle.
      </Text>
      {metrics.dm_p_vs_naive === null && (
        <Text type="body" color="secondary">
          Diebold-Mariano contre la naïve saisonnière récursive : sans objet
          quand la naïve est le modèle retenu.
        </Text>
      )}
      {/* The winner's DM test and the best-challenger note are the same test
          when the winner is the best challenger: print it once. */}
      {metrics.dm_p_vs_naive !== null &&
        metrics.best_challenger?.model !== metrics.selected_model && (
          <Text type="body" color="secondary">
            Diebold-Mariano (HLN) du modèle retenu contre la naïve saisonnière
            récursive : p = {fmtFixed(metrics.dm_p_vs_naive, 2)}.
          </Text>
        )}
      {challengerNote(metrics) !== null && (
        <Text type="body" color="secondary">
          {challengerNote(metrics)}
        </Text>
      )}
      {isCity && metrics.reconciliation != null && (
        <Text type="body" color="secondary">
          Prévisions citywide réconciliées (bottom-up : arrondissements
          modélisés + résidu saisonnier des arrondissements non modélisés) ;
          écart moyen avec la prévision citywide brute :{' '}
          {fmtFixed(metrics.reconciliation.delta_mean, 2)} crimes par trimestre.
        </Text>
      )}
      {!isCity && (
        <Text type="body" color="secondary">
          Prévision de l'arrondissement (série modélisée séparément) ; la
          réconciliation bottom-up ne concerne que la prévision citywide.
        </Text>
      )}

      <Card>
        <VStack gap={3}>
          <Heading level={3}>Prévisions {scopeLabel} : historique et éventail</Heading>
          <AspectRatio ratio={2.4}>
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart
                data={fan}
                margin={{top: 12, right: 16, bottom: 8, left: 8}}>
                <CartesianGrid
                  stroke={tokenColor('--color-border')}
                  vertical={false}
                />
                <XAxis
                  dataKey="quarter"
                  stroke={axisColor()}
                  tick={AXIS_STYLE}
                  minTickGap={24}
                  label={{
                    value: 'Trimestre',
                    position: 'insideBottom',
                    offset: -4,
                    style: {...AXIS_STYLE, fill: axisColor()},
                  }}
                />
                <YAxis
                  width={56}
                  stroke={axisColor()}
                  tick={AXIS_STYLE}
                  label={{
                    value: 'Crimes',
                    angle: -90,
                    position: 'insideLeft',
                    style: {...AXIS_STYLE, fill: axisColor()},
                  }}
                />
                <Tooltip content={<FanTooltip />} />
                {gapQuarter !== null && (
                  <ReferenceLine
                    x={seriesData.quarters.find(label => label > gapQuarter)}
                    stroke={tokenColor('--color-text-secondary')}
                    strokeDasharray="4 4"
                    label={{
                      value: `${gapQuarter} absent`,
                      position: 'insideTopRight',
                      style: {...AXIS_STYLE, fill: axisColor()},
                    }}
                  />
                )}
                <Area
                  dataKey="interval"
                  name={`Intervalle à ${level} %`}
                  fill={tokenColor('--color-data-categorical-blue')}
                  fillOpacity={0.2}
                  stroke="none"
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="history"
                  name="Observé"
                  stroke={tokenColor('--color-data-categorical-blue')}
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="forecast"
                  name="Prévision"
                  stroke={tokenColor('--color-data-categorical-orange')}
                  strokeWidth={2}
                  strokeDasharray="6 3"
                  isAnimationActive={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </AspectRatio>
          <Text type="supporting" color="secondary">
            Intervalle à {level} % issu de l'artefact.{' '}
            {metrics.forecast_footnote ?? data.metrics.city.forecast_footnote ?? ''}
          </Text>
          <Text type="supporting" color="secondary">
            {data.caveat_fr}
          </Text>
        </VStack>
      </Card>

      <Card>
        <VStack gap={3}>
          <Heading level={3}>
            Backtest : réel vs règle naïve à un pas ({scopeLabel})
          </Heading>
          <AspectRatio ratio={3}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={backtest}
                margin={{top: 12, right: 16, bottom: 8, left: 8}}>
                <CartesianGrid
                  stroke={tokenColor('--color-border')}
                  vertical={false}
                />
                <XAxis
                  dataKey="quarter"
                  stroke={axisColor()}
                  tick={AXIS_STYLE}
                  minTickGap={16}
                  label={{
                    value: 'Trimestre',
                    position: 'insideBottom',
                    offset: -4,
                    style: {...AXIS_STYLE, fill: axisColor()},
                  }}
                />
                <YAxis
                  width={56}
                  stroke={axisColor()}
                  tick={AXIS_STYLE}
                  label={{
                    value: 'Crimes',
                    angle: -90,
                    position: 'insideLeft',
                    style: {...AXIS_STYLE, fill: axisColor()},
                  }}
                />
                <Tooltip content={<RuleTooltip />} />
                <Line
                  type="monotone"
                  dataKey="actual"
                  name="Réel"
                  stroke={tokenColor('--color-data-categorical-blue')}
                  strokeWidth={2}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="rule"
                  name="Règle à un pas"
                  stroke={tokenColor('--color-data-categorical-orange')}
                  strokeWidth={2}
                  strokeDasharray="6 3"
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </AspectRatio>
          <Text type="supporting" color="secondary">
            Le réel est la série observée ; la règle prédit chaque trimestre
            avec la valeur du même trimestre un an plus tôt. MAE de référence
            (artefact) : {fmtFixed(metrics.baseline_mae_seasonal_rule, 2)}.
          </Text>
        </VStack>
      </Card>

      <Card>
        <VStack gap={3}>
          <Heading level={3}>Prévisions {scopeLabel}</Heading>
          <Table density="compact">
            <TableHeader>
              <TableRow>
                <TableHeaderCell>Trimestre</TableHeaderCell>
                <TableHeaderCell>Prévision</TableHeaderCell>
                <TableHeaderCell>Borne basse</TableHeaderCell>
                <TableHeaderCell>Borne haute</TableHeaderCell>
              </TableRow>
            </TableHeader>
            <TableBody>
              {points.map(point => (
                <TableRow key={point.quarter}>
                  <TableCell>{point.quarter}</TableCell>
                  <TableCell>{fmtFixed(point.point, 1)}</TableCell>
                  <TableCell>{fmtFixed(point.lower, 1)}</TableCell>
                  <TableCell>{fmtFixed(point.upper, 1)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <Text type="supporting" color="secondary">
            Valeurs en nombre de crimes par trimestre.
          </Text>
        </VStack>
      </Card>

      <VStack gap={2}>
        <Heading level={3}>Limites de la prévision</Heading>
        {data.caveats.map(caveat => (
          <Text key={caveat} type="body" color="secondary">
            {caveat}
          </Text>
        ))}
        {Object.entries(data.metrics.skipped_boroughs).map(
          ([borough, reason]) => (
            <Text key={borough} type="body" color="secondary">
              {borough} — non prévu : {reason}.
            </Text>
          ),
        )}
      </VStack>
    </VStack>
  );
}
