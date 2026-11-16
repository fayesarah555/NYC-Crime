# Data dictionary

Every output of the pipeline (ticket 0049). Counts are complaints, not
convictions. The seven JSON payloads are validated against the schemas in
`export/schemas/` before they are written; the same schemas are exercised by
the test suite.

## 1. Long table: `data/processed/park_crime_long.csv`

One row per (quarter, park, crime type), built by `etl/parse.py`.

| Column | Type | Unit | Source |
| --- | --- | --- | --- |
| `quarter_label` | text | `YYYYQn` (e.g. `2025Q4`) | quarter/year parsed from the workbook filename `nyc-park-crime-stats-qN-YYYY.xlsx` |
| `period_start` | date (ISO 8601) | day | first date on the workbook's `Report covering the period Between … and …` line |
| `period_end` | date (ISO 8601) | day | second date on the same line |
| `park` | text | — | `PARK` column, surrounding whitespace stripped |
| `borough` | text | — | `BOROUGH` column, uppercase, whitespace collapsed (source pads with trailing spaces) |
| `size_acres` | real | acres | `SIZE (ACRES)` column, numeric text parsed |
| `category` | text | — | `CATEGORY` column, whitespace collapsed |
| `crime_type` | text | — | one of the seven `SEVEN MAJOR COMPLAINTS` columns, see vocabulary below |
| `count` | integer or empty (NULL) | complaints | the complaint count for that park/quarter/crime; numeric text such as `'0'` parsed. NULL when the workbook has no such column (see below) |
| `count_missing` | 0/1 | flag | 1 when `count` is NULL because the workbook lacks that crime column; 0 otherwise |
| `total_mismatch` | 0/1 | flag | 1 when the source row's `TOTAL` disagrees with its components; the seven components are kept and only TOTAL-based checks exclude the row |

### Crime-type vocabulary

`MURDER`, `RAPE`, `ROBBERY`, `FELONY ASSAULT`, `BURGLARY`, `GRAND LARCENY`,
`GRAND LARCENY AUTO`.

The header spelling drift `GRAND LARCENY OF MOTOR VEHICLE` (older workbooks) and
`GRAND LARCENY AUTO` (newer ones) both map to `GRAND LARCENY AUTO`.

Two workbooks (`q1-2025`, `q2-2024`) have no `MURDER` column at all; those
rows carry `count = NULL` with `count_missing = 1` for `MURDER`, and an
`outputs/tables/source_anomalies.csv` row of `kind = missing_column`. NULL
means missing: EDA, model, export and the web app exclude it from sums, rates
and shares and never impute it or count it as zero. Every other quarter keeps
the seven crime types.

### Parsing rules

- The header row is the first row whose first cell is `PARK`, on whichever sheet
  carries it (`Sheet1`, `Page1`, `Page1_1`, …).
- Header names are uppercased and whitespace-collapsed before mapping
  (`Murder` and `MURDER` are the same column).
- The quarter in the filename must equal the quarter parsed from the workbook's
  reporting period; a mismatch raises instead of mislabelling the data.
- Rows whose `PARK` cell is not a non-empty string are skipped; this drops the
  trailing `TOTAL` footer and the stray date/time metadata rows two workbooks
  (2021Q3, 2021Q4) carry below the table.
- Integrity: `TOTAL` is compared with the components the workbook actually
  has. A disagreement keeps the seven components with `total_mismatch = 1`
  (Flushing Meadows 2025Q4: TOTAL 17 vs sum 18), records a `total_mismatch`
  anomaly, and excludes the row only from TOTAL-based checks. Unparseable
  cells remain hard violations and their rows are dropped.

### `--allow-anomalies` semantics

`python etl/parse.py` without the flag aborts when any integrity violation or
empty workbook is found: it prints the violations, writes no CSV and no SQLite
table, and exits `1`.

`python etl/parse.py --allow-anomalies` records the violations to
`outputs/tables/source_anomalies.csv` with `kind = total_mismatch | missing_column`
(plus `kind = no_rows` for an empty workbook), then writes the outputs anyway
and exits `0`. It never repairs or drops data; the flags travel with the rows.
When no anomaly exists, the run still rewrites `source_anomalies.csv` as an
empty table so a stale file from an earlier run cannot survive.

`python etl/parse.py --check` validates only, writes nothing, and exits `0`
when clean or `1` when not, whether or not `--allow-anomalies` is present.

