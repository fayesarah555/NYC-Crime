# Changelog

Toutes les dates sont en UTC.

## Non publié

### Ajouté
- Tableau de bord web Astryx (Vite/React) : carte, filtres, recherche,
  onglets Exploration / Prévisions / Méthode, état partageable par URL.
- Cube park × trimestre × type, prévision réconciliée, table de risque par
  parc, palette Okabe–Ito partagée web/Streamlit/figures.
- CI GitHub Actions (Python 3.11 et 3.14, tests web, couverture, E2E
  Playwright), verrou de manifeste de données, schémas JSON des payloads.
- Licence MIT, attribution NYC Open Data dans le README.

### Modifié
- Les colonnes absentes de la source sont NULL et signalées, plus jamais 0.
- La ligne Flushing Meadows 2025Q4 conserve ses composants (TOTAL erroné
  signalé) : total ville 12 544 crimes.
- Modélisation : backtest à origines glissantes, Diebold–Mariano, variable de
  couverture Central Park, intervalles Poisson/log, clustering stabilisé
  (ARI) et réconciliation ville ↔ arrondissements.

## 2026-11-15

### Ajouté
- Version initiale : pipeline ETL, analyses, modèles, application Streamlit,
  deck de présentation.
