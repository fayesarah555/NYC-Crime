# Data dictionary: park crime, long format

Outputs of `python etl/parse.py`:

- `data/processed/park_crime_long.csv`: one row per (quarter, park, crime type).
- `data/warehouse.db`: same rows in the `crimes_long` table, indexed on
  `(quarter_label, park, crime_type)`.

Both are built from the workbooks in `data/raw/` (NYPD park-crime quarterly
statistics). Zero counts are kept: they are evidence of coverage.

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
| `count` | integer | complaints | the complaint count for that park/quarter/crime; numeric text such as `'0'` parsed |

## Crime-type vocabulary

`MURDER`, `RAPE`, `ROBBERY`, `FELONY ASSAULT`, `BURGLARY`, `GRAND LARCENY`,
`GRAND LARCENY AUTO`.

The header spelling drift `GRAND LARCENY OF MOTOR VEHICLE` (older workbooks) and
`GRAND LARCENY AUTO` (newer ones) both map to `GRAND LARCENY AUTO`.

Two workbooks (`q1-2025`, `q2-2024`) have no `MURDER` column at all; those rows
are emitted with `count = 0` for `MURDER` so every quarter carries the same
seven crime types. This is a source omission, not a computed zero.

## Parsing rules

- The header row is the first row whose first cell is `PARK`, on whichever sheet
  carries it (`Sheet1`, `Page1`, `Page1_1`, …).
- Header names are uppercased and whitespace-collapsed before mapping
  (`Murder` and `MURDER` are the same column).
- Rows whose `PARK` cell is not a non-empty string are skipped; this drops the
  trailing `TOTAL` footer and the stray date/time metadata rows two workbooks
  (2021Q3, 2021Q4) carry below the table.
- Integrity gate: every source park row must satisfy
  `TOTAL == sum(seven crime columns)`. Any violation aborts the run with a
  non-zero exit and the offending rows; no outputs are written.

## Lineage

`etl/download.py` → `data/raw/*.xlsx` + `manifest.json` → `etl/parse.py` →
`data/processed/park_crime_long.csv`, `data/warehouse.db`.
