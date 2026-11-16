// Méthode tab — sources, periods, anomalies, coverage and licence.
import {Card} from '@astryxdesign/core/Card';
import {HStack, VStack} from '@astryxdesign/core/Layout';
import {Heading, Text} from '@astryxdesign/core/Text';
import {meta, parks} from '../lib/data';

function Section({
  title,
  lines,
  links,
}: {
  title: string;
  lines: string[];
  links?: {label: string; url: string}[];
}) {
  return (
    <Card>
      <VStack gap={2}>
        <Heading level={3}>{title}</Heading>
        {lines.map(line => (
          <Text key={line} type="body" color="secondary">
            {line}
          </Text>
        ))}
        {links?.map(link => (
          <Text key={link.url} type="body">
            <a href={link.url} target="_blank" rel="noreferrer">
              {link.label}
            </a>
          </Text>
        ))}
      </VStack>
    </Card>
  );
}

export default function MethodTab() {
  // Computed on render, not at module load: a rejected payload must reach
  // Dashboard's dataError guard instead of throwing during import.
  const combo = parks.filter(park => park.borough === 'BROOKLYN/QUEENS');
  const comboCrimes = combo.reduce((sum, park) => sum + park.total, 0);
  const withoutCoords = meta.geo.parks - meta.geo.matched;
  const crimeParksWithoutCoords = parks.filter(
    park => park.lat === null || park.lon === null,
  ).length;
  const freshness = `Export généré le ${meta.generated_at} (commit ${meta.git_commit}${
    meta.git_dirty ? ', arbre de travail modifié' : ''
  }).`;

  return (
    <VStack gap={4}>
      <Card>
        <VStack gap={2}>
          <Heading level={3}>Architecture interactive</Heading>
          <Text type="body" color="secondary">
            Les étapes du pipeline, leurs entrées et les deux interfaces, en
            diagramme navigable. Le fichier est servi avec le site.
          </Text>
          <iframe
            src="/architecture.html"
            title="Architecture du pipeline NYC park crime"
            loading="lazy"
            style={{width: '100%', height: '60vh', border: 'none'}}
          />
        </VStack>
      </Card>
      <Section
        title="Sources"
        lines={[
          ...meta.sources,
          freshness,
          "L'application ne fait aucun appel réseau (hors tuiles OpenStreetMap) et ne recalcule aucun modèle.",
        ]}
        links={meta.source_links}
      />
      <Section
        title="Périodes"
        lines={[
          `${meta.periods.count} trimestres, de ${meta.periods.first} à ${meta.periods.last}.`,
        ]}
      />
      <Section
        title="Limites et anomalies"
        lines={[
          ...meta.caveats_fr,
          `Libellé combiné BROOKLYN/QUEENS : ${meta.combined_borough.parks_source} parcs dans la source, ${meta.combined_borough.parks_with_crimes} avec au moins un crime, ${comboCrimes} crimes ; série trop courte pour la modélisation.`,
          `Géolocalisation : ${meta.geo.matched} parcs sur ${meta.geo.parks} rapprochés (${meta.geo.coverage_pct} %, ${meta.geo.weighted_coverage_pct} % pondéré par volume) ; ${withoutCoords} parcs sans coordonnées, dont ${crimeParksWithoutCoords} parmi les parcs avec crimes.`,
          'Les deux rapprochements flous audités sont écartés (data/geo_denylist.csv) ou corrigés par override (data/geo_overrides.csv).',
        ]}
      />
      <Section
        title="Licence et attribution"
        lines={[
          'Code : licence MIT, voir LICENSE.',
          'Données : © City of New York / NYPD, diffusées via NYC Open Data et nyc.gov ; elles ne sont pas couvertes par la licence du code.',
        ]}
        links={[
          {
            label: 'LICENSE (MIT)',
            url: 'https://github.com/youcisla/NYC-Crime/blob/main/LICENSE',
          },
          {
            label: "Conditions d'utilisation de NYC Open Data",
            url: 'https://opendata.cityofnewyork.us/overview/#terms',
          },
        ]}
      />
      <HStack gap={2} vAlign="center">
        <Text type="supporting" color="secondary">
          Palette Okabe–Ito partagée par le tableau de bord, Streamlit et les figures.
        </Text>
      </HStack>
    </VStack>
  );
}
