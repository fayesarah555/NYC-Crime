"""Network-free: download retries/gaps/lock, parse rejection and multi-sheet,
geo pagination and fuzzy guards, warehouse schema and atomic swap."""

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest
import requests
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from etl import download, geo, parse  # noqa: E402

pytestmark = pytest.mark.network_free

HEADER = [
    "PARK", "BOROUGH", "SIZE (ACRES)", "CATEGORY",
    "Murder", "RAPE", "ROBBERY", "FELONY ASSAULT", "BURGLARY",
    "GRAND LARCENY", "Grand  Larceny Auto", "TOTAL",
]
ZIP = b"PK\x03\x04fake workbook bytes"


# --------------------------------------------------------------------------
# download.py
# --------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, status_code=200, content=b"", text="", headers=None):
        self.status_code = status_code
        self.content = content
        self.text = text
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self):
        return json.loads(self.text)


class FakeSession:
    """Routes each URL to a handler; records the headers sent."""

    def __init__(self, handlers):
        self.handlers = handlers
        self.calls = []

    def get(self, url, headers=None, timeout=None, params=None):
        self.calls.append({"url": url, "headers": headers or {}, "params": params})
        for fragment, handler in self.handlers.items():
            if fragment in url:
                return handler(url, headers or {})
        raise requests.ConnectionError(f"unexpected URL {url}")


def page_html(quarters):
    links = "".join(
        f'<a href="/assets/nypd/downloads/excel/crime_statistics/park-crime/'
        f'nyc-park-crime-stats-q{q}-{year}.xlsx">q{q}</a>'
        for year, q in quarters
    )
    return f"<html>{links}</html>"