## 2. SQLite warehouse: `data/warehouse.db`

Built by `etl/parse.py` (`crimes_long`) and `etl/geo.py` (`parks`).

### Table `crimes_long`

Same columns and semantics as the long CSV above, plus `park_id` (the stable
identity from the `parks` dimension). The primary key is
`(quarter_label, park_id, crime_type)`; `quarter_label` and `park_id` are
foreign keys into `quarters` and `parks`. `count` is `INTEGER` and nullable
(a missing source column is NULL, never 0). Index
`idx_crimes_quarter_park_crime` on `(quarter_label, park, crime_type)`.

### Table `quarters`

One row per parsed reporting period: `quarter_label` (primary key),
`period_start`, `period_end`.

### Table `pipeline_runs`

Lineage for each build: `id`, `run_at` (UTC ISO timestamp), `git_sha`,
`source_manifest_sha256` (sha256 of `data/raw/manifest.json`),
`workbook_count`, `source_rows`, `long_rows`.

### Table `parks`

One row per park label in the crime data, with the geography match.

| Column | Type | Meaning |
| --- | --- | --- |
| `park` | text | park label exactly as the crime workbooks spell it |
| `borough` | text | borough label as the crime workbooks spell it |
| `park_id` | text | stable identity: NYC Parks `gispropnum` (fallback `omppropid`), else `BOROUGH:NAME` |
| `canonical_name` | text | matched property's own name, when a property matched |
| `lat` | real | latitude of the matched property, NULL when unmatched |
| `lon` | real | longitude of the matched property, NULL when unmatched |
| `acres_geo` | real | property acreage from the parks reference |
| `typecategory` | text | property type (Playground, Park, …) |
| `match_type` | text | match route: `override` / `signname` / `name311` / `fuzzy` / `none` |

`data/processed/parks_geo.csv` carries the same columns and is the artifact the
analysis scripts join on.

## 3. `outputs/tables/` schemas

### Anomaly tables

`source_anomalies.csv` — one row per integrity finding:

| Column | Meaning |
| --- | --- |
| `workbook` | source `.xlsx` filename |
| `sheet`, `excel_row` | where the finding was seen (empty when workbook-level) |
| `park`, `borough` | offending row (empty for `missing_column`) |
| `total_recorded` | the workbook's own `TOTAL` value |
| `sum_computed` | sum of the seven crime columns |
| `delta` | `sum_computed - total_recorded` |
| `kind` | `total_mismatch`, `missing_column`, `invalid_count`, `invalid_acres`, `conflicting_duplicate`, `period_mismatch`, or `no_rows` |

`source_anomaly_sensitivity.csv` — both city totals for each TOTAL mismatch:

| Column | Meaning |
| --- | --- |
| `park`, `quarter` | flagged cell |
| `total_recorded` | workbook `TOTAL` |
| `sum_components` | sum of the kept components |
| `city_total_from_components` | citywide total as published (components) |
| `city_total_using_recorded_total` | citywide total if the `TOTAL` line were followed |

### Coverage table

`coverage_gaps.csv` — per-park gaps against the continuous quarter grid:

| Column | Meaning |
| --- | --- |
| `park`, `borough` | park |
| `first_quarter`, `last_quarter` | first and last quarter observed for the park |
| `missing_quarters` | space-separated labels inside that span not usable |
| `gap_reasons` | `label: no_rows` or `label: total_mismatch`, `; `-joined |
| `n_missing` | number of unusable quarters inside the span |
| `total_crimes` | all-type total for the park over observed quarters |

### Rate table

`rate_by_borough.csv` — crime rate per 100 acres, perimeter and coverage
stated:

| Column | Meaning |
| --- | --- |
| `borough` | borough label (BROOKLYN/QUEENS kept as the source gives it) |
| `parks` | parks in the source |
| `parks_with_crimes` | parks with at least one crime |
| `parks_with_acreage` | parks with a non-NULL `size_acres` |
| `total_crimes` | all-type crimes for the borough |
| `crimes_with_acreage` | crimes in parks that have acreage |
| `excluded_crimes` | `total_crimes - crimes_with_acreage` |
| `crime_coverage_pct` | share of crimes covered by the acreage denominator |
| `acres` | sum of latest known acreage |
| `rate_per_100_acres` | `crimes_with_acreage / acres * 100` |
| `rate_excl_central_park` | same rate with Central Park removed from both terms |
| `central_park_crimes` | Central Park's crimes |
| `central_park_acres` | Central Park's acreage |
| `note` | free-text note (combined borough label only) |

