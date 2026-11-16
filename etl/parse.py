"""Parse the cached NYPD park-crime workbooks into one tidy CSV and a SQLite warehouse.

Usage:
    python etl/parse.py                    # parse data/raw/*.xlsx -> CSV + SQLite
    python etl/parse.py --check            # validate headers/periods/TOTAL without writing
    python etl/parse.py --allow-anomalies  # record TOTAL violations, still write outputs

Integrity policy: negative or non-integer counts and unparseable acreage are
flagged as anomalies, never truncated. A workbook may carry several sheets with
a PARK header; identical (quarter, park, crime type) rows are deduplicated.
"""

import argparse
import hashlib
import os
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):  # running as `python etl/parse.py`
    sys.path.insert(0, str(ROOT))
from etl import schema  # noqa: E402
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
CSV_PATH = PROCESSED_DIR / "park_crime_long.csv"
GEO_CSV = PROCESSED_DIR / "parks_geo.csv"
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
    "count_missing",
    "total_mismatch",
]
QUARTER_RE = re.compile(r"nyc-park-crime-stats-q(\d)-(\d{4})\.xlsx$")
PERIOD_RE = re.compile(
    r"Between\s+([A-Za-z]+)\.?\s*(\d{1,2}),\s*(\d{4})\s*and\s+([A-Za-z]+)\.?\s*(\d{1,2}),\s*(\d{4})"
)
# Explicit English abbreviations: never depend on the process locale.
MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


class InvalidCount(ValueError):
    pass


class InvalidAcres(ValueError):
    pass


def normalize_cell(value):
    """Uppercase and collapse whitespace so header variants compare equal."""
    return " ".join(str(value).split()).upper() if value is not None else ""


def to_count(value):
    """Non-negative integer count. Raises InvalidCount instead of truncating."""
    if value is None:
        return 0
    if isinstance(value, bool):
        raise InvalidCount(f"non-integer value {value!r}")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        if not value.is_integer():
            raise InvalidCount(f"non-integer value {value!r}")
        parsed = int(value)
    else:
        text = str(value).strip().replace(",", "")
        if not text:
            return 0
        if not re.fullmatch(r"\d+", text):
            raise InvalidCount(f"non-integer value {value!r}")
        parsed = int(text)
    if parsed < 0:
        raise InvalidCount(f"negative value {parsed}")
    return parsed