def patch_download_paths(monkeypatch, tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    monkeypatch.setattr(download, "RAW_DIR", raw)
    monkeypatch.setattr(download, "MANIFEST", raw / "manifest.json")
    monkeypatch.setattr(download, "LOCK_PATH", tmp_path / "manifest.lock.json")
    monkeypatch.setattr(download, "GAPS_CSV", tmp_path / "tables" / "download_gaps.csv")
    monkeypatch.setattr(download, "WORKERS", 2)
    monkeypatch.setattr(download, "ROOT", tmp_path)
    return raw


def test_session_retries_three_times_on_server_errors():
    session = download.make_session()
    try:
        adapter = session.adapters["https://"]
        assert adapter.max_retries.total == 3
        assert {429, 500, 502, 503, 504} <= set(adapter.max_retries.status_forcelist)
        assert adapter.max_retries.backoff_factor > 0
    finally:
        session.close()


def test_failed_files_are_gaps_and_do_not_abort_the_run(monkeypatch, tmp_path):
    raw = patch_download_paths(monkeypatch, tmp_path)
    quarters = [(2020, 1), (2020, 2), (2020, 3)]
    session = FakeSession({
        download.PAGE_URL: lambda url, headers: FakeResponse(text=page_html(quarters)),
        "q1-2020": lambda url, headers: FakeResponse(content=ZIP),
        "q2-2020": lambda url, headers: FakeResponse(status_code=500),
        "q3-2020": lambda url, headers: (_ for _ in ()).throw(
            requests.Timeout("timed out")
        ),
    })

    assert download.run(allow_missing=True, session=session) == 0

    entries = download.load_manifest()
    assert set(entries) == {"nyc-park-crime-stats-q1-2020.xlsx"}
    gaps = pd.read_csv(download.GAPS_CSV)
    assert list(gaps["quarter"]) == ["2020Q2", "2020Q3"]
    assert set(gaps["reason"]) == {"download_failed"}
    lock = json.loads(download.LOCK_PATH.read_text(encoding="utf-8"))["workbooks"]
    assert [entry["filename"] for entry in lock] == ["nyc-park-crime-stats-q1-2020.xlsx"]
    assert "url" not in lock[0]  # hashes only, nothing environment-specific
    assert (raw / "nyc-park-crime-stats-q1-2020.xlsx").read_bytes() == ZIP


def test_gaps_exit_nonzero_without_allow_missing(monkeypatch, tmp_path):
    patch_download_paths(monkeypatch, tmp_path)
    quarters = [(2020, 1), (2020, 2)]
    session = FakeSession({
        download.PAGE_URL: lambda url, headers: FakeResponse(text=page_html(quarters)),
        "q1-2020": lambda url, headers: FakeResponse(content=ZIP),
        "q2-2020": lambda url, headers: FakeResponse(status_code=500),
    })
    assert download.run(session=session) == 1
    assert download.GAPS_CSV.exists()


def test_cond_get_304_reuses_the_cached_workbook(monkeypatch, tmp_path):
    raw = patch_download_paths(monkeypatch, tmp_path)
    name = "nyc-park-crime-stats-q1-2020.xlsx"
    (raw / name).write_bytes(ZIP)
    download.write_manifest([{
        "url": download.BASE_URL + "/assets/nypd/downloads/excel/crime_statistics/"
        "park-crime/nyc-park-crime-stats-q1-2020.xlsx",
        "filename": name,
        "bytes": len(ZIP),
        "sha256": hashlib.sha256(ZIP).hexdigest(),
        "quarter": 1,
        "year": 2020,
        "etag": '"v1"',
        "last_modified": "Mon, 01 Apr 2024 00:00:00 GMT",
    }])
    page = page_html([(2020, 1)])
    session = FakeSession({
        download.PAGE_URL: lambda url, headers: FakeResponse(text=page),
        "q1-2020": lambda url, headers: FakeResponse(status_code=304),
    })

    assert download.run(force=True, session=session) == 0

    sent = [call["headers"] for call in session.calls if "q1-2020" in call["url"]]
    assert sent and sent[0]["If-None-Match"] == '"v1"'
    assert sent[0]["If-Modified-Since"] == "Mon, 01 Apr 2024 00:00:00 GMT"
    entries = download.load_manifest()
    assert entries[name]["etag"] == '"v1"'
    assert entries[name]["sha256"] == hashlib.sha256(ZIP).hexdigest()


def test_discovery_failure_without_a_manifest_exits_two(monkeypatch, tmp_path):
    patch_download_paths(monkeypatch, tmp_path)
    session = FakeSession({
        download.PAGE_URL: lambda url, headers: (_ for _ in ()).throw(
            requests.ConnectionError("offline")
        ),
    })
    assert download.run(session=session) == 2


def test_verify_lock_detects_drift(monkeypatch, tmp_path):
    raw = patch_download_paths(monkeypatch, tmp_path)
    name = "nyc-park-crime-stats-q1-2020.xlsx"
    (raw / name).write_bytes(ZIP)
    download.write_lock([{
        "filename": name, "bytes": len(ZIP),
        "sha256": hashlib.sha256(ZIP).hexdigest(), "quarter": 1, "year": 2020,
    }])
    assert download.verify_lock() == 0
    (raw / name).write_bytes(ZIP + b"\0")
    assert download.verify_lock() == 2


# --------------------------------------------------------------------------
# parse.py
# --------------------------------------------------------------------------

def make_workbook(path, rows, header=HEADER, period="Apr 1, 2020 and Jun 30, 2020"):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["2nd QTR PARK CRIME REPORT"])
    sheet.append([f"Report covering the period Between {period}"])
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    return path


def test_negative_count_is_rejected_not_truncated(tmp_path):
    path = make_workbook(
        tmp_path / "nyc-park-crime-stats-q2-2020.xlsx",
        [["PARK A", "BROOKLYN", "1.5", "ONE ACRE OR LARGER", -3, 2, 3, 4, 5, 6, 7, 27]],
    )
    result = parse.parse_workbook(path)

    assert result["records"] == []
    (violation,) = result["violations"]
    assert violation["kind"] == "invalid_count"
    assert "negative value -3" in violation["message"]