### Other tables

`top_parks.csv` — `park_id`, `park`, `borough`, `total`, and one column per
crime type. `borough_type_share.csv` — `borough`, `crime_type`, `crimes`,
`share_pct`. `yoy_changes.csv` — `quarter`, `crimes`, `prior_year_crimes`,
`yoy_change`, `yoy_pct`. `forecast_city.csv` — `scope`, `quarter_label`,
`point`, `lower`, `upper`, `clipless_lower`, `clipped`; the city rows are the
bottom-up reconciled forecast (the unreconciled values stay in
`model_metrics.json` under `reconciliation.base_forecast`).
`forecast_boroughs.csv` adds `borough` in place of `scope`. `park_clusters.csv` — `park_id`, `park`,
`borough`, `cluster`, `silhouette` (global score, repeated), `sample_silhouette`
(per park), `dominant_type`, `total_crimes`. `cluster_profiles.csv` — `cluster`,
`n_parks`, `total_crimes`, `mean_acres`, `mean_silhouette`, one share column per
crime type (`share_burglary`, `share_felony_assault`, `share_grand_larceny`,
`share_grand_larceny_auto`, `share_murder`, `share_rape`, `share_robbery`),
`top_type`, `name` (honest French label from the two crime types most
over-represented vs the citywide mix; unique across clusters). `park_risk.csv`
— per park: `park_id`, `park`, `borough`, `crimes`, `acres`,
`crimes_per_100_acres` (null when acreage is missing or zero — never a
divide-by-zero), `risk_rank` (rank of the rate, 1 = highest, null without a
rate), `coverage_first`, `coverage_era` (first–last quarter observed),
`cluster`. `interpolation_sensitivity.csv` — `interpolation` (`linear` or
`seasonal`), `model`, `mae`, `mae_sd`, `quarter_label`, `point`, `lower`,
`upper`: the same city forecast under both fills of the missing 2020Q1 quarter.
`forecast_city_without_central_park.csv` — `quarter_label`, `point`, `lower`,
`upper`, `excluded` (`CENTRAL PARK`): consistent-perimeter sensitivity of the
city forecast. `geo_coverage.csv` — `metric`, `value` (one row per
coverage metric, plus `fuzzy_false_positive` rows).
`geo_false_positives.csv` — `park`, `matched_property`, `distance_km`.
`geo_fuzzy_audit.csv` — one row per accepted fuzzy match: `park`, `borough`,
`matched_property`, `runner_up` and `distance_km` between the two candidates
(empty when the fuzzy candidate is unique).
`download_gaps.csv` — `quarter`, `filename`, `reason`
(`not_published` when the page lists no workbook for the quarter,
`download_failed` when the request failed).

## 4. JSON payloads: `app/web/src/data/`

Written by `export/export_web.py`; validated against `export/schemas/` before
the directory swap. Top-level shape per file:

- `meta.json` — `generated_by`, `generated_at`, `git_commit`, `git_dirty`,
  optional `git_commit_note` (`fr`, `en`), `pipeline_version`, `source_manifest_sha256`,
  `schema_version`, `quarters_total`, `missing_quarters`, `ci_alpha`, `periods`
  (`first`, `last`, `count`, `missing`, `labels`), `totals` (`crimes`,
  `park_quarters`, `long_rows`, `parks`, `parks_with_crimes`), `geo` (`parks`,
  `matched`, `coverage_pct`, `weighted_coverage_pct`), `combined_borough`
  (`label`, `parks_source`, `parks_with_crimes`), `sources`, `source_links`
  (each `label`, `url`), `caveats`, `caveats_fr`.
- `parks.json` — array of `park_id`, `park`, `borough`, `lat`, `lon`, `acres`,
  `total`, `dominant_type`, `cluster`, `crimes_per_100_acres` (null without
  acreage), `risk_rank` (null without a rate), `coverage_era` (first–last
  quarter observed), `counts` (one entry per `crime_type`, `null` when the
  workbook lacked the column).
- `series.json` — `quarters`, `city`, `city_by_type`, `boroughs` (each series
  aligns with `quarters`).
- `borough_type.json` — `crime_types`, `boroughs` (`borough`, `total`,
  `counts`).
