"""Warehouse DDL shared by etl/parse.py (build) and etl/geo.py (park enrich).

Explicit types and constraints: the long table is keyed by
(quarter_label, park_id, crime_type), dimensions carry the period and the park
reference, and pipeline_runs records the lineage of the run that wrote it.
"""

import sqlite3

DDL = """
CREATE TABLE IF NOT EXISTS quarters (
    quarter_label TEXT PRIMARY KEY,
    period_start  TEXT NOT NULL,
    period_end    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS parks (
    park_id        TEXT PRIMARY KEY,
    park           TEXT NOT NULL,
    borough        TEXT NOT NULL,
    canonical_name TEXT,
    lat            REAL,
    lon            REAL,
    acres_geo      REAL,
    typecategory   TEXT,
    match_type     TEXT
);

CREATE TABLE IF NOT EXISTS crimes_long (
    quarter_label  TEXT NOT NULL,
    park_id        TEXT NOT NULL,
    park           TEXT NOT NULL,
    borough        TEXT NOT NULL,
    period_start   TEXT NOT NULL,
    period_end     TEXT NOT NULL,
    size_acres     REAL,
    category       TEXT,
    crime_type     TEXT NOT NULL,
    count          INTEGER,
    count_missing  INTEGER NOT NULL DEFAULT 0,
    total_mismatch INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (quarter_label, park_id, crime_type),
    FOREIGN KEY (quarter_label) REFERENCES quarters (quarter_label),
    FOREIGN KEY (park_id)       REFERENCES parks (park_id)
);

CREATE INDEX IF NOT EXISTS idx_crimes_quarter_park_crime
    ON crimes_long (quarter_label, park, crime_type);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at                 TEXT NOT NULL,
    git_sha                TEXT,
    source_manifest_sha256 TEXT,
    workbook_count         INTEGER NOT NULL,
    source_rows            INTEGER NOT NULL,
    long_rows              INTEGER NOT NULL
);
"""


def connect(path):
    """Open a connection with foreign keys enforced."""
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def ensure_schema(connection):
    connection.executescript(DDL)
