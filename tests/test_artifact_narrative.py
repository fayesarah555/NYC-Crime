"""No hand-typed narrative in artefacts; the dictionary covers every output.

Ticket 0049. Artefact scripts must derive every factual literal they print
from their own data or metrics; the data dictionary must name every exported
column, table and JSON key.
"""

import csv
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Artefact scripts and user-facing modules: every factual literal they print
# must come from their data, so the same patterns are scanned everywhere.
ARTEFACT_SCRIPTS = (
    ROOT / "analysis" / "eda.py",
    ROOT / "analysis" / "model.py",
    ROOT / "export" / "export_web.py",
    ROOT / "presentation" / "build_deck.py",
    ROOT / "app" / "app.py",
)

FORBIDDEN = (
    r"\b2020Q1\b",
    r"\b2014Q4\b",
    r"\b2026Q2\b",
    r"\b2026Q3\b",
    r"\b2026Q4\b",
    r"\b1e-200\b",
    r"\b12,?544\b",
    r"\b53,?088\b",
    r"TOTAL 17",
    r"17 vs",
    r"17 contre",
    r"somme 18",
    r"sum 18",
    r"\b5 parcs\b",
    r"\b46\b",
    r"sept composantes",
    r"seven components",
    r"95 ?%",
    r"8 mêmes",
    r"8 held-out",
    r"huit trimestres",
)


def test_artefact_scripts_have_no_hardcoded_narrative_literals():
    offenders = []
    for script in ARTEFACT_SCRIPTS:
        for number, line in enumerate(
            script.read_text(encoding="utf-8").splitlines(), start=1
        ):
            for pattern in FORBIDDEN:
                if re.search(pattern, line):
                    offenders.append(f"{script.name}:{number}: {pattern}")
    assert offenders == []


def _exported_payloads():
    data = ROOT / "app" / "web" / "src" / "data"
    names = (
        "meta.json", "parks.json", "series.json", "borough_type.json",
        "forecast.json", "clusters.json", "cubes.json",
    )
    missing = [name for name in names if not (data / name).is_file()]
    assert missing == [], (
        f"exported payloads missing from app/web/src/data: {missing}"
    )
    return {name: json.loads((data / name).read_text(encoding="utf-8"))
            for name in names}


# Maps whose keys are data values (park ids, quarters, borough names, crime
# types, model names) rather than schema keys; their nested keys are still
# walked, only the identifier level is skipped.
DYNAMIC_KEY_PATHS = (
    ("series.json", "city_by_type"),
    ("series.json", "boroughs"),
    ("forecast.json", "boroughs"),
    ("forecast.json", "metrics", "boroughs"),
    ("forecast.json", "metrics", "skipped_boroughs"),
    ("forecast.json", "metrics", "city", "backtest_metrics"),
    ("forecast.json", "metrics", "city", "model_failures"),
    ("forecast.json", "metrics", "boroughs", "*", "backtest_metrics"),
    ("forecast.json", "metrics", "boroughs", "*", "model_failures"),
    ("parks.json", "*", "counts"),
    ("borough_type.json", "boroughs", "*", "counts"),
    ("cubes.json", "parks"),
    ("cubes.json", "parks", "*"),
)


def _is_dynamic(path):
    return any(
        len(pattern) == len(path)
        and all(step == "*" or step == part for step, part in zip(pattern, path))
        for pattern in DYNAMIC_KEY_PATHS
    )


def _all_keys(node, path, keys):
    """Every dict key of the payload, recursing through lists and dicts."""
    if isinstance(node, dict):
        if not _is_dynamic(path):
            keys.update(node)
        for key, value in node.items():
            _all_keys(value, path + (key,), keys)
    elif isinstance(node, list):
        for item in node:
            _all_keys(item, path + ("*",), keys)
    return keys


def _required_keys(payloads):
    keys = set()
    for name, payload in payloads.items():
        _all_keys(payload, (name,), keys)
    return keys


def test_data_dictionary_covers_csv_tables_and_json(fixture_warehouse):
    doc = (ROOT / "docs" / "data_dictionary.md").read_text(encoding="utf-8")

    csv_path = fixture_warehouse["csv"]
    with csv_path.open(encoding="utf-8", newline="") as handle:
        columns = next(csv.reader(handle))
    for column in columns:
        assert f"`{column}`" in doc, column

    with sqlite3.connect(fixture_warehouse["db"]) as conn:
        tables = [
            name for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        ]
        table_columns = {
            table: [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
            for table in tables
        }
    for table, columns in table_columns.items():
        assert f"`{table}`" in doc, table
        for column in columns:
            assert f"`{column}`" in doc, f"{table}.{column}"

    payloads = _exported_payloads()
    for name in payloads:
        assert name in doc, name
    for key in _required_keys(payloads):
        assert f"`{key}`" in doc, key


def test_missing_quarter_sentence_follows_eda_stats_only(tmp_path):
    """Semantic twin of the grep gate: the absence sentence must vanish when
    `missing_quarters` is gone, and follow altered labels, never a literal."""
    sys.path.insert(0, str(ROOT / "app"))
    import app as streamlit_app
    from export.export_web import documented_missing

    stats = {"missing_quarters": ["2020Q1"]}
    labels = documented_missing(stats)
    assert streamlit_app.missing_quarter_notes(stats) == [
        f"- {label} est absent de la source : jamais traité comme zéro."
        for label in labels
    ]

    altered = json.loads(json.dumps(stats))
    altered["missing_quarters"] = ["2099Q9"]
    copy = tmp_path / "eda_stats.json"
    copy.write_text(json.dumps(altered), encoding="utf-8")
    reloaded = json.loads(copy.read_text(encoding="utf-8"))
    assert reloaded["missing_quarters"] == ["2099Q9"]
    assert streamlit_app.missing_quarter_notes(reloaded) == [
        "- 2099Q9 est absent de la source : jamais traité comme zéro."
    ]

    del reloaded["missing_quarters"]
    reloaded.pop("missing_quarter", None)
    copy.write_text(json.dumps(reloaded), encoding="utf-8")
    reloaded = json.loads(copy.read_text(encoding="utf-8"))
    assert streamlit_app.missing_quarter_notes(reloaded) == []
    assert documented_missing(reloaded) == []
