"""Génère presentation/nyc_crime_deck.pptx depuis les artefacts du projet.

Usage: python presentation/build_deck.py (ou make deck).

Les chiffres sont lus à la construction dans outputs/metrics/*.json,
outputs/tables/*.csv, data/warehouse.db, app/web/public/data/ et app/web/dist/ :
aucune valeur n'est saisie à la main dans ce script. Les notes de l'orateur
sont recopiées depuis presentation/script_oral.md (sections « ## Slide N »).
Les diapositives elles-mêmes ne portent ni timing ni prénom.
"""

from __future__ import annotations

import csv
import gzip
import json
import re
import sqlite3
import subprocess
import sys
from collections import Counter
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "presentation"
FIG_DIR = ROOT / "outputs" / "figures"
METRICS_DIR = ROOT / "outputs" / "metrics"
TABLES_DIR = ROOT / "outputs" / "tables"
WAREHOUSE_CSV = ROOT / "data" / "processed" / "park_crime_long.csv"
WAREHOUSE_DB = ROOT / "data" / "warehouse.db"
RAW_DIR = ROOT / "data" / "raw"
WEB_DATA_DIR = ROOT / "app" / "web" / "public" / "data"
WEB_DIST_DIR = ROOT / "app" / "web" / "dist" / "assets"
VERCEL_JSON = ROOT / "vercel.json"
SCRIPT_MD = OUT_DIR / "script_oral.md"
DECK = OUT_DIR / "nyc_crime_deck.pptx"
WEB_CAPTURE = ROOT / "docs" / "screenshots" / "web_dashboard.png"
SITE_URL = "nyc-crimes.vercel.app"
REPO_URL = "github.com/youcisla/NYC-Crime"

SLIDE_W, SLIDE_H = 13.333, 7.5
INK = RGBColor(0x1B, 0x2A, 0x41)
ACCENT = RGBColor(0xB0, 0x3A, 0x2E)
MUTED = RGBColor(0x5C, 0x64, 0x72)
LIGHT = RGBColor(0xF1, 0xF3, 0xF6)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
CODE_BG = RGBColor(0x1B, 0x2A, 0x41)
CODE_FG = RGBColor(0xE6, 0xEA, 0xF0)
GOOD = RGBColor(0x2E, 0x7D, 0x5B)


# --- Lecture des artefacts --------------------------------------------------


def read_rows(name):
    with (TABLES_DIR / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def seasonal_means():
    """Moyenne des totaux trimestriels par trimestre de l'année, lue dans l'entrepôt."""
    totals = {}
    with WAREHOUSE_CSV.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            label = row["quarter_label"]
            totals[label] = totals.get(label, 0) + int(row["count"])
    per_quarter = {}
    for label, total in totals.items():
        per_quarter.setdefault(label[-1], []).append(total)
    return {quarter: sum(values) / len(values) for quarter, values in per_quarter.items()}


def warehouse_counts():
    connection = sqlite3.connect(WAREHOUSE_DB)
    try:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("crimes_long", "parks")
        }
    finally:
        connection.close()


def collected_tests():
    """Nombre de tests pytest par fichier, via --collect-only (aucun test exécuté)."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    per_file = Counter(
        line.split("::", 1)[0].replace("\\", "/").rsplit("/", 1)[-1]
        for line in result.stdout.splitlines()
        if "::" in line
    )
    return per_file


def bundle_sizes():
    """Taille gzip (Ko) de chaque paquet JS de app/web/dist, ou {} sans build web."""
    sizes = {}
    if not WEB_DIST_DIR.exists():
        return sizes
    for path in WEB_DIST_DIR.glob("*.js"):
        name = re.sub(r"-[\w-]{8}$", "", path.stem)  # retire le hash Vite (8 caractères)
        sizes[name] = sizes.get(name, 0) + len(gzip.compress(path.read_bytes(), 9)) / 1024
    return sizes


def speaker_notes():
    """{numéro de slide: texte} depuis les sections « ## Slide N » du script oral."""
    if not SCRIPT_MD.exists():
        return {}
    notes, current, paragraphs = {}, None, []

    def flush():
        if current is not None:
            notes[current] = "\n\n".join(p for p in paragraphs if p).strip()

    for line in SCRIPT_MD.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^## Slide (\d+)\b", line)
        if match or line.startswith("## "):
            flush()
            current, paragraphs = (int(match.group(1)) if match else None), [""]
            continue
        if current is None:
            continue
        text = line.replace("**", "").strip()
        if line.startswith("> "):  # une ligne de citation = un paragraphe du speech
            paragraphs.extend([text[2:], ""])
        elif not text:
            paragraphs.append("")
        else:  # les lignes de régie repliées dans le Markdown forment un seul paragraphe
            paragraphs[-1] = f"{paragraphs[-1]} {text}".strip()
    flush()
    return notes


try:
    EDA = json.loads((METRICS_DIR / "eda_stats.json").read_text(encoding="utf-8"))
    MODEL = json.loads((METRICS_DIR / "model_metrics.json").read_text(encoding="utf-8"))
    CITY = MODEL["citywide"]
    CLUSTERS = MODEL["clustering"]
    GEO = {row["metric"]: row["value"] for row in read_rows("geo_coverage.csv")}
    GEO_FALSE_POSITIVES = [r for r in read_rows("geo_coverage.csv") if r["metric"] == "fuzzy_false_positive"]
    RATES = {row["borough"]: float(row["rate_per_100_acres"]) for row in read_rows("rate_by_borough.csv")}
    TOP_PARKS = read_rows("top_parks.csv")
    PROFILES = read_rows("cluster_profiles.csv")
    ANOMALIES = read_rows("source_anomalies.csv")
    SHARES = {(r["borough"], r["crime_type"]): float(r["share_pct"]) for r in read_rows("borough_type_share.csv")}
    SEASON = seasonal_means()
    WAREHOUSE = warehouse_counts()
    N_WORKBOOKS = len(list(RAW_DIR.glob("*.xlsx")))
except FileNotFoundError as exc:
    print(
        f"Artefact manquant : {exc.filename}\n"
        "Construisez d'abord la chaîne de données puis le deck :\n"
        "  make all   (ou make data warehouse geo eda model)\n"
        "  make deck",
        file=sys.stderr,
    )
    raise SystemExit(2)

TESTS = collected_tests()
BUNDLE = bundle_sizes()
NOTES = speaker_notes()
WEB_JSON = {path.name: path.stat().st_size for path in sorted(WEB_DATA_DIR.glob("*.json"))}


def fr(value, digits=0):
    """1245.5 -> « 1 245,5 » (séparateurs français)."""
    return f"{float(value):,.{digits}f}".replace(",", " ").replace(".", ",")


def workbook_quarter(name):
    """'nyc-park-crime-stats-q4-2025.xlsx' -> '2025Q4'."""
    quarter, year = re.search(r"q(\d)-(\d{4})", name).groups()
    return f"{year}Q{quarter}"


def park_name(name):
    """'RANDALL'S ISLAND PARK' -> 'Randall's Island Park' (title() capitaliserait le S)."""
    return re.sub(r"'S\b", "'s", name.title())


def signed(value, digits=2):
    text = fr(abs(value), digits)
    return f"+{text}" if value >= 0 else f"−{text}"


