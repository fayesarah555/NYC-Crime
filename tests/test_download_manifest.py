"""Network-free: the manifest on disk must match the workbooks on disk."""

import hashlib
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.network_free

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
MANIFEST = RAW_DIR / "manifest.json"
if not RAW_DIR.exists():
    pytest.skip(
        "data/raw absent; run `make data` then `make warehouse` first",
        allow_module_level=True,
    )


def load_manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["workbooks"]


def test_manifest_matches_disk():
    workbooks = load_manifest()
    assert workbooks, "manifest lists no workbook"

    for entry in workbooks:
        path = RAW_DIR / entry["filename"]
        assert path.exists(), f"{entry['filename']} missing"
        data = path.read_bytes()
        assert path.name == f"nyc-park-crime-stats-q{entry['quarter']}-{entry['year']}.xlsx"
        assert len(data) == entry["bytes"], f"{entry['filename']} size changed"
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], (
            f"{entry['filename']} sha256 changed"
        )


def test_no_untracked_workbook():
    listed = {entry["filename"] for entry in load_manifest()}
    assert listed, "manifest lists no workbook"
    on_disk = {path.name for path in RAW_DIR.glob("*.xlsx")}
    assert on_disk == listed
