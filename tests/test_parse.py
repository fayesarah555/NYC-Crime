"""Network-free: workbook parsing, period parsing and the TOTAL integrity gate."""

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import etl.parse as parse  # noqa: E402
from etl.parse import (  # noqa: E402
    CRIME_HEADERS,
    CRIME_TYPES,
    normalize_cell,
    parse_all,
    parse_period,
    parse_workbook,
    write_anomalies,
)

HEADER = [
    "PARK",
    "BOROUGH",
    "SIZE (ACRES)",
    "CATEGORY",
    "Murder",
    "RAPE",
    "ROBBERY",
    "FELONY ASSAULT",
    "BURGLARY",
    "GRAND LARCENY",
    "Grand  Larceny Auto",
    "TOTAL",
]


def make_workbook(path, rows, header=HEADER):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["2nd QTR PARK CRIME REPORT"])
    sheet.append(["Report covering the period Between Apr 1, 2020 and Jun 30, 2020"])
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    sheet.append(["TOTAL", None, None, None, 1, 2, 3, 4, 5, 6, 7, 28])
    workbook.save(path)
    return path


def test_header_variants_map_to_one_motor_vehicle_column():
    assert CRIME_HEADERS["GRAND LARCENY OF MOTOR VEHICLE"] == "GRAND LARCENY AUTO"
    assert CRIME_HEADERS["GRAND LARCENY AUTO"] == "GRAND LARCENY AUTO"
    assert CRIME_HEADERS["MURDER"] == "MURDER"
    assert normalize_cell("Murder") == "MURDER"
    assert normalize_cell(" Grand   Larceny Auto ") == "GRAND LARCENY AUTO"


@pytest.mark.parametrize(
    "text, start, end",
    [
        (
            "Report covering the period  Between Jan 1, 2015 and Mar 31, 2015",
            date(2015, 1, 1),
            date(2015, 3, 31),
        ),
        (
            "Report covering the period  Between July1, 2015 and Sept. 30, 2015",
            date(2015, 7, 1),
            date(2015, 9, 30),
        ),
        (
            "Report covering the period  Between Apr 1, 2016and Jun 30, 2016",
            date(2016, 4, 1),
            date(2016, 6, 30),
        ),
        (
            "Report covering the period  Between Jan 1, 2019 and March 31, 2019",
            date(2019, 1, 1),
            date(2019, 3, 31),
        ),
        (
            "Report covering the period Between July 1, 2019 and Sep 30, 2019",
            date(2019, 7, 1),
            date(2019, 9, 30),
        ),
    ],
)
def test_parse_period_variants(text, start, end):
    assert parse_period(text) == (start, end)


def test_melt_emits_one_row_per_crime_and_drops_footer(tmp_path):
    path = make_workbook(
        tmp_path / "nyc-park-crime-stats-q2-2020.xlsx",
        [
            ["PARK A", "BROOKLYN", "1.5", "ONE ACRE OR LARGER", 1, 2, 3, 4, 5, 6, 7, 28],
            ["PARK B", "QUEENS", "0.1", "PLAYGROUND", 0, "0", "0", "0", "0", "0", "0", 0],
        ],
    )
    result = parse_workbook(path)

    assert result["violations"] == []
    assert result["source_rows"] == 2
    assert result["quarter"] == "2020Q2"
    assert (result["period_start"], result["period_end"]) == (
        date(2020, 4, 1),
        date(2020, 6, 30),
    )
    assert len(result["records"]) == 2 * len(CRIME_TYPES)
    park_a = [r for r in result["records"] if r["park"] == "PARK A"]
    assert [r["count"] for r in park_a] == [1, 2, 3, 4, 5, 6, 7]
    assert park_a[0]["crime_type"] == "MURDER"
    assert park_a[-1]["crime_type"] == "GRAND LARCENY AUTO"
    assert park_a[0]["size_acres"] == 1.5
    park_b = [r for r in result["records"] if r["park"] == "PARK B"]
    assert all(r["count"] == 0 for r in park_b)


