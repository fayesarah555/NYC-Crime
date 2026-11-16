// Page shell, navigation and the three tabs. One Filters state drives every
// Exploration view; Prévisions and Méthode read static artefacts only.
// Filters and the tab live in the URL (see lib/urlState).
import {lazy, Suspense, useMemo, useState} from 'react';
import type {ReactNode} from 'react';
import {Card} from '@astryxdesign/core/Card';
import {EmptyState} from '@astryxdesign/core/EmptyState';
import {Grid} from '@astryxdesign/core/Grid';
import {List, ListItem} from '@astryxdesign/core/List';
import {Layout, LayoutContent, HStack, VStack} from '@astryxdesign/core/Layout';
import {Switch} from '@astryxdesign/core/Switch';
import {
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
} from '@astryxdesign/core/Table';
import {Tab, TabList} from '@astryxdesign/core/TabList';
import {TopNav} from '@astryxdesign/core/TopNav';
import {Heading, Text} from '@astryxdesign/core/Text';
import FilterPanel from '../components/FilterPanel';
// Leaflet only ships when the map is rendered
const CrimeMap = lazy(() => import('../components/CrimeMap'));
import Legend from '../components/Legend';
import ParkDetail from '../components/ParkDetail';
import {
  BoroughTypeGrid,
  TopParksChart,
  TrendChart,
} from '../components/Charts';
// recharts only ships when the forecast tab is opened
const ForecastTab = lazy(() => import('../components/ForecastTab'));
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
  selectedCount,
  topParks,
  trendData,
  typeLabel,
  zeroCrimeParks,
} from '../lib/filters';
import type {Park} from '../lib/data';
import {clusters, cube, dataError, meta, parks} from '../lib/data';
import {coverageBreak, gapAnnotation} from '../lib/forecastChart';
import {GROUP_MAX_ZOOM} from '../lib/mapMarkers';
import {fmtFixed} from '../lib/format'
import {
  defaultFilters,
  isTabId,
  useUrlState,
  type TabId,
  type UrlState,
} from '../lib/urlState';

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

/** Parks ranked by crimes per 100 acres; parks without a rate are excluded. */
function topRiskParks(rows: Park[], limit = 10): Park[] {
  return rows
    .filter(row => row.risk_rank !== null && row.crimes_per_100_acres !== null)
    .sort((a, b) => (a.risk_rank ?? 0) - (b.risk_rank ?? 0))
    .slice(0, limit);
}

const LIST_LIMIT = 50;