# --- Primitives de mise en page --------------------------------------------


def style_run(run, size, color=INK, bold=False, italic=False, font="Calibri", strike=False):
    face = run.font
    face.size = Pt(size)
    face.bold = bold
    face.italic = italic
    face.color.rgb = color
    face.name = font
    if strike:
        run._r.get_or_add_rPr().set("strike", "sngStrike")


def add_text(slide, x, y, w, h, text, size=16, color=INK, bold=False, italic=False,
             align=PP_ALIGN.LEFT, font="Calibri", strike=False, anchor=None):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = box.text_frame
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = 0
    frame.margin_top = frame.margin_bottom = 0
    if anchor is not None:
        frame.vertical_anchor = anchor
    for position, line in enumerate(text.split("\n")):
        paragraph = frame.paragraphs[0] if position == 0 else frame.add_paragraph()
        paragraph.alignment = align
        run = paragraph.add_run()
        run.text = line
        style_run(run, size, color, bold, italic, font, strike)
    return box


def add_bullets(slide, x, y, w, h, items, size=16, space_after=8, color=INK):
    """items: str ou (amorce en gras, reste)."""
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = box.text_frame
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = 0
    frame.margin_top = frame.margin_bottom = 0
    for position, item in enumerate(items):
        paragraph = frame.paragraphs[0] if position == 0 else frame.add_paragraph()
        paragraph.space_after = Pt(space_after)
        lead, rest = item if isinstance(item, tuple) else ("", item)
        style_run(add_run(paragraph, "•  "), size, ACCENT, bold=True)
        if lead:
            style_run(add_run(paragraph, lead), size, color, bold=True)
        style_run(add_run(paragraph, rest), size, color)
    return box


def add_run(paragraph, text):
    run = paragraph.add_run()
    run.text = text
    return run


def rect(slide, x, y, w, h, fill=LIGHT, line=None, shape=MSO_SHAPE.ROUNDED_RECTANGLE):
    box = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    box.fill.solid()
    box.fill.fore_color.rgb = fill
    if line is None:
        box.line.fill.background()
    else:
        box.line.color.rgb = line
        box.line.width = Pt(0.75)
    box.shadow.inherit = False
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        box.adjustments[0] = 0.08
    return box


def labelled_box(slide, x, y, w, h, title, detail="", fill=LIGHT, line=ACCENT,
                 title_size=14, detail_size=10, title_color=INK):
    box = rect(slide, x, y, w, h, fill, line)
    frame = box.text_frame
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = Inches(0.08)
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    head = frame.paragraphs[0]
    head.alignment = PP_ALIGN.CENTER
    style_run(add_run(head, title), title_size, title_color, bold=True)
    if detail:
        body = frame.add_paragraph()
        body.alignment = PP_ALIGN.CENTER
        style_run(add_run(body, detail), detail_size, MUTED, font="Consolas")
    return box


def arrow(slide, x, y, w, h=0.2, down=False):
    shape = MSO_SHAPE.DOWN_ARROW if down else MSO_SHAPE.RIGHT_ARROW
    item = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    item.fill.solid()
    item.fill.fore_color.rgb = ACCENT
    item.line.fill.background()
    item.shadow.inherit = False
    return item


def flow(slide, stages, left, top, width, height, title_size=13, detail_size=9, gap=0.3):
    box_w = (width - gap * (len(stages) - 1)) / len(stages)
    for position, (name, detail) in enumerate(stages):
        x = left + position * (box_w + gap)
        labelled_box(slide, x, top, box_w, height, name, detail,
                     title_size=title_size, detail_size=detail_size)
        if position < len(stages) - 1:
            arrow(slide, x + box_w + 0.04, top + height / 2 - 0.1, gap - 0.08)


def code_box(slide, x, y, w, h, code, size=11):
    box = rect(slide, x, y, w, h, CODE_BG)
    frame = box.text_frame
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = Inches(0.18)
    frame.margin_top = frame.margin_bottom = Inches(0.12)
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    for position, line in enumerate(code.split("\n")):
        paragraph = frame.paragraphs[0] if position == 0 else frame.add_paragraph()
        paragraph.alignment = PP_ALIGN.LEFT
        style_run(add_run(paragraph, line), size, CODE_FG, font="Consolas")
    return box


def stat(slide, x, y, w, value, label, value_size=30, color=ACCENT, label_size=12):
    add_text(slide, x, y, w, 0.6, value, value_size, color, bold=True)
    add_text(slide, x, y + value_size / 72 + 0.12, w, 0.6, label, label_size, MUTED)


def add_table(slide, x, y, w, rows, col_widths, size=12, row_h=0.36, bold_rows=(), accent_rows=()):
    shape = slide.shapes.add_table(len(rows), len(rows[0]), Inches(x), Inches(y),
                                   Inches(w), Inches(row_h * len(rows)))
    table = shape.table
    for index, width in enumerate(col_widths):
        table.columns[index].width = Inches(width)
    for r, row in enumerate(rows):
        table.rows[r].height = Inches(row_h)
        for c, value in enumerate(row):
            cell = table.cell(r, c)
            cell.fill.solid()
            cell.fill.fore_color.rgb = INK if r == 0 else (LIGHT if r % 2 else WHITE)
            cell.margin_left = cell.margin_right = Inches(0.08)
            cell.margin_top = cell.margin_bottom = Inches(0.03)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            frame = cell.text_frame
            frame.word_wrap = True
            paragraph = frame.paragraphs[0]
            paragraph.alignment = PP_ALIGN.LEFT if (c == 0 or len(row) == 2) else PP_ALIGN.RIGHT
            color = WHITE if r == 0 else (ACCENT if r in accent_rows else INK)
            style_run(add_run(paragraph, str(value)), size, color,
                      bold=(r == 0 or r in bold_rows or r in accent_rows))
    return table


def place_picture(slide, image, x, y, w, h):
    """Insère une image centrée dans la boîte (x, y, w, h), proportions conservées."""
    pic = slide.shapes.add_picture(str(image), 0, 0)
    scale = min(w * 914400 / pic.width, h * 914400 / pic.height)
    pic.width = int(pic.width * scale)
    pic.height = int(pic.height * scale)
    pic.left = int(Inches(x) + (Inches(w) - pic.width) / 2)
    pic.top = int(Inches(y) + (Inches(h) - pic.height) / 2)
    return pic


def source_line(slide, text):
    add_text(slide, 0.75, 6.72, 11.8, 0.25, text, 9, MUTED, italic=True)


# --- Cadre commun -------------------------------------------------------------


TOTAL_SLIDES = 23


def background(slide):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = WHITE


def header(slide, title, kicker):
    add_text(slide, 0.75, 0.36, 11.8, 0.3, kicker.upper(), 11, ACCENT, bold=True)
    add_text(slide, 0.75, 0.66, 11.8, 0.72, title, 27, INK, bold=True)
    rule = rect(slide, 0.78, 1.44, 1.1, 0.04, ACCENT, shape=MSO_SHAPE.RECTANGLE)
    return rule


def footer(slide, index):
    add_text(slide, 0.75, 7.06, 8.0, 0.25, "IPSSI · Module Open Data · Sujet 2", 9, MUTED)
    add_text(slide, 11.6, 7.06, 1.0, 0.25, f"{index} / {TOTAL_SLIDES}", 9, MUTED, align=PP_ALIGN.RIGHT)


