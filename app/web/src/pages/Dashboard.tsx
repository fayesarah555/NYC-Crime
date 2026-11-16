// Page shell, navigation and the three tabs. One Filters state drives every
// Exploration view; Prévisions and Méthode read static artefacts only.
import {useMemo, useState} from 'react';
import type {ReactNode} from 'react';
import {Card} from '@astryxdesign/core/Card';
import {Grid} from '@astryxdesign/core/Grid';
import {Layout, LayoutContent, HStack, VStack} from '@astryxdesign/core/Layout';
import {Switch} from '@astryxdesign/core/Switch';
import {Tab, TabList} from '@astryxdesign/core/TabList';
import {TopNav} from '@astryxdesign/core/TopNav';
import {Heading, Text} from '@astryxdesign/core/Text';
import FilterPanel from '../components/FilterPanel';
import CrimeMap from '../components/CrimeMap';
import Legend from '../components/Legend';
import {
  BoroughTypeGrid,
  TopParksChart,
  TrendChart,
} from '../components/Charts';
import ForecastTab from '../components/ForecastTab';
import MethodTab from '../components/MethodTab';
import {
  boroughTypeMatrix,
  computeKpis,
  filterParks,
  formatInt,
  formatPct,
  mapParks,
  parksWithoutCoordinates,
  plural,
  topParks,
  trendData,
  type Filters,
  typeLabel,
  zeroCrimeParks,
} from '../lib/filters';
import {clusters, meta, parks, series} from '../lib/data';

const INITIAL_FILTERS: Filters = {
  boroughs: [],
  types: [],
  range: [0, series.quarters.length - 1],
  query: '',
};

function Kpi({
  label,
  value,
  note,
}: {
  label: string;
  value: ReactNode;
  note: string;
}) {
  return (
    <Card>
      <VStack gap={2}>
        <Text type="supporting" color="secondary">
          {label}
        </Text>
        <Heading level={2}>{value}</Heading>
        <Text type="supporting" color="secondary">
          {note}
        </Text>
      </VStack>
    </Card>
  );
}

function clusterLabel(topType: string): string {
  return typeLabel(topType.toUpperCase().replaceAll('_', ' '));
}

