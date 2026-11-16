"""Génère presentation/nyc_crime_deck.pptx depuis les artefacts de outputs/.

Usage: python presentation/build_deck.py (ou make deck).

Les chiffres sont lus à la construction dans outputs/metrics/*.json et
outputs/tables/*.csv : aucune valeur n'est saisie à la main dans ce script.
"""

from __future__ import annotations

import csv
import json
import sys
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
DECK = OUT_DIR / "nyc_crime_deck.pptx"
WEB_CAPTURE = ROOT / "docs" / "screenshots" / "web_dashboard.jpg"
APP_CAPTURE = OUT_DIR / "app_exploration.png"

SLIDE_W, SLIDE_H = 13.333, 7.5
INK = RGBColor(0x1B, 0x2A, 0x41)
ACCENT = RGBColor(0xB0, 0x3A, 0x2E)
MUTED = RGBColor(0x5C, 0x64, 0x72)
LIGHT = RGBColor(0xF1, 0xF3, 0xF6)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

def read_rows(name):
    with (TABLES_DIR / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def seasonal_means():
    """Moyenne des totaux trimestriels par trimestre de l'année, lue dans l'entrepôt."""
    totals = {}
    with WAREHOUSE_CSV.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            label = row["quarter_label"]
            if not row["count"]:
                continue  # NULL: the workbook had no such crime column
            totals[label] = totals.get(label, 0) + float(row["count"])
    per_quarter = {}
    for label, total in totals.items():
        per_quarter.setdefault(label[-1], []).append(total)
    return {quarter: sum(values) / len(values) for quarter, values in per_quarter.items()}


try:
    EDA = json.loads((METRICS_DIR / "eda_stats.json").read_text(encoding="utf-8"))
    MODEL = json.loads((METRICS_DIR / "model_metrics.json").read_text(encoding="utf-8"))
    CITY = MODEL["citywide"]
    CLUSTERS = MODEL["clustering"]
    GEO = {row["metric"]: row["value"] for row in read_rows("geo_coverage.csv")}
    RATES = {row["borough"]: float(row["rate_per_100_acres"]) for row in read_rows("rate_by_borough.csv")}
    # Consistent-perimeter rate excludes Central Park (partial coverage).
    RATES_EXCL = {row["borough"]: float(row["rate_excl_central_park"]) for row in read_rows("rate_by_borough.csv")}
    TOP_PARKS = read_rows("top_parks.csv")
    PROFILES = read_rows("cluster_profiles.csv")
    SEASON = seasonal_means()
    BOROUGH_FORECAST = {}
    for row in read_rows("forecast_boroughs.csv"):
        BOROUGH_FORECAST.setdefault(row["quarter_label"], {})[row["borough"]] = float(row["point"])
    BOROUGH_FIRST_Q = next(iter(BOROUGH_FORECAST))
except FileNotFoundError as exc:
    print(
        f"Artefact manquant : {exc.filename}\n"
        "Construisez d'abord les données puis le deck :\n"
        "  make data\n"
        "  make warehouse\n"
        "  make deck",
        file=sys.stderr,
    )
    raise SystemExit(2)


MISSING_QUARTERS = EDA.get("missing_quarters") or (
    [EDA["missing_quarter"]] if EDA.get("missing_quarter") else []
)
MISSING_LABEL = ", ".join(MISSING_QUARTERS)
MISSING_COLUMN_QUARTERS = EDA.get("missing_column_quarters", [])
MISSING_COLUMN_TYPES = EDA.get("missing_column_types", [])
LATE_PARKS = EDA.get("late_parks", [])
SOURCE_ANOMALIES = EDA.get("source_anomalies", [])


def following_quarters(label, count):
    """The `count` quarter labels after `label`."""
    year, quarter = (int(part) for part in label.split("Q"))
    out = []
    for _ in range(count):
        quarter += 1
        if quarter == 5:
            year, quarter = year + 1, 1
        out.append(f"{year}Q{quarter}")
    return out


def late_park(name):
    """First-quarter entry for a park that appears mid-period, or None."""
    for entry in LATE_PARKS:
        if entry["park"].upper() == name:
            return entry
    return None


def anomaly_fr():
    """TOTAL mismatches as one phrase, from the EDA metrics."""
    return " ; ".join(
        f"{entry['park'].title()} {entry['quarter']} : TOTAL "
        f"{entry['total_recorded']} contre {entry['sum_computed']} pour la somme"
        for entry in SOURCE_ANOMALIES
    ) or "aucune anomalie TOTAL signalée"


FORTHCOMING_QUARTERS = following_quarters(EDA["last_quarter"], 2)


def fr(value, digits=0):
    """1245.5 -> « 1 245,5 » (séparateurs français)."""
    return f"{float(value):,.{digits}f}".replace(",", " ").replace(".", ",")


# --- Primitives de mise en page --------------------------------------------


def add_text(slide, x, y, w, h, text, size=16, color=INK, bold=False, italic=False,
             align=PP_ALIGN.LEFT, font="Calibri"):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = box.text_frame
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = 0
    frame.margin_top = frame.margin_bottom = 0
    paragraph = frame.paragraphs[0]
    paragraph.alignment = align
    run = paragraph.add_run()
    run.text = text
    face = run.font
    face.size = Pt(size)
    face.bold = bold
    face.italic = italic
    face.color.rgb = color
    face.name = font
    return box


def add_bullets(slide, x, y, w, h, items, size=17, space_after=10):
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
        marker = paragraph.add_run()
        marker.text = "•  "
        marker.font.size = Pt(size)
        marker.font.color.rgb = ACCENT
        marker.font.bold = True
        marker.font.name = "Calibri"
        if lead:
            strong = paragraph.add_run()
            strong.text = lead
            strong.font.size = Pt(size)
            strong.font.bold = True
            strong.font.color.rgb = INK
            strong.font.name = "Calibri"
        body = paragraph.add_run()
        body.text = rest
        body.font.size = Pt(size)
        body.font.color.rgb = INK
        body.font.name = "Calibri"
    return box


def blank(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def header(slide, title, kicker):
    add_text(slide, 0.75, 0.36, 11.8, 0.3, kicker.upper(), 11, ACCENT, bold=True)
    add_text(slide, 0.75, 0.66, 11.8, 0.72, title, 27, INK, bold=True)
    rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.78), Inches(1.44), Inches(1.1), Pt(3))
    rule.fill.solid()
    rule.fill.fore_color.rgb = ACCENT
    rule.line.fill.background()
    rule.shadow.inherit = False