def finish(slide, index):
    footer(slide, index)
    slide.notes_slide.notes_text_frame.text = NOTES.get(index, "")


def new_slide(prs, kicker, title):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    background(slide)
    header(slide, title, kicker)
    return slide


def top_bar(slide):
    rect(slide, 0, 0, SLIDE_W, 0.22, ACCENT, shape=MSO_SHAPE.RECTANGLE)


# --- Diapositives -------------------------------------------------------------


def s01_title(prs, index):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    background(slide)
    top_bar(slide)
    add_text(slide, 0.9, 1.7, 7.2, 0.4, "MODULE OPEN DATA · IPSSI · SUJET 2", 13, ACCENT, bold=True)
    add_text(slide, 0.9, 2.25, 7.2, 1.7, "Criminalité dans les parcs\nde New York", 42, INK, bold=True)
    add_text(slide, 0.9, 4.15, 7.0, 0.9,
             f"De {N_WORKBOOKS} classeurs Excel du NYPD à un tableau de bord "
             "public et reproductible", 20, MUTED)
    rect(slide, 0.93, 5.25, 1.4, 0.04, ACCENT, shape=MSO_SHAPE.RECTANGLE)
    add_text(slide, 0.9, 5.5, 7.0, 0.4, SITE_URL, 18, ACCENT, bold=True, font="Consolas")
    add_text(slide, 0.9, 6.0, 7.0, 0.4, "Novembre 2026", 14, MUTED)
    rect(slide, 8.35, 0.75, 4.35, 6.05, LIGHT)
    place_picture(slide, WEB_CAPTURE, 8.5, 0.9, 4.05, 5.75)
    finish(slide, index)


def s02_hook(prs, index):
    slide = new_slide(prs, "Accroche", "Le chiffre qui mentait")
    year, prev = EDA["latest_complete_year"], EDA["previous_year"]
    rect(slide, 0.75, 1.85, 5.6, 3.3, LIGHT)
    add_text(slide, 1.05, 2.05, 5.0, 0.3, f"SOURCE BRUTE · {year} CONTRE {prev}", 12, MUTED, bold=True)
    add_text(slide, 1.05, 2.5, 5.0, 1.3, f"{signed(EDA['yoy_change_pct'])} %", 72, MUTED, bold=True, strike=True)
    add_text(slide, 1.05, 4.05, 5.0, 0.5,
             f"{fr(EDA['latest_complete_year_crimes'])} crimes contre {fr(EDA['previous_year_crimes'])}", 17, MUTED)
    arrow(slide, 6.5, 3.35, 0.55, 0.32)
    rect(slide, 7.2, 1.85, 5.4, 3.3, WHITE, ACCENT)
    add_text(slide, 7.5, 2.05, 4.8, 0.3, "À PÉRIMÈTRE CONSTANT", 12, ACCENT, bold=True)
    add_text(slide, 7.5, 2.5, 4.8, 1.3, f"{signed(EDA['yoy_excluding_new_parks_pct'])} %", 72, ACCENT, bold=True)
    add_text(slide, 7.5, 4.05, 4.8, 0.5,
             f"{fr(EDA['latest_complete_year_excluding_new_parks_crimes'])} crimes contre "
             f"{fr(EDA['previous_year_crimes'])}", 17, INK)
    park = EDA["new_parks"][0].title()
    add_text(slide, 0.75, 5.5, 11.85, 0.9,
             f"{park} n'apparaît dans les classeurs du NYPD qu'à partir de {year}Q1 : "
             f"+{fr(EDA['new_parks_latest_year_crimes'])} crimes « nouveaux » qui ne sont "
             "que des crimes enfin comptés.", 19, INK, italic=True)
    source_line(slide, "Source : outputs/metrics/eda_stats.json (yoy_change_pct, yoy_excluding_new_parks_pct)")
    finish(slide, index)


def s03_overview(prs, index):
    slide = new_slide(prs, "Problématique", "Trois questions, une chaîne de bout en bout")
    questions = [
        ("Mesurer", "Volume, saisonnalité, arrondissement × type de délit"),
        ("Localiser", "Quels parcs concentrent le risque, une fois la surface prise en compte"),
        ("Prévoir", "Un modèle bat-il une règle naïve, et avec quelle incertitude ?"),
    ]
    for position, (name, detail) in enumerate(questions):
        x = 0.75 + position * 4.0
        rect(slide, x, 1.8, 3.75, 1.55, LIGHT)
        add_text(slide, x + 0.25, 1.95, 3.3, 0.45, f"{position + 1}. {name}", 20, ACCENT, bold=True)
        add_text(slide, x + 0.25, 2.5, 3.3, 0.8, detail, 14, INK)
    flow(slide, [
        ("nyc.gov", "46 × .xlsx" if N_WORKBOOKS == 46 else f"{N_WORKBOOKS} × .xlsx"),
        ("Ingestion", "etl/download.py"),
        ("Entrepôt", "SQLite"),
        ("Analyse & modèles", "eda.py · model.py"),
        ("Export", "6 × JSON"),
        ("Site statique", "Vercel"),
    ], 0.75, 3.85, 11.85, 1.25, title_size=13, detail_size=10)
    rect(slide, 0.75, 5.55, 11.85, 0.85, WHITE, ACCENT)
    add_text(slide, 1.0, 5.68, 11.4, 0.6,
             "Une seule source de vérité : chaque chiffre affiché (site, slides, README) sort "
             "d'un fichier généré, jamais d'une saisie à la main.", 16, INK, bold=True,
             anchor=MSO_ANCHOR.MIDDLE)
    finish(slide, index)


def s04_ingestion(prs, index):
    slide = new_slide(prs, "Data · Ingestion", "Collecter sans jamais faire confiance")
    add_bullets(slide, 0.75, 1.8, 6.6, 2.0, [
        ("NYPD Park Crime Statistics. ", "Un classeur .xlsx par trimestre, 7 crimes majeurs par parc."),
        ("NYC Parks Properties. ", "API Socrata enfh-gkve : surface et géométrie des parcs."),
    ], size=15, space_after=10)
    add_text(slide, 0.75, 3.55, 6.6, 0.3, "ETL/DOWNLOAD.PY", 11, ACCENT, bold=True)
    add_bullets(slide, 0.75, 3.9, 6.6, 2.7, [
        "Découverte automatique des liens par regex sur la page nyc.gov",
        "Signature ZIP (PK\\x03\\x04) contrôlée : une page d'erreur HTML ne passe pas pour un classeur",
        "Empreinte sha256 par fichier dans data/raw/manifest.json : une relance ne retélécharge que ce qui a changé",
        "--check détecte toute dérive entre le disque et le manifeste",
    ], size=14, space_after=7)
    rect(slide, 7.75, 1.8, 4.85, 2.35, LIGHT)
    stat(slide, 8.05, 1.95, 4.3, f"{N_WORKBOOKS} classeurs", f"{EDA['first_quarter']} → {EDA['last_quarter']}, tous vérifiés", 32)
    add_text(slide, 8.05, 3.3, 4.3, 0.7,
             "2026Q3 et 2026Q4 : erreur 404, pas encore publiés → rejetés et signalés", 12, INK)
    code_box(slide, 7.75, 4.4, 4.85, 1.35,
             "if not data.startswith(ZIP_MAGIC):\n"
             "    rejected.append(\n"
             "        (filename, \"payload is not a ZIP workbook\"))", 11)
    source_line(slide, "Source : etl/download.py · data/raw/manifest.json")
    finish(slide, index)


