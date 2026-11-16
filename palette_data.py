"""One palette for the web dashboard, Streamlit and the matplotlib figures.

Colours follow Okabe–Ito (colour-blind safe). The exporter serialises this
module to `app/web/src/data/palette.json`, so the browser reads the same values
the Python side draws with instead of keeping a second table.
"""

# Order matters: it matches the canonical crime-type order used by the cube.
TYPE_PALETTE = [
    {"en": "MURDER", "fr": "Meurtre", "color": "#000000"},
    {"en": "RAPE", "fr": "Viol", "color": "#CC79A7"},
    {"en": "ROBBERY", "fr": "Vol qualifié", "color": "#D55E00"},
    {"en": "FELONY ASSAULT", "fr": "Agression", "color": "#E69F00"},
    {"en": "BURGLARY", "fr": "Cambriolage", "color": "#56B4E9"},
    {"en": "GRAND LARCENY", "fr": "Larcin", "color": "#0072B2"},
    {"en": "GRAND LARCENY AUTO", "fr": "Vol de véhicule", "color": "#009E73"},
]

CLUSTER_PALETTE = [
    "#0072B2",
    "#E69F00",
    "#009E73",
    "#CC79A7",
    "#56B4E9",
    "#D55E00",
]

NEUTRAL_COLOR = "#8C8C8C"


def type_colors():
    return {entry["en"]: entry["color"] for entry in TYPE_PALETTE}


def short_labels():
    return {entry["en"]: entry["fr"] for entry in TYPE_PALETTE}


def payload():
    return {
        "crime_types": [entry["en"] for entry in TYPE_PALETTE],
        "labels_fr": short_labels(),
        "colors": type_colors(),
        "clusters": CLUSTER_PALETTE,
        "neutral": NEUTRAL_COLOR,
        "source": "Okabe-Ito",
    }
