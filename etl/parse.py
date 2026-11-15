"""Parse the cached NYPD park-crime workbooks into one tidy CSV and a SQLite warehouse.

Usage:
    python etl/parse.py                    # parse data/raw/*.xlsx -> CSV + SQLite
    python etl/parse.py --check            # validate headers/periods/TOTAL without writing
    python etl/parse.py --allow-anomalies  # record TOTAL violations, still write outputs
"""

import argparse
import calendar
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
CSV_PATH = PROCESSED_DIR / "park_crime_long.csv"
DB_PATH = ROOT / "data" / "warehouse.db"
ANOMALIES_CSV = ROOT / "outputs" / "tables" / "source_anomalies.csv"
ANOMALY_COLUMNS = [
    "workbook",
    "sheet",
    "excel_row",
    "park",
    "borough",
    "total_recorded",
    "sum_computed",
    "delta",
    "kind",
]

CRIME_TYPES = [
    "MURDER",
    "RAPE",
    "ROBBERY",
    "FELONY ASSAULT",
    "BURGLARY",
    "GRAND LARCENY",
    "GRAND LARCENY AUTO",
]
# Normalized header -> canonical crime_type. The two motor-vehicle spellings
# from the source workbooks collapse into one column.
CRIME_HEADERS = {
    "MURDER": "MURDER",
    "RAPE": "RAPE",
    "ROBBERY": "ROBBERY",
    "FELONY ASSAULT": "FELONY ASSAULT",
    "BURGLARY": "BURGLARY",
    "GRAND LARCENY": "GRAND LARCENY",
    "GRAND LARCENY OF MOTOR VEHICLE": "GRAND LARCENY AUTO",
    "GRAND LARCENY AUTO": "GRAND LARCENY AUTO",
}
OUTPUT_COLUMNS = [
    "quarter_label",
    "period_start",
    "period_end",
    "park",
    "borough",
    "size_acres",
    "category",
    "crime_type",
    "count",
]
QUARTER_RE = re.compile(r"nyc-park-crime-stats-q(\d)-(\d{4})\.xlsx$")
PERIOD_RE = re.compile(
    r"Between\s+([A-Za-z]+)\.?\s*(\d{1,2}),\s*(\d{4})\s*and\s+([A-Za-z]+)\.?\s*(\d{1,2}),\s*(\d{4})"
)


def normalize_cell(value):
    """Uppercase and collapse whitespace so header variants compare equal."""
    return " ".join(str(value).split()).upper() if value is not None else ""


def to_count(value):
    """Integer count, or None when the cell is not numeric."""
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return 0
    try:
        return int(float(text))
    except ValueError:
        return None


def to_acres(value):
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    return float(text)


def month_number(name):
    return list(calendar.month_abbr).index(name[:3].title())


def parse_period(text):
    """Parse 'Between Mon D, YYYY and Mon D, YYYY' into two dates."""
    match = PERIOD_RE.search(text)
    if not match:
        raise ValueError(f"cannot parse reporting period: {text!r}")
    start = date(int(match.group(3)), month_number(match.group(1)), int(match.group(2)))
    end = date(int(match.group(6)), month_number(match.group(4)), int(match.group(5)))
    return start, end


def quarter_label(path):
    match = QUARTER_RE.search(path.name)
    if not match:
        raise ValueError(f"not a park-crime workbook name: {path.name}")
    return f"{match.group(2)}Q{match.group(1)}"


def find_header(rows):
    for index, row in enumerate(rows):
        if row and normalize_cell(row[0]) == "PARK":
            return index
    return None


def integrity_violation(sheet, excel_row, park, borough, total, computed, message):
    return {
        "sheet": sheet,
        "excel_row": excel_row,
        "park": park,
        "borough": borough,
        "total_recorded": total,
        "sum_computed": computed,
        "delta": None if total is None or computed is None else total - computed,
        "kind": "total_mismatch",
        "message": message,
    }