def s05_parsing(prs, index):
    slide = new_slide(prs, "Data · Nettoyage", f"{N_WORKBOOKS} classeurs hétérogènes, un format long unique")
    add_text(slide, 0.75, 1.8, 6.4, 0.3, "ETL/PARSE.PY · OPENPYXL + PANDAS", 11, ACCENT, bold=True)
    add_bullets(slide, 0.75, 2.15, 6.4, 2.4, [
        "Ligne d'en-tête recherchée dans chaque feuille : sa position varie selon les années",
        "En-têtes normalisés : GRAND LARCENY OF MOTOR VEHICLE et GRAND LARCENY AUTO → une seule colonne",
        "Période lue dans le texte « Between Jan 1, 2025 and Mar 31, 2025 »",
    ], size=14, space_after=7)
    anomaly = ANOMALIES[0] if ANOMALIES else None
    rect(slide, 0.75, 4.45, 6.4, 1.95, WHITE, ACCENT)
    add_text(slide, 1.0, 4.6, 5.9, 0.3, "VÉRIFICATION D'INTÉGRITÉ : TOTAL PUBLIÉ = SOMME DES 7 TYPES", 11, ACCENT, bold=True)
    if anomaly:
        add_text(slide, 1.0, 5.0, 5.9, 1.3,
                 f"{len(ANOMALIES)} violation : {anomaly['park'].title()}, "
                 f"{workbook_quarter(anomaly['workbook'])} : TOTAL "
                 f"{anomaly['total_recorded']} contre somme {anomaly['sum_computed']}.\n"
                 "Ligne exclue et journalisée dans source_anomalies.csv ; "
                 "par défaut, le parseur s'arrête et nomme la ligne.", 14, INK)
    labelled_box(slide, 7.6, 1.85, 5.0, 1.15, "Format large (source)",
                 "PARK | BOROUGH | MURDER | RAPE | … | TOTAL", title_size=13, detail_size=10)
    arrow(slide, 9.95, 3.08, 0.3, 0.4, down=True)
    labelled_box(slide, 7.6, 3.55, 5.0, 1.15, "Format long (entrepôt)",
                 "quarter_label | park | crime_type | count", title_size=13, detail_size=10)
    source_rows = EDA["rows_total"] // 7 + len(ANOMALIES)
    stat(slide, 7.6, 4.95, 2.4, fr(source_rows), "lignes source", 24)
    stat(slide, 10.1, 4.95, 2.5, fr(EDA["rows_total"]), f"lignes longues, {fr(EDA['share_zero_rows_pct'], 0)} % de zéros conservés", 24)
    source_line(slide, "Source : etl/parse.py · outputs/tables/source_anomalies.csv · eda_stats.json")
    finish(slide, index)


def s06_geo(prs, index):
    slide = new_slide(prs, "Data · Géolocalisation & variables", "Relier deux sources, construire les variables")
    add_text(slide, 0.75, 1.8, 6.8, 0.3, "ETL/GEO.PY · RAPPROCHEMENT EN TROIS NIVEAUX, MÊME ARRONDISSEMENT", 11, ACCENT, bold=True)
    for position, (name, detail) in enumerate([
        ("1", "Nom exact signname"),
        ("2", "Nom exact name311"),
        ("3", "Correspondance floue difflib, seuil 0,88"),
    ]):
        y = 2.2 + position * 0.62
        labelled_box(slide, 0.75, y, 0.5, 0.5, name, title_size=14, fill=ACCENT, title_color=WHITE)
        add_text(slide, 1.45, y + 0.1, 6.0, 0.4, detail, 15, INK)
    add_bullets(slide, 0.75, 4.2, 6.8, 1.0, [
        ("representative_point() ", "(shapely) : point toujours à l'intérieur du polygone, contrairement au centroïde."),
    ], size=14)
    rect(slide, 7.95, 1.8, 4.65, 2.75, LIGHT)
    stat(slide, 8.25, 1.95, 4.1,
         f"{fr(GEO['matched_parks'])} / {fr(GEO['parks'])}",
         f"parcs géolocalisés ({fr(float(GEO['unweighted_coverage']) * 100, 1)} %)", 30)
    add_text(slide, 8.25, 3.25, 4.1, 1.2,
             f"{fr(float(GEO['weighted_coverage']) * 100, 1)} % pondéré par le volume de crimes\n"
             f"{len(GEO_FALSE_POSITIVES)} faux positifs audités et assumés (geo_false_positives.csv)", 13, INK)
    add_text(slide, 0.75, 5.0, 11.8, 0.3, "VARIABLES CONSTRUITES", 11, ACCENT, bold=True)
    code_box(slide, 0.75, 5.35, 11.85, 1.2,
             "taux_100_acres = Σ crimes / Σ acres (parcs distincts) × 100\n"
             "typologie      = [7 parts de délit, log1p(total), log1p(acres)] → StandardScaler", 12)
    finish(slide, index)