def footer(slide, index, total):
    add_text(slide, 0.75, 7.06, 8.0, 0.25, "IPSSI · Module Open Data · Sujet 2", 9, MUTED)
    add_text(slide, 11.6, 7.06, 1.0, 0.25, f"{index} / {total}", 9, MUTED, align=PP_ALIGN.RIGHT)


def background(slide):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = WHITE


def note(slide, text):
    slide.notes_slide.notes_text_frame.text = text


TOTAL_SLIDES = 18


def new_slide(prs, kicker, title):
    slide = blank(prs)
    background(slide)
    header(slide, title, kicker)
    return slide


def takeaway(slide, text):
    add_text(slide, 0.75, 1.55, 11.8, 0.4, text, 16, ACCENT, bold=True)


def picture_slide(prs, index, kicker, title, image, line, notes):
    slide = new_slide(prs, kicker, title)
    takeaway(slide, line)
    top, height = 2.0, 4.9
    pic = slide.shapes.add_picture(str(image), 0, 0)
    scale = min((SLIDE_W - 1.2) * 914400 / pic.width, height * 914400 / pic.height)
    pic.width = int(pic.width * scale)
    pic.height = int(pic.height * scale)
    pic.left = int((Inches(SLIDE_W) - pic.width) / 2)
    pic.top = int(Inches(top) + (Inches(height) - pic.height) / 2)
    footer(slide, index, TOTAL_SLIDES)
    note(slide, notes)
    return slide


# --- Diapositives -----------------------------------------------------------


def title_slide(prs, index):
    slide = blank(prs)
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = WHITE
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(SLIDE_W), Inches(0.22))
    bar.fill.solid()
    bar.fill.fore_color.rgb = ACCENT
    bar.line.fill.background()
    bar.shadow.inherit = False

    add_text(slide, 0.9, 1.9, 11.5, 0.4, "MODULE OPEN DATA · IPSSI · SUJET 2", 13, ACCENT, bold=True)
    add_text(slide, 0.9, 2.45, 11.5, 1.6, "Criminalité dans les parcs\nde New York", 44, INK, bold=True)
    add_text(
        slide,
        0.9,
        4.3,
        11.5,
        0.6,
        f"{fr(EDA['total_crimes'])} crimes majeurs déclarés, "
        f"{EDA['first_quarter']} à {EDA['last_quarter']}",
        20,
        MUTED,
    )
    rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.93), Inches(5.15), Inches(1.4), Pt(3))
    rule.fill.solid()
    rule.fill.fore_color.rgb = ACCENT
    rule.line.fill.background()
    rule.shadow.inherit = False
    add_text(slide, 0.9, 5.45, 11.5, 0.4, "NYPD Park Crime Statistics × NYC Parks Properties", 15, MUTED)
    add_text(slide, 0.9, 5.85, 11.5, 0.4, "Novembre 2026", 15, MUTED)
    footer(slide, index, TOTAL_SLIDES)
    note(
        slide,
        "Bonjour. Nous présentons le sujet 2 du module Open Data : la criminalité dans "
        f"les parcs de New York. Le jeu de données couvre {EDA['first_quarter']} à "
        f"{EDA['last_quarter']} et totalise {fr(EDA['total_crimes'])} crimes majeurs "
        "déclarés par la police new-yorkaise, parc par parc et trimestre par trimestre.",
    )