- `forecast.json` — `city`, `boroughs`, `metrics` (`city`, `boroughs`,
  `skipped_boroughs`), `caveats`, and the optional clipping `caveat` /
  `caveat_fr`. Each point is `quarter`, `point`, `lower`, `upper`, `clipped`;
  `lower` is never negative. `metrics.city` carries `selected_model`,
  `selected_mae`, `selected_mae_sd`, `selected_rmse`, `selected_mape`,
  `baseline_mae`, `baseline_mae_sd`, `baseline_mae_seasonal_rule`,
  `baseline_wins`, `dm_p_vs_naive`, `best_challenger` (`model`, `mae`,
  `mae_sd`, `dm_p`), `interval_coverage_95`, `tie_tolerance_pct`,
  `improvement_pct`, `backtest_quarters`, `backtest_window`,
  `backtest_origins` (per origin: `train_end`, `test_window`, `metrics`, each
  row `model`/`mae`/`rmse`), `backtest_metrics` (per model: `mae`, `mae_sd`,
  `rmse`, `mape`, `coverage_95`, `dm_p`), `model_failures`,
  `interval_clipped_rows`, `interpolated_quarters`, `n_quarters`,
  `forecast_footnote`, `selection_caveat`, `selection_caveat_fr`,
  `diagnostics` (`scope`, `order`, `seasonal_order`, `aicc`, `ljung_box_p`,
  `adf_p`, `kpss_p`, `params` as `name`/`value` rows, `aicc_grid_top`,
  `grid_failures`), `coverage_handling` (`method`, `coverage_from`,
  `n_late_parks`, `consistent_perimeter` with `excluded_parks`,
  `selected_model`, `selected_mae`, `selected_mae_sd`, `points`),
  `reconciliation` (`method`, `base_forecast` with `quarter`/`point`,
  `delta_by_quarter` with `quarter`/`delta`, `delta_mean`, `residual_mean`,
  `residual_sd`), and `interpolation_sensitivity` (`interpolation`, `model`,
  `mae`, `mae_sd`, `quarter_label`, `point`, `lower`, `upper`). Each
  `metrics.boroughs` entry repeats the per-series keys except
  `forecast_footnote`, `interpolated_quarters`, `n_quarters`,
  `selection_caveat_fr`, `diagnostics`, `coverage_handling`, `reconciliation`
  and `interpolation_sensitivity`; `skipped_boroughs` maps each excluded
  borough label to its reason.
- `clusters.json` — `k`, `silhouette`, `features`, `profiles` (`cluster`,
  `n_parks`, `total_crimes`, `mean_acres`, `mean_silhouette`, `top_type`,
  `name`), `parks` (`park`, `borough`, `cluster`, `sample_silhouette`,
  `crimes_per_100_acres`).
- `cubes.json` — `quarters`, `crime_types`, `parks`: `park_id` →
  `quarter_label` → one count per crime type in `crime_types` order. A `null`
  count means a missing column, never zero.
- `palette.json` — `crime_types`, `labels_fr`, `colors` (crime type → hex),
  `clusters` (hex list), `neutral`, `source`. Generated from
  `palette_data.py`, the single palette used by the web dashboard, Streamlit
  and the matplotlib figures.

### Schema files

`export/schemas/meta.schema.json`, `parks.schema.json`, `series.schema.json`,
`borough_type.schema.json`, `forecast.schema.json`, `clusters.schema.json`,
`cubes.schema.json`, `palette.schema.json` (JSON Schema draft 2020-12). The exporter validates every
payload before writing; `tests/test_export_web.py` validates a real export
against the same files. The browser validator in `app/web/src/lib/data.ts`
keeps its hand-written shape checks (it cannot read the schema files at
runtime); the schemas and the TS checks express the same contract.

## 5. Lineage

`etl/download.py` → `data/raw/*.xlsx` + `manifest.json`, hashes-only
`data/manifest.lock.json` (checked by `make data-verify`) → `etl/parse.py` →
`data/processed/park_crime_long.csv`, `data/warehouse.db` (with a
`pipeline_runs` row) → `etl/geo.py` →
`data/processed/parks_geo.csv`, `parks` table → `analysis/eda.py`,
`analysis/model.py` → `outputs/tables`, `outputs/figures`,
`outputs/metrics` → `export/export_web.py` → `app/web/src/data/*.json` and
`presentation/build_deck.py` → `presentation/nyc_crime_deck.pptx`.