def s07_pitfalls(prs, index):
    slide = new_slide(prs, "Data · Qualité", "Quatre pièges de la source, traités explicitement")
    year = EDA["latest_complete_year"]
    no_coords = 100 - float(GEO["unweighted_coverage"]) * 100
    cards = [
        ("Couverture mouvante",
         f"{EDA['new_parks'][0].title()} seulement à partir de {year}Q1 → toute comparaison "
         "annuelle est donnée avec et sans ce parc (coverage_gaps.csv)."),
        ("Trimestre manquant",
         f"{EDA['missing_quarter']} absent → interpolé linéairement pour le modèle, "
         "jamais traité comme un zéro."),
        ("Total incohérent",
         f"{ANOMALIES[0]['park'].title() if ANOMALIES else 'Aucune ligne'} : TOTAL ≠ somme "
         "→ ligne exclue et journalisée (source_anomalies.csv)."),
        ("Géolocalisation partielle",
         f"{fr(no_coords, 1)} % des parcs sans coordonnées → signalé dans l'interface, pas masqué."),
    ]
    for position, (name, detail) in enumerate(cards):
        x = 0.75 + (position % 2) * 6.0
        y = 1.85 + (position // 2) * 2.35
        rect(slide, x, y, 5.85, 2.15, LIGHT)
        rect(slide, x, y, 0.09, 2.15, ACCENT, shape=MSO_SHAPE.RECTANGLE)
        add_text(slide, x + 0.35, y + 0.22, 5.3, 0.4, name, 19, ACCENT, bold=True)
        add_text(slide, x + 0.35, y + 0.8, 5.25, 1.25, detail, 15, INK)
    source_line(slide, "Aucun de ces choix n'est silencieux : chacun a sa table dans outputs/tables/.")
    finish(slide, index)


def s08_trend(prs, index):
    slide = new_slide(prs, "Résultats · Mesurer", "Une tendance, un rythme saisonnier")
    place_picture(slide, FIG_DIR / "fig01_quarterly_trend.png", 0.75, 1.75, 7.9, 4.85)
    stat(slide, 9.0, 1.8, 3.6, fr(EDA["total_crimes"]), f"crimes majeurs déclarés, {EDA['first_quarter']} → {EDA['last_quarter']}", 30)
    stat(slide, 9.0, 2.95, 3.6, f"{EDA['peak_quarter']} · {fr(EDA['peak_quarter_crimes'])}", "pic trimestriel", 24)
    stat(slide, 9.0, 3.95, 3.6, f"× {fr(SEASON['3'] / SEASON['1'], 1)}",
         f"été contre hiver : {fr(SEASON['3'])} crimes au T3 contre {fr(SEASON['1'])} au T1", 24)
    place_picture(slide, FIG_DIR / "fig02_seasonality.png", 9.0, 5.05, 3.6, 1.6)
    source_line(slide, "Marche de 2025Q1 : effet de couverture (Central Park), pas une hausse réelle.")
    finish(slide, index)


def s09_locate(prs, index):
    slide = new_slide(prs, "Résultats · Localiser", "Le volume ment, la surface rectifie")
    add_text(slide, 0.75, 1.75, 5.4, 0.3, "TOP PARCS EN VOLUME", 11, ACCENT, bold=True)
    rows = [["Parc", "Arrond.", "Crimes"]] + [
        [park_name(p["park"]), p["borough"].title(), fr(int(p["total"]))] for p in TOP_PARKS[:5]
    ]
    add_table(slide, 0.75, 2.1, 5.6, rows, [3.2, 1.35, 1.05], size=12, row_h=0.4)
    add_text(slide, 6.75, 1.75, 5.9, 0.3, "CRIMES POUR 100 ACRES", 11, ACCENT, bold=True)
    place_picture(slide, FIG_DIR / "fig05_rate_per_100acres.png", 6.75, 2.1, 5.85, 2.75)
    rect(slide, 0.75, 4.75, 5.6, 1.5, LIGHT)
    stat(slide, 1.0, 4.85, 5.2,
         f"× {fr(RATES['MANHATTAN'] / RATES['STATEN ISLAND'], 0)}",
         f"Manhattan {fr(RATES['MANHATTAN'], 1)} contre Staten Island {fr(RATES['STATEN ISLAND'], 1)} "
         "crimes / 100 acres : une exposition, pas un risque par visiteur", 28, label_size=12)
    rect(slide, 6.75, 5.05, 5.85, 1.2, WHITE, ACCENT)
    add_text(slide, 7.0, 5.17, 5.4, 1.0,
             f"Arrondissement × type : χ² = {fr(EDA['chi2_statistic'], 1)} ; ddl = {EDA['chi2_dof']} ; "
             f"p < 1e-200 ; V de Cramér = {fr(EDA['cramers_v'], 3)} → liaison réelle mais faible.\n"
             f"Manhattan : {fr(SHARES[('MANHATTAN', 'GRAND LARCENY')], 1)} % de vols simples · "
             f"Bronx : {fr(SHARES[('BRONX', 'ROBBERY')], 1)} % de vols qualifiés", 13, INK)
    finish(slide, index)


def s10_forecast(prs, index):
    slide = new_slide(prs, "Résultats · Prévoir", "Battre la règle naïve, honnêtement")
    window = CITY["backtest_window"]
    add_text(slide, 0.75, 1.75, 5.6, 0.3,
             f"BACKTEST SUR {CITY['backtest_quarters']} TRIMESTRES ({window[0]} → {window[-1]})", 11, ACCENT, bold=True)
    metrics = CITY["backtest_metrics"]
    names = {"seasonal_naive": "Saisonnier naïf (réf.)", "holt_winters": "Holt-Winters",
             "sarimax": "SARIMAX (1,1,1)(1,1,0)₄"}
    rows = [["Modèle", "MAE", "MAPE"]]
    order = ["seasonal_naive", "holt_winters", "sarimax"]
    for name in order:
        rows.append([names[name], fr(metrics[name]["mae"], 2), f"{fr(metrics[name]['mape'], 2)} %"])
    selected = order.index(CITY["selected_model"]) + 1
    add_table(slide, 0.75, 2.1, 5.6, rows, [3.3, 1.1, 1.2], size=13, row_h=0.45, accent_rows=(selected,))
    stat(slide, 0.75, 4.15, 2.7, f"−{fr(CITY['improvement_pct'], 1)} %", "d'erreur contre la référence", 30)
    first = CITY["forecast"][0]
    stat(slide, 3.55, 4.15, 2.8, fr(first["point"]),
         f"crimes prévus en {first['quarter_label']}, IC 95 % [{fr(first['lower'])} ; {fr(first['upper'])}]", 30)
    place_picture(slide, FIG_DIR / "fig07_forecast.png", 6.7, 1.75, 5.9, 3.55)
    rect(slide, 6.7, 5.45, 5.9, 0.85, WHITE, ACCENT)
    add_text(slide, 6.95, 5.56, 5.45, 0.7,
             "Réserves : modèle choisi sur la même fenêtre que celle qu'il rapporte, donc un "
             "avantage optimiste ; prévision gonflée par l'ajout de Central Park.", 13, INK)
    source_line(slide, "Source : outputs/metrics/model_metrics.json · analysis/model.py")
    finish(slide, index)


def cluster_name(profile, profiles):
    biggest = max(profiles, key=lambda p: float(p["mean_acres"]))
    violent = max(profiles, key=lambda p: float(p["share_murder"]))
    if profile is biggest:
        return "Grands parcs"
    if profile is violent:
        return "Sites violents"
    if profile["top_type"] == "grand_larceny":
        return "Proximité, vol simple"
    return "Proximité, vol qualifié"


def s11_clusters(prs, index):
    slide = new_slide(prs, "Résultats · Typologie", "Quatre profils de parcs")
    place_picture(slide, FIG_DIR / "fig08_clusters.png", 0.75, 1.75, 6.2, 4.3)
    add_text(slide, 0.75, 6.15, 6.2, 0.5,
             f"KMeans sur {fr(CLUSTERS['n_parks'])} parcs (au moins 5 crimes), k choisi par silhouette "
             f"entre 2 et 6 → k = {CLUSTERS['selected_k']}, silhouette {fr(CLUSTERS['silhouette'], 3)}",
             12, MUTED)
    ordered = sorted(PROFILES, key=lambda p: -int(p["total_crimes"]))
    for position, profile in enumerate(ordered):
        y = 1.8 + position * 1.2
        name = cluster_name(profile, PROFILES)
        if name == "Grands parcs":
            detail = (f"{profile['n_parks']} parcs · {fr(float(profile['mean_acres']))} acres en moyenne · "
                      f"{fr(int(profile['total_crimes']))} crimes ({fr(int(profile['total_crimes']) / EDA['total_crimes'] * 100, 0)} % du total)")
        elif name == "Sites violents":
            detail = (f"{profile['n_parks']} parcs · {fr(float(profile['share_murder']) * 100, 0)} % d'homicides · "
                      f"{fr(float(profile['share_felony_assault']) * 100, 0)} % d'agressions")
        elif name == "Proximité, vol simple":
            detail = (f"{profile['n_parks']} parcs · {fr(float(profile['share_grand_larceny']) * 100, 0)} % de vols simples")
        else:
            detail = (f"{profile['n_parks']} petits parcs ({fr(float(profile['mean_acres']), 1)} acres) · "
                      f"{fr(float(profile['share_robbery']) * 100, 0)} % de vols qualifiés")
        rect(slide, 7.3, y, 5.3, 1.05, LIGHT)
        rect(slide, 7.3, y, 0.09, 1.05, ACCENT, shape=MSO_SHAPE.RECTANGLE)
        add_text(slide, 7.6, y + 0.12, 4.9, 0.35, name, 16, ACCENT, bold=True)
        add_text(slide, 7.6, y + 0.5, 4.9, 0.5, detail, 12, INK)
    finish(slide, index)


def s12_architecture(prs, index):
    slide = new_slide(prs, "Architecture", "Une chaîne de lots, des artefacts comme contrats")
    layers = [
        ("Ingestion", "etl/download.py", "data/raw/*.xlsx + manifest.json"),
        ("Entrepôt", "etl/parse.py · etl/geo.py", "data/warehouse.db"),
        ("Calcul", "analysis/eda.py · analysis/model.py", "outputs/tables · metrics · figures"),
        ("Publication", "export/export_web.py", "app/web/public/data/*.json"),
        ("Interfaces", "app/web · app/app.py · build_deck.py", "site · Streamlit · diaporama"),
    ]
    for position, (name, code, output) in enumerate(layers):
        y = 1.8 + position * 0.95
        labelled_box(slide, 0.75, y, 1.9, 0.72, name, fill=ACCENT, line=ACCENT, title_color=WHITE, title_size=14)
        rect(slide, 2.8, y, 3.6, 0.72, LIGHT)
        add_text(slide, 2.95, y + 0.2, 3.4, 0.4, code, 11, INK, font="Consolas")
        arrow(slide, 6.5, y + 0.26, 0.4)
        rect(slide, 7.0, y, 3.0, 0.72, WHITE, MUTED)
        add_text(slide, 7.12, y + 0.2, 2.85, 0.4, output, 10, MUTED, font="Consolas")
    add_bullets(slide, 10.3, 1.8, 2.4, 4.6, [
        ("Contrat. ", "chaque couche ne lit que les fichiers de la précédente."),
        ("Orchestration. ", "Makefile : make all, make all-web."),
        ("Git. ", f"données brutes non versionnées ; seuls les JSON du site ({fr(sum(WEB_JSON.values()) / 1024)} Ko) sont commités."),
    ], size=13, space_after=12)
    finish(slide, index)


def s13_database(prs, index):
    slide = new_slide(prs, "Base de données", "Un entrepôt SQLite en format long")
    size_mb = WAREHOUSE_DB.stat().st_size / 1024 / 1024
    code_box(slide, 0.75, 1.8, 6.6, 3.6,
             f"-- data/warehouse.db  (~{fr(size_mb)} Mo)\n"
             f"crimes_long   -- {fr(WAREHOUSE['crimes_long'])} lignes\n"
             "  quarter_label, period_start, period_end,\n"
             "  park, borough, size_acres, category,\n"
             "  crime_type, count\n"
             f"parks         -- {fr(WAREHOUSE['parks'])} lignes\n"
             "  park, borough, lat, lon, acres_geo,\n"
             "  typecategory, match_type\n\n"
             "CREATE INDEX idx_crimes_quarter_park_crime\n"
             "  ON crimes_long (quarter_label, park, crime_type);", 12)
    add_text(slide, 7.75, 1.8, 4.85, 0.3, "POURQUOI SQLITE PLUTÔT QUE POSTGRESQL", 11, ACCENT, bold=True)
    add_bullets(slide, 7.75, 2.2, 4.85, 3.4, [
        ("Un fichier. ", "Aucun serveur à maintenir, portable, requêtable en SQL."),
        ("Lecture seule. ", "Données rafraîchies une fois par trimestre."),
        ("Idempotent. ", "to_sql(..., if_exists=\"replace\") : reconstruit à l'identique à chaque exécution."),
        ("Index composite. ", "aligné sur les agrégations trimestre × parc × type."),
    ], size=14, space_after=10)
    source_line(slide, "Source : etl/parse.py (write_outputs) · etl/geo.py")
    finish(slide, index)


def s14_contract(prs, index):
    slide = new_slide(prs, "Données servies", "Pas de serveur d'API : un contrat de données statique et vérifié")
    add_text(slide, 0.75, 1.8, 3.6, 0.3, "EXPORT/EXPORT_WEB.PY", 11, ACCENT, bold=True)
    rows = [["Fichier", "Ko"]] + [[name, fr(size / 1024, 1)] for name, size in WEB_JSON.items()]
    rows.append(["Total", fr(sum(WEB_JSON.values()) / 1024)])
    add_table(slide, 0.75, 2.15, 3.6, rows, [2.5, 1.1], size=12, row_h=0.38, bold_rows=(len(rows) - 1,))
    add_text(slide, 4.75, 1.8, 3.9, 0.3, "L'EXPORT ÉCHOUE SI…", 11, ACCENT, bold=True)
    add_bullets(slide, 4.75, 2.15, 3.9, 2.6, [
        "total d'un parc ≠ somme de ses types",
        "total citywide ≠ total de l'analyse",
        "poids > 2 Mo (MAX_PAYLOAD_BYTES)",
    ], size=14, space_after=10)
    add_text(slide, 4.75, 3.9, 3.9, 0.3, "CONTRAT TYPÉ CÔTÉ CLIENT", 11, ACCENT, bold=True)
    code_box(slide, 4.75, 4.25, 3.9, 1.6,
             "// app/web/src/lib/data.ts\n"
             "export interface Park {\n"
             "  park: string; lat: number | null;\n"
             "  total: number; cluster: number | null;\n"
             "  counts: Record<string, number>; }", 10)
    rows = [["", "API REST", "JSON statique"],
            ["Coût", "serveur", "0"],
            ["Latence", "requête + BDD", "CDN"],
            ["Surface d'attaque", "endpoints", "quasi nulle"],
            ["Disponibilité", "à surveiller", "fichiers"]]
    add_text(slide, 9.0, 1.8, 3.6, 0.3, "COMPARATIF", 11, ACCENT, bold=True)
    add_table(slide, 9.0, 2.15, 3.6, rows, [1.35, 1.1, 1.15], size=11, row_h=0.45)
    add_text(slide, 9.0, 4.55, 3.6, 1.3,
             "Les données changent une fois par trimestre : les calculer à chaque requête "
             "n'apporterait rien.", 13, INK, italic=True)
    finish(slide, index)


def s15_deploy(prs, index):
    slide = new_slide(prs, "Déploiement", "Du push Git à la production")
    config = json.loads(VERCEL_JSON.read_text(encoding="utf-8"))
    config.pop("$schema", None)
    code_box(slide, 0.75, 1.8, 5.6, 2.3, "// vercel.json\n" + json.dumps(config, indent=2), 12)
    flow(slide, [
        ("git push", "main"),
        ("npm ci", "package-lock"),
        ("tsc -b", "erreur = arrêt"),
        ("vite build", "app/web/dist"),
        ("CDN", SITE_URL),
    ], 0.75, 4.45, 11.85, 1.15, title_size=14, detail_size=9)
    add_bullets(slide, 6.75, 1.8, 5.85, 2.4, [
        ("Aucun Python au build. ", "Les JSON commités suffisent ; .vercelignore exclut /data et .venv."),
        ("Deux rythmes. ", "Chaîne data locale (make all), une fois par trimestre ; chaîne web à chaque commit."),
        ("Contributions ", "par pull request."),
    ], size=14, space_after=10)
    source_line(slide, "Source : vercel.json · .vercelignore · app/web/package.json")
    finish(slide, index)


def s16_quality(prs, index):
    slide = new_slide(prs, "Qualité", f"{sum(TESTS.values())} tests et des étapes qui refusent les données fausses")
    add_text(slide, 0.75, 1.8, 4.6, 0.3, "PYTEST · TESTS COLLECTÉS PAR FICHIER", 11, ACCENT, bold=True)
    rows = [["Fichier", "Tests"]] + [[name, str(count)] for name, count in sorted(TESTS.items())]
    add_table(slide, 0.75, 2.15, 4.6, rows, [3.6, 1.0], size=12, row_h=0.42)
    add_text(slide, 5.8, 1.8, 6.8, 0.3, "CASCADE D'ARRÊTS AUTOMATIQUES", 11, ACCENT, bold=True)
    gates = [("Signature ZIP", "download.py"), ("sha256", "manifest.json"),
             ("TOTAL = somme", "parse.py"), ("Vérifications", "export_web.py"),
             ("Typage TS", "tsc -b")]
    for position, (name, where) in enumerate(gates):
        x = 5.8 + position * 0.25
        y = 2.2 + position * 0.62
        labelled_box(slide, x, y, 3.6, 0.5, f"{name}  ·  {where}", title_size=12)
    add_bullets(slide, 5.8, 5.4, 6.8, 1.2, [
        ("Front. ", "Vitest + Testing Library (filters, FilterPanel, ForecastTab) ; lint oxlint."),
        ("Reproductible. ", "SEED = 42 ; après reconstruction complète, git status reste vide."),
    ], size=13, space_after=6)
    finish(slide, index)


def s17_security(prs, index):
    slide = new_slide(prs, "Sécurité & performance", "Le site statique comme choix de sécurité et de vitesse")
    add_text(slide, 0.75, 1.8, 5.6, 0.3, "SÉCURITÉ", 11, ACCENT, bold=True)
    add_bullets(slide, 0.75, 2.15, 5.6, 4.3, [
        "Aucun serveur, aucune base exposée, aucun secret (.env* dans .gitignore)",
        "Seul appel réseau à l'exécution : les tuiles OpenStreetMap",
        "Textes affichés via React (échappement automatique) : pas d'injection par la donnée",
        "Intégrité des entrées : signature ZIP + sha256",
        "Installation reproductible avec npm ci",
    ], size=14, space_after=9)
    add_text(slide, 6.75, 1.8, 5.85, 0.3, "PERFORMANCE", 11, ACCENT, bold=True)
    add_bullets(slide, 6.75, 2.15, 5.85, 1.3, [
        "Filtres recalculés côté client (useMemo), sans aller-retour réseau",
        "Bundle découpé par manualChunks (Vite), mis en cache séparément",
    ], size=14, space_after=8)
    wanted = [("react", "React"), ("leaflet", "Leaflet"), ("recharts", "Recharts"),
              ("astryx", "Astryx"), ("index", "Application + données")]
    if BUNDLE:
        rows = [["Paquet JS", "Ko gzip"]] + [
            [label, fr(BUNDLE[key])] for key, label in wanted if key in BUNDLE
        ]
        add_table(slide, 6.75, 3.5, 5.85, rows, [4.2, 1.65], size=12, row_h=0.36)
    else:
        add_text(slide, 6.75, 3.5, 5.85, 0.6, "Tailles de bundle : lancer make web-build puis make deck.", 12, MUTED, italic=True)
    add_text(slide, 6.75, 5.85, 5.85, 0.6,
             "Prochaine étape : charger les onglets Prévisions et Méthode à la demande.", 13, ACCENT, bold=True)
    finish(slide, index)


def s18_ui(prs, index):
    slide = new_slide(prs, "Interface", "Rendre la nuance visible")
    rect(slide, 0.75, 1.75, 4.3, 4.9, LIGHT)
    place_picture(slide, WEB_CAPTURE, 0.85, 1.85, 4.1, 4.7)
    chips = ["React 19", "TypeScript", "Vite 8", "Astryx", "Leaflet", "Recharts"]
    x = 5.45
    for chip in chips:
        width = 0.3 + 0.09 * len(chip)
        labelled_box(slide, x, 1.8, width, 0.42, chip, title_size=12, fill=WHITE)
        x += width + 0.1
    for position, (name, intent) in enumerate([("Exploration", "chercher"),
                                                ("Prévisions", "anticiper, avec l'incertitude"),
                                                ("Méthode", "vérifier sources et anomalies")]):
        x = 5.45 + position * 2.4
        rect(slide, x, 2.5, 2.25, 1.15, LIGHT)
        add_text(slide, x + 0.15, 2.6, 2.0, 0.35, name, 15, ACCENT, bold=True)
        add_text(slide, x + 0.15, 3.0, 2.0, 0.6, intent, 12, INK)
    add_bullets(slide, 5.45, 3.95, 7.15, 2.7, [
        ("4 indicateurs ", "recalculés à chaque filtre : crimes, parcs touchés, délit dominant, évolution."),
        ("Réserves ", "affichées là où l'on lit le chiffre, pas dans une page « À propos »."),
        ("Recherche ", "insensible aux accents et à la casse (normalisation NFKD)."),
        ("Accessibilité : ", "interface en français, y compris les libellés aria (fr-FR)."),
    ], size=14, space_after=9)
    finish(slide, index)


def s19_viz(prs, index):
    slide = new_slide(prs, "Visualisation", "Chaque encodage est un choix")
    add_bullets(slide, 0.75, 1.8, 6.6, 4.8, [
        ("Carte : ", "rayon = 2 + 4·√n, plafonné à 36 → l'aire suit le volume, sans exagérer les gros parcs."),
        ("Couleur : ", "délit dominant, ou profil de parc (interrupteur « Colorer par cluster »)."),
        ("Palette : ", "couleurs catégorielles du thème (--color-data-categorical-*), traduites en RGB pour le SVG (tokens.ts)."),
        ("Figures Python : ", "palette Okabe-Ito, lisible par les daltoniens."),
        ("Prévision : ", "intervalle à 95 % toujours affiché avec la valeur centrale."),
    ], size=15, space_after=12)
    rect(slide, 7.75, 1.8, 4.85, 4.8, LIGHT)
    add_text(slide, 8.0, 1.95, 4.4, 0.3, "RAYON ∝ √n : L'AIRE SUIT LE VOLUME", 11, ACCENT, bold=True)
    scale = 0.022  # pouces par unité de rayon Leaflet
    baseline = 4.9
    x = 8.15
    for n in (10, 40, 100):
        radius = min(36, 2 + 4 * n ** 0.5)
        diameter = 2 * radius * scale
        circle = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(baseline - diameter),
                                        Inches(diameter), Inches(diameter))
        circle.fill.solid()
        circle.fill.fore_color.rgb = ACCENT
        circle.line.fill.background()
        circle.shadow.inherit = False
        add_text(slide, x - 0.2, baseline + 0.15, diameter + 0.4, 0.3, f"n = {n}", 12, INK, bold=True, align=PP_ALIGN.CENTER)
        add_text(slide, x - 0.2, baseline + 0.45, diameter + 0.4, 0.3, f"r = {fr(radius, 1)}", 11, MUTED, align=PP_ALIGN.CENTER)
        x += diameter + 0.45
    add_text(slide, 8.0, 5.85, 4.4, 0.6, "n = 100 atteint le plafond (r = 36).", 11, MUTED, italic=True)
    source_line(slide, "Source : app/web/src/components/CrimeMap.tsx · app/web/src/lib/tokens.ts")
    finish(slide, index)