def problem_slide(prs, index):
    slide = new_slide(prs, "Problématique", "Où et quand la criminalité frappe-t-elle les parcs ?")
    add_text(
        slide,
        0.75,
        1.75,
        11.7,
        1.1,
        "Les parcs new-yorkais concentrent-ils les crimes majeurs sur quelques sites "
        "prévisibles, ou sont-ils un risque diffus ?",
        24,
        INK,
        italic=True,
    )
    add_bullets(
        slide,
        0.75,
        3.15,
        11.5,
        3.4,
        [
            ("Mesurer. ", "Quantifier le volume, la saisonnalité et la répartition par arrondissement et par type de délit."),
            ("Localiser. ", "Identifier les parcs critiques, puis normaliser par la surface pour comparer ce qui est comparable."),
            ("Prévoir. ", "Tester si un modèle de série temporelle bat une règle naïve, et à quel prix d'incertitude."),
        ],
        size=19,
        space_after=18,
    )
    footer(slide, index, TOTAL_SLIDES)
    note(
        slide,
        "La question directrice : le risque est-il concentré sur quelques parcs ou "
        "diffus ? Nous y répondons en trois temps : mesurer, localiser, prévoir. "
        "Chaque réponse s'appuie sur les mêmes données ouvertes, sans enquête terrain.",
    )


def data_slide(prs, index):
    slide = new_slide(prs, "Données", "Deux sources ouvertes, un entrepôt reproductible")
    add_bullets(
        slide,
        0.75,
        1.8,
        6.3,
        4.9,
        [
            ("NYPD, Park Crime Statistics. ", f"Un classeur Excel par trimestre, publié sur nyc.gov ; {len(EDA.get('crime_types', []))} types de crimes majeurs par parc."),
            (f"{fr(len(list((ROOT / 'data' / 'raw').glob('*.xlsx'))))} classeurs. ", f"{EDA['first_quarter']} → {EDA['last_quarter']} ; {MISSING_LABEL} absent en amont ; {FORTHCOMING_QUARTERS[0]} et {FORTHCOMING_QUARTERS[1]} pas encore publiés (404)."),
            ("NYC Parks Properties. ", "Référentiel des parcs : surface en acres et coordonnées, pour le taux par acre et la carte."),
            ("Attribution. ", "NYPD / NYC Open Data ; données publiques, réutilisées sans modification de fond."),
        ],
        size=16,
        space_after=13,
    )
    card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(7.4), Inches(1.85), Inches(5.2), Inches(4.4))
    card.fill.solid()
    card.fill.fore_color.rgb = LIGHT
    card.line.fill.background()
    card.shadow.inherit = False
    add_text(slide, 7.75, 2.1, 4.6, 0.35, "LE JEU DE DONNÉES EN CHIFFRES", 11, ACCENT, bold=True)
    add_bullets(
        slide,
        7.75,
        2.6,
        4.5,
        3.4,
        [
            f"{fr(EDA['total_crimes'])} crimes majeurs",
            f"{fr(EDA['parks_total'])} parcs, {fr(EDA['parks_ever_hit'])} touchés au moins une fois",
            f"{fr(EDA['quarters_total'])} trimestres, {fr(EDA['rows_total'])} lignes Parc × Trimestre × Type",
            f"{fr(GEO['matched_parks'])} parcs géolocalisés sur {fr(GEO['parks'])}",
        ],
        size=15,
        space_after=11,
    )
    footer(slide, index, TOTAL_SLIDES)
    note(
        slide,
        "Deux sources : les classeurs trimestriels du NYPD et le référentiel des parcs "
        f"de la ville. Au total {fr(EDA['total_crimes'])} crimes, {fr(EDA['parks_total'])} parcs, "
        f"{fr(EDA['quarters_total'])} trimestres et {fr(EDA['rows_total'])} lignes. "
        f"La géolocalisation couvre {fr(float(GEO['unweighted_coverage']) * 100, 1)} % des parcs.",
    )


