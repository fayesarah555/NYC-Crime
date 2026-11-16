"""Cache every published NYPD park-crime quarterly workbook under data/raw/.

Usage:
    python etl/download.py            # download missing / changed workbooks
    python etl/download.py --check    # re-verify the manifest against disk
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import requests

PAGE_URL = "https://www.nyc.gov/site/nypd/stats/crime-statistics/park-crime-stats.page"
BASE_URL = "https://www.nyc.gov"
HREF_RE = re.compile(
    r"/assets/nypd/downloads/excel/crime_statistics/park-crime/"
    r"nyc-park-crime-stats-q(\d)-(\d{4})\.xlsx"
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": PAGE_URL,
}
ZIP_MAGIC = b"PK\x03\x04"
ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
MANIFEST = RAW_DIR / "manifest.json"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def discover():
    """Return [(href, quarter, year)] sorted by year then quarter."""
    page = requests.get(PAGE_URL, headers=HEADERS, timeout=60)
    page.raise_for_status()
    found = {
        m.group(0): (int(m.group(1)), int(m.group(2)))
        for m in HREF_RE.finditer(page.text)
    }
    return [
        (href, quarter, year)
        for href, (quarter, year) in sorted(
            found.items(), key=lambda kv: (kv[1][1], kv[1][0])
        )
    ]


def load_manifest():
    if not MANIFEST.exists():
        return {}
    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))["workbooks"]
    return {e["filename"]: e for e in entries}


def download(href):
    resp = requests.get(BASE_URL + href, headers=HEADERS, timeout=120)
    resp.raise_for_status()
    return resp.content


def write_manifest(entries):
    MANIFEST.write_text(
        json.dumps({"workbooks": entries}, indent=2) + "\n", encoding="utf-8"
    )


def run():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    previous = load_manifest()
    entries, downloaded, reused, rejected = [], 0, 0, []
    for href, quarter, year in discover():
        filename = href.rsplit("/", 1)[-1]
        dest = RAW_DIR / filename
        data = None
        if dest.exists() and previous.get(filename, {}).get("sha256") == sha256(
            dest.read_bytes()
        ):
            data = dest.read_bytes()
            reused += 1
        else:
            try:
                data = download(href)
            except requests.HTTPError as exc:
                rejected.append((filename, str(exc)))
                continue
            if not data.startswith(ZIP_MAGIC):
                rejected.append((filename, "payload is not a ZIP workbook"))
                continue
            dest.write_bytes(data)
            downloaded += 1
        entries.append(
            {
                "url": BASE_URL + href,
                "filename": filename,
                "bytes": len(data),
                "sha256": sha256(data),
                "quarter": quarter,
                "year": year,
            }
        )
    for filename, reason in rejected:
        print(f"rejected: {filename} ({reason})", file=sys.stderr)
    if not entries:
        print("error: no valid workbooks downloaded or reused", file=sys.stderr)
        return 2
    write_manifest(entries)
    print(f"valid workbooks: {len(entries)} in {RAW_DIR.relative_to(ROOT)}")
    print(f"downloaded: {downloaded}, reused: {reused}, rejected: {len(rejected)}")
    return 0


def check():
    if not MANIFEST.exists():
        print(f"missing manifest: {MANIFEST}", file=sys.stderr)
        return 2
    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))["workbooks"]
    listed = {entry["filename"] for entry in entries}
    orphans = sorted(
        path.name for path in RAW_DIR.glob("*.xlsx") if path.name not in listed
    )
    drift = 0
    for entry in entries:
        path = RAW_DIR / entry["filename"]
        if not path.exists():
            print(f"drift: {entry['filename']} missing")
        elif path.stat().st_size != entry["bytes"]:
            print(f"drift: {entry['filename']} size {path.stat().st_size} != {entry['bytes']}")
        elif sha256(path.read_bytes()) != entry["sha256"]:
            print(f"drift: {entry['filename']} sha256 mismatch")
        else:
            continue
        drift += 1
    if drift:
        print(f"{drift} of {len(entries)} manifest entries drifted", file=sys.stderr)
    for name in orphans:
        print(f"orphan: {name} not in manifest")
    if drift or orphans:
        if orphans:
            print(f"{len(orphans)} workbook(s) in {RAW_DIR.name} not in manifest", file=sys.stderr)
        return 2
    print(f"OK: {len(entries)} workbooks verified against manifest")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify files against manifest")
    args = parser.parse_args()
    return check() if args.check else run()


if __name__ == "__main__":
    sys.exit(main())
