// Méthode tab — sources, periods, anomalies, coverage and licence.
import {Card} from '@astryxdesign/core/Card';
import {VStack} from '@astryxdesign/core/Layout';
import {Heading, Text} from '@astryxdesign/core/Text';
import {meta, parks} from '../lib/data';

const combo = parks.filter(park => park.borough === 'BROOKLYN/QUEENS');
const comboCrimes = combo.reduce((sum, park) => sum + park.total, 0);
const withoutCoords = meta.geo.parks - meta.geo.matched;
const crimeParksWithoutCoords = parks.filter(
  park => park.lat === null || park.lon === null,
).length;

function Section({title, lines}: {title: string; lines: string[]}) {
  return (
    <Card>
      <VStack gap={2}>
        <Heading level={3}>{title}</Heading>
        {lines.map(line => (
          <Text key={line} type="body" color="secondary">
            {line}
          </Text>
        ))}
      </VStack>
    </Card>
  );
}

export default function MethodTab() {
  return (
    <VStack gap={4}>
      <Section
        title="Sources"
        lines={[
          ...meta.sources,
          "L'application ne fait aucun appel réseau (hors tuiles OpenStreetMap) et ne recalcule aucun modèle.",
        ]}
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
          ...meta.caveats_fr.slice(0, 3),
          `Libellé combiné BROOKLYN/QUEENS : ${combo.length} parcs, ${comboCrimes} crimes ; série trop courte pour la modélisation.`,
          `Géolocalisation : ${meta.geo.matched} parcs sur ${meta.geo.parks} rapprochés (${meta.geo.coverage_pct} %, ${meta.geo.weighted_coverage_pct} % pondéré par volume) ; ${withoutCoords} parcs sans coordonnées, dont ${crimeParksWithoutCoords} parmi les parcs avec crimes.`,
          'Deux rapprochements flous du palier 0,88 sont des faux positifs assumés (geo_false_positives.csv).',
        ]}
      />
      <Section
        title="Licence et attribution"
        lines={[
          "Code : usage pédagogique dans le cadre du module Open Data de l'IPSSI.",
          'Données : © City of New York / NYPD, diffusées via NYC Open Data et nyc.gov.',
        ]}
      />
    </VStack>
  );
}