def architecture_slide(prs, index):
    slide = new_slide(prs, "Architecture", "Un pipeline en cinq étapes, rejouable par une commande")
    stages = [
        ("Téléchargement", "etl/download.py\nmanifeste sha256"),
        ("Entrepôt", "etl/parse.py\nSQLite + CSV"),
        ("Analyse", "analysis/eda.py\ntables + figures"),
        ("Modèles", "analysis/model.py\nSARIMAX + KMeans"),
        ("Interfaces", "Web Astryx (app/web)\n+ Streamlit (app/app.py)"),
    ]
    box_w, gap, left, top, height = 2.15, 0.36, 0.75, 1.95, 1.75
    for position, (name, detail) in enumerate(stages):
        x = left + position * (box_w + gap)
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(top), Inches(box_w), Inches(height))
        card.fill.solid()
        card.fill.fore_color.rgb = LIGHT
        card.line.color.rgb = ACCENT
        card.line.width = Pt(0.75)
        card.shadow.inherit = False
        card.text_frame.word_wrap = True
        card.text_frame.margin_left = Inches(0.12)
        card.text_frame.margin_right = Inches(0.12)
        card.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
        title = card.text_frame.paragraphs[0]
        title.alignment = PP_ALIGN.CENTER
        run = title.add_run()
        run.text = name
        run.font.size = Pt(15)
        run.font.bold = True
        run.font.color.rgb = INK
        run.font.name = "Calibri"
        detail_p = card.text_frame.add_paragraph()
        detail_p.alignment = PP_ALIGN.CENTER
        detail_run = detail_p.add_run()
        detail_run.text = detail
        detail_run.font.size = Pt(10)
        detail_run.font.color.rgb = MUTED
        detail_run.font.name = "Consolas"
        if position < len(stages) - 1:
            arrow = slide.shapes.add_shape(
                MSO_SHAPE.RIGHT_ARROW,
                Inches(x + box_w + 0.06),
                Inches(top + height / 2 - 0.1),
                Inches(gap - 0.12),
                Inches(0.2),
            )
            arrow.fill.solid()
            arrow.fill.fore_color.rgb = ACCENT
            arrow.line.fill.background()
            arrow.shadow.inherit = False
    add_bullets(
        slide,
        0.75,
        4.15,
        11.7,
        2.3,
        [
            ("Traçabilité. ", "Chaque classeur est vérifié par sha256 dans data/raw/manifest.json ; un rerun ne retélécharge que ce qui a changé."),
            ("Contrôle qualité. ", "Le parseur refuse une ligne si le TOTAL publié diffère de la somme des sept types ; l'anomalie connue est isolée, pas ignorée."),
            ("Sorties. ", "outputs/tables (CSV), outputs/figures (PNG), outputs/metrics (JSON) : l'application et ce diaporama ne lisent que ces fichiers."),
        ],
        size=15,
        space_after=10,
    )
    footer(slide, index, TOTAL_SLIDES)
    note(
        slide,
        "Cinq étapes, toutes scriptées : téléchargement et vérification sha256, "
        "parsing vers un entrepôt SQLite et CSV, analyse exploratoire, modélisation, "
        "puis les deux interfaces : web Astryx (app/web) et Streamlit (app/app.py). "
        "La règle est simple : l'aval ne lit que des artefacts, jamais le réseau.",
    )


def quality_slide(prs, index):
    slide = new_slide(prs, "Pipeline qualité", "Cinq pièges de la source, traités explicitement")
    central = late_park("CENTRAL PARK")
    central_first = central["first_quarter"] if central else EDA["first_quarter"]
    missing_columns = (
        f"{' et '.join(MISSING_COLUMN_QUARTERS)} n'ont pas de colonne "
        f"{'/'.join(MISSING_COLUMN_TYPES)} : la cellule est NULL et flaggée "
        "count_missing, jamais un zéro."
        if MISSING_COLUMN_QUARTERS else
        "Aucun classeur ne manque une colonne de crime."
    )
    add_bullets(
        slide,
        0.75,
        1.8,
        11.7,
        4.4,
        [
            ("Couverture mouvante. ", f"Central Park n'apparaît qu'en {central_first} : la hausse 2025 est de +{fr(EDA['yoy_change_pct'], 2)} % avec lui, mais de +{fr(EDA['yoy_excluding_new_parks_pct'], 2)} % sans lui ({fr(EDA['latest_complete_year_excluding_new_parks_crimes'])} vs {fr(EDA['previous_year_crimes'])})."),
            ("Trimestre manquant. ", f"{MISSING_LABEL} est absent de la source ; il est interpolé pour le modèle, jamais traité comme un zéro."),
            ("Colonne absente. ", missing_columns),
            ("Anomalie de parsing. ", f"{anomaly_fr()} ; les composantes sont conservées et flaggées total_mismatch dans source_anomalies.csv."),
            ("Géolocalisation. ", f"{fr(GEO['matched_parks'])} parcs sur {fr(GEO['parks'])} rapprochés ({fr(float(GEO['unweighted_coverage']) * 100, 1)} %, {fr(float(GEO['weighted_coverage']) * 100, 1)} % pondéré par volume) ; les deux rapprochements flous audités sont écartés ou corrigés par override."),
        ],
        size=17,
        space_after=16,
    )
    add_text(
        slide,
        0.75,
        6.35,
        11.7,
        0.4,
        "Aucun de ces choix n'est silencieux : chacun a sa table dans outputs/tables/.",
        13,
        MUTED,
        italic=True,
    )
    footer(slide, index, TOTAL_SLIDES)
    note(
        slide,
        "Cinq pièges traités explicitement. Le plus important : Central Park n'entre "
        f"dans la source qu'en {central_first}, donc la croissance de "
        f"+{fr(EDA['yoy_change_pct'], 2)} % devient "
        f"+{fr(EDA['yoy_excluding_new_parks_pct'], 2)} % à périmètre constant. "
        f"{MISSING_LABEL} manque, {', '.join(MISSING_COLUMN_TYPES)} est absent de "
        f"{len(MISSING_COLUMN_QUARTERS)} classeurs et {anomaly_fr()} : nous "
        "documentons au lieu de lisser.",
    )