def s20_demo(prs, index):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    background(slide)
    top_bar(slide)
    add_text(slide, 0.9, 2.0, 11.5, 1.0, "Démonstration", 48, INK, bold=True)
    add_text(slide, 0.9, 3.2, 11.5, 0.5, SITE_URL, 24, ACCENT, bold=True, font="Consolas")
    flow(slide, [("Exploration", "filtres · carte · période"),
                 ("Prévisions", "backtest · intervalle 95 %"),
                 ("Méthode", "sources · anomalies")],
         0.9, 4.3, 11.5, 1.2, title_size=18, detail_size=12, gap=0.5)
    finish(slide, index)


def s21_limits(prs, index):
    slide = new_slide(prs, "Limites", "Limites & feuille de route")
    lower = min(point["lower"] for point in CITY["forecast"])
    rows = [
        ["Limite", "Prochaine étape"],
        ["Pas de fréquentation : un taux par acre n'est pas un risque par visiteur",
         "Croiser avec des données de fréquentation ou d'événements"],
        ["Plaintes déclarées, pas faits établis", "Croiser avec les données d'arrestations NYPD"],
        ["Modèle choisi sur sa propre fenêtre de test",
         "Validation glissante (rolling origin) sur une fenêtre tenue à part"],
        [f"Intervalle gaussien sur des comptages (borne basse {signed(lower, 1)})",
         "Tronquer à 0, ou modèle de Poisson / binomiale négative"],
        [f"{', '.join(b.title() for b in MODEL.get('skipped_boroughs', ['Staten Island', 'Brooklyn/Queens']))} hors prévision par arrondissement",
         "Modèle hiérarchique par arrondissement"],
        ["Pas de CI de tests ; dépendances Python non épinglées",
         "GitHub Actions (pytest + vitest) ; versions épinglées"],
    ]
    add_table(slide, 0.75, 1.85, 11.85, rows, [6.2, 5.65], size=13, row_h=0.66)
    finish(slide, index)


