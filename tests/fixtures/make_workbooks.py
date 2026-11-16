"""Generate the committed synthetic workbooks in tests/fixtures/workbooks/.

Run once and commit the .xlsx files:

    python tests/fixtures/make_workbooks.py

The set carries the three source shapes the parser must survive: the standard
header (with the double-space "Grand  Larceny Auto" variant), a workbook whose
TOTAL disagrees with its components, and a workbook with no MURDER column.
Parks and boroughs never change between quarters so the exporter's continuous
quarter grid holds.
"""

import os
import re
import time
import zipfile
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

OUT = Path(__file__).resolve().parent / "workbooks"

# Regeneration is byte-identical: zip entry timestamps and the workbook's
# created/modified properties come from this fixed epoch (1980-01-01, the zip
# minimum), overridable with SOURCE_DATE_EPOCH like any reproducible build.
_FIXED_EPOCH = max(int(os.environ.get("SOURCE_DATE_EPOCH", "315532800")), 315532800)
_EPOCH = time.gmtime(_FIXED_EPOCH)[:6]
_FIXED_STAMP = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(_FIXED_EPOCH))

TITLE = "2nd QTR PARK CRIME REPORT"
HEADER_A = [
    "PARK", "BOROUGH", "SIZE (ACRES)", "CATEGORY", "Murder", "RAPE",
    "ROBBERY", "FELONY ASSAULT", "BURGLARY", "GRAND LARCENY",
    "Grand  Larceny Auto", "TOTAL",
]
HEADER_B = [*HEADER_A[:10], "GRAND LARCENY OF MOTOR VEHICLE", HEADER_A[11]]
HEADER_NO_MURDER = [name for name in HEADER_A if name != "Murder"]

WORKBOOKS = {
    "nyc-park-crime-stats-q1-2019.xlsx": (
        "Report covering the period Between Jan 1, 2019 and Mar 31, 2019",
        HEADER_A,
        [
            ["ALPHA PARK", "BRONX", 1.5, "ONE ACRE OR LARGER",
             1, 2, 3, 4, 5, 6, 7, 28],
            ["BETA PARK", "MANHATTAN", 0.5, "PLAYGROUND",
             0, 0, 0, 0, 0, 0, 0, 0],
            ["COMBO PARK", "BROOKLYN/QUEENS", 2.0, "ONE ACRE OR LARGER",
             1, 0, 1, 0, 1, 0, 1, 4],
        ],
    ),
    "nyc-park-crime-stats-q2-2019.xlsx": (
        "Report covering the period Between Apr 1, 2019 and Jun 30, 2019",
        HEADER_B,
        [
            ["ALPHA PARK", "BRONX", 1.5, "ONE ACRE OR LARGER",
             2, 1, 1, 1, 1, 1, 1, 8],
            ["BETA PARK", "MANHATTAN", 0.5, "PLAYGROUND",
             1, 1, 1, 1, 1, 1, 1, 7],
            # Components sum to 1; the recorded TOTAL is deliberately wrong.
            ["COMBO PARK", "BROOKLYN/QUEENS", 2.0, "ONE ACRE OR LARGER",
             1, 0, 0, 0, 0, 0, 0, 999],
        ],
    ),
    "nyc-park-crime-stats-q3-2019.xlsx": (
        "Report covering the period Between July 1, 2019 and Sep 30, 2019",
        HEADER_NO_MURDER,
        [
            ["ALPHA PARK", "BRONX", 1.5, "ONE ACRE OR LARGER",
             3, 2, 1, 4, 2, 1, 13],
            ["BETA PARK", "MANHATTAN", 0.5, "PLAYGROUND",
             0, 0, 0, 0, 0, 0, 0],
            ["COMBO PARK", "BROOKLYN/QUEENS", 2.0, "ONE ACRE OR LARGER",
             1, 1, 1, 1, 1, 1, 6],
        ],
    ),
}


def _normalise_archive(path):
    """Rewrite the saved zip with fixed timestamps and platform-independent
    metadata, so the same workbook content always yields the same bytes."""
    with zipfile.ZipFile(path) as archive:
        members = [(info.filename, archive.read(info)) for info in archive.infolist()]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members:
            if name == "docProps/core.xml":
                # openpyxl stamps `modified` with the wall clock during save.
                data = re.sub(
                    rb"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)",
                    rb"\g<1>" + _FIXED_STAMP.encode() + rb"\g<2>",
                    data,
                )
            info = zipfile.ZipInfo(name, _EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0o600 << 16
            archive.writestr(info, data)


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    for filename, (period, header, rows) in WORKBOOKS.items():
        workbook = Workbook()
        workbook.properties.created = datetime(*_EPOCH)
        sheet = workbook.active
        sheet.append([TITLE])
        sheet.append([period])
        sheet.append(header)
        for row in rows:
            sheet.append(row)
        total = [None] * (len(header) - 1) + [
            sum(row[-1] for row in rows)
        ]
        total[0] = "TOTAL"
        sheet.append(total)
        workbook.save(OUT / filename)
        _normalise_archive(OUT / filename)
        print(f"wrote {OUT / filename}")


if __name__ == "__main__":
    build()