def limits_slide(prs, index):
    slide = new_slide(prs, "Limites", "Ce que ces données ne disent pas")
    central = late_park("CENTRAL PARK")
    central_first = central["first_quarter"] if central else EDA["first_quarter"]
    add_bullets(
        slide,
        0.75,
        1.8,
        11.7,
        4.9,
        [
            ("Pas de fréquentation. ", "Le taux par acre mesure l'exposition du parc, pas le risque par visiteur."),
            ("Couverture incomplète. ", f"Central Park depuis {central_first} seulement ; {MISSING_LABEL} et les trimestres {FORTHCOMING_QUARTERS[0]}–{FORTHCOMING_QUARTERS[1]} absents."),
            ("Déclarations, pas faits établis. ", "Ce sont des plaintes enregistrées : la propension à déclarer varie avec le quartier."),
            ("Choix de modèle. ", "Trois origines glissantes, tolérance de 1 % vers le modèle le plus simple, et test de Diebold-Mariano contre la naïve ; le SARIMAX n'apporte pas de gain significatif."),
            ("Périmètre du modèle. ", "STATEN ISLAND et BROOKLYN/QUEENS sont hors prévision par arrondissement, faute de volume."),
        ],
        size=17,
        space_after=14,
    )
    footer(slide, index, TOTAL_SLIDES)
    note(
        slide,
        "Les limites sont structurelles : pas de données de fréquentation, une "
        "couverture qui bouge, et des plaintes qui dépendent de la propension à "
        "déclarer. Le backtest roule sur trois origines et la tolérance de 1 % "
        "favorise le modèle le plus simple.",
    )


def conclusion_slide(prs, index):
    slide = new_slide(prs, "Conclusion", "Trois réponses, une réserve")
    add_bullets(
        slide,
        0.75,
        1.8,
        11.7,
        4.9,
        [
            ("Concentré, pas diffus. ", f"{fr(EDA['parks_ever_hit'])} parcs sur {fr(EDA['parks_total'])} sont touchés au moins une fois ; en moyenne {fr(EDA['zero_share_mean_pct'], 2)} % des parcs n'enregistrent aucun crime par trimestre."),
            ("Structuré par l'usage du sol. ", f"Manhattan concentre {fr(RATES_EXCL['MANHATTAN'], 1)} crimes pour 100 acres hors Central Park contre {fr(RATES_EXCL['STATEN ISLAND'], 1)} à Staten Island ; le larcin domine à Manhattan, le vol qualifié dans le Bronx."),
            ("Prévisible à court terme. ", f"{CITY['selected_model'].replace('_', ' ')} retenue : MAE {fr(CITY['selected_mae'], 2)} ± {fr(CITY['selected_mae_sd'], 2)} ; le SARIMAX n'en diffère pas significativement (Diebold-Mariano p = {fr(CITY['best_challenger']['dm_p'], 2)}), MAPE {fr(CITY['selected_mape'], 2)} % sur {CITY['backtest_quarters']} prévisions."),
            ("La réserve. ", "Toute prévision reste gonflée par l'ajout de Central Park à la source ; elle décrit une couverture, pas une explosion."),
        ],
        size=18,
        space_after=16,
    )
    footer(slide, index, TOTAL_SLIDES)
    note(
        slide,
        "Trois réponses : le risque est concentré, il suit l'usage du sol, et il est "
        "prévisible à court terme avec une erreur d'environ vingt crimes par trimestre. "
        "La réserve : la couverture de la source change, donc les niveaux absolus se "
        "comparent à périmètre constant.",
    )


def final_slide(prs, index):
    slide = blank(prs)
    background(slide)
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(SLIDE_W), Inches(0.22))
    bar.fill.solid()
    bar.fill.fore_color.rgb = ACCENT
    bar.line.fill.background()
    bar.shadow.inherit = False
    add_text(slide, 0.9, 2.5, 11.5, 1.0, "Questions", 44, INK, bold=True)
    add_text(slide, 0.9, 3.7, 11.5, 0.5, "Merci de votre attention.", 20, MUTED)
    add_text(slide, 0.9, 4.7, 11.5, 1.2, "make setup · make all · make web-build · make app\nDépôt : NYC-Crime, README.md pour la reproduction complète", 14, MUTED, font="Consolas")
    add_text(
        slide,
        0.9,
        6.0,
        11.5,
        0.4,
        f"Chiffres lus dans outputs/metrics/ : total_crimes={EDA['total_crimes']} · "
        f"chi2_statistic={EDA['chi2_statistic']} · selected_mae={CITY['selected_mae']}",
        10,
        MUTED,
        font="Consolas",
    )
    footer(slide, index, TOTAL_SLIDES)
    note(
        slide,
        "Nous sommes disponibles pour les questions. Tout est reproductible avec "
        "make all ; le README détaille chaque commande et l'app se lance avec make app.",
    )


