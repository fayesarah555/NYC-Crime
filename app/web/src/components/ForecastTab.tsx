// Prévisions tab — static artefacts only, no model recomputation.
import {Card} from '@astryxdesign/core/Card';
import {Grid} from '@astryxdesign/core/Grid';
import {VStack} from '@astryxdesign/core/Layout';
import {
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
} from '@astryxdesign/core/Table';
import {Heading, Text} from '@astryxdesign/core/Text';
import {forecast} from '../lib/data';

const metrics = forecast.metrics.city;

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

export default function ForecastTab() {
  return (
    <VStack gap={6}>
      <Grid columns={{minWidth: 200, repeat: 'fit'}} gap={4}>
        <Metric label="Modèle retenu" value={String(metrics.selected_model).toUpperCase()} />
        <Metric label="MAE (backtest)" value={Number(metrics.selected_mae).toFixed(2)} />
        <Metric label="RMSE (backtest)" value={Number(metrics.selected_rmse).toFixed(2)} />
        <Metric label="MAPE (backtest)" value={`${Number(metrics.selected_mape).toFixed(2)} %`} />
      </Grid>

      <Text type="supporting" color="secondary">
        Avertissement (texte du modèle) :{' '}
        {String(metrics.selection_caveat_fr)}
      </Text>
      <Text type="body">
        Baseline naïve saisonnière : MAE {String(metrics.baseline_mae)} —
        amélioration de {String(metrics.improvement_pct)} % sur{' '}
        {String(metrics.backtest_quarters)} trimestres de backtest.
      </Text>

      <Card>
        <VStack gap={3}>
          <Heading level={3}>Prévisions citywide</Heading>
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
              {forecast.city.map(point => (
                <TableRow key={point.quarter}>
                  <TableCell>{point.quarter}</TableCell>
                  <TableCell>{point.point.toFixed(1)}</TableCell>
                  <TableCell>{point.lower.toFixed(1)}</TableCell>
                  <TableCell>{point.upper.toFixed(1)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <Text type="supporting" color="secondary">
            Intervalle à 95 %. {String(metrics.forecast_footnote)}
          </Text>
        </VStack>
      </Card>

      <VStack gap={2}>
        <Heading level={3}>Limites de la prévision</Heading>
        {forecast.caveats.map(caveat => (
          <Text key={caveat} type="body" color="secondary">
            {caveat}
          </Text>
        ))}
        <Text type="body" color="secondary">
          Modèle SARIMAX ajusté sur la série citywide ; STATEN ISLAND et
          BROOKLYN/QUEENS sont exclus des prévisions par arrondissement (trop
          peu de données).
        </Text>
      </VStack>
    </VStack>
  );
}