def test_total_mismatch_keeps_components_and_flags_the_row(tmp_path):
    path = make_workbook(
        tmp_path / "nyc-park-crime-stats-q2-2020.xlsx",
        [["BAD PARK", "BRONX", "2.0", "ONE ACRE OR LARGER", 1, 1, 1, 1, 1, 1, 1, 999]],
    )
    result = parse_workbook(path)

    # The seven components are kept; only TOTAL-based checks exclude the row.
    assert len(result["records"]) == len(CRIME_TYPES)
    assert {r["count"] for r in result["records"]} == {1}
    assert {r["total_mismatch"] for r in result["records"]} == {1}
    assert {r["count_missing"] for r in result["records"]} == {0}
    (violation,) = result["violations"]
    assert violation["message"].startswith("BAD PARK: TOTAL 999 != sum of crimes 7")
    assert violation["kind"] == "total_mismatch"
    assert violation["excel_row"] == 4
    assert violation["park"] == "BAD PARK"
    assert violation["borough"] == "BRONX"
    assert (violation["total_recorded"], violation["sum_computed"], violation["delta"]) == (
        999,
        7,
        992,
    )


def test_missing_crime_column_is_null_and_flagged(tmp_path):
    header = [h for h in HEADER if h != "Murder"]
    path = make_workbook(
        tmp_path / "nyc-park-crime-stats-q2-2020.xlsx",
        [["PARK A", "BROOKLYN", "1.5", "ONE ACRE OR LARGER", 2, 3, 4, 5, 6, 7, 27]],
        header=header,
    )
    result = parse_workbook(path)

    (violation,) = result["violations"]
    assert violation["kind"] == "missing_column"
    murder = [r for r in result["records"] if r["crime_type"] == "MURDER"]
    assert len(murder) == 1
    assert murder[0]["count"] is None
    assert murder[0]["count_missing"] == 1
    assert all(r["count_missing"] == 0 for r in result["records"] if r["crime_type"] != "MURDER")
    # TOTAL is checked against the six components the workbook actually has.
    assert {r["total_mismatch"] for r in result["records"]} == {0}


def test_filename_quarter_must_match_the_parsed_period(tmp_path):
    path = make_workbook(
        tmp_path / "nyc-park-crime-stats-q3-2020.xlsx",  # period says Q2 2020
        [["PARK A", "BROOKLYN", "1.5", "ONE ACRE OR LARGER", 1, 2, 3, 4, 5, 6, 7, 28]],
    )
    with pytest.raises(ValueError, match="filename quarter 2020Q3"):
        parse_workbook(path)


def test_allow_anomalies_writes_evidence_csv(tmp_path):
    out = tmp_path / "source_anomalies.csv"
    write_anomalies(
        [
            {
                "workbook": "nyc-park-crime-stats-q4-2025.xlsx",
                "sheet": "Page1",
                "excel_row": 315,
                "park": "FLUSHING MEADOWS CORONA PARK",
                "borough": "QUEENS",
                "total_recorded": 17,
                "sum_computed": 18,
                "delta": -1,
                "kind": "total_mismatch",
            }
        ],
        path=out,
    )

    frame = pd.read_csv(out)
    assert list(frame.columns) == [
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
    assert frame.loc[0, "kind"] == "total_mismatch"
    assert frame.loc[0, "workbook"] == "nyc-park-crime-stats-q4-2025.xlsx"
    assert frame.loc[0, "excel_row"] == 315
    assert frame.loc[0, "delta"] == -1


def test_committed_fixture_workbooks_parse_end_to_end(fixture_raw):
    """The committed dataset covers all three source shapes (ticket 0050)."""
    parsed, records, violations = parse_all(fixture_raw)

    assert [workbook["quarter"] for workbook in parsed] == [
        "2019Q1", "2019Q2", "2019Q3"
    ]
    assert {entry["kind"] for entry in violations} == {
        "total_mismatch", "missing_column"
    }
    assert len(records) == sum(w["source_rows"] for w in parsed) * len(CRIME_TYPES)
    assert {r["quarter_label"] for r in records} == {"2019Q1", "2019Q2", "2019Q3"}
    assert {r["crime_type"] for r in records} == set(CRIME_TYPES)
    assert any(r["count"] == 0 for r in records)
    murder = [r for r in records if r["quarter_label"] == "2019Q3"
              and r["crime_type"] == "MURDER"]
    assert all(r["count"] is None and r["count_missing"] == 1 for r in murder)
    assert all(r["period_start"] <= r["period_end"] for r in records)


def test_footer_total_colon_is_not_a_park(tmp_path):
    path = tmp_path / "nyc-park-crime-stats-q2-2020.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Report covering the period Between Apr 1, 2020 and Jun 30, 2020"])
    sheet.append(HEADER)
    sheet.append(["PARK A", "BROOKLYN", "1.5", "ONE ACRE OR LARGER", 1, 2, 3, 4, 5, 6, 7, 28])
    sheet.append(["TOTAL:", None, None, None, 1, 2, 3, 4, 5, 6, 7, 28])
    workbook.save(path)

    result = parse_workbook(path)

    assert result["source_rows"] == 1
    assert {r["park"] for r in result["records"]} == {"PARK A"}