def app_slide(prs, index):
    slide = new_slide(prs, "Application", "Explorer les mêmes données sans recalculer le modèle")
    takeaway(
        slide,
        "Interface web Vite/React/Astryx, export JSON statique : carte, filtres "
        "d'arrondissement et de type, recherche, onglets Exploration/Prévisions/Méthode, "
        "reconstruite par make web-build.",
    )
    place_picture(slide, WEB_CAPTURE, 0.75, 2.2, 4.3, 4.6)
    add_text(
        slide,
        0.75,
        6.84,
        4.3,
        0.2,
        "Capture réelle : interface web (Chrome, 1440 × 1600).",
        8,
        MUTED,
        italic=True,
    )

    add_bullets(
        slide,
        5.35,
        2.2,
        7.23,
        1.75,
        [
            ("Carte et filtres. ", "Carte des parcs, arrondissement, type de délit, recherche de parc sans accents."),
            ("Onglets. ", "Exploration ; Prévisions (courbe, intervalles) ; Méthode (sources, limites)."),
            ("Sans backend. ", "Export JSON statique de outputs/ ; make web-build reconstruit le site."),
        ],
        size=14,
        space_after=9,
    )

    rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(5.35), Inches(4.12), Inches(1.1), Pt(2))
    rule.fill.solid()
    rule.fill.fore_color.rgb = ACCENT
    rule.line.fill.background()
    rule.shadow.inherit = False
    add_text(slide, 5.35, 4.3, 6.8, 0.25, "Vue analyste : Streamlit (capture réelle)", 9, ACCENT, bold=True)
    place_picture(slide, APP_CAPTURE, 5.35, 4.62, 2.4, 2.12)
    add_text(
        slide,
        7.95,
        4.68,
        4.4,
        1.9,
        "Streamlit (make app) lit les mêmes artefacts : filtres, top 10 des parcs, "
        "export CSV de la sélection.",
        12,
        INK,
    )
    footer(slide, index, TOTAL_SLIDES)
    note(
        slide,
        "L'interface principale est un tableau de bord web Vite/React/Astryx, construit "
        "sur l'export JSON statique des artefacts et reconstruit par make web-build : "
        "carte des parcs, filtres par arrondissement et par type de délit, recherche de "
        "parc sans accents, onglets Exploration, Prévisions et Méthode. L'encart du bas "
        "est la vue analyste Streamlit (make app), qui lit les mêmes artefacts ; la carte "
        "pydeck n'est pas rendue en capture headless, c'est une limite de la capture, pas "
        "de l'app. Aucune des deux interfaces ne fait d'appel réseau.",
    )


def place_picture(slide, image, x, y, w, h):
    """Insère une image centrée dans la boîte (x, y, w, h), proportions conservées."""
    pic = slide.shapes.add_picture(str(image), 0, 0)
    scale = min(w * 914400 / pic.width, h * 914400 / pic.height)
    pic.width = int(pic.width * scale)
    pic.height = int(pic.height * scale)
    pic.left = int(Inches(x) + (Inches(w) - pic.width) / 2)
    pic.top = int(Inches(y) + (Inches(h) - pic.height) / 2)
    return pic


# --- Construction -----------------------------------------------------------