def test_non_integer_count_is_rejected_not_truncated(tmp_path):
    path = make_workbook(
        tmp_path / "nyc-park-crime-stats-q2-2020.xlsx",
        [["PARK A", "BROOKLYN", "1.5", "ONE ACRE OR LARGER", 1.5, 2, 3, 4, 5, 6, 7, 28]],
    )
    result = parse.parse_workbook(path)

    assert result["records"] == []
    (violation,) = result["violations"]
    assert violation["kind"] == "invalid_count"
    assert "non-integer" in violation["message"]


def test_unparseable_acres_is_flagged_and_the_row_kept(tmp_path):
    path = make_workbook(
        tmp_path / "nyc-park-crime-stats-q2-2020.xlsx",
        [["PARK A", "BROOKLYN", "n/a", "ONE ACRE OR LARGER", 1, 2, 3, 4, 5, 6, 7, 28]],
    )
    result = parse.parse_workbook(path)

    assert len(result["records"]) == len(parse.CRIME_TYPES)
    assert {record["size_acres"] for record in result["records"]} == {None}
    (violation,) = result["violations"]
    assert violation["kind"] == "invalid_acres"


def test_month_map_is_explicit_and_locale_proof():
    from datetime import date

    assert parse.parse_period("Between Sept. 1, 2019 and Dec 31, 2019") == (
        date(2019, 9, 1), date(2019, 12, 31),
    )
    with pytest.raises(ValueError, match="unknown month"):
        parse.parse_period("Between Foo 1, 2019 and Dec 31, 2019")


def test_multi_sheet_workbook_parses_every_park_sheet_and_dedupes(tmp_path):
    path = make_workbook(
        tmp_path / "nyc-park-crime-stats-q2-2020.xlsx",
        [["PARK A", "BROOKLYN", "1.5", "ONE ACRE OR LARGER", 1, 2, 3, 4, 5, 6, 7, 28]],
    )
    workbook = Workbook()
    del workbook
    from openpyxl import load_workbook

    book = load_workbook(path)
    copy = book.create_sheet("Data copy")
    copy.append(HEADER)
    copy.append(["PARK A", "BROOKLYN", "1.5", "ONE ACRE OR LARGER", 1, 2, 3, 4, 5, 6, 7, 28])
    book.save(path)

    result = parse.parse_workbook(path)

    # Identical rows across sheets collapse; the row count is not doubled.
    assert result["source_rows"] == 1
    assert len(result["records"]) == len(parse.CRIME_TYPES)
    assert result["violations"] == []


def test_conflicting_duplicate_across_sheets_is_flagged(tmp_path):
    path = make_workbook(
        tmp_path / "nyc-park-crime-stats-q2-2020.xlsx",
        [["PARK A", "BROOKLYN", "1.5", "ONE ACRE OR LARGER", 1, 2, 3, 4, 5, 6, 7, 28]],
    )
    from openpyxl import load_workbook

    book = load_workbook(path)
    copy = book.create_sheet("Data copy")
    copy.append(HEADER)
    copy.append(["PARK A", "BROOKLYN", "1.5", "ONE ACRE OR LARGER", 9, 2, 3, 4, 5, 6, 7, 36])
    book.save(path)

    result = parse.parse_workbook(path)

    (violation,) = result["violations"]
    assert violation["kind"] == "conflicting_duplicate"
    murder = [r for r in result["records"] if r["crime_type"] == "MURDER"]
    assert [r["count"] for r in murder] == [1]  # first sheet wins


# --------------------------------------------------------------------------
# geo.py
# --------------------------------------------------------------------------

def square(lon, lat):
    ring = [
        [lon - 0.05, lat - 0.05], [lon + 0.05, lat - 0.05],
        [lon + 0.05, lat + 0.05], [lon - 0.05, lat + 0.05],
        [lon - 0.05, lat - 0.05],
    ]
    return {"type": "MultiPolygon", "coordinates": [[ring]]}


def property_(signname, borough, lon=-73.95, lat=40.75, acres="1.0"):
    return {
        "signname": signname,
        "name311": signname,
        "borough": borough,
        "acres": acres,
        "typecategory": "Park",
        "multipolygon": square(lon, lat),
    }