export default function Dashboard() {
  const [filters, setFilters] = useState<Filters>(INITIAL_FILTERS);
  const [clusterMode, setClusterMode] = useState(false);
  const [tab, setTab] = useState('exploration');

  const kpis = useMemo(
    () => computeKpis(parks, filters, series),
    [filters],
  );
  const selected = useMemo(() => filterParks(parks, filters), [filters]);
  const markers = useMemo(() => mapParks(parks, filters), [filters]);
  const withoutCoords = useMemo(
    () => parksWithoutCoordinates(parks, filters),
    [filters],
  );
  const zeroCrime = useMemo(() => zeroCrimeParks(parks, filters), [filters]);
  const trend = useMemo(() => trendData(series, filters), [filters]);
  const matrix = useMemo(
    () => boroughTypeMatrix(parks, filters),
    [filters],
  );
  const top = useMemo(() => topParks(parks, filters), [filters]);

  const changeLabel =
    kpis.changeBasis === 'annuelle'
      ? `Évolution annuelle ${kpis.latestQuarter}`
      : kpis.changeBasis === 'trimestrielle'
        ? `Variation trimestrielle ${kpis.latestQuarter}`
        : 'Évolution';

  return (
    <Layout
      height="fill"
      content={
        <LayoutContent padding={6}>
          <VStack gap={6}>
            <TopNav
              label="Navigation principale"
              heading={
                <Heading level={2}>
                  Criminalité dans les parcs de New York
                </Heading>
              }
              endContent={
                <Text type="supporting" color="secondary">
                  {meta.periods.first}–{meta.periods.last} · {meta.periods.count}{' '}
                  trimestres · export JSON statique
                </Text>
              }
            />

            <TabList
              value={tab}
              onChange={setTab}
              role="tablist"
              aria-label="Sections du tableau de bord"
              hasDivider>
              <Tab
                value="exploration"
                id="tab-exploration"
                panelId="panel-exploration"
                label="Exploration"
              />
              <Tab
                value="forecast"
                id="tab-forecast"
                panelId="panel-forecast"
                label="Prévisions"
              />
              <Tab
                value="method"
                id="tab-method"
                panelId="panel-method"
                label="Méthode"
              />
            </TabList>

            {tab === 'exploration' && (
              <VStack
                gap={6}
                role="tabpanel"
                id="panel-exploration"
                aria-labelledby="tab-exploration">
                <FilterPanel
                  filters={filters}
                  quarters={series.quarters}
                  onChange={setFilters}
                />

                <Grid columns={{minWidth: 220, repeat: 'fit'}} gap={4}>
                  <Kpi
                    label="Crimes (sélection)"
                    value={formatInt(kpis.total)}
                    note={`${formatInt(selected.length)} ${plural(selected.length, 'parc')} dans la sélection`}
                  />
                  <Kpi
                    label="Parcs touchés"
                    value={formatInt(kpis.parks)}
                    note="Parcs avec au moins un crime sélectionné"
                  />
                  <Kpi
                    label="Délit dominant"
                    value={kpis.topType === null ? '—' : typeLabel(kpis.topType)}
                    note={
                      kpis.topType === null
                        ? 'Aucune sélection'
                        : `Type complet : ${kpis.topType}`
                    }
                  />
                  <Kpi
                    label={changeLabel}
                    value={formatPct(kpis.changePct)}
                    note={
                      filters.types.length > 0 && filters.boroughs.length > 0
                        ? "Par arrondissement (pas de détail type × trimestre)"
                        : filters.types.length > 0
                          ? "Même trimestre, types sélectionnés"
                          : "Même trimestre de l'année précédente"
                    }
                  />
                </Grid>

                <Card>
                  <VStack gap={4}>
                    <HStack hAlign="between" vAlign="center">
                      <Heading level={3}>Carte des parcs</Heading>
                      <Switch
                        label="Colorer par cluster"
                        value={clusterMode}
                        onChange={setClusterMode}
                      />
                    </HStack>
                    <Text
                      id="carte-resume"
                      type="supporting"
                      color="secondary">
                      Carte : {formatInt(markers.length)}{' '}
                      {plural(markers.length, 'parc')}{' '}
                      {plural(markers.length, 'géolocalisé', 'géolocalisés')} ·{' '}
                      {formatInt(withoutCoords)} sans coordonnées ·{' '}
                      {formatInt(zeroCrime)} {plural(zeroCrime, 'parc')}{' '}
                      {plural(zeroCrime, 'géolocalisé', 'géolocalisés')}{' '}
                      {plural(zeroCrime, 'exclu', 'exclus')} (aucun crime dans
                      la sélection).
                    </Text>
                    <CrimeMap
                      parks={markers}
                      types={filters.types}
                      clusterMode={clusterMode}
                    />
                    <Legend clusterMode={clusterMode} types={filters.types} />
                    {clusterMode && (
                      <Text type="supporting" color="secondary">
                        Clusters (k = {clusters.k}, silhouette{' '}
                        {clusters.silhouette}) : {clusters.parks.length} parcs
                        couverts :{' '}
                        {clusters.profiles
                          .map(
                            profile =>
                              `${profile.cluster} ${clusterLabel(profile.top_type)}`,
                          )
                          .join(' · ')}
                        .
                      </Text>
                    )}
                  </VStack>
                </Card>

                <Grid columns={{minWidth: 420, repeat: 'fit'}} gap={4}>
                  <TrendChart data={trend} />
                  <TopParksChart rows={top} types={filters.types} />
                </Grid>
                <Text type="supporting" color="secondary">
                  {filters.boroughs.length === 0
                    ? 'Tendance citywide.'
                    : "Somme des séries des arrondissements sélectionnés ; le libellé BROOKLYN/QUEENS n'a pas de série propre."}
                </Text>

                <BoroughTypeGrid types={matrix.types} rows={matrix.rows} />
              </VStack>
            )}

            {tab === 'forecast' && (
              <VStack
                gap={6}
                role="tabpanel"
                id="panel-forecast"
                aria-labelledby="tab-forecast">
                <ForecastTab />
              </VStack>
            )}
            {tab === 'method' && (
              <VStack
                gap={6}
                role="tabpanel"
                id="panel-method"
                aria-labelledby="tab-method">
                <MethodTab />
              </VStack>
            )}
          </VStack>
        </LayoutContent>
      }
    />
  );
}
