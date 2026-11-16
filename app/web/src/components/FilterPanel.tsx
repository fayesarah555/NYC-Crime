// Four controls driving every Exploration view from one Filters object.
import {Card} from '@astryxdesign/core/Card';
import {VStack} from '@astryxdesign/core/Layout';
import {Grid} from '@astryxdesign/core/Grid';
import {MultiSelector} from '@astryxdesign/core/MultiSelector';
import {Slider} from '@astryxdesign/core/Slider';
import {TextInput} from '@astryxdesign/core/TextInput';
import {Heading, Text} from '@astryxdesign/core/Text';
import {
  BOROUGH_OPTIONS,
  CRIME_TYPES,
  type Filters,
  typeLabel,
} from '../lib/filters';

export default function FilterPanel({
  filters,
  quarters,
  onChange,
}: {
  filters: Filters;
  quarters: string[];
  onChange: (filters: Filters) => void;
}) {
  return (
    <Card>
      <VStack gap={4}>
        <Heading level={3}>Filtres</Heading>
        <Grid columns={{minWidth: 220, repeat: 'fit'}} gap={4}>
          <MultiSelector
            label="Arrondissements"
            options={BOROUGH_OPTIONS}
            value={filters.boroughs}
            onChange={boroughs => onChange({...filters, boroughs})}
            placeholder="Tous"
            triggerDisplay="labels"
          />
          <MultiSelector
            label="Types de délit"
            options={CRIME_TYPES.map(type => ({
              value: type,
              label: typeLabel(type),
            }))}
            value={filters.types}
            onChange={types => onChange({...filters, types})}
            placeholder="Tous"
            triggerDisplay="labels"
          />
          <Slider
            label="Période"
            value={filters.range}
            min={0}
            max={quarters.length - 1}
            step={1}
            onChange={(range: [number, number]) =>
              onChange({...filters, range})
            }
            formatValue={index => quarters[index] ?? ''}
            valueDisplay="text"
          />
          <TextInput
            label="Rechercher un parc"
            value={filters.query}
            onChange={query => onChange({...filters, query})}
            placeholder="Ex. : central, pelham"
            hasClear
          />
        </Grid>
        <Text type="supporting" color="secondary">
          La période filtre la série trimestrielle ; les totaux par parc sont
          toutes périodes (export statique sans détail parc × trimestre).
        </Text>
      </VStack>
    </Card>
  );
}