def test_fuzzy_never_crosses_north_and_south():
    index = geo.build_index([property_("ROSE PLAYGROUND SOUTH", "M")])
    hit, kind = geo.match_park("ROSE PLAYGROUND NORTH", "MANHATTAN", index)
    assert (hit, kind) == (None, "none")


def test_fuzzy_never_swaps_numeric_siblings():
    index = geo.build_index([property_("PLAYGROUND 5", "M")])
    hit, kind = geo.match_park("PLAYGROUND 6", "MANHATTAN", index)
    assert (hit, kind) == (None, "none")
    index = geo.build_index([property_("PLAYGROUND 6", "M")])
    hit, kind = geo.match_park("PLAYGROUND 6", "MANHATTAN", index)
    assert kind == "signname" and hit["signname"] == "PLAYGROUND 6"


def test_denylist_and_override_are_applied():
    index = geo.build_index([
        property_("ROSE PLAYGROUND", "M"),
        property_("ROSE GARDEN", "M", lon=-73.90),
    ])
    denied = frozenset({("ROSE PLAYGROUNDS", "ROSE PLAYGROUND")})
    hit, kind = geo.match_park("ROSE PLAYGROUNDS", "MANHATTAN", index, denylist=denied)
    assert kind == "none" and hit is None

    overrides = {("ROSE PLAYGROUNDS", "MANHATTAN"): "ROSE GARDEN"}
    hit, kind = geo.match_park("ROSE PLAYGROUNDS", "MANHATTAN", index, overrides=overrides)
    assert kind == "override"
    assert hit["signname"] == "ROSE GARDEN"


def test_fuzzy_match_records_a_distance_audit():
    index = geo.build_index([
        property_("ROSE PLAYGROUND", "M", lon=-73.95),
        property_("ROSE PLAYGROUNDS", "M", lon=-73.90),
    ])
    parks = pd.DataFrame({"park": ["ROSE PLAYGROUNDZ"], "borough": ["MANHATTAN"], "count": [1]})
    frame, audit = geo.build_frame(parks, index, denylist=frozenset(), overrides={})

    assert frame.loc[0, "match_type"] == "fuzzy"
    (row,) = audit
    assert row["matched_property"] == "ROSE PLAYGROUND"
    assert row["distance_km"] and row["distance_km"] > 0


def test_socrata_pagination_until_a_short_page(monkeypatch, tmp_path):
    monkeypatch.setattr(geo, "PAGE_SIZE", 2)
    pages = {
        0: [{"signname": "A"}, {"signname": "B"}],
        2: [{"signname": "C"}],
    }
    session = FakeSession({})  # replaced below by a params-aware fake

    calls = []

    class PagedSession:
        def get(self, url, params=None, timeout=None):
            calls.append(dict(params))
            return FakeResponse(text=json.dumps(pages[params["$offset"]]))

    result = geo.fetch_properties(
        cache_path=tmp_path / "cache.json", refresh=True, session=PagedSession()
    )

    assert [item["signname"] for item in result] == ["A", "B", "C"]
    assert [call["$offset"] for call in calls] == [0, 2]
    assert all(call["$order"] == ":id" for call in calls)
    cached = json.loads((tmp_path / "cache.json").read_text(encoding="utf-8"))
    assert cached["count"] == 3
    assert cached["sha256"] == geo.sha256(
        json.dumps(result, sort_keys=True, ensure_ascii=False).encode("utf-8")
    )
    assert cached["fetched_at"]
    assert "unexpected" not in str(session.calls)


def test_cache_ttl_skips_the_network_until_refresh(monkeypatch, tmp_path):
    monkeypatch.setattr(geo, "PAGE_SIZE", 2)
    cache = tmp_path / "cache.json"
    requests_made = []

    class Session:
        def get(self, url, params=None, timeout=None):
            requests_made.append(params["$offset"])
            return FakeResponse(text=json.dumps([{"signname": "A"}]))

    assert geo.fetch_properties(cache_path=cache, refresh=True, session=Session()) == [
        {"signname": "A"}
    ]
    # A second, non-refresh call is served from the fresh cache.
    assert geo.fetch_properties(cache_path=cache, session=Session()) == [{"signname": "A"}]
    assert requests_made == [0]
    # --refresh goes back to the API.
    geo.fetch_properties(cache_path=cache, refresh=True, session=Session())
    assert requests_made == [0, 0]


