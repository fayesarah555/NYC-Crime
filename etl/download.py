"""Cache every published NYPD park-crime quarterly workbook under data/raw/.

Usage:
    python etl/download.py                 # download missing / changed workbooks
    python etl/download.py --force         # re-download everything
    python etl/download.py --allow-missing # record gaps, still exit 0
    python etl/download.py --check         # re-verify data/raw/manifest.json
    python etl/download.py --verify-lock   # verify data/manifest.lock.json

Requests retry 3x with exponential backoff on 429/5xx. A failed file is
recorded as a gap and the run continues; without --allow-missing any gap makes
the exit code non-zero. The hashes-only snapshot committed as
data/manifest.lock.json is what `make data-verify` checks.
"""

import argparse
import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

PAGE_URL = "https://www.nyc.gov/site/nypd/stats/crime-statistics/park-crime-stats.page"
BASE_URL = "https://www.nyc.gov"
HREF_RE = re.compile(
    r"/assets/nypd/downloads/excel/crime_statistics/park-crime/"
    r"nyc-park-crime-stats-q(\d)-(\d{4})\.xlsx"
)
QUARTER_RE = re.compile(r"nyc-park-crime-stats-q(\d)-(\d{4})\.xlsx$")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": PAGE_URL,
}
ZIP_MAGIC = b"PK\x03\x04"
WORKERS = 4
DELAY = 0.5  # seconds between request starts across the pool
RETRY = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"GET", "HEAD"}),
    raise_on_status=False,
)
ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
MANIFEST = RAW_DIR / "manifest.json"
LOCK_PATH = ROOT / "data" / "manifest.lock.json"
GAPS_CSV = ROOT / "outputs" / "tables" / "download_gaps.csv"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def quarter_label(year, quarter):
    return f"{year}Q{quarter}"


def quarter_grid(quarters):
    """Every (year, quarter) from the earliest to the latest, inclusive."""
    if not quarters:
        return []
    low, high = min(quarters), max(quarters)
    year, quarter = low
    grid = []
    while (year, quarter) <= high:
        grid.append((year, quarter))
        quarter += 1
        if quarter == 5:
            year, quarter = year + 1, 1
    return grid


def make_session():
    """A session that retries transient failures on every request."""
    session = requests.Session()
    session.headers.update(HEADERS)
    adapter = HTTPAdapter(max_retries=RETRY)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def discover(session=None):
    """Return [(href, quarter, year)] sorted by year then quarter."""
    response = (session or requests).get(PAGE_URL, timeout=60)
    response.raise_for_status()
    found = {
        match.group(0): (int(match.group(1)), int(match.group(2)))
        for match in HREF_RE.finditer(response.text)
    }
    return [
        (href, quarter, year)
        for href, (quarter, year) in sorted(
            found.items(), key=lambda item: (item[1][1], item[1][0])
        )
    ]


def load_manifest():
    if not MANIFEST.exists():
        return {}
    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))["workbooks"]
    return {entry["filename"]: entry for entry in entries}


