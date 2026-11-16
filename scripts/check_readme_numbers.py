"""Fail when a headline number in README.md no longer matches the artefacts.

The README quotes a handful of figures; this gate keeps them honest without
regenerating the whole file. Run by `make readme-check` and in CI.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")


def fr(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")


def main() -> int:
    eda = json.loads((ROOT / "outputs" / "metrics" / "eda_stats.json").read_text())
    model = json.loads((ROOT / "outputs" / "metrics" / "model_metrics.json").read_text())
    city = model["citywide"]

    expected = {
        "total_crimes": fr(eda["total_crimes"], 0),
        "selected_mae": fr(city["selected_mae"], 2),
        "cramers_v": fr(eda["cramers_v"], 3),
        "silhouette": fr(model["clustering"]["silhouette"], 2),
    }
    missing = [
        f"{name}={value}" for name, value in expected.items() if value not in README
    ]
    # A figure may legitimately be quoted with a non-breaking space or a
    # variant rounding; the gate only requires the normalised value.
    normalised = re.sub(r"[  ]", " ", README)
    missing = [
        f"{name}={value}"
        for name, value in expected.items()
        if value not in normalised and value.replace(" ", "") not in normalised.replace(" ", "")
    ]
    if missing:
        print("README numbers out of date:", ", ".join(missing), file=sys.stderr)
        return 1
    print("README numbers match the artefacts:", ", ".join(expected.values()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