@pytest.mark.parametrize("argv", [["parse.py"], ["parse.py", "--check"]])
def test_zero_park_rows_exits_nonzero_and_names_workbook(
    tmp_path, monkeypatch, capsys, argv
):
    raw = tmp_path / "raw"
    raw.mkdir()
    name = "nyc-park-crime-stats-q2-2020.xlsx"
    make_workbook(raw / name, [])
    monkeypatch.setattr(parse, "RAW_DIR", raw)
    monkeypatch.setattr(sys, "argv", argv)

    assert parse.main() == 1
    assert name in capsys.readouterr().err


def test_allow_anomalies_records_no_rows_and_continues(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    name = "nyc-park-crime-stats-q2-2020.xlsx"
    make_workbook(raw / name, [])
    anomalies = tmp_path / "outputs" / "source_anomalies.csv"
    monkeypatch.setattr(parse, "ROOT", tmp_path)
    monkeypatch.setattr(parse, "RAW_DIR", raw)
    monkeypatch.setattr(parse, "PROCESSED_DIR", tmp_path / "processed")
    monkeypatch.setattr(
        parse, "CSV_PATH", tmp_path / "processed" / "park_crime_long.csv"
    )
    monkeypatch.setattr(parse, "DB_PATH", tmp_path / "warehouse.db")
    monkeypatch.setattr(parse, "ANOMALIES_CSV", anomalies)
    monkeypatch.setattr(sys, "argv", ["parse.py", "--allow-anomalies"])

    assert parse.main() == 0
    frame = pd.read_csv(anomalies)
    assert list(frame.columns) == parse.ANOMALY_COLUMNS
    assert frame.loc[0, "workbook"] == name
    assert frame.loc[0, "kind"] == "no_rows"


def test_allow_anomalies_rewrites_stale_csv(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    make_workbook(
        raw / "nyc-park-crime-stats-q2-2020.xlsx",
        [["PARK A", "BROOKLYN", "1.5", "ONE ACRE OR LARGER", 1, 2, 3, 4, 5, 6, 7, 28]],
    )
    anomalies = tmp_path / "outputs" / "source_anomalies.csv"
    anomalies.parent.mkdir(parents=True)
    anomalies.write_text("stale,row\n1,2\n")
    monkeypatch.setattr(parse, "ROOT", tmp_path)
    monkeypatch.setattr(parse, "RAW_DIR", raw)
    monkeypatch.setattr(parse, "PROCESSED_DIR", tmp_path / "processed")
    monkeypatch.setattr(
        parse, "CSV_PATH", tmp_path / "processed" / "park_crime_long.csv"
    )
    monkeypatch.setattr(parse, "DB_PATH", tmp_path / "warehouse.db")
    monkeypatch.setattr(parse, "ANOMALIES_CSV", anomalies)
    monkeypatch.setattr(sys, "argv", ["parse.py", "--allow-anomalies"])

    assert parse.main() == 0
    frame = pd.read_csv(anomalies)
    assert list(frame.columns) == parse.ANOMALY_COLUMNS
    assert frame.empty


def test_to_count_rejects_booleans():
    for bad in (True, False):
        with pytest.raises(parse.InvalidCount):
            parse.to_count(bad)
