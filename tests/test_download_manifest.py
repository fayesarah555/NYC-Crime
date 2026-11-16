"""Network-free: the manifest must match the workbooks on disk."""

import hashlib
import json

import pytest

pytestmark = pytest.mark.network_free


def load_manifest(raw):
    return json.loads((raw / "manifest.json").read_text(encoding="utf-8"))["workbooks"]


def test_manifest_matches_fixture_disk(fixture_raw):
    workbooks = load_manifest(fixture_raw)
    assert workbooks, "manifest lists no workbook"

    for entry in workbooks:
        path = fixture_raw / entry["filename"]
        assert path.exists(), f"{entry['filename']} missing"
        data = path.read_bytes()
        assert path.name == (
            f"nyc-park-crime-stats-q{entry['quarter']}-{entry['year']}.xlsx"
        )
        assert len(data) == entry["bytes"], f"{entry['filename']} size changed"
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], (
            f"{entry['filename']} sha256 changed"
        )


def test_no_untracked_workbook(fixture_raw):
    listed = {entry["filename"] for entry in load_manifest(fixture_raw)}
    assert listed, "manifest lists no workbook"
    on_disk = {path.name for path in fixture_raw.glob("*.xlsx")}
    assert on_disk == listed


def test_download_check_verifies_the_fixture_manifest(fixture_raw, monkeypatch):
    from etl import download

    monkeypatch.setattr(download, "RAW_DIR", fixture_raw)
    monkeypatch.setattr(download, "MANIFEST", fixture_raw / "manifest.json")

    assert download.check() == 0


def test_download_check_reports_drift(fixture_raw, tmp_path, monkeypatch):
    import shutil

    from etl import download

    raw = tmp_path / "raw"
    shutil.copytree(fixture_raw, raw)
    monkeypatch.setattr(download, "RAW_DIR", raw)
    monkeypatch.setattr(download, "MANIFEST", raw / "manifest.json")
    victim = next(raw.glob("*.xlsx"))
    victim.write_bytes(victim.read_bytes() + b"\0")

    assert download.check() == 2
