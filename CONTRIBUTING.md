# Contribuer

## Installation

```bash
python -m venv .venv && . .venv/Scripts/activate   # Windows
make setup
cd app/web && npm ci && cd ../..
```

## Vérifications avant une pull request

```bash
make check        # ruff, mypy, pytest avec seuil de couverture
cd app/web && npm test && npx tsc -b && npm run build
make e2e          # Playwright sur le site construit
```

Aucune pull request ne doit affaiblir un test, un seuil de couverture ou un
contrôle d'intégrité pour passer. Un chiffre affiché doit venir d'un artefact
produit par le pipeline, jamais d'une valeur saisie à la main.

## Données

Les classeurs NYPD ne sont pas versionnés. `make data` les télécharge,
`make warehouse` reconstruit l'entrepôt, `make web-export` régénère les JSON du
tableau de bord. `data/manifest.lock.json` fige les empreintes du jeu de
données analysé.

## Style

- Python : ruff et mypy (configuration dans `pyproject.toml`), libellés des
  figures en français, code et commentaires en anglais.
- Web : Astryx pour les composants, tokens pour les couleurs d'interface, la
  palette de données vient de `palette_data.py` / `palette.json`.
- Prose : le README, le deck et les interfaces suivent la passe humanizer :
  pas de formules creuses ni de chiffres non sourcés.