function DashboardContent() {
  const quarters = cube.quarters;
  const [state, setUrlState] = useUrlState(quarters);
  const {filters, tab} = state;
  const [clusterMode, setClusterMode] = useState(false);
  const [groupMode, setGroupMode] = useState(false);
  const [selectedParkId, setSelectedParkId] = useState<string | null>(null);

  const kpis = useMemo(() => computeKpis(parks, filters, cube), [filters]);
  const selected = useMemo(() => filterParks(parks, filters, cube), [filters]);
  const markers = useMemo(() => mapParks(parks, filters, cube), [filters]);
  const withoutCoords = useMemo(
    () => parksWithoutCoordinates(parks, filters, cube),
    [filters],
  );
  const zeroCrime = useMemo(() => zeroCrimeParks(parks, filters, cube), [filters]);
  const trend = useMemo(() => trendData(parks, filters, cube), [filters]);
  const matrix = useMemo(
    () => boroughTypeMatrix(parks, filters, cube),
    [filters],
  );
  const top = useMemo(() => topParks(parks, filters, cube), [filters]);
  const topRisk = useMemo(() => topRiskParks(parks), []);
  const gap = useMemo(
    () => gapAnnotation(quarters, meta.missing_quarters),
    [quarters],
  );
  const breakQuarter = useMemo(() => coverageBreak(meta), []);
  const selectedPark =
    selectedParkId === null
      ? null
      : (parks.find(park => park.park_id === selectedParkId) ?? null);
  const empty = selected.length === 0;

  const update = (next: UrlState) => setUrlState(next);
  const changeTab = (value: string) => {
    if (isTabId(value)) update({filters, tab: value});
  };
  const reset = () => {
    setSelectedParkId(null);
    update({filters: defaultFilters(quarters), tab});
  };

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
                <Heading level={1}>
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
              onChange={changeTab}
              role="tablist"
              aria-label="Sections du tableau de bord"
              hasDivider>
              <Tab
                value={'exploration' satisfies TabId}
                id="tab-exploration"
                panelId="panel-exploration"
                label="Exploration"
              />
              <Tab
                value={'previsions' satisfies TabId}
                id="tab-previsions"
                panelId="panel-previsions"
                label="Prévisions"
              />
              <Tab
                value={'methode' satisfies TabId}
                id="tab-methode"
                panelId="panel-methode"
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
                  quarters={quarters}
                  onChange={next => update({filters: next, tab})}
                  onReset={reset}
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
                      filters.types.length > 0
                        ? 'Même trimestre, types sélectionnés'
                        : "Même trimestre de l'année précédente"
                    }
                  />
                </Grid>

                {selectedPark !== null && (
                  <ParkDetail
                    park={selectedPark}
                    types={filters.types}
                    onClose={() => setSelectedParkId(null)}
                  />
                )}

                {empty ? (
                  <Card>
                    <EmptyState
                      title="Aucune donnée pour ces filtres"
                      description="Aucun parc ne correspond aux arrondissements, types, période et recherche sélectionnés. Élargissez la période ou utilisez « Réinitialiser »."
                    />
                  </Card>
                ) : (
                  <>
                    <Card>
                      <VStack gap={4}>
                        <HStack hAlign="between" vAlign="center">
                          <Heading level={3}>Carte des parcs</Heading>
                          <HStack gap={4} vAlign="center">
                            <Switch
                              label="Colorer par cluster"
                              value={clusterMode}
                              onChange={setClusterMode}
                            />
                            <Switch
                              label="Regrouper à faible zoom"
                              value={groupMode}
                              onChange={setGroupMode}
                            />
                          </HStack>
                        </HStack>
                        <Text
                          id="carte-resume"
                          type="supporting"
                          color="secondary">
                          Carte : {formatInt(markers.length)}{' '}
                          {plural(markers.length, 'parc')}{' '}
                          {plural(markers.length, 'géolocalisé', 'géolocalisés')}{' '}
                          · {formatInt(withoutCoords)} sans coordonnées ·{' '}
                          {formatInt(zeroCrime)} {plural(zeroCrime, 'parc')}{' '}
                          {plural(zeroCrime, 'géolocalisé', 'géolocalisés')}{' '}
                          {plural(zeroCrime, 'exclu', 'exclus')} (aucun crime
                          dans la sélection).
                        </Text>
                        <Suspense fallback={<Text type="body">Chargement de la carte…</Text>}>
                        <CrimeMap
                          parks={markers}
                          types={filters.types}
                          clusterMode={clusterMode}
                          k={clusters.k}
                          groupMode={groupMode}
                          selectedParkId={selectedParkId}
                          onSelect={setSelectedParkId}
                        />
                        <Legend
                          clusterMode={clusterMode}
                          types={filters.types}
                          k={clusters.k}
                        />
                        </Suspense>
                        <Text type="supporting" color="secondary">
                          Regroupement par grille de 0,05° sous le zoom{' '}
                          {GROUP_MAX_ZOOM} (les parcs proches partagent un
                          marqueur) ; zoom
                          molette avec Ctrl. Tuiles © OpenStreetMap
                          contributors, chargées directement par votre
                          navigateur : aucun autre appel réseau, aucune donnée
                          personnelle collectée.
                        </Text>
                        {clusterMode && (
                          <Text type="supporting" color="secondary">
                            Clusters (k = {clusters.k}, silhouette{' '}
                            {clusters.silhouette}) : {clusters.parks.length} parcs
                            couverts :{' '}
                            {clusters.profiles
                              .map(
                                profile =>
                                  `${profile.cluster} ${profile.name || clusterLabel(profile.top_type)}`,
                              )
                              .join(' · ')}
                            .
                          </Text>
                        )}
                      </VStack>
                    </Card>

                    <Grid columns={{minWidth: 420, repeat: 'fit'}} gap={4}>
                      <TrendChart
                        data={trend}
                        gap={gap}
                        breakQuarter={breakQuarter}
                      />
                      <TopParksChart
                        rows={top}
                        types={filters.types}
                        onSelect={setSelectedParkId}
                      />
                    </Grid>
                    <Text type="supporting" color="secondary">
                      {filters.boroughs.length === 0
                        ? 'Tendance citywide.'
                        : 'Somme des séries trimestrielles des arrondissements sélectionnés.'}
                    </Text>

                    <Card>
                      <VStack gap={3}>
                        <Heading level={3}>
                          Parcs de la sélection (liste au clavier)
                        </Heading>
                        <Text type="supporting" color="secondary">
                          {selected.length > LIST_LIMIT
                            ? `Les ${LIST_LIMIT} premiers sur ${formatInt(selected.length)}, du plus de crimes au moins ; ouvrez un parc pour son détail.`
                            : "Ouvrez un parc pour son détail ; la carte et cette liste partagent la même sélection."}
                        </Text>
                        <List density="compact" aria-label="Parcs de la sélection">
                          {[...selected]
                            .sort(
                              (a, b) =>
                                selectedCount(b, filters.types) -
                                selectedCount(a, filters.types),
                            )
                            .slice(0, LIST_LIMIT)
                            .map(park => (
                              <ListItem
                                key={park.park_id}
                                label={park.park}
                                description={`${park.borough} · ${formatInt(selectedCount(park, filters.types))} crimes`}
                                isSelected={park.park_id === selectedParkId}
                                onClick={() => setSelectedParkId(park.park_id)}
                              />
                            ))}
                        </List>
                      </VStack>
                    </Card>

                    <Card>
                      <VStack gap={3}>
                        <Heading level={3}>
                          Parcs les plus à risque (crimes / 100 acres)
                        </Heading>
                        <Table density="compact">
                          <TableHeader>
                            <TableRow>
                              <TableHeaderCell>Rang</TableHeaderCell>
                              <TableHeaderCell>Parc</TableHeaderCell>
                              <TableHeaderCell>Arrondissement</TableHeaderCell>
                              <TableHeaderCell>Crimes</TableHeaderCell>
                              <TableHeaderCell>Acres</TableHeaderCell>
                              <TableHeaderCell>Crimes / 100 acres</TableHeaderCell>
                              <TableHeaderCell>Couverture</TableHeaderCell>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {topRisk.map(row => (
                              <TableRow key={row.park_id}>
                                <TableCell>{row.risk_rank}</TableCell>
                                <TableCell>{row.park}</TableCell>
                                <TableCell>{row.borough}</TableCell>
                                <TableCell>{formatInt(row.total)}</TableCell>
                                <TableCell>{row.acres == null ? '—' : fmtFixed(row.acres, 2)}</TableCell>
                                <TableCell>
                                  {row.crimes_per_100_acres == null ? '—' : fmtFixed(row.crimes_per_100_acres, 0)}
                                </TableCell>
                                <TableCell>{row.coverage_era}</TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                        <Text type="supporting" color="secondary">
                          Classement sur toute la période (période complète, hors
                          filtres) ; un parc sans superficie connue n'a pas de taux.
                        </Text>
                      </VStack>
                    </Card>

                    <BoroughTypeGrid types={matrix.types} rows={matrix.rows} />
                  </>
                )}
              </VStack>
            )}

            {tab === 'previsions' && (
              <VStack
                gap={6}
                role="tabpanel"
                id="panel-previsions"
                aria-labelledby="tab-previsions">
                <Suspense fallback={<Text type="body">Chargement des prévisions…</Text>}>
                  <ForecastTab />
                </Suspense>
              </VStack>
            )}
            {tab === 'methode' && (
              <VStack
                gap={6}
                role="tabpanel"
                id="panel-methode"
                aria-labelledby="tab-methode">
                <MethodTab />
              </VStack>
            )}
          </VStack>
        </LayoutContent>
      }
    />
  );
}

export default function Dashboard() {
  // The payloads were validated at load; a malformed bundle stops here,
  // before any selector or the initial range touches a rejected payload.
  if (dataError !== null) {
    return (
      <Layout
        height="fill"
        content={
          <LayoutContent padding={6}>
            <Card>
              <VStack gap={2}>
                <Heading level={2}>Chargement des données impossible</Heading>
                <Text type="body">{dataError}</Text>
              </VStack>
            </Card>
          </LayoutContent>
        }
      />
    );
  }
  return <DashboardContent />;
}