def parse_workbook(path, quarter=None):
    """Parse one workbook into long records plus any TOTAL-vs-sum violations."""
    quarter = quarter or quarter_label(path)
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        rows, header_index, sheet_name = None, None, None
        for sheet in workbook.worksheets:
            candidate = list(sheet.iter_rows(values_only=True))
            header_index = find_header(candidate)
            if header_index is not None:
                rows = candidate
                sheet_name = sheet.title
                break
        if rows is None:
            raise ValueError(f"{path.name}: no PARK header row in any sheet")
    finally:
        workbook.close()

    header = [normalize_cell(cell) for cell in rows[header_index]]
    positions = {}
    for index, name in enumerate(header):
        if name:
            positions.setdefault(name, index)
    for required in ("PARK", "BOROUGH", "SIZE (ACRES)", "CATEGORY", "TOTAL"):
        if required not in positions:
            raise ValueError(f"{path.name}: missing column {required!r}")

    period_text = next(
        (
            value
            for row in rows[:header_index]
            for value in row
            if isinstance(value, str) and "Report covering the period" in value
        ),
        None,
    )
    if period_text is None:
        raise ValueError(f"{path.name}: no 'Report covering the period' line")
    period_start, period_end = parse_period(period_text)

    crime_columns = {
        CRIME_HEADERS[name]: index
        for index, name in enumerate(header)
        if name in CRIME_HEADERS
    }
    if not crime_columns:
        raise ValueError(f"{path.name}: no crime columns found")

    records, violations, source_rows = [], [], 0
    park_i, borough_i = positions["PARK"], positions["BOROUGH"]
    acres_i, category_i = positions["SIZE (ACRES)"], positions["CATEGORY"]
    total_i = positions["TOTAL"]
    for excel_row, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        park = row[park_i] if park_i < len(row) else None
        # Footer TOTAL rows ("TOTAL", "TOTAL:") and the stray date/time
        # metadata rows some workbooks carry after the table are not park rows.
        if not isinstance(park, str) or not park.strip():
            continue
        if park.strip().upper().startswith("TOTAL"):
            continue
        source_rows += 1
        counts = {}
        for crime_type in CRIME_TYPES:
            index = crime_columns.get(crime_type)
            value = row[index] if index is not None and index < len(row) else None
            counts[crime_type] = to_count(value) if index is not None else 0
        total = to_count(row[total_i]) if total_i < len(row) else None
        borough = normalize_cell(row[borough_i]) if borough_i < len(row) else None

        bad_counts = [name for name, value in counts.items() if value is None]
        if bad_counts or total is None:
            violations.append(
                integrity_violation(
                    sheet_name,
                    excel_row,
                    park.strip(),
                    borough,
                    total,
                    None,
                    f"{park.strip()}: unparseable counts {bad_counts or ['TOTAL']}",
                )
            )
            continue
        computed = sum(counts.values())
        if total != computed:
            violations.append(
                integrity_violation(
                    sheet_name,
                    excel_row,
                    park.strip(),
                    borough,
                    total,
                    computed,
                    f"{park.strip()}: TOTAL {total} != sum of crimes {computed}",
                )
            )
            continue

        meta = {
            "quarter_label": quarter,
            "period_start": period_start,
            "period_end": period_end,
            "park": park.strip(),
            "borough": borough,
            "size_acres": to_acres(row[acres_i]) if acres_i < len(row) else None,
            "category": (
                " ".join(str(row[category_i]).split()) if category_i < len(row) else None
            ),
        }
        for crime_type in CRIME_TYPES:
            records.append({**meta, "crime_type": crime_type, "count": counts[crime_type]})

    return {
        "path": path,
        "quarter": quarter,
        "period_start": period_start,
        "period_end": period_end,
        "source_rows": source_rows,
        "records": records,
        "violations": violations,
    }


def parse_all(raw_dir=RAW_DIR):
    paths = list(Path(raw_dir).glob("nyc-park-crime-stats-q*-*.xlsx"))
    paths.sort(key=lambda p: (int(QUARTER_RE.search(p.name).group(2)), int(QUARTER_RE.search(p.name).group(1))))
    parsed = [parse_workbook(path) for path in paths]
    records = [record for workbook in parsed for record in workbook["records"]]
    violations = [
        {**entry, "workbook": workbook["path"].name}
        for workbook in parsed
        for entry in workbook["violations"]
    ]
    return parsed, records, violations


def write_anomalies(violations, path=ANOMALIES_CSV):
    """Record integrity violations as evidence instead of aborting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(violations, columns=ANOMALY_COLUMNS).to_csv(path, index=False)


def write_outputs(records):
    frame = pd.DataFrame(records, columns=OUTPUT_COLUMNS)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_csv(CSV_PATH, index=False)
    connection = sqlite3.connect(DB_PATH)
    try:
        frame.to_sql("crimes_long", connection, if_exists="replace", index=False)
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_crimes_quarter_park_crime "
            "ON crimes_long (quarter_label, park, crime_type)"
        )
        connection.commit()
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate only, write nothing")
    parser.add_argument(
        "--allow-anomalies",
        action="store_true",
        help="write integrity violations to outputs/tables/source_anomalies.csv and still write outputs",
    )
    args = parser.parse_args()

    if not RAW_DIR.exists() or next(RAW_DIR.glob("*.xlsx"), None) is None:
        print(f"error: no workbooks in {RAW_DIR}; run etl/download.py first", file=sys.stderr)
        return 2

    parsed, records, violations = parse_all(RAW_DIR)
    source_rows = sum(workbook["source_rows"] for workbook in parsed)
    print(f"workbooks: {len(parsed)}, source rows: {source_rows}, long rows: {len(records)}")
    no_rows = [workbook["path"].name for workbook in parsed if workbook["source_rows"] == 0]
    for name in no_rows:
        print(f"error: {name}: no park rows", file=sys.stderr)
    if violations:
        for entry in violations:
            print(f"integrity: {entry['workbook']}: {entry['message']}", file=sys.stderr)
        print(f"{len(violations)} integrity violation(s)", file=sys.stderr)
    if violations or no_rows:
        if args.check:
            return 1
        if not args.allow_anomalies:
            print("no outputs written", file=sys.stderr)
            return 1
        anomalies = violations + [{"workbook": name, "kind": "no_rows"} for name in no_rows]
        write_anomalies(anomalies, ANOMALIES_CSV)
        print(f"anomalies: {len(anomalies)} row(s) -> {ANOMALIES_CSV.relative_to(ROOT)}")
    elif args.check:
        print(f"OK: {len(parsed)} workbooks consistent")
        return 0
    elif args.allow_anomalies:
        # Always rewrite so a stale anomalies file from an earlier run cannot survive.
        write_anomalies([], ANOMALIES_CSV)
    write_outputs(records)
    print(f"wrote {CSV_PATH.relative_to(ROOT)}")
    print(f"wrote {DB_PATH.relative_to(ROOT)} (table crimes_long)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