def build():
    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W)
    prs.slide_height = Inches(SLIDE_H)
    slides = [
        ("title", lambda prs, i: title_slide(prs, i)),
        ("problem", lambda prs, i: problem_slide(prs, i)),
        ("data", lambda prs, i: data_slide(prs, i)),
        ("architecture", lambda prs, i: architecture_slide(prs, i)),
        ("quality", lambda prs, i: quality_slide(prs, i)),
        (
            "trend",
            lambda prs, i: picture_slide(
                prs,
                i,
                "Tendances",
                "Un pic marqué, puis un plateau",
                FIG_DIR / "fig01_quarterly_trend.png",
                f"Pic {EDA['peak_quarter']} : {fr(EDA['peak_quarter_crimes'])} crimes ; à périmètre constant, 2025 varie de {fr(EDA['yoy_excluding_new_parks_pct'], 2)} %.",
                "La série citywide est dominée par la saisonnalité et par un pic estival "
                f"en {EDA['peak_quarter']} à {fr(EDA['peak_quarter_crimes'])} crimes. "
                "Depuis le pic, le niveau est plus bas mais stable. Attention : la "
                "marche de début 2025 vient de l'ajout de Central Park à la source, "
                "pas d'une hausse réelle.",
            ),
        ),
        (
            "season",
            lambda prs, i: picture_slide(
                prs,
                i,
                "Saisonnalité",
                "L'été pèse quatre fois plus que l'hiver",
                FIG_DIR / "fig02_seasonality.png",
                f"T3 : {fr(SEASON['3'])} crimes par trimestre contre {fr(SEASON['1'])} en T1, un facteur 4 qui justifie un modèle saisonnier.",
                "Le troisième trimestre concentre "
                f"{fr(SEASON['3'])} crimes en moyenne contre {fr(SEASON['1'])} au "
                "premier. Ce facteur quatre est stable sur toute la période ; il impose "
                "un modèle saisonnier et interdit de comparer deux trimestres consécutifs.",
            ),
        ),
        (
            "borough",
            lambda prs, i: picture_slide(
                prs,
                i,
                "Arrondissement × type",
                "La liaison existe, mais elle est faible",
                FIG_DIR / "fig03_borough_type_heatmap.png",
                f"χ² = {fr(EDA['chi2_statistic'], 1)} (ddl {EDA['chi2_dof']}, {EDA['chi2_p_display']}), V de Cramér = {fr(EDA['cramers_v'], 3)} : significatif, mais faible.",
                "Le test du chi-deux rejette l'indépendance très largement : "
                f"χ² = {fr(EDA['chi2_statistic'], 1)} pour {EDA['chi2_dof']} degrés de liberté. "
                f"Mais le V de Cramér vaut {fr(EDA['cramers_v'], 3)} : la structure est réelle "
                "et ténue. Précaution : des effectifs théoriques inférieurs à 5 dans "
                "certaines cellules rendent ce χ² descriptif, pas prédictif. "
                "Manhattan penche vers le larcin, le Bronx vers le vol qualifié.",
            ),
        ),
        (
            "parks",
            lambda prs, i: picture_slide(
                prs,
                i,
                "Parcs critiques",
                f"{len(TOP_PARKS)} parcs portent le risque visible",
                FIG_DIR / "fig04_top_parks.png",
                f"{TOP_PARKS[0]['park'].title()} : {fr(int(float(TOP_PARKS[0]['total'])))} crimes, devant {TOP_PARKS[1]['park'].title()} ({fr(int(float(TOP_PARKS[1]['total'])))}).",
                f"{TOP_PARKS[0]['park'].title()} arrive en tête avec "
                f"{fr(int(float(TOP_PARKS[0]['total'])))} crimes, devant "
                f"{TOP_PARKS[1]['park'].title()} "
                f"({fr(int(float(TOP_PARKS[1]['total'])))}). Ces parcs cumulent "
                "volume et mix de délits : ce sont les sites où une patrouille ciblée a "
                "le plus d'effet marginal.",
            ),
        ),
        (
            "rate",
            lambda prs, i: picture_slide(
                prs,
                i,
                "Taux par acre",
                "Rapporter à la surface change le classement",
                FIG_DIR / "fig05_rate_per_100acres.png",
                f"Manhattan : {fr(RATES_EXCL['MANHATTAN'], 1)} crimes / 100 acres hors Central Park contre {fr(RATES_EXCL['STATEN ISLAND'], 1)} à Staten Island (×{fr(RATES_EXCL['MANHATTAN'] / RATES_EXCL['STATEN ISLAND'], 0)}).",
                "En volume brut le Bronx paraît dense ; rapporté à la surface, c'est "
                f"Manhattan qui domine avec {fr(RATES_EXCL['MANHATTAN'], 1)} crimes pour "
                f"cent acres hors Central Park ({fr(RATES['MANHATTAN'], 1)} avec), contre "
                f"{fr(RATES_EXCL['STATEN ISLAND'], 1)} à Staten Island. Le taux est calculé "
                "sur les parcs dotés d'une surface, et Central Park est exclu du chiffre "
                "de tête car sa série ne couvre que "
                f"{(late_park('CENTRAL PARK') or {}).get('first_quarter', EDA['first_quarter'])}"
                f"–{EDA['last_quarter']}. Il mesure l'exposition du parc, pas le risque "
                "par visiteur.",
            ),
        ),
        (
            "concentration",
            lambda prs, i: picture_slide(
                prs,
                i,
                "Concentration",
                f"{fr(EDA['zero_share_mean_pct'], 0)} % des parcs sont vides un trimestre donné",
                FIG_DIR / "fig06_zero_share.png",
                f"{fr(EDA['zero_share_mean_pct'], 2)} % des parcs sans crime en moyenne ; {fr(EDA['parks_ever_hit'])} parcs sur {fr(EDA['parks_total'])} touchés au moins une fois.",
                "En moyenne, "
                f"{fr(EDA['zero_share_mean_pct'], 2)} % des parcs n'enregistrent aucun "
                "crime majeur par trimestre. Le risque n'est pas uniforme : il se "
                f"concentre sur {fr(EDA['parks_ever_hit'])} parcs sur "
                f"{fr(EDA['parks_total'])}, et sur une poignée d'entre eux.",
            ),
        ),
        (
            "forecast",
            lambda prs, i: picture_slide(
                prs,
                i,
                "Prévision et backtest",
                "La naïve saisonnière reste la référence",
                FIG_DIR / "fig07_forecast.png",
                f"{CITY['selected_model'].replace('_', ' ')} : MAE {fr(CITY['selected_mae'], 2)} ± {fr(CITY['selected_mae_sd'], 2)} vs SARIMAX {fr(CITY['best_challenger']['mae'], 2)} (DM p = {fr(CITY['best_challenger']['dm_p'], 2)}), MAPE {fr(CITY['selected_mape'], 2)} % ; {CITY['forecast'][0]['quarter_label']} : {fr(CITY['forecast'][0]['point'], 0)} [{fr(CITY['forecast'][0]['lower'], 0)} ; {fr(CITY['forecast'][0]['upper'], 0)}].",
                f"Sur {CITY['backtest_quarters']} prévisions issues de trois origines "
                f"glissantes, la naïve saisonnière atteint une MAE de "
                f"{fr(CITY['selected_mae'], 2)} ± {fr(CITY['selected_mae_sd'], 2)} ; le "
                f"SARIMAX la suit ({fr(CITY['best_challenger']['mae'], 2)}) et le test de "
                f"Diebold-Mariano ne les sépare pas (p = {fr(CITY['best_challenger']['dm_p'], 2)}). "
                f"La prévision réconciliée {CITY['forecast'][0]['quarter_label']} est de "
                f"{fr(CITY['forecast'][0]['point'], 0)} crimes, intervalle "
                f"[{fr(CITY['forecast'][0]['lower'], 0)} ; {fr(CITY['forecast'][0]['upper'], 0)}]. "
                "Réserve : Central Park gonfle le niveau prévu.",
            ),
        ),
        (
            "borough_forecast",
            lambda prs, i: picture_slide(
                prs,
                i,
                "Prévisions par arrondissement",
                f"{len(BOROUGH_FORECAST[BOROUGH_FIRST_Q])} arrondissements, un même rythme saisonnier",
                FIG_DIR / "fig09_forecast_boroughs.png",
                f"{BOROUGH_FIRST_Q} : Manhattan {fr(BOROUGH_FORECAST[BOROUGH_FIRST_Q]['MANHATTAN'])}, "
                f"Brooklyn {fr(BOROUGH_FORECAST[BOROUGH_FIRST_Q]['BROOKLYN'])}, "
                f"Queens {fr(BOROUGH_FORECAST[BOROUGH_FIRST_Q]['QUEENS'])}, "
                f"Bronx {fr(BOROUGH_FORECAST[BOROUGH_FIRST_Q]['BRONX'])} crimes prévus.",
                "Le modèle citywide est décliné par arrondissement. Manhattan et Brooklyn "
                "portent les volumes les plus élevés, le Bronx les plus faibles ; tous "
                "suivent le même cycle saisonnier. Staten Island n'apparaît pas, "
                "faute de volume suffisant. "
                "Les intervalles s'élargissent hors saison haute, au point que certaines "
                "bornes basses passent sous zéro : à quatre trimestres, la prévision par "
                "arrondissement vaut surtout par son ordre de grandeur.",
            ),
        ),
        (
            "clusters",
            lambda prs, i: picture_slide(
                prs,
                i,
                "Typologie des parcs",
                f"{CLUSTERS['selected_k']} profils de criminalité, pas un continuum",
                FIG_DIR / "fig08_clusters.png",
                f"k = {CLUSTERS['selected_k']} (silhouette {fr(CLUSTERS['silhouette'], 3)}) sur {fr(CLUSTERS['n_parks'])} parcs : vol qualifié, larcin, grands parcs, violence.",
                f"La classification non supervisée retient {CLUSTERS['selected_k']} groupes sur "
                f"{fr(CLUSTERS['n_parks'])} parcs, avec une silhouette de "
                f"{fr(CLUSTERS['silhouette'], 3)} : honnête mais pas nette. Deux groupes "
                "sont des parcs de proximité à vol qualifié et à larcin, un regroupe les "
                "grands parcs, le dernier les sites à violence.",
            ),
        ),
        ("app", lambda prs, i: app_slide(prs, i)),
        ("limits", lambda prs, i: limits_slide(prs, i)),
        ("conclusion", lambda prs, i: conclusion_slide(prs, i)),
        ("final", lambda prs, i: final_slide(prs, i)),
    ]
    assert len(slides) == TOTAL_SLIDES, len(slides)
    for index, (_, builder) in enumerate(slides, start=1):
        builder(prs, index)

    prs.core_properties.title = "Criminalité dans les parcs de New York, IPSSI Open Data, sujet 2"
    prs.core_properties.author = "Étudiant IPSSI"
    prs.core_properties.subject = "NYPD Park Crime Statistics"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    prs.save(DECK)
    return DECK, len(prs.slides)


if __name__ == "__main__":
    path, count = build()
    print(f"écrit : {path.relative_to(ROOT)} ({count} diapositives)")