def s22_conclusion(prs, index):
    slide = new_slide(prs, "Conclusion", "Trois réponses, une méthode")
    answers = [
        ("Mesurer", f"{fr(EDA['zero_share_mean_pct'], 1)} %",
         f"des parcs sans crime un trimestre donné ; {fr(EDA['parks_ever_hit'])} touchés sur {fr(EDA['parks_total'])}"),
        ("Localiser", f"× {fr(RATES['MANHATTAN'] / RATES['STATEN ISLAND'], 0)}",
         f"Manhattan {fr(RATES['MANHATTAN'], 1)} contre Staten Island {fr(RATES['STATEN ISLAND'], 1)} crimes / 100 acres"),
        ("Prévoir", f"−{fr(CITY['improvement_pct'], 0)} %",
         f"d'erreur pour SARIMAX contre la règle naïve (MAE {fr(CITY['selected_mae'], 2)} contre {fr(CITY['baseline_mae'], 2)})"),
    ]
    for position, (name, value, detail) in enumerate(answers):
        x = 0.75 + position * 4.0
        rect(slide, x, 1.85, 3.75, 2.75, LIGHT)
        add_text(slide, x + 0.25, 2.0, 3.3, 0.35, name.upper(), 12, ACCENT, bold=True)
        add_text(slide, x + 0.25, 2.4, 3.3, 0.8, value, 40, INK, bold=True)
        add_text(slide, x + 0.25, 3.35, 3.3, 1.2, detail, 13, INK)
    rect(slide, 0.75, 4.95, 11.85, 1.55, WHITE, ACCENT)
    add_text(slide, 1.05, 5.1, 2.6, 0.6, f"{signed(EDA['yoy_change_pct'])} %", 30, MUTED, bold=True, strike=True)
    arrow(slide, 2.75, 5.32, 0.5, 0.25)
    add_text(slide, 3.45, 5.1, 2.6, 0.6, f"{signed(EDA['yoy_excluding_new_parks_pct'])} %", 30, ACCENT, bold=True)
    add_text(slide, 1.05, 5.85, 11.3, 0.5,
             "Une donnée ouverte n'est pas une donnée juste, sauf si la chaîne est conçue pour ça.",
             16, INK, italic=True)
    finish(slide, index)