# --------------------------------------------------------------------------
# warehouse
# --------------------------------------------------------------------------

def record(park="PARK A", crime_type="MURDER", count=1, quarter="2020Q1"):
    return {
        "quarter_label": quarter,
        "period_start": "2020-01-01",
        "period_end": "2020-03-31",
        "park": park,
        "borough": "BROOKLYN",
        "size_acres": 1.5,
        "category": "PARK",
        "crime_type": crime_type,
        "count": count,
        "count_missing": 0,
        "total_mismatch": 0,
    }


def patch_parse_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(parse, "DB_PATH", tmp_path / "warehouse.db")
    monkeypatch.setattr(parse, "CSV_PATH", tmp_path / "park_crime_long.csv")
    monkeypatch.setattr(parse, "PROCESSED_DIR", tmp_path)
    monkeypatch.setattr(parse, "GEO_CSV", tmp_path / "missing_geo.csv")
    monkeypatch.setattr(parse, "RAW_DIR", tmp_path / "raw-without-manifest")


def test_schema_has_keys_dims_and_pipeline_runs(monkeypatch, tmp_path):
    patch_parse_paths(monkeypatch, tmp_path)
    parse.write_outputs([record(), record(crime_type="RAPE")], workbook_count=1, source_rows=1)

    connection = sqlite3.connect(parse.DB_PATH)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )}
        assert {"crimes_long", "parks", "quarters", "pipeline_runs"} <= tables
        run = connection.execute(
            "SELECT run_at, workbook_count, source_rows, long_rows FROM pipeline_runs"
        ).fetchone()
        assert run[1:] == (1, 1, 2)
        assert run[0].endswith("+00:00")
        assert connection.execute("SELECT COUNT(*) FROM quarters").fetchone()[0] == 1

        with pytest.raises(sqlite3.IntegrityError):  # PK (quarter, park_id, crime_type)
            connection.execute(
                "INSERT INTO crimes_long VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                ("2020Q1", "BROOKLYN:PARK A", "PARK A", "BROOKLYN",
                 "2020-01-01", "2020-03-31", 1.5, "PARK", "MURDER", 1, 0, 0),
            )
        with pytest.raises(sqlite3.IntegrityError):  # NOT NULL park
            connection.execute(
                "INSERT INTO crimes_long VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                ("2020Q1", "unknown", None, "BROOKLYN",
                 "2020-01-01", "2020-03-31", None, None, "RAPE", 1, 0, 0),
            )
        with pytest.raises(sqlite3.IntegrityError):  # unknown quarter dimension
            connection.execute(
                "INSERT INTO crimes_long VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                ("1999Q1", "BROOKLYN:PARK A", "PARK A", "BROOKLYN",
                 "1999-01-01", "1999-03-31", 1.5, "PARK", "MURDER", 1, 0, 0),
            )
    finally:
        connection.close()


def test_failed_swap_leaves_the_old_database_intact(monkeypatch, tmp_path):
    patch_parse_paths(monkeypatch, tmp_path)
    connection = sqlite3.connect(parse.DB_PATH)
    connection.execute("CREATE TABLE sentinel (value TEXT)")
    connection.execute("INSERT INTO sentinel VALUES ('old')")
    connection.commit()
    connection.close()

    duplicates = [record(), record(count=99)]  # same PK, different count
    with pytest.raises(sqlite3.IntegrityError):
        parse.write_outputs(duplicates)

    assert not (tmp_path / "warehouse.db.tmp").exists()
    connection = sqlite3.connect(parse.DB_PATH)
    try:
        assert connection.execute("SELECT value FROM sentinel").fetchone() == ("old",)
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'crimes_long'"
        ).fetchone() is None
    finally:
        connection.close()