def write_json(path, payload):
    """Write through a sibling temp file so a crash cannot truncate it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_manifest(entries):
    ordered = sorted(entries, key=lambda entry: (entry["year"], entry["quarter"]))
    write_json(MANIFEST, {"workbooks": ordered})


def write_lock(entries):
    """Hashes-only snapshot, safe to commit: no URLs, no absolute paths."""
    ordered = sorted(entries, key=lambda entry: (entry["year"], entry["quarter"]))
    write_json(
        LOCK_PATH,
        {
            "workbooks": [
                {
                    "filename": entry["filename"],
                    "bytes": entry["bytes"],
                    "sha256": entry["sha256"],
                    "quarter": entry["quarter"],
                    "year": entry["year"],
                }
                for entry in ordered
            ]
        },
    )


def fetch_one(session, href, previous, force=False, delay=DELAY):
    """Return (entry, status); raise on an unrecoverable problem.

    A 304 keeps the cached workbook; otherwise the payload is validated before
    it replaces the cached file.
    """
    filename = href.rsplit("/", 1)[-1]
    dest = RAW_DIR / filename
    match = QUARTER_RE.search(filename)
    if not match:
        raise ValueError(f"not a park-crime workbook name: {filename}")
    quarter, year = int(match.group(1)), int(match.group(2))
    prior = previous.get(filename, {})

    if not force and dest.exists() and prior.get("sha256") == sha256(dest.read_bytes()):
        return (
            {
                "url": BASE_URL + href,
                "filename": filename,
                "bytes": dest.stat().st_size,
                "sha256": prior["sha256"],
                "quarter": quarter,
                "year": year,
                "etag": prior.get("etag"),
                "last_modified": prior.get("last_modified"),
            },
            "reused",
        )

    conditional = {}
    if prior.get("etag"):
        conditional["If-None-Match"] = prior["etag"]
    if prior.get("last_modified"):
        conditional["If-Modified-Since"] = prior["last_modified"]
    time.sleep(delay)
    response = session.get(
        BASE_URL + href, headers=conditional or None, timeout=(15, 120)
    )
    if response.status_code == 304 and dest.exists():
        data = dest.read_bytes()
        status = "unchanged"
    else:
        response.raise_for_status()
        data = response.content
        if not data.startswith(ZIP_MAGIC):
            raise ValueError("payload is not a ZIP workbook")
        dest.write_bytes(data)
        status = "downloaded"
    return (
        {
            "url": BASE_URL + href,
            "filename": filename,
            "bytes": len(data),
            "sha256": sha256(data),
            "quarter": quarter,
            "year": year,
            "etag": response.headers.get("ETag") or prior.get("etag"),
            "last_modified": response.headers.get("Last-Modified")
            or prior.get("last_modified"),
        },
        status,
    )


def targets_from_page(session, previous):
    """Discovered links plus anything already in the manifest.

    The manifest union keeps the snapshot intact when the page briefly omits a
    workbook or cannot be reached at all.
    """
    try:
        discovered = discover(session)
    except requests.RequestException as exc:
        if not previous:
            raise
        print(f"warning: page discovery failed ({exc}); using the manifest", file=sys.stderr)
        discovered = []
    seen = {href for href, _, _ in discovered}
    for filename, entry in previous.items():
        href = entry["url"][len(BASE_URL):]
        if href not in seen:
            discovered.append((href, int(entry["quarter"]), int(entry["year"])))
    return sorted(discovered, key=lambda item: (item[2], item[1]))


def write_gaps(gaps):
    GAPS_CSV.parent.mkdir(parents=True, exist_ok=True)
    lines = ["quarter,filename,reason"]
    lines += [f"{label},{filename},{reason}" for label, filename, reason in gaps]
    GAPS_CSV.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(force=False, allow_missing=False, session=None):
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    session = session or make_session()
    previous = load_manifest()
    try:
        targets = targets_from_page(session, previous)
    except requests.RequestException as exc:
        print(f"error: cannot discover workbooks and no manifest to fall back "
              f"on ({exc})", file=sys.stderr)
        return 2
    if not targets:
        print("error: no park-crime links found and no manifest to fall back on",
              file=sys.stderr)
        return 2

    entries, failures = [], []
    counts = {"downloaded": 0, "reused": 0, "unchanged": 0}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {
            pool.submit(fetch_one, session, href, previous, force): (href, quarter, year)
            for href, quarter, year in targets
        }
        for future in as_completed(futures):
            href, quarter, year = futures[future]
            filename = href.rsplit("/", 1)[-1]
            try:
                entry, status = future.result()
            except Exception as exc:  # one failed file never aborts the run
                failures.append((filename, str(exc)))
                print(f"rejected: {filename} ({exc})", file=sys.stderr)
                continue
            entries.append(entry)
            counts[status] += 1
            write_manifest(entries)  # incremental: a crash keeps the progress

    have = {(entry["year"], entry["quarter"]) for entry in entries}
    grid = quarter_grid([(year, quarter) for _, quarter, year in targets])
    failed = {name: reason for name, reason in failures}
    gaps = []
    for year, quarter in grid:
        if (year, quarter) in have:
            continue
        label = quarter_label(year, quarter)
        filename = f"nyc-park-crime-stats-q{quarter}-{year}.xlsx"
        reason = "download_failed" if filename in failed else "not_published"
        gaps.append((label, filename, reason))

    print(
        f"valid workbooks: {len(entries)} in {RAW_DIR.relative_to(ROOT)}"
        f" (downloaded {counts['downloaded']}, reused {counts['reused']},"
        f" unchanged {counts['unchanged']}, failed {len(failures)})"
    )
    if not entries:
        print("error: no valid workbooks downloaded or reused", file=sys.stderr)
        return 2
    if gaps:
        write_gaps(gaps)
        print(
            f"{len(gaps)} missing quarter(s) -> {GAPS_CSV.relative_to(ROOT)}",
            file=sys.stderr,
        )
        if not allow_missing:
            print(
                "error: coverage gaps; rerun with --allow-missing to accept them",
                file=sys.stderr,
            )
            return 1
    elif allow_missing:
        write_gaps([])  # never leave a stale gap list behind
    write_lock(entries)
    return 0


def verify_entries(entries, raw_dir, label):
    """Shared drift check for the raw manifest and the committed lock."""
    listed = {entry["filename"] for entry in entries}
    on_disk = {path.name for path in raw_dir.glob("*.xlsx")}
    drift = 0
    for entry in entries:
        path = raw_dir / entry["filename"]
        if not path.exists():
            print(f"drift: {entry['filename']} missing")
        elif path.stat().st_size != entry["bytes"]:
            print(f"drift: {entry['filename']} size {path.stat().st_size} != {entry['bytes']}")
        elif sha256(path.read_bytes()) != entry["sha256"]:
            print(f"drift: {entry['filename']} sha256 mismatch")
        else:
            continue
        drift += 1
    orphans = sorted(on_disk - listed)
    for name in orphans:
        print(f"orphan: {name} not in {label}")
    if drift or orphans:
        if drift:
            print(f"{drift} of {len(entries)} {label} entries drifted", file=sys.stderr)
        if orphans:
            print(f"{len(orphans)} workbook(s) in {raw_dir.name} not in {label}", file=sys.stderr)
        return 2
    print(f"OK: {len(entries)} workbooks verified against {label}")
    return 0


def check():
    if not MANIFEST.exists():
        print(f"missing manifest: {MANIFEST}", file=sys.stderr)
        return 2
    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))["workbooks"]
    return verify_entries(entries, RAW_DIR, "manifest")


def verify_lock():
    if not LOCK_PATH.exists():
        print(f"missing lock: {LOCK_PATH}", file=sys.stderr)
        return 2
    entries = json.loads(LOCK_PATH.read_text(encoding="utf-8"))["workbooks"]
    return verify_entries(entries, RAW_DIR, "lock")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify files against manifest")
    parser.add_argument("--verify-lock", action="store_true", help="verify files against the committed lock")
    parser.add_argument("--force", action="store_true", help="re-download every workbook")
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="record missing quarters in outputs/tables/download_gaps.csv and exit 0",
    )
    args = parser.parse_args()
    if args.check:
        return check()
    if args.verify_lock:
        return verify_lock()
    return run(force=args.force, allow_missing=args.allow_missing)


if __name__ == "__main__":
    sys.exit(main())