def s23_questions(prs, index):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    background(slide)
    top_bar(slide)
    add_text(slide, 0.9, 2.0, 11.5, 1.0, "Questions", 48, INK, bold=True)
    add_text(slide, 0.9, 3.15, 11.5, 0.5, "Merci de votre attention.", 20, MUTED)
    add_bullets(slide, 0.9, 4.1, 11.5, 2.0, [
        ("Site : ", SITE_URL),
        ("Code : ", REPO_URL),
        ("Reproduire : ", "make all-web"),
    ], size=17, space_after=8)
    add_text(slide, 0.9, 6.3, 11.5, 0.4,
             "Données : © City of New York / NYPD, diffusées via NYC Open Data et nyc.gov.", 11, MUTED)
    finish(slide, index)


# --- Construction -----------------------------------------------------------


SLIDES = [
    s01_title, s02_hook, s03_overview, s04_ingestion, s05_parsing, s06_geo,
    s07_pitfalls, s08_trend, s09_locate, s10_forecast, s11_clusters,
    s12_architecture, s13_database, s14_contract, s15_deploy, s16_quality,
    s17_security, s18_ui, s19_viz, s20_demo, s21_limits, s22_conclusion,
    s23_questions,
]


def build():
    assert len(SLIDES) == TOTAL_SLIDES, len(SLIDES)
    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W)
    prs.slide_height = Inches(SLIDE_H)
    for index, builder in enumerate(SLIDES, start=1):
        builder(prs, index)
    prs.core_properties.title = "Criminalité dans les parcs de New York, IPSSI Open Data, sujet 2"
    prs.core_properties.author = "IPSSI, module Open Data"
    prs.core_properties.subject = "NYPD Park Crime Statistics"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    prs.save(DECK)
    missing = [i for i in range(1, TOTAL_SLIDES + 1) if not NOTES.get(i)]
    return DECK, len(prs.slides), missing


if __name__ == "__main__":
    path, count, missing = build()
    print(f"écrit : {path.relative_to(ROOT)} ({count} diapositives)")
    if missing:
        print(f"attention : pas de notes pour les slides {missing}", file=sys.stderr)