def to_acres(value):
    """Non-negative acreage or None. Raises InvalidAcres on a parse error."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise InvalidAcres(f"non-numeric acreage {value!r}")
    if isinstance(value, (int, float)):
        acres = float(value)
    else:
        text = str(value).strip().replace(",", "")
        if not text:
            return None
        try:
            acres = float(text)
        except ValueError:
            raise InvalidAcres(f"unparseable acreage {value!r}") from None
    if acres < 0:
        raise InvalidAcres(f"negative acreage {acres}")
    return acres


def month_number(name):
    try:
        return MONTHS[name[:3].upper()]
    except KeyError:
        raise ValueError(f"unknown month name: {name!r}") from None


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


def find_period(rows):
    return next(
        (
            value
            for row in rows
            for value in row
            if isinstance(value, str) and "Report covering the period" in value
        ),
        None,
    )


def integrity_violation(sheet, excel_row, park, borough, total, computed, message,
                        kind="total_mismatch"):
    return {
        "sheet": sheet,
        "excel_row": excel_row,
        "park": park,
        "borough": borough,
        "total_recorded": total,
        "sum_computed": computed,
        "delta": None if total is None or computed is None else total - computed,
        "kind": kind,
        "message": message,
    }


def parse_sheet(sheet_name, rows, header_index, path, quarter, period_start, period_end):
    """Parse one sheet with a PARK header into long records plus flags."""
    header = [normalize_cell(cell) for cell in rows[header_index]]
    positions = {}
    for index, name in enumerate(header):
        if name:
            positions.setdefault(name, index)
    for required in ("PARK", "BOROUGH", "TOTAL"):
        if required not in positions:
            raise ValueError(f"{path.name}: missing column {required!r}")

    crime_columns = {
        CRIME_HEADERS[name]: index
        for index, name in enumerate(header)
        if name in CRIME_HEADERS
    }
    if not crime_columns:
        raise ValueError(f"{path.name}: no crime columns found")
    missing_types = [t for t in CRIME_TYPES if t not in crime_columns]

    records, violations = [], []
    # A missing crime column is a source omission: the rows are kept with
    # count = None and count_missing = 1, never as measured zeros.
    for crime_type in missing_types:
        violations.append(
            integrity_violation(
                sheet_name, None, None, None, None, None,
                f"no {crime_type} column; count is NULL, not 0",
                kind="missing_column",
            )
        )
    park_i, borough_i = positions["PARK"], positions["BOROUGH"]
    acres_i, category_i = positions.get("SIZE (ACRES)"), positions.get("CATEGORY")
    total_i = positions["TOTAL"]
    park_keys = set()
    for excel_row, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        park = row[park_i] if park_i < len(row) else None
        # Footer TOTAL rows ("TOTAL", "TOTAL:") and the stray date/time
        # metadata rows some workbooks carry after the table are not park rows.
        if not isinstance(park, str) or not park.strip():
            continue
        if park.strip().upper().startswith("TOTAL"):
            continue
        borough = normalize_cell(row[borough_i]) if borough_i < len(row) else None
        park_keys.add((park.strip(), borough))

        bad_counts = []
        counts = {}
        for crime_type in CRIME_TYPES:
            index = crime_columns.get(crime_type)
            if index is None:
                counts[crime_type] = None
                continue
            try:
                counts[crime_type] = to_count(row[index] if index < len(row) else None)
            except InvalidCount as exc:
                counts[crime_type] = None
                bad_counts.append(f"{crime_type}: {exc}")
        try:
            total = to_count(row[total_i] if total_i < len(row) else None)
        except InvalidCount as exc:
            total = None
            bad_counts.append(f"TOTAL: {exc}")

        acres = None
        if acres_i is not None:
            try:
                acres = to_acres(row[acres_i] if acres_i < len(row) else None)
            except InvalidAcres as exc:
                violations.append(
                    integrity_violation(
                        sheet_name, excel_row, park.strip(), borough, None, None,
                        f"{park.strip()}: {exc}; size_acres is NULL, row kept",
                        kind="invalid_acres",
                    )
                )

        if bad_counts or total is None:
            violations.append(
                integrity_violation(
                    sheet_name,
                    excel_row,
                    park.strip(),
                    borough,
                    total,
                    None,
                    f"{park.strip()}: rejected counts ({'; '.join(bad_counts) or 'TOTAL'})",
                    kind="invalid_count",
                )
            )
            continue
        # TOTAL is compared with the components the workbook actually has.
        computed = sum(value for value in counts.values() if value is not None)
        mismatch = int(total != computed)
        if mismatch:
            # Keep the seven components; only TOTAL-based checks exclude the row.
            violations.append(
                integrity_violation(
                    sheet_name,
                    excel_row,
                    park.strip(),
                    borough,
                    total,
                    computed,
                    f"{park.strip()}: TOTAL {total} != sum of crimes {computed}; "
                    "components kept, flagged total_mismatch",
                )
            )

        meta = {
            "quarter_label": quarter,
            "period_start": period_start,
            "period_end": period_end,
            "park": park.strip(),
            "borough": borough,
            "size_acres": acres,
            "category": (
                None
                if category_i is None or row[category_i] is None
                else " ".join(str(row[category_i]).split())
            ),
        }
        for crime_type in CRIME_TYPES:
            records.append({
                **meta,
                "crime_type": crime_type,
                "count": counts[crime_type],
                "count_missing": int(counts[crime_type] is None),
                "total_mismatch": mismatch,
            })

    return records, violations, park_keys


def parse_workbook(path, quarter=None):
    """Parse one workbook into long records plus integrity flags.

    Every sheet carrying a PARK header is parsed. Rows that repeat a
    (quarter, park, borough, crime type) key with an identical count are
    dropped; a conflicting count is flagged and the first row is kept.
    """
    quarter = quarter or quarter_label(path)
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        candidates = []
        for sheet in workbook.worksheets:
            rows = list(sheet.iter_rows(values_only=True))
            header_index = find_header(rows)
            if header_index is not None:
                candidates.append((sheet.title, rows, header_index))
    finally:
        workbook.close()
    if not candidates:
        raise ValueError(f"{path.name}: no PARK header row in any sheet")

    periods = [
        (sheet_name, find_period(rows))
        for sheet_name, rows, _ in candidates
        if find_period(rows) is not None
    ]
    if not periods:
        raise ValueError(f"{path.name}: no 'Report covering the period' line")
    period_start, period_end = parse_period(periods[0][1])
    violations = []
    for sheet_name, text in periods[1:]:
        if parse_period(text) != (period_start, period_end):
            violations.append(
                integrity_violation(
                    sheet_name, None, None, None, None, None,
                    f"reporting period {text.strip()!r} differs from sheet "
                    f"{periods[0][0]!r}; workbook period used",
                    kind="period_mismatch",
                )
            )

    period_quarter = f"{period_start.year}Q{(period_start.month - 1) // 3 + 1}"
    if period_quarter != quarter:
        raise ValueError(
            f"{path.name}: filename quarter {quarter} != parsed period "
            f"{period_quarter} ({periods[0][1].strip()})"
        )

    records, seen, park_keys = [], {}, set()
    for sheet_name, rows, header_index in candidates:
        sheet_records, sheet_violations, sheet_keys = parse_sheet(
            sheet_name, rows, header_index, path, quarter, period_start, period_end
        )
        violations.extend(sheet_violations)
        park_keys |= sheet_keys
        for record in sheet_records:
            key = (
                record["quarter_label"],
                record["park"],
                record["borough"],
                record["crime_type"],
            )
            if key not in seen:
                seen[key] = record
                records.append(record)
            elif seen[key]["count"] != record["count"]:
                violations.append(
                    integrity_violation(
                        sheet_name, None, record["park"], record["borough"],
                        record["count"], seen[key]["count"],
                        f"{record['park']}: {record['crime_type']} differs across "
                        f"sheets ({record['count']} vs {seen[key]['count']}); first kept",
                        kind="conflicting_duplicate",
                    )
                )

    return {
        "path": path,
        "quarter": quarter,
        "period_start": period_start,
        "period_end": period_end,
        "source_rows": len(park_keys),
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


def load_geo_rows():
    """(park, borough) -> geography row, when a previous geo run produced one."""
    if not GEO_CSV.exists():
        return {}
    frame = pd.read_csv(GEO_CSV)
    rows = {}
    for raw in frame.to_dict("records"):
        rows[(raw["park"], raw["borough"])] = {
            key: (None if pd.isna(raw.get(key)) else raw.get(key))
            for key in PARK_GEO_COLUMNS
        }
    return rows


PARK_GEO_COLUMNS = [
    "park_id", "canonical_name", "lat", "lon", "acres_geo", "typecategory", "match_type",
]


def git_sha():
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def source_manifest_sha256():
    path = RAW_DIR / "manifest.json"
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_outputs(records, workbook_count=0, source_rows=0):
    """Build the warehouse in a temp file, then swap it in atomically."""
    frame = pd.DataFrame(records, columns=OUTPUT_COLUMNS)

    geo_rows = load_geo_rows()
    park_ids, parks = {}, {}
    for record in records:
        key = (record["park"], record["borough"])
        if key in parks:
            continue
        geo = geo_rows.get(key, {})
        park_id = geo.get("park_id") or f"{record['borough']}:{record['park']}"
        park_ids[key] = park_id
        parks[key] = (
            park_id,
            record["park"],
            record["borough"],
            geo.get("canonical_name"),
            geo.get("lat"),
            geo.get("lon"),
            geo.get("acres_geo"),
            geo.get("typecategory"),
            geo.get("match_type"),
        )

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DB_PATH.with_name(DB_PATH.name + ".tmp")
    try:
        connection = schema.connect(tmp)
        try:
            schema.ensure_schema(connection)
            quarters = {}
            for record in records:
                quarters.setdefault(
                    record["quarter_label"],
                    (str(record["period_start"]), str(record["period_end"])),
                )
            connection.executemany(
                "INSERT OR REPLACE INTO quarters VALUES (?, ?, ?)",
                [(label, start, end) for label, (start, end) in quarters.items()],
            )
            connection.executemany(
                "INSERT INTO parks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                list(parks.values()),
            )
            connection.executemany(
                "INSERT INTO crimes_long VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        record["quarter_label"],
                        park_ids[(record["park"], record["borough"])],
                        record["park"],
                        record["borough"],
                        str(record["period_start"]),
                        str(record["period_end"]),
                        record["size_acres"],
                        record["category"],
                        record["crime_type"],
                        record["count"],
                        record["count_missing"],
                        record["total_mismatch"],
                    )
                    for record in records
                ],
            )
            connection.execute(
                "INSERT INTO pipeline_runs (run_at, git_sha, source_manifest_sha256, "
                "workbook_count, source_rows, long_rows) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    git_sha(),
                    source_manifest_sha256(),
                    workbook_count,
                    source_rows,
                    len(records),
                ),
            )
            connection.commit()
        finally:
            connection.close()
        os.replace(tmp, DB_PATH)
    finally:
        # A failed build never leaves a partial temp database behind.
        tmp.unlink(missing_ok=True)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_csv(CSV_PATH, index=False)


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
    write_outputs(records, workbook_count=len(parsed), source_rows=source_rows)
    print(f"wrote {CSV_PATH.relative_to(ROOT)}")
    print(f"wrote {DB_PATH.relative_to(ROOT)} (tables crimes_long, parks, quarters, pipeline_runs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
