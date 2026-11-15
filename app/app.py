"""Application Streamlit — criminalité dans les parcs de New York (ticket 0036).

Lancement : `streamlit run app/app.py` ou `make app`.
Les fonctions pures (filtre, KPI, agrégats) sont importables sans serveur et
testées par tests/test_app.py.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import pydeck as pdk
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
CRIME_FILE = ROOT / "data" / "processed" / "park_crime_long.csv"
GEO_FILE = ROOT / "data" / "processed" / "parks_geo.csv"
FORECAST_FILE = ROOT / "outputs" / "tables" / "forecast_city.csv"
METRICS_FILE = ROOT / "outputs" / "metrics" / "model_metrics.json"
GEO_COVERAGE_FILE = ROOT / "outputs" / "tables" / "geo_coverage.csv"
COVERAGE_GAPS_FILE = ROOT / "outputs" / "tables" / "coverage_gaps.csv"
ANOMALIES_FILE = ROOT / "outputs" / "tables" / "source_anomalies.csv"
FIG07_FILE = ROOT / "outputs" / "figures" / "fig07_forecast.png"
SOURCE_URL = "https://www.nyc.gov/site/nypd/stats/crime-statistics/park-crime-stats.page"

CRIME_COLUMNS = ["quarter_label", "park", "borough", "crime_type", "count"]
GEO_COLUMNS = ["park", "borough", "lat", "lon"]

TYPE_COLORS = {
    "BURGLARY": "#4C72B0",
    "FELONY ASSAULT": "#DD8452",
    "GRAND LARCENY": "#55A868",
    "GRAND LARCENY AUTO": "#C44E52",
    "MURDER": "#8172B3",
    "RAPE": "#937860",
    "ROBBERY": "#DA8BC3",
}
UNKNOWN_COLOR = "#8C8C8C"

SHORT_TYPE_LABELS = {
    "BURGLARY": "Cambriolage",
    "FELONY ASSAULT": "Agression",
    "GRAND LARCENY": "Larcin",
    "GRAND LARCENY AUTO": "Vol de véhicule",
    "MURDER": "Meurtre",
    "RAPE": "Viol",
    "ROBBERY": "Vol qualifié",
}


# --- Helpers purs (testés sans serveur) -------------------------------------


def normalize_text(value: str) -> str:
    """Minuscules sans accents, pour la recherche de parc."""
    decomposed = unicodedata.normalize("NFKD", str(value))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def filter_dataframe(df, boroughs=None, crime_types=None, quarter_range=None, park_query=""):
    """Filtre la table longue. Une liste vide signifie « pas de filtre »."""
    out = df
    if boroughs:
        wanted = set(boroughs)
        # Les lignes BROOKLYN/QUEENS appartiennent aux deux arrondissements ;
        # isin() garde une seule copie quand les deux sont sélectionnés.
        if wanted & {"BROOKLYN", "QUEENS"}:
            wanted.add("BROOKLYN/QUEENS")
        out = out[out["borough"].isin(wanted)]
    if crime_types:
        out = out[out["crime_type"].isin(list(crime_types))]
    if quarter_range:
        start, end = quarter_range
        out = out[(out["quarter_label"] >= start) & (out["quarter_label"] <= end)]
    query = normalize_text(park_query).strip()
    if query:
        out = out[out["park"].map(normalize_text).str.contains(query, regex=False)]
    return out


def totals_by(df, *columns):
    """Somme des crimes par colonnes de regroupement (table vide -> table vide)."""
    if df.empty:
        return pd.DataFrame(columns=[*columns, "count"])
    return df.groupby(list(columns), as_index=False)["count"].sum()


def year_ago(quarter_label):
    """« 2026Q2 » -> « 2025Q2 »."""
    year, quarter = quarter_label.split("Q")
    return f"{int(year) - 1}Q{quarter}"


def count_label(count, singular, plural):
    """« 1 parc », « 2 parcs » — 0 et 1 prennent le singulier."""
    return f"{count} {singular if count <= 1 else plural}"


def kpis(df):
    if df.empty:
        return {
            "total_crimes": 0,
            "parks": 0,
            "top_type": None,
            "latest_quarter": None,
            "latest_change_pct": None,
            "change_basis": None,
        }
    total = int(df["count"].sum())
    by_quarter = df.groupby("quarter_label")["count"].sum().sort_index()
    change = None
    basis = None
    if total:
        latest = by_quarter.index[-1]
        previous = year_ago(latest)
        # Même trimestre l'an dernier d'abord : il neutralise la saisonnalité.
        if previous in by_quarter.index and by_quarter[previous]:
            change = (by_quarter[latest] - by_quarter[previous]) / by_quarter[previous] * 100
            basis = "annuelle"
        elif len(by_quarter) >= 2 and by_quarter.iloc[-2]:
            change = (by_quarter.iloc[-1] - by_quarter.iloc[-2]) / by_quarter.iloc[-2] * 100
            basis = "trimestrielle"
    return {
        "total_crimes": total,
        # Un parc sans crime dans la sélection n'est pas « touché ».
        "parks": int(df.loc[df["count"] > 0, "park"].nunique()),
        "top_type": df.groupby("crime_type")["count"].sum().idxmax() if total else None,
        "latest_quarter": by_quarter.index[-1],
        "latest_change_pct": change,
        "change_basis": basis,
    }


def dominant_type(df):
    """Type de délit le plus fréquent par parc."""
    if df.empty:
        return pd.DataFrame(columns=["park", "crime_type"])
    totals = df.groupby(["park", "crime_type"], as_index=False)["count"].sum()
    return totals.loc[totals.groupby("park")["count"].idxmax(), ["park", "crime_type"]]


def top_parks(df, n=10):
    totals = df.groupby("park", as_index=False)["count"].sum()
    return totals.sort_values("count", ascending=False).head(n)


def park_totals(df):
    """Crimes par parc, parcs à zéro retirés. Retourne (totaux, nombre de zéros)."""
    totals = totals_by(df, "park").rename(columns={"count": "total"})
    zero = int((totals["total"] <= 0).sum())
    return totals[totals["total"] > 0], zero


def hex_to_rgb(value):
    value = value.lstrip("#")
    return [int(value[i : i + 2], 16) for i in (0, 2, 4)]


# --- Chargement en cache (aucun appel réseau, aucun recalcul de modèle) -----


@st.cache_data(show_spinner=False)
def load_crimes():
    return pd.read_csv(CRIME_FILE, usecols=CRIME_COLUMNS)


@st.cache_data(show_spinner=False)
def load_geo():
    return pd.read_csv(GEO_FILE, usecols=GEO_COLUMNS)


@st.cache_data(show_spinner=False)
def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


@st.cache_data(show_spinner=False)
def load_table(path):
    return pd.read_csv(path)


# --- Rendu ----------------------------------------------------------------


def render_map(selection, geo):
    st.subheader("Carte des parcs")
    totals, zero_parks = park_totals(selection)
    without_coords = int(geo.loc[geo["park"].isin(selection["park"]), "lat"].isna().sum())

    map_df = totals.merge(dominant_type(selection), on="park", how="left")
    map_df = map_df.merge(geo, on="park", how="left").dropna(subset=["lat", "lon"]).copy()
    map_df["radius"] = 12 * np.sqrt(map_df["total"])
    map_df["color"] = (
        map_df["crime_type"].map(TYPE_COLORS).fillna(UNKNOWN_COLOR).map(hex_to_rgb)
    )

    st.caption(
        f"Carte : {count_label(len(map_df), 'parc géolocalisé', 'parcs géolocalisés')} · "
        f"{count_label(without_coords, 'parc', 'parcs')} sans coordonnées · "
        f"{count_label(zero_parks, 'parc', 'parcs')} sans crime dans la sélection. "
        "Rayon = nombre de crimes ; couleur = délit dominant."
    )
    if map_df.empty:
        st.info("Aucun parc géolocalisé dans la sélection.")
        return

    layer = pdk.Layer(
        "ScatterplotLayer",
        data=map_df,
        get_position=["lon", "lat"],
        get_radius="radius",
        get_fill_color="color",
        pickable=True,
        radius_min_pixels=3,
        radius_max_pixels=80,
    )
    view = pdk.ViewState(
        latitude=40.73, longitude=-73.94, zoom=10, pitch=0, bearing=0
    )
    tooltip = {"html": "<b>{park}</b><br/>{total} crimes — délit dominant : {crime_type}"}
    st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view, tooltip=tooltip))


def render_exploration(selection):
    with st.container():
        render_map(selection, load_geo())

    if selection.empty:
        st.warning("Aucune donnée ne correspond aux filtres.")
        return

    st.subheader("Tendance trimestrielle")
    trend = totals_by(selection, "quarter_label").sort_values("quarter_label")
    fig = px.line(
        trend,
        x="quarter_label",
        y="count",
        markers=True,
        labels={"quarter_label": "Trimestre", "count": "Crimes"},
    )
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig)

    st.subheader("Arrondissement × type de délit")
    heat = selection.pivot_table(
        index="borough", columns="crime_type", values="count", aggfunc="sum", fill_value=0
    )
    fig = px.imshow(
        heat,
        text_auto=True,
        aspect="auto",
        color_continuous_scale="Blues",
        labels={"x": "Type de délit", "y": "Arrondissement", "color": "Crimes"},
    )
    st.plotly_chart(fig)

    st.subheader("Top 10 des parcs")
    top = top_parks(selection, 10)
    fig = px.bar(
        top,
        x="count",
        y="park",
        orientation="h",
        labels={"count": "Crimes", "park": ""},
    )
    fig.update_layout(yaxis={"categoryorder": "total ascending"}, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig)

    st.subheader("Données filtrées")
    summary = (
        selection.groupby(["borough", "park"], as_index=False)["count"]
        .sum()
        .sort_values("count", ascending=False)
    )
    st.dataframe(summary, hide_index=True)
    st.download_button(
        "Télécharger la sélection (CSV)",
        summary.to_csv(index=False).encode("utf-8-sig"),
        "selection_parcs_crimes.csv",
        "text/csv",
    )


def render_forecast():
    metrics = load_json(METRICS_FILE)["citywide"]
    columns = st.columns(4)
    columns[0].metric("Modèle retenu", str(metrics["selected_model"]).upper())
    columns[1].metric("MAE (backtest)", metrics["selected_mae"])
    columns[2].metric("RMSE (backtest)", metrics["selected_rmse"])
    columns[3].metric("MAPE (backtest)", f"{metrics['selected_mape']} %")
    st.caption(
        "Avertissement de sélection (texte du modèle, en anglais) : "
        + metrics["selection_caveat"]
    )
    st.write(
        f"Baseline naïve saisonnière : MAE {metrics['baseline_mae']} — amélioration de "
        f"{metrics['improvement_pct']} % sur {metrics['backtest_quarters']} trimestres de backtest."
    )

    st.subheader("Prévisions citywide")
    forecast = load_table(FORECAST_FILE).rename(
        columns={
            "scope": "Périmètre",
            "quarter_label": "Trimestre",
            "point": "Prévision",
            "lower": "Borne basse",
            "upper": "Borne haute",
        }
    )
    st.dataframe(forecast, hide_index=True)

    if FIG07_FILE.exists():
        st.image(str(FIG07_FILE), caption="Prévision citywide et intervalle à 80 % (fig07).")


def render_method(crimes):
    geo = load_geo()
    st.subheader("Sources")
    st.markdown(
        f"- NYPD, *Park Crime Statistics* : <{SOURCE_URL}>\n"
        "- Fichiers locaux : `data/processed/park_crime_long.csv`, "
        "`data/processed/parks_geo.csv`, `outputs/tables/`, `outputs/metrics/`, "
        "`outputs/figures/`.\n"
        "- L'application ne fait aucun appel réseau et ne recalcule aucun modèle."
    )

    st.subheader("Périodes")
    st.write(
        f"- {crimes['quarter_label'].nunique()} trimestres, de "
        f"{crimes['quarter_label'].min()} à {crimes['quarter_label'].max()}."
    )
    st.write("- 2020Q1 est absent de la source : jamais traité comme zéro.")

    st.subheader("Limites et anomalies")
    combo = crimes[crimes["borough"] == "BROOKLYN/QUEENS"]
    st.write(
        "- Couverture : Central Park n'apparaît qu'à partir de 2025Q1, ce qui gonfle "
        "artificiellement la croissance 2024Q4 → 2025Q1 (voir la table des lacunes)."
    )
    st.write(
        "- Parsing : une ligne Flushing Meadows Corona Park (2025Q4) est exclue, le "
        "total publié (17) différant de la somme des lignes (18)."
    )
    st.write(
        f"- Libellé combiné `BROOKLYN/QUEENS` : "
        f"{count_label(combo['park'].nunique(), 'parc', 'parcs')}, "
        f"{int(combo['count'].sum())} crimes ; série trop courte pour la modélisation."
    )
    st.write(
        f"- Géolocalisation : {int(geo['lat'].isna().sum())} parcs sur "
        f"{len(geo)} n'ont pas de coordonnées ; ils restent comptés dans les agrégats."
    )
    st.write(
        "- Modélisation : STATEN ISLAND et BROOKLYN/QUEENS sont exclus du modèle "
        "par arrondissement (trop peu de données) ; les prévisions affichées sont citywide."
    )

    st.subheader("Couverture géographique")
    st.dataframe(load_table(GEO_COVERAGE_FILE), hide_index=True)

    st.subheader("Lacunes de couverture")
    st.dataframe(load_table(COVERAGE_GAPS_FILE), hide_index=True)

    st.subheader("Anomalies de source")
    st.dataframe(load_table(ANOMALIES_FILE), hide_index=True)

    st.subheader("Avertissements du modèle")
    for caveat in load_json(METRICS_FILE).get("caveats", []):
        st.write(f"- {caveat}")


def main():
    st.set_page_config(
        page_title="Criminalité dans les parcs de New York", layout="wide"
    )
    crimes = load_crimes()
    quarters = sorted(crimes["quarter_label"].unique())

    with st.sidebar:
        st.header("Filtres")
        boroughs = st.multiselect(
            "Arrondissements",
            sorted(crimes["borough"].unique()),
            help="Aucune sélection = tous les arrondissements.",
        )
        crime_types = st.multiselect(
            "Types de délit",
            sorted(crimes["crime_type"].unique()),
            help="Aucune sélection = tous les types.",
        )
        quarter_range = st.select_slider(
            "Plage de trimestres",
            options=quarters,
            value=(quarters[0], quarters[-1]),
        )
        park_query = st.text_input(
            "Rechercher un parc",
            placeholder="Ex. : central, pelham",
            help="Recherche insensible à la casse et aux accents.",
        )

    selection = filter_dataframe(
        crimes,
        boroughs=boroughs,
        crime_types=crime_types,
        quarter_range=quarter_range,
        park_query=park_query,
    )

    st.title("Criminalité dans les parcs de New York")
    st.caption(
        "NYPD Park Crime Statistics — données trimestrielles par parc, "
        "2014Q4 à 2026Q2. Source et limites détaillées dans l'onglet Méthode."
    )

    summary = kpis(selection)
    columns = st.columns(4)
    columns[0].metric("Crimes (sélection)", f"{summary['total_crimes']:,}".replace(",", " "))
    columns[1].metric("Parcs touchés", f"{summary['parks']:,}".replace(",", " "))
    top_type = summary["top_type"]
    columns[2].metric(
        "Délit dominant",
        "—" if top_type is None else SHORT_TYPE_LABELS.get(top_type, top_type),
        help=None if top_type is None else f"Type complet (anglais) : {top_type}",
    )
    change = summary["latest_change_pct"]
    quarter = summary["latest_quarter"]
    if summary["change_basis"] == "annuelle":
        change_label = f"Évolution annuelle {quarter}"
        change_help = (
            "Base : même trimestre de l'année précédente "
            f"({year_ago(quarter)}), pour neutraliser la saisonnalité."
        )
    elif summary["change_basis"] == "trimestrielle":
        change_label = f"Variation trimestrielle {quarter}"
        change_help = (
            "Base : trimestre précédent (pas de données au même trimestre "
            "de l'année précédente)."
        )
    else:
        change_label = f"Évolution {quarter or '—'}"
        change_help = (
            "Aucune base de comparaison disponible (ni même trimestre l'an "
            "dernier, ni trimestre précédent avec des crimes)."
        )
    columns[3].metric(
        change_label,
        "—" if change is None else f"{change:+.1f} %",
        delta_color="inverse",
        help=change_help,
    )

    tab_exploration, tab_forecast, tab_method = st.tabs(
        ["Exploration", "Prévisions", "Méthode"]
    )
    with tab_exploration:
        render_exploration(selection)
    with tab_forecast:
        render_forecast()
    with tab_method:
        render_method(crimes)


if __name__ == "__main__":
    main()
