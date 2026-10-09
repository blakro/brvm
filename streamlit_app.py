"""BRVM — la bourse d'Afrique de l'Ouest, expliquée simplement.

Point d'entrée de Streamlit Community Cloud. L'app ne lit que les CSV
versionnés du dépôt (`data/`) et, sur demande, la cote du jour sur
brvm.org. Elle n'écrit rien.

Cinq onglets, pensés pour quelqu'un qui veut le maximum d'informations
avant d'acheter ou de vendre une action :

1. Aujourd'hui  — ce qui s'est passé à la dernière séance ;
2. Une action   — la fiche d'une société, avec une liste de vérifications
                  avant d'acheter ou de vendre et un simulateur de frais ;
3. Prédictions  — le modèle de `prediction.py`, présenté sans exagération :
                  ce qu'il prévoit pour le mois et le trimestre qui
                  viennent, combien de fois il a eu raison, et pourquoi
                  les frais mangent son avance ;
4. Dividendes   — ce qui rapporte vraiment sur ce marché ;
5. Comprendre   — un guide pour débuter, les règles, un glossaire.

Les analyses plus poussées (classement, backtest, seuil de frais)
restent en ligne de commande : `brvm --help`.
"""

from __future__ import annotations

import html

import altair as alt
import pandas as pd
import streamlit as st

from brvm import db, pedagogie, prediction
from brvm.config import DEFAUTS, charger
from brvm.ingestion import brvm_org

st.set_page_config(page_title="BRVM — la bourse expliquée simplement",
                   page_icon="📈", layout="wide")


# --- Couleurs -------------------------------------------------------------

def _sombre() -> bool:
    """Thème actif côté navigateur, si Streamlit sait le dire."""
    try:
        return getattr(st.context.theme, "type", "light") == "dark"
    except Exception:  # noqa: BLE001 — hors runtime, ou version ancienne
        return False


SOMBRE = _sombre()

# Hausse et baisse gardent toujours une flèche ▲ ▼ à côté de la couleur :
# un lecteur qui confond le vert et le rouge lit quand même le sens.
HAUSSE, BAISSE, STABLE = "#10b981", "#f43f5e", "#94a3b8"
VIOLET, BLEU, CYAN, ORANGE, ROSE, AMBRE, TURQUOISE = (
    "#8b5cf6", "#3b82f6", "#06b6d4", "#f97316", "#ec4899", "#f59e0b",
    "#14b8a6")

if SOMBRE:
    FOND, SURFACE, ENCRE, DOUX = "#0b1020", "#141a2e", "#f1f5f9", "#94a3b8"
    BORDURE = "rgba(255,255,255,0.08)"
else:
    FOND, SURFACE, ENCRE, DOUX = "#f6f7fb", "#ffffff", "#0f172a", "#64748b"
    BORDURE = "rgba(15,23,42,0.08)"

SECTEURS = {
    "Services Financiers": ("🏦", "#6366f1"),
    "Télécommunications": ("📡", CYAN),
    "Consommation de Base": ("🛒", AMBRE),
    "Consommation Discrétionnaire": ("🛍️", ROSE),
    "Industriels": ("🏭", VIOLET),
    "Energie": ("⚡", ORANGE),
    "Services Publics": ("💡", TURQUOISE),
}

# Les niveaux d'un point de la fiche « avant d'acheter » : une couleur ET
# un symbole, pour ne jamais confier le sens à la couleur seule.
NIVEAUX = {
    "bon": ("✅", HAUSSE, "Point fort"),
    "moyen": ("🟡", AMBRE, "Correct"),
    "attention": ("⚠️", BAISSE, "Vigilance"),
    "info": ("ℹ️", BLEU, "À savoir"),
}

# Frais d'un passage (achat OU vente) : courtage et commissions, plus
# l'écart entre le prix affiché et le prix obtenu. Mêmes valeurs que la
# configuration du backtest — environ 3 % pour un aller-retour.
FRAIS_PAR_SENS = (float(DEFAUTS["backtest"]["frais_pourcent"])
                  + float(DEFAUTS["backtest"]["impact_pourcent"]))
SEUIL_LIQUIDITE = float(DEFAUTS["analyse"]["volume_median_min_fcfa"])
LIMITE_SEANCE = 0.075

# Les deux échéances de la météo du devin, en séances (environ 250 par an).
# Le modèle est RÉENTRAÎNÉ pour chacune, sur le rendement des 20 ou des 60
# séances suivantes : rebaptiser « le mois qui vient » sa prévision à cinq
# séances serait annoncer ce qu'elle ne mesure pas.
#
# PAS LA SEMAINE, ALORS QUE C'EST LÀ QUE LE MODÈLE ORDONNE LE MIEUX LA COTE.
# La configuration garde cinq séances pour la ligne de commande, où la
# question est « à quel horizon prévoit-il le mieux ? ». L'app s'adresse à
# quelqu'un qui va acheter, et une météo de la semaine l'invite à passer un
# ordre par semaine : c'est la cadence que les frais punissent le plus. Aux
# deux échéances affichées, le modèle tient encore — 52 bonnes réponses sur
# 100, neuf années sur dix au-dessus de la pièce —, mais l'avance de ses
# favorites n'est plus démontrée au trimestre, ce que l'onglet Prédictions
# et la fiche d'une action disent quand c'est le cas.
#
# Les deux rendements du piège des frais sont les seuls chiffres de l'onglet
# qui ne se recalculent pas : un rejeu coûte plusieurs minutes. Rejeu du
# modèle de CETTE échéance, ses favorites rachetées à la même cadence, prix
# seul, écart annuel contre le marché en moyenne sur plusieurs calendriers
# décalés, sans frais puis à 1,50 % par sens :
#
#     échéance          calendriers   sans frais   1,50 % par sens
#      5 (semaine)           5           +9,9 %        -36,3 %
#     20 (mois)              7           +5,2 %        -14,5 %
#     60 (trimestre)         6           +1,3 %         -5,7 %
#
# Archive arrêtée au 8 octobre 2026 ; les commandes qui refont chaque ligne
# sont dans docs/technique.md.
HORIZONS = {
    20: {"bouton": "🗓️ Le mois qui vient", "mots": "le mois qui vient",
         "unite": "mois", "unites": "mois", "un": "un mois",
         "sans_frais": 0.0516, "avec_frais": -0.1447},
    60: {"bouton": "🔭 Le trimestre qui vient",
         "mots": "le trimestre qui vient",
         "unite": "trimestre", "unites": "trimestres", "un": "un trimestre",
         "sans_frais": 0.0129, "avec_frais": -0.0574},
}
HORIZON_DEFAUT = 20
ARCHIVE_DU_REJEU = "8 octobre 2026"


def _secteur(nom) -> tuple[str, str]:
    return SECTEURS.get(nom, ("🏢", BLEU))


def _rgba(couleur: str, alpha: float) -> str:
    c = couleur.lstrip("#")
    r, v, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{v},{b},{alpha})"


def _sens(valeur) -> int:
    if valeur is None or pd.isna(valeur) or valeur == 0:
        return 0
    return 1 if valeur > 0 else -1


def _couleur(valeur) -> str:
    return {1: HAUSSE, -1: BAISSE, 0: STABLE}[_sens(valeur)]


def _fleche(valeur) -> str:
    return {1: "▲", -1: "▼", 0: "●"}[_sens(valeur)]


def _texte(valeur, defaut: str = "") -> str:
    """Une cellule en texte sûr : NaN devient `defaut`, pas « nan »."""
    return defaut if valeur is None or pd.isna(valeur) else html.escape(str(valeur))


def _pastille(valeur) -> str:
    """« ▲ +2,1 % » dans une pastille colorée."""
    c = _couleur(valeur)
    return (f'<span class="pastille" style="background:{_rgba(c, .14)};'
            f'color:{c}">{_fleche(valeur)} {pedagogie.pourcentage(valeur)}</span>')


def _pct(valeur, signe: bool = False) -> str:
    return pedagogie.pourcentage(valeur, signe=signe)


# --- Habillage ------------------------------------------------------------

def _habiller() -> None:
    st.markdown(f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&display=swap');
@property --n {{ syntax: '<integer>'; initial-value: 0; inherits: false; }}

html, body, [class*="css"], .stMarkdown, button, input {{
  font-family: 'Plus Jakarta Sans', system-ui, sans-serif !important;
}}
.stApp {{
  background:
    radial-gradient(900px 500px at 0% 0%, {_rgba(VIOLET, .12)}, transparent 60%),
    radial-gradient(900px 500px at 100% 0%, {_rgba(CYAN, .12)}, transparent 60%),
    radial-gradient(900px 600px at 50% 100%, {_rgba(ROSE, .08)}, transparent 60%),
    {FOND};
  background-attachment: fixed;
}}
.block-container {{ padding-top: 3.2rem; max-width: 1280px; }}

/* --- Animations ------------------------------------------------------- */
@keyframes monte {{ from {{ opacity: 0; transform: translateY(18px); }}
                    to {{ opacity: 1; transform: none; }} }}
@keyframes degrade {{ 0% {{ background-position: 0% 50%; }}
                      50% {{ background-position: 100% 50%; }}
                      100% {{ background-position: 0% 50%; }} }}
@keyframes flotte {{ 0%,100% {{ transform: translateY(0); }}
                     50% {{ transform: translateY(-8px); }} }}
@keyframes pousse {{ from {{ transform: scaleX(0); }} to {{ transform: scaleX(1); }} }}
@keyframes pouls {{ 0% {{ box-shadow: 0 0 0 0 {_rgba(HAUSSE, .6)}; }}
                    70% {{ box-shadow: 0 0 0 10px {_rgba(HAUSSE, 0)}; }}
                    100% {{ box-shadow: 0 0 0 0 {_rgba(HAUSSE, 0)}; }} }}
@keyframes compte {{ from {{ --n: 0; }} to {{ --n: var(--cible); }} }}
@keyframes brille {{ from {{ left: -60%; }} to {{ left: 130%; }} }}
@keyframes tourne {{ 0% {{ transform: rotateY(0); }} 100% {{ transform: rotateY(360deg); }} }}
@keyframes lueur {{ 0%,100% {{ filter: drop-shadow(0 0 6px {_rgba(VIOLET, .6)}); }}
                    50% {{ filter: drop-shadow(0 0 22px {_rgba(CYAN, .9)}); }} }}
@keyframes glisse {{ from {{ left: 50%; }} to {{ left: var(--pos); }} }}

.anime {{ animation: monte .6s cubic-bezier(.2,.8,.2,1) both; }}
.d1 {{ animation-delay: .05s; }} .d2 {{ animation-delay: .12s; }}
.d3 {{ animation-delay: .19s; }} .d4 {{ animation-delay: .26s; }}
.d5 {{ animation-delay: .33s; }} .d6 {{ animation-delay: .40s; }}
.d7 {{ animation-delay: .47s; }}

.compteur {{ animation: compte 1.4s cubic-bezier(.2,.8,.2,1) forwards;
            counter-reset: n var(--n); }}
.compteur::after {{ content: counter(n); }}

/* --- Bandeau d'accueil ------------------------------------------------ */
.bandeau {{
  position: relative; overflow: hidden; border-radius: 24px;
  padding: 1.8rem 2rem; color: #fff;
  background: linear-gradient(120deg, #7c3aed, #2563eb, #06b6d4, #ec4899, #7c3aed);
  background-size: 300% 300%; animation: degrade 14s ease infinite;
  box-shadow: 0 20px 45px -20px {_rgba(VIOLET, .7)};
}}
.bandeau::after {{
  content: ""; position: absolute; top: 0; bottom: 0; width: 40%;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,.18), transparent);
  transform: skewX(-20deg); animation: brille 6s ease-in-out infinite;
}}
.bandeau h1 {{ color: #fff !important; font-size: 2.1rem !important;
              font-weight: 800 !important; margin: 0 !important;
              padding: 0 !important; letter-spacing: -.02em; }}
.bandeau p {{ margin: .35rem 0 0; opacity: .92; font-size: 1.02rem; }}
.bandeau .emoji {{ font-size: 3rem; display: inline-block;
                  animation: flotte 3.5s ease-in-out infinite; }}
.puce {{ display: inline-flex; align-items: center; gap: .4rem;
        background: rgba(255,255,255,.18); backdrop-filter: blur(6px);
        border: 1px solid rgba(255,255,255,.25); border-radius: 999px;
        padding: .28rem .8rem; font-size: .82rem; font-weight: 600;
        margin: .8rem .4rem 0 0; }}
.point-direct {{ width: 9px; height: 9px; border-radius: 50%;
                background: #34d399; animation: pouls 1.8s infinite; }}

/* --- Cartes ----------------------------------------------------------- */
.carte {{
  background: {SURFACE}; border: 1px solid {BORDURE}; border-radius: 20px;
  padding: 1.1rem 1.25rem; height: 100%; color: {ENCRE};
  box-shadow: 0 10px 30px -18px rgba(15,23,42,.35);
  transition: transform .25s ease, box-shadow .25s ease;
}}
.carte:hover {{ transform: translateY(-4px);
               box-shadow: 0 18px 40px -18px rgba(15,23,42,.45); }}
.stat {{ color: #fff; border: none; position: relative; overflow: hidden; }}
.stat .icone {{ position: absolute; right: .7rem; bottom: .4rem;
               font-size: 2.6rem; opacity: .28; }}
.stat .label, .stat .valeur, .stat .note {{ position: relative; z-index: 1; }}
.stat .label {{ font-size: .78rem; font-weight: 700; text-transform: uppercase;
               letter-spacing: .06em; opacity: .9; }}
.stat .valeur {{ font-size: 2.1rem; font-weight: 800; line-height: 1.15;
                letter-spacing: -.02em; margin-top: .2rem; }}
.stat .note {{ font-size: .82rem; opacity: .92; margin-top: .2rem; }}

.titre {{ font-size: 1.25rem; font-weight: 800; color: {ENCRE};
         margin: 1.8rem 0 .8rem; display: flex; align-items: center; gap: .5rem; }}
.titre .barre {{ width: 6px; height: 1.3rem; border-radius: 4px;
                background: linear-gradient(180deg, {VIOLET}, {CYAN}); }}
.sous {{ color: {DOUX}; font-size: .95rem; margin: -.5rem 0 1rem; }}

.pastille {{ display: inline-block; padding: .18rem .6rem; border-radius: 999px;
            font-weight: 700; font-size: .85rem; white-space: nowrap; }}

.ligne {{ display: flex; align-items: center; gap: .75rem; padding: .6rem .2rem;
         border-bottom: 1px dashed {BORDURE}; }}
.ligne:last-child {{ border-bottom: none; }}
.rang {{ width: 2rem; height: 2rem; border-radius: 50%; display: grid;
        place-items: center; font-weight: 800; color: #fff; flex: 0 0 auto; }}
.nom {{ flex: 1; min-width: 0; }}
.nom b {{ color: {ENCRE}; }}
.nom small {{ color: {DOUX}; display: block; white-space: nowrap;
             overflow: hidden; text-overflow: ellipsis; }}
.jauge {{ height: 10px; border-radius: 999px; background: {_rgba(STABLE, .2)};
         overflow: hidden; display: flex; }}
.jauge > div {{ height: 100%; transform-origin: left;
               animation: pousse 1.1s cubic-bezier(.2,.8,.2,1) both; }}

.secteur {{ border-top: 5px solid; text-align: center; }}
.secteur .emo {{ font-size: 1.9rem; }}
.secteur .nomsec {{ font-size: .78rem; font-weight: 700; color: {DOUX};
                   min-height: 2.4em; line-height: 1.2; margin: .2rem 0; }}

.meteo {{ display: flex; align-items: center; gap: 1.1rem; }}
.meteo .emoji {{ font-size: 3.6rem; animation: flotte 4s ease-in-out infinite; }}
.meteo h3 {{ margin: 0 !important; padding: 0 !important; color: {ENCRE};
            font-size: 1.5rem !important; font-weight: 800 !important; }}
.meteo p {{ margin: .2rem 0 0; color: {DOUX}; }}
.echeance {{ font-size: .78rem; font-weight: 800; text-transform: uppercase;
            letter-spacing: .06em; color: {DOUX}; margin-bottom: .6rem; }}

.lecon {{ border-radius: 20px; padding: 1.2rem 1.4rem; color: #fff;
         background: linear-gradient(120deg, {ORANGE}, {ROSE});
         box-shadow: 0 18px 40px -20px {_rgba(ROSE, .8)}; line-height: 1.55; }}
.lecon b {{ font-size: 1.1rem; }}

.mot {{ border-left: 6px solid; }}
.mot h4 {{ margin: 0 0 .3rem !important; padding: 0 !important;
          color: {ENCRE}; font-size: 1.05rem !important; }}
.mot p {{ margin: 0; color: {DOUX}; font-size: .92rem; line-height: 1.5; }}

.point {{ border-left: 6px solid; margin-bottom: 1rem; }}
.point .entete {{ display: flex; justify-content: space-between;
                 align-items: center; gap: .5rem; }}
.point .quoi {{ font-weight: 800; color: {ENCRE}; font-size: 1rem; }}
.point .chiffre {{ font-size: 1.45rem; font-weight: 800; margin: .35rem 0 .2rem; }}
.point p {{ margin: 0; color: {DOUX}; font-size: .88rem; line-height: 1.45; }}

.etape {{ display: flex; gap: .9rem; align-items: flex-start; }}
.etape .num {{ width: 2.4rem; height: 2.4rem; border-radius: 50%; flex: 0 0 auto;
              display: grid; place-items: center; color: #fff; font-weight: 800; }}
.etape h4 {{ margin: 0 0 .2rem !important; padding: 0 !important;
            color: {ENCRE}; font-size: 1rem !important; }}
.etape p {{ margin: 0; color: {DOUX}; font-size: .9rem; line-height: 1.45; }}

/* --- Prédictions ------------------------------------------------------ */
.boule {{ font-size: 4.2rem; display: inline-block;
         animation: flotte 3.2s ease-in-out infinite, lueur 3.2s ease-in-out infinite; }}
.piece {{ font-size: 3.4rem; display: inline-block;
         animation: tourne 2.6s linear infinite; }}
.oracle {{ border-radius: 24px; padding: 1.4rem 1.6rem; color: #fff;
          background: linear-gradient(135deg, #1e1b4b, #4c1d95 45%, #0e7490);
          box-shadow: 0 22px 50px -24px {_rgba(VIOLET, .9)};
          display: flex; gap: 1.4rem; align-items: center; flex-wrap: wrap; }}
.oracle h3 {{ color: #fff !important; margin: 0 !important; padding: 0 !important;
             font-size: 1.5rem !important; font-weight: 800 !important; }}
.oracle p {{ margin: .35rem 0 0; opacity: .92; line-height: 1.55; }}
.regle-piece {{ position: relative; height: 22px; border-radius: 999px; margin: 1.6rem 0 .4rem;
               background: linear-gradient(90deg, {BAISSE}, {STABLE} 50%, {HAUSSE}); }}
.regle-piece .milieu {{ position: absolute; left: 50%; top: -6px; bottom: -6px;
                       width: 2px; background: {ENCRE}; opacity: .5; }}
.regle-piece .curseur {{ position: absolute; top: 50%; left: var(--pos);
  transform: translate(-50%, -50%); width: 34px; height: 34px; border-radius: 50%;
  background: {SURFACE}; border: 3px solid {ENCRE}; display: grid; place-items: center;
  font-size: 1rem; animation: glisse 1.6s cubic-bezier(.2,.8,.2,1) both;
  box-shadow: 0 6px 16px -6px rgba(0,0,0,.5); }}
.graduation {{ display: flex; justify-content: space-between; color: {DOUX};
              font-size: .78rem; font-weight: 700; }}
.puce-valeur {{ display: inline-flex; align-items: center; gap: .35rem;
               border-radius: 999px; padding: .3rem .7rem; margin: .2rem .15rem;
               font-weight: 700; font-size: .85rem; }}

/* --- Onglets : des pilules ------------------------------------------- */
.stTabs [role="tablist"] {{
  gap: .4rem; background: {SURFACE}; padding: .4rem; border-radius: 999px;
  border: 1px solid {BORDURE}; width: fit-content; max-width: 100%;
  overflow-x: auto; box-shadow: 0 8px 24px -16px rgba(15,23,42,.4);
}}
.stTabs [role="tablist"] > *:not([role="tab"]) {{ display: none; }}
.stTabs [role="tab"] {{
  border-radius: 999px; padding: .55rem 1.15rem !important; font-weight: 700;
  transition: background .25s ease, color .25s ease, transform .2s ease;
  border: none !important; height: auto; margin: 0 !important;
}}
.stTabs [role="tab"] p {{ font-weight: 700; font-size: .98rem; }}
.stTabs [role="tab"]:hover {{ background: {_rgba(VIOLET, .1)}; transform: translateY(-1px); }}
.stTabs [role="tab"][aria-selected="true"] {{
  background: linear-gradient(120deg, {VIOLET}, {BLEU}) !important;
  color: #fff !important; box-shadow: 0 8px 18px -8px {_rgba(VIOLET, .9)};
}}
.stTabs [role="tab"][aria-selected="true"] p {{ color: #fff !important; }}
.stTabs [role="tabpanel"] {{ animation: monte .5s ease both; }}

[data-testid^="stBaseButton"] {{
  border-radius: 999px !important; font-weight: 700; border: none !important;
  color: #fff !important; padding: .6rem 1rem !important;
  background: linear-gradient(120deg, {VIOLET}, {BLEU}) !important;
  transition: transform .2s ease, box-shadow .2s ease;
}}
[data-testid^="stBaseButton"] p {{ color: #fff !important; font-weight: 700; }}
[data-testid^="stBaseButton"]:hover {{ transform: translateY(-2px) scale(1.02);
  box-shadow: 0 10px 24px -10px {_rgba(VIOLET, .9)}; }}
[data-testid="stExpander"] details {{ border-radius: 16px;
  background: {SURFACE}; border: 1px solid {BORDURE}; }}
[data-testid="stVerticalBlockBorderWrapper"] {{ border-radius: 20px; }}

@media (max-width: 640px) {{
  .bandeau {{ padding: 1.3rem; }} .bandeau h1 {{ font-size: 1.5rem !important; }}
  .stat .valeur {{ font-size: 1.7rem; }}
}}
@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{ animation: none !important; transition: none !important; }}
}}
</style>""", unsafe_allow_html=True)


def _html(code: str) -> None:
    st.markdown(code, unsafe_allow_html=True)


def _titre(texte: str, sous: str = "") -> None:
    _html(f'<div class="titre anime"><span class="barre"></span>{texte}</div>'
          + (f'<div class="sous">{sous}</div>' if sous else ""))


def _stat(colonne, label: str, valeur: str, note: str, couleurs: tuple,
          icone: str, delai: int = 1, nombre: int | None = None) -> None:
    """Une carte colorée. `nombre` : un entier qui défile de 0 à sa valeur."""
    contenu = (f'<span class="compteur" style="--cible:{nombre}" '
               f'aria-label="{nombre}"></span>' if nombre is not None
               else valeur)
    colonne.markdown(
        f'<div class="carte stat anime d{min(delai, 7)}" style="background:'
        f'linear-gradient(135deg,{couleurs[0]},{couleurs[1]});'
        f'box-shadow:0 16px 36px -18px {couleurs[0]}">'
        f'<span class="icone">{icone}</span>'
        f'<div class="label">{label}</div>'
        f'<div class="valeur">{contenu}</div>'
        f'<div class="note">{note}</div></div>',
        unsafe_allow_html=True)


def _legende(*lignes: str) -> None:
    """Comment lire l'onglet : couleurs, icônes et chiffres, en clair."""
    with st.expander("🗺️ Légende — comment lire cette page"):
        st.markdown("\n".join(f"- {ligne}" for ligne in lignes))


# Graphiques : fond transparent, grille discrète, et les nombres et les
# dates à la française (« 1 800 », « 3,5 », « oct. 2026 »).
@alt.theme.register("brvm_couleurs", enable=True)
def _theme_graphiques() -> alt.theme.ThemeConfig:
    return alt.theme.ThemeConfig({
        "background": "transparent",
        "view": {"stroke": "transparent"},
        "font": "Plus Jakarta Sans, system-ui, sans-serif",
        "axis": {"labelColor": DOUX, "titleColor": DOUX, "gridColor": BORDURE,
                 "domain": False, "tickColor": BORDURE, "labelFontSize": 12},
        "legend": {"labelColor": ENCRE, "titleColor": DOUX},
        "locale": {
            "number": {"decimal": ",", "thousands": " ",
                       "grouping": [3], "currency": ["", " FCFA"]},
            "time": {
                "dateTime": "%A %e %B %Y à %X", "date": "%d/%m/%Y",
                "time": "%H:%M:%S", "periods": ["AM", "PM"],
                "days": ["dimanche", "lundi", "mardi", "mercredi", "jeudi",
                         "vendredi", "samedi"],
                "shortDays": ["dim.", "lun.", "mar.", "mer.", "jeu.", "ven.",
                              "sam."],
                "months": pedagogie.MOIS,
                "shortMonths": ["janv.", "févr.", "mars", "avr.", "mai", "juin",
                                "juil.", "août", "sept.", "oct.", "nov.",
                                "déc."],
            },
        },
    })


# --- Données --------------------------------------------------------------

@st.cache_data(ttl=900)
def charger_archive():
    return (db.charger_archive("cours"), db.charger_archive("referentiel"),
            db.charger_archive("dividendes"), db.charger_archive("fondamentaux"))


@st.cache_data(ttl=900, show_spinner="Lecture de brvm.org…")
def lire_en_direct():
    """Séance publiée sur brvm.org. (cote, erreur) — l'un vaut None.

    Affichée seulement, jamais archivée.
    """
    try:
        return brvm_org.lire_cote(), None
    except Exception as erreur:  # noqa: BLE001
        detail = str(erreur).splitlines()[0][:110]
        return None, f"{type(erreur).__name__} — {detail}"


# Les tables passent en `_table` : Streamlit ne les hache pas (cent mille
# lignes à chaque appel coûteraient une partie de ce qu'on économise). C'est
# `cle`, l'empreinte de l'archive, qui distingue les entrées du cache, avec
# l'échéance. Quatre entrées : les deux échéances, pour l'archive seule et
# pour l'archive complétée par la séance lue en direct.
@st.cache_data(max_entries=4, show_spinner=(
    "🔮 Le devin relit onze ans d'historique… (une quinzaine de secondes par "
    "échéance, la première fois seulement)"))
def prevoir(_cours, _referentiel, cle, horizon: int) -> dict:
    """La prévision du modèle à `horizon` séances, et sa fiabilité à ce terme.

    Le modèle est validé et entraîné pour l'échéance demandée : chacune a
    son propre bilan, sa propre avance et son propre calibrage, que rien ne
    permet de transposer de l'une à l'autre. Seules les pièces affichées
    sont gardées : la validation complète porte des matrices et des modèles
    dont l'app n'a pas l'usage.

    QUAND LE MODÈLE ÉCHOUE À SA PORTE DE PRODUCTION, LE DEVIN SE TAIT.
    `valider` rend alors « composite », et `predire` se rabat sur ce score
    sans apprentissage — utile à la ligne de commande, qui doit bien classer
    quelque chose, mais dont les dix premières ont fait moins bien que le
    marché sur l'archive, aux deux échéances (-0,12 % par mois, -0,27 % par
    trimestre en octobre 2026). L'afficher ici sous le nom du devin, à côté
    du bilan du modèle, mêlerait deux classements sans le dire. `echoue` le
    signale, les probabilités restent vides, et tout ce qui est rendu —
    bilan comme avance — est celui du modèle : c'est lui que la page juge.
    """
    reglages = charger()
    reglages["prediction"]["horizon"] = int(horizon)
    validation = prediction.valider(_cours, reglages, referentiel=_referentiel)
    if validation["periodes"].empty:
        return {"pret": False, "horizon": validation.get("horizon"),
                "lignes": validation.get("lignes", 0),
                "minimum": validation.get("lignes_minimum", 0)}
    echoue = validation.get("retenue") != "combinaison"
    probas = (pd.DataFrame(columns=["ticker", "probabilite", "incertitude",
                                    "rang_combine", "calibree"])
              if echoue else
              prediction.predire(_cours, reglages, referentiel=_referentiel,
                                 validation=validation))
    stabilite = validation.get("stabilite") or {}
    # L'avance du MODÈLE, et non celle de ce qui part en production : les
    # deux sont la même tant que la porte s'ouvre — vérifié —, et quand elle
    # se ferme, c'est celle du modèle qui explique pourquoi.
    modele = (validation.get("sources") or {}).get("combinaison") or {}
    return {
        "pret": True,
        "horizon": int(validation["horizon"]),
        "echoue": echoue,
        "ic": float(stabilite.get("ic", float("nan"))),
        "probas": probas,
        "periodes": validation["periodes"][["periode", "precision"]].copy(),
        "avantage": modele.get("avantage") or validation.get("avantage") or {},
        "stabilite": stabilite,
        "retenue": validation.get("retenue"),
        "motif": validation.get("motif"),
    }


@st.cache_data(max_entries=2, show_spinner=False)
def agitation_du_marche(_cours, cle) -> pd.Series:
    """Ampleur habituelle des mouvements d'une semaine, par valeur, sur un an."""
    dates_an = sorted(_cours["date"].unique())[-251:]
    an = _cours[_cours["date"].isin(dates_an)].sort_values("date")
    rendements = an.groupby("ticker")["cloture"].pct_change()
    return (rendements.groupby(an["ticker"]).std() * 5 ** 0.5).dropna()


cours, referentiel, dividendes, fondamentaux = charger_archive()
if referentiel.empty:
    referentiel = brvm_org.referentiel_amorce()

_habiller()

# La cote relue sur le site doit rester affichée d'une relance à l'autre :
# c'est l'INTENTION qui est retenue dans la session, et `lire_en_direct`
# garde la réponse un quart d'heure, donc la rejouer ne coûte rien.
haut_1, haut_2 = st.columns([5, 1], vertical_alignment="bottom")
with haut_2:
    if st.button("🔄 Actualiser", width="stretch",
                 help="Relire la cote publiée sur brvm.org"):
        lire_en_direct.clear()
        st.session_state["en_direct"] = True

direct, echec = (None, None)
if cours.empty or st.session_state.get("en_direct"):
    direct, echec = lire_en_direct()
if direct is not None and not direct.empty:
    cours = (pd.concat([cours, direct], ignore_index=True)
             .drop_duplicates(subset=["date", "ticker"], keep="last"))

if cours.empty:
    st.warning("**Aucune donnée.** L'archive est vide et brvm.org n'a pas "
               "répondu" + (f" — {echec}." if echec else "."))
    st.stop()

dates = sorted(cours["date"].unique())
derniere = dates[-1]
en_direct = direct is not None and not direct.empty
cotees_du_jour = cours.loc[cours["date"] == derniere, "ticker"].nunique()
CLE = (len(cours), derniere, float(cours["cloture"].sum(skipna=True)))

with haut_1:
    _html(
        '<div class="bandeau anime"><div style="display:flex;gap:1.1rem;'
        'align-items:center;position:relative;z-index:1">'
        '<span class="emoji">📈</span><div>'
        '<h1>La Bourse d\'Afrique de l\'Ouest</h1>'
        f'<p>Les {cotees_du_jour} sociétés cotées à la BRVM, expliquées '
        'simplement — tout savoir avant d\'acheter ou de vendre.</p></div></div>'
        '<div style="position:relative;z-index:1">'
        + (f'<span class="puce"><span class="point-direct"></span>En direct · '
           f'{pedagogie.jour(derniere)}</span>' if en_direct else
           f'<span class="puce">📅 Dernière séance : '
           f'{pedagogie.jour(derniere)}</span>')
        + '<span class="puce">🌍 8 pays · 1 bourse</span>'
          '<span class="puce">⚠️ Pas un conseil d\'investissement</span>'
          '</div></div>')

if echec:
    st.caption(f"brvm.org injoignable ({echec}) — affichage de l'archive.")

st.write("")

# --- Onglets --------------------------------------------------------------
# `key` garde l'onglet ouvert d'une relance à l'autre ; `on_change="rerun"`
# permet de ne calculer que l'onglet visible. L'onglet voyage aussi dans
# l'URL (`?onglet=action`), pour survivre à un rechargement de la page.
ONGLETS = {"aujourdhui": "🏠 Aujourd'hui", "action": "🔎 Une action",
           "predictions": "🔮 Prédictions", "dividendes": "💰 Dividendes",
           "comprendre": "🎓 Comprendre"}
PAR_LIBELLE = {v: k for k, v in ONGLETS.items()}

_demande = st.query_params.get("onglet")
if "onglet" not in st.session_state and _demande in ONGLETS:
    st.session_state["onglet"] = ONGLETS[_demande]

onglets = st.tabs(list(ONGLETS.values()), key="onglet", on_change="rerun")

_actuel = PAR_LIBELLE.get(st.session_state["onglet"], "aujourdhui")
if st.query_params.get("onglet") != _actuel:
    st.query_params["onglet"] = _actuel

noms = referentiel.set_index("ticker")["nom"]
secteurs_par_valeur = referentiel.set_index("ticker")["secteur"]


def _nom(ticker) -> str:
    nom = noms.get(ticker)
    return str(ticker) if nom is None or pd.isna(nom) else str(nom)


def _seance(table: pd.DataFrame) -> pd.DataFrame:
    """Dernière séance, avec la variation face à la précédente."""
    jour = table[table["date"] == derniere].copy()
    if len(dates) >= 2:
        veille = (table[table["date"] == dates[-2]]
                  .set_index("ticker")["cloture"])
        precedent = jour["ticker"].map(veille)
        jour["variation"] = (jour["cloture"] / precedent.where(precedent > 0)
                             - 1)
    else:
        jour["variation"] = float("nan")
    jour["nom"] = jour["ticker"].map(noms)
    jour["secteur"] = jour["ticker"].map(secteurs_par_valeur)
    return jour


def _palmares(lignes: pd.DataFrame, couleur: str) -> str:
    """Cinq valeurs, chacune avec sa pastille et une jauge qui pousse."""
    plafond = max(lignes["variation"].abs().max(), 1e-9)
    morceaux = []
    for i, ligne in enumerate(lignes.itertuples(), start=1):
        part = abs(ligne.variation) / plafond
        morceaux.append(
            f'<div class="ligne anime d{i}">'
            f'<div class="rang" style="background:linear-gradient(135deg,'
            f'{couleur},{_rgba(couleur, .6)})">{i}</div>'
            f'<div class="nom"><b>{_texte(ligne.ticker)}</b>'
            f'<small>{_texte(ligne.nom)}</small>'
            f'<div class="jauge" style="margin-top:.35rem"><div style="'
            f'width:{max(part, .04):.0%};background:linear-gradient(90deg,'
            f'{_rgba(couleur, .5)},{couleur});animation-delay:{.1 * i:.1f}s">'
            f'</div></div></div>{_pastille(ligne.variation)}</div>')
    return "".join(morceaux)


def _horizon_en_mots(horizon: int) -> str:
    """« le mois qui vient (20 séances) » : glissant, pas le mois du
    calendrier — la prévision part de la dernière clôture."""
    if horizon in HORIZONS:
        return f"{HORIZONS[horizon]['mots']} ({horizon} séances)"
    return f"les {horizon} prochaines séances"


def _silence(devin: dict) -> str:
    """Pourquoi le devin se tait à une échéance, dans les mots du lecteur.

    Les deux causes sont celles de la porte de `prediction.valider` : un IC
    négatif, ou des favorites qui ont perdu contre le marché. La troisième
    phrase couvre une avance qu'on n'a pas pu mesurer.
    """
    ic = devin.get("ic", float("nan"))
    ecart = (devin.get("avantage") or {}).get("avantage", float("nan"))
    if pd.notna(ic) and ic <= 0:
        return ("son classement n'a pas fait mieux que le hasard sur les "
                "années qu'il n'avait jamais vues")
    if pd.notna(ecart) and ecart <= 0:
        return ("ses dix favorites ont fait moins bien que le marché sur les "
                "années qu'il n'avait jamais vues")
    return "il n'a pas fait ses preuves sur les années qu'il n'avait jamais vues"


def _phrase(texte: str) -> str:
    """Une majuscule en tête, sans toucher au reste, contrairement à
    `str.capitalize`."""
    return texte[:1].upper() + texte[1:]


def _meteo_prevision(rang: float) -> tuple[str, str, str]:
    """Le tiers du classement du modèle, dit comme une météo."""
    if rang >= 2 / 3:
        return "☀️", "Plutôt favorable", HAUSSE
    if rang >= 1 / 3:
        return "⛅", "Neutre", AMBRE
    return "🌧️", "Plutôt défavorable", BAISSE


def _regle_piece(probabilite: float) -> str:
    """Une règle de 40 % à 60 % : la pièce au milieu, l'action à sa place."""
    position = min(max((probabilite - 0.40) / 0.20, 0.02), 0.98)
    return (
        f'<div class="regle-piece"><div class="milieu"></div>'
        f'<div class="curseur" style="--pos:{position:.1%}">🎯</div></div>'
        '<div class="graduation"><span>40 %</span>'
        '<span>🪙 50 % = pile ou face</span><span>60 %</span></div>')


# --- 🏠 Aujourd'hui ---------------------------------------------------------
if onglets[0].open:
    with onglets[0]:
        jour = _seance(cours)
        connues = jour.dropna(subset=["variation"])
        hausses = int((connues["variation"] > 0).sum())
        baisses = int((connues["variation"] < 0).sum())
        stables = len(connues) - hausses - baisses
        echange = float(jour["volume_fcfa"].sum(skipna=True))
        mediane = connues["variation"].median() if not connues.empty else None

        # La météo du marché : une image que tout le monde comprend.
        if connues.empty:
            meteo = ("🌤️", "Une seule séance en archive",
                     "Les variations apparaîtront dès la deuxième.")
        elif hausses > 1.5 * max(baisses, 1) and (mediane or 0) >= 0:
            meteo = ("☀️", "Belle journée sur le marché",
                     f"La majorité des actions a monté : {hausses} en hausse "
                     f"contre {baisses} en baisse.")
        elif baisses > 1.5 * max(hausses, 1) and (mediane or 0) <= 0:
            meteo = ("🌧️", "Journée difficile sur le marché",
                     f"La majorité des actions a baissé : {baisses} en baisse "
                     f"contre {hausses} en hausse.")
        else:
            meteo = ("⛅", "Journée partagée",
                     f"{hausses} actions montent, {baisses} baissent, "
                     f"{stables} ne bougent pas.")
        _html(f'<div class="carte meteo anime"><span class="emoji">{meteo[0]}'
              f'</span><div><h3>{meteo[1]}</h3><p>{meteo[2]}</p></div></div>')
        st.write("")

        c = st.columns(4)
        _stat(c[0], "Séance", pedagogie.jour(derniere),
              f"{len(dates)} séances en archive", (BLEU, CYAN), "📅", 1)
        _stat(c[1], "Montent", "", "actions en hausse",
              ("#059669", "#34d399"), "🚀", 2, nombre=hausses)
        _stat(c[2], "Baissent", "", "actions en baisse",
              ("#e11d48", "#fb7185"), "📉", 3, nombre=baisses)
        _stat(c[3], "Argent échangé", pedagogie.montant(echange),
              "sur toute la séance", (VIOLET, ROSE), "💸", 4)

        if not connues.empty:
            total = max(len(connues), 1)
            _html(
                '<div class="carte anime d5" style="margin-top:1rem">'
                f'<div style="display:flex;justify-content:space-between;'
                f'font-weight:700;margin-bottom:.5rem">'
                f'<span style="color:{HAUSSE}">▲ {hausses} en hausse</span>'
                f'<span style="color:{DOUX}">● {stables} stables</span>'
                f'<span style="color:{BAISSE}">▼ {baisses} en baisse</span></div>'
                '<div class="jauge" style="height:16px;gap:3px;background:none">'
                f'<div style="flex:{hausses / total} 0 0;background:{HAUSSE};'
                'border-radius:999px"></div>'
                f'<div style="flex:{stables / total} 0 0;background:{STABLE};'
                'border-radius:999px;animation-delay:.15s"></div>'
                f'<div style="flex:{baisses / total} 0 0;background:{BAISSE};'
                'border-radius:999px;animation-delay:.3s"></div></div></div>')

            gauche, droite = st.columns(2)
            with gauche:
                _titre("🚀 Les plus fortes hausses")
                montee = connues[connues["variation"] > 0].nlargest(5, "variation")
                _html('<div class="carte anime">'
                      + (_palmares(montee, HAUSSE) if not montee.empty
                         else f'<p style="color:{DOUX}">Aucune hausse.</p>')
                      + '</div>')
            with droite:
                _titre("📉 Les plus fortes baisses")
                descente = connues[connues["variation"] < 0].nsmallest(5, "variation")
                _html('<div class="carte anime">'
                      + (_palmares(descente, BAISSE) if not descente.empty
                         else f'<p style="color:{DOUX}">Aucune baisse.</p>')
                      + '</div>')

            if connues["secteur"].notna().any():
                _titre("🧭 Les secteurs",
                       "La variation typique (médiane) des actions de chaque "
                       "famille de métiers.")
                par_secteur = (connues.dropna(subset=["secteur"])
                               .groupby("secteur")["variation"].median()
                               .sort_values(ascending=False))
                cartes = st.columns(len(par_secteur))
                for i, (colonne, (nom, var)) in enumerate(
                        zip(cartes, par_secteur.items()), start=1):
                    emo, teinte = _secteur(nom)
                    colonne.markdown(
                        f'<div class="carte secteur anime d{min(i, 7)}" '
                        f'style="border-top-color:{teinte};background:'
                        f'linear-gradient(180deg,{_rgba(teinte, .14)},{SURFACE} 70%)">'
                        f'<div class="emo">{emo}</div>'
                        f'<div class="nomsec">{html.escape(nom)}</div>'
                        f'{_pastille(var)}</div>', unsafe_allow_html=True)

        _titre("📋 Toutes les actions de la séance",
               "Cliquez sur un titre de colonne pour trier.")
        tableau = jour[["ticker", "nom", "secteur", "cloture", "variation",
                        "volume_fcfa"]].sort_values("variation", ascending=False)
        st.dataframe(
            tableau.style.map(
                lambda v: f"color:{_couleur(v)};font-weight:700",
                subset=["variation"]),
            width="stretch", hide_index=True, height=420,
            column_config={
                "ticker": st.column_config.TextColumn("Symbole"),
                "nom": st.column_config.TextColumn("Société"),
                "secteur": st.column_config.TextColumn("Secteur"),
                "cloture": st.column_config.NumberColumn(
                    "Prix (FCFA)", format="localized"),
                "variation": st.column_config.NumberColumn(
                    "Variation", format="percent",
                    help="Par rapport au prix de clôture de la séance "
                         "précédente."),
                "volume_fcfa": st.column_config.NumberColumn(
                    "Échangé (FCFA)", format="localized",
                    help="Montant total des achats et ventes de la séance."),
            })
        _legende(
            "**Météo** ☀️ / ⛅ / 🌧️ : plus d'actions en hausse, autant des deux, "
            "ou plus d'actions en baisse.",
            "**Vert ▲** = le prix a monté depuis la séance précédente, "
            "**rouge ▼** = il a baissé, **gris ●** = il n'a pas bougé.",
            "**Barre tricolore** : la part des actions qui montent, ne bougent "
            "pas, ou baissent.",
            "**Jauges des palmarès** : plus la barre est longue, plus la "
            "variation est forte (la première du classement remplit la barre).",
            "**Secteurs** : la variation *médiane* — la moitié des actions du "
            "secteur a fait mieux, l'autre moitié moins bien.",
            "**Argent échangé** : la somme de tous les achats de la séance. "
            "Une séance calme n'est pas une mauvaise séance.",
        )


# --- 🔎 Une action ----------------------------------------------------------
if onglets[1].open:
    with onglets[1]:
        cotees = sorted(cours["ticker"].unique())
        # La société choisie va dans l'URL : une fiche se partage par son
        # lien, `?onglet=action&valeur=SNTS`.
        _demandee = st.query_params.get("valeur")
        if "valeur" not in st.session_state and _demandee in cotees:
            st.session_state["valeur"] = _demandee
        choix = st.selectbox(
            "Choisissez une société (tapez son nom pour la chercher)", cotees,
            format_func=lambda t: f"{t} — {_nom(t)}",
            key="valeur", persist_state="session")
        if st.query_params.get("valeur") != choix:
            st.query_params["valeur"] = choix

        serie = (cours[cours["ticker"] == choix].dropna(subset=["cloture"])
                 .sort_values("date"))
        if serie.empty:
            st.warning("Aucun prix connu pour cette société.")
            st.stop()
        dernier = serie.iloc[-1]
        prix = float(dernier["cloture"])
        precedent = float(serie["cloture"].iloc[-2]) if len(serie) >= 2 else 0
        variation = prix / precedent - 1 if precedent > 0 else None
        secteur = secteurs_par_valeur.get(choix)
        emo, teinte = _secteur(secteur)
        nom = _nom(choix)

        if dernier["date"] != derniere:
            st.warning(f"⚠️ Pas de prix pour {choix} à la dernière séance : le "
                       f"dernier connu date du {pedagogie.jour(dernier['date'])}.")

        _html(
            f'<div class="carte anime" style="margin-top:.6rem;border-left:8px '
            f'solid {teinte};background:linear-gradient(120deg,'
            f'{_rgba(teinte, .16)},{SURFACE} 65%)">'
            '<div style="display:flex;flex-wrap:wrap;gap:1rem;'
            'align-items:center;justify-content:space-between">'
            f'<div><div style="font-size:2.4rem">{emo}</div>'
            f'<div style="font-size:1.6rem;font-weight:800">'
            f'{html.escape(nom)}</div>'
            f'<div style="color:{DOUX};font-weight:600">{html.escape(choix)} · '
            f'{_texte(secteur, "secteur inconnu")}</div></div>'
            '<div style="text-align:right">'
            f'<div style="color:{DOUX};font-size:.85rem;font-weight:700">'
            f'PRIX D\'UNE ACTION</div>'
            f'<div style="font-size:2.6rem;font-weight:800;line-height:1.1">'
            f'{pedagogie.montant(prix)}</div>'
            + (_pastille(variation) + f' <span style="color:{DOUX}">'
               'sur la séance</span>' if variation is not None else "")
            + '</div></div></div>')

        # Ce que seraient devenus 100 000 FCFA placés il y a 1 mois, 1 an, 5 ans.
        reculs = [(21, "1 mois", (BLEU, CYAN), "🗓️"),
                  (250, "1 an", (VIOLET, ROSE), "📆"),
                  (1250, "5 ans", (ORANGE, AMBRE), "⏳")]
        c = st.columns(3)
        for i, (pas, mot, couleurs, icone) in enumerate(reculs):
            if len(serie) > pas and serie["cloture"].iloc[-1 - pas] > 0:
                evol = prix / float(serie["cloture"].iloc[-1 - pas]) - 1
                _stat(c[i], f"Sur {mot}", f"{_fleche(evol)} "
                      f"{pedagogie.pourcentage(evol)}",
                      f"100 000 FCFA seraient devenus "
                      f"{pedagogie.montant(100_000 * (1 + evol))}",
                      couleurs, icone, i + 1)
            else:
                _stat(c[i], f"Sur {mot}", "—", "pas assez d'historique",
                      couleurs, icone, i + 1)
        st.caption("Évolution du prix seul : sans les dividendes reçus et sans "
                   "les frais d'achat et de vente. Le passé ne dit pas l'avenir.")

        if len(serie) >= 2:
            _titre("📈 L'évolution du prix")
            periodes = {"1 mois": 21, "6 mois": 125, "1 an": 250,
                        "5 ans": 1250, "Tout": None}
            periode = st.segmented_control(
                "Période", list(periodes), default="1 an",
                key="periode", label_visibility="collapsed") or "1 an"
            n = periodes[periode]
            vue = serie.tail(n + 1) if n else serie
            couleur = (HAUSSE if vue["cloture"].iloc[-1] >= vue["cloture"].iloc[0]
                       else BAISSE)
            vue = vue.assign(jour=pd.to_datetime(vue["date"]))
            survol = alt.selection_point(nearest=True, on="pointermove",
                                         fields=["jour"], empty=False)
            # Format explicite : les dates par défaut de Vega sont en anglais
            # (« Oct 26 »), quelle que soit la langue du lecteur.
            base = alt.Chart(vue).encode(
                x=alt.X("jour:T", title=None,
                        axis=alt.Axis(format="%d/%m/%y", tickCount=8)),
                # `stack=None` : une aire est empilée par défaut, ce qui
                # ramène l'axe à zéro et écrase la courbe tout en haut.
                y=alt.Y("cloture:Q", title="prix (FCFA)", stack=None,
                        scale=alt.Scale(zero=False), axis=alt.Axis(format="~s")))
            aire = base.mark_area(
                line={"color": couleur, "strokeWidth": 3},
                interpolate="monotone",
                color=alt.Gradient(
                    gradient="linear", x1=1, x2=1, y1=1, y2=0,
                    stops=[alt.GradientStop(color=_rgba(couleur, 0), offset=0),
                           alt.GradientStop(color=_rgba(couleur, .45), offset=1)]))
            capteur = base.mark_rule(strokeWidth=20, opacity=0).encode(
                tooltip=[alt.Tooltip("jour:T", title="Date", format="%d/%m/%Y"),
                         alt.Tooltip("cloture:Q", title="Prix (FCFA)",
                                     format=",.0f")]
            ).add_params(survol)
            point = base.mark_point(size=120, filled=True, color=couleur,
                                    stroke="white", strokeWidth=2
                                    ).transform_filter(survol)
            st.altair_chart((aire + capteur + point).properties(height=340),
                            width="stretch")
            st.caption("Survolez la courbe pour lire le prix d'un jour. Verte "
                       "si le prix a monté sur la période choisie, rouge sinon.")

        # --- La fiche avant d'acheter ou de vendre ------------------------
        _titre("🧭 Avant d'acheter ou de vendre : la fiche",
               "Six points à regarder. ✅ point fort · 🟡 correct · "
               "⚠️ vigilance · ℹ️ à savoir.")

        points = []
        recents = serie.tail(60)
        liquidite = float(recents["volume_fcfa"].median()) \
            if recents["volume_fcfa"].notna().any() else 0.0
        vides = int((recents["volume_fcfa"].fillna(0) == 0).sum())
        jours_vides = vides / max(len(recents), 1)
        if liquidite >= SEUIL_LIQUIDITE and jours_vides < 0.10:
            niveau, phrase = "bon", ("S'échange presque tous les jours : on "
                                     "achète et on revend sans trop attendre.")
        elif liquidite >= SEUIL_LIQUIDITE / 3:
            niveau, phrase = "moyen", ("S'échange régulièrement, mais pas en "
                                       "grande quantité : un gros ordre peut "
                                       "prendre plusieurs séances.")
        else:
            niveau, phrase = "attention", ("Très peu échangée : vous pourriez "
                                           "attendre longtemps pour revendre, "
                                           "ou devoir baisser votre prix.")
        points.append(("💧", "Facile à revendre ?",
                       f"{pedagogie.montant(liquidite)} / séance", niveau,
                       f"{phrase} "
                       + (f"Échangée à chacune des {len(recents)} dernières "
                          "séances." if not vides else
                          f"Aucun échange lors de {vides} des {len(recents)} "
                          "dernières séances.")))

        agitations = agitation_du_marche(cours, CLE)
        agitation = agitations.get(choix)
        if agitation is not None and agitation == agitation and len(agitations):
            typique = float(agitations.median())
            rapport = agitation / typique if typique else 1.0
            niveau = ("bon" if rapport < 0.8 else
                      "moyen" if rapport <= 1.3 else "attention")
            comparaison = ("plus calme que" if rapport < 0.8 else
                           "comparable à" if rapport <= 1.3 else
                           "plus agité que")
            points.append((
                "🎢", "Prix agité ?", f"±\u00a0{_pct(agitation)}",
                niveau,
                f"En une semaine ordinaire, son prix varie d'environ "
                f"±\u00a0{_pct(agitation)}. C'est {comparaison} l'action typique "
                f"(±\u00a0{_pct(typique)})."))

        an = serie.tail(251)
        if len(an) >= 20:
            chute = float((an["cloture"] / an["cloture"].cummax() - 1).min())
            niveau = ("bon" if chute > -0.15 else
                      "moyen" if chute > -0.30 else "attention")
            points.append((
                "🪂", "Pire chute (1 an)", _pct(chute, signe=True), niveau,
                "Au pire moment de l'année écoulée, une personne qui avait "
                f"acheté au plus haut perdait {_pct(-chute)}. C'est le genre "
                "de baisse qu'il faut être prêt à supporter."))
            haut_an, bas_an = float(an["cloture"].max()), float(an["cloture"].min())
            points.append((
                "🏔️", "Sur un an",
                f"{_pct(prix / haut_an - 1, signe=True)} du plus haut", "info",
                f"Plus haut de l'année : {pedagogie.montant(haut_an)}, plus bas : "
                f"{pedagogie.montant(bas_an)}. Un prix proche du plus bas n'est "
                "pas forcément une bonne affaire, ni l'inverse."))

        div_fiche = fondamentaux[(fondamentaux["ticker"] == choix)
                                 & (fondamentaux["indicateur"] == "dividende")]
        exercices = fondamentaux.loc[
            fondamentaux["indicateur"] == "dividende", "date"].nunique()
        if exercices:
            payes = int((div_fiche["valeur"] > 0).sum())
            if payes:
                dernier_div = float(div_fiche.sort_values("date")["valeur"].iloc[-1])
                rendement = dernier_div / prix if prix > 0 else float("nan")
                niveau = ("bon" if payes == exercices and rendement >= 0.05 else
                          "moyen")
                points.append((
                    "💰", "Dividendes ?",
                    f"{_pct(rendement)} par an", niveau,
                    f"Un dividende est connu pour {payes} des {exercices} "
                    f"dernières années. Le plus récent "
                    f"({pedagogie.montant(dernier_div)} net par action) "
                    "rapporte ce pourcentage au prix actuel."
                    + ("" if payes == exercices else
                       " Une année absente peut venir d'un trou dans la "
                       "source, pas forcément d'une absence de versement.")))
            else:
                points.append((
                    "💰", "Dividendes ?", "aucun connu",
                    "attention",
                    f"Aucun dividende trouvé pour les {exercices} dernières "
                    "années. Si elle n'en verse pas, tout le gain devra venir "
                    "de la hausse du prix, la partie la moins prévisible."))

        aller_retour = (1 + FRAIS_PAR_SENS / 100) / (1 - FRAIS_PAR_SENS / 100) - 1
        points.append((
            "💸", "Frais", f"≈ {_pct(aller_retour)}",
            "info",
            f"Un achat puis une revente coûtent environ {_pct(aller_retour)} "
            "(courtage, commissions, écart de prix). Le prix doit donc monter "
            "d'au moins autant pour que vous ne perdiez rien."))

        for debut in range(0, len(points), 3):
            colonnes = st.columns(3)
            for i, (icone, quoi, chiffre, niveau, texte) in enumerate(
                    points[debut:debut + 3]):
                symbole, teinte_n, mot_niveau = NIVEAUX[niveau]
                colonnes[i].markdown(
                    f'<div class="carte point anime d{i + 1}" style="'
                    f'border-left-color:{teinte_n};background:linear-gradient('
                    f'120deg,{_rgba(teinte_n, .10)},{SURFACE} 60%)">'
                    f'<div class="entete"><span class="quoi">{icone} {quoi}'
                    f'</span><span class="pastille" style="background:'
                    f'{_rgba(teinte_n, .15)};color:{teinte_n}">{symbole} '
                    f'{mot_niveau}</span></div>'
                    f'<div class="chiffre" style="color:{teinte_n}">{chiffre}</div>'
                    f'<p>{texte}</p></div>', unsafe_allow_html=True)

        # --- Le simulateur ------------------------------------------------
        _titre("🧮 Simuler un achat",
               "Ce que vous payez vraiment, et à partir de quel prix vous "
               "commencez à gagner.")
        with st.container(border=True):
            g, d = st.columns(2)
            somme = g.number_input(
                "Somme que vous voulez investir (FCFA)", min_value=10_000,
                max_value=1_000_000_000, value=500_000, step=50_000,
                key="sim_somme")
            frais = d.slider(
                "Frais par opération (%)", 0.0, 3.0, FRAIS_PAR_SENS, 0.1,
                key="sim_frais",
                help="Demandez le tarif exact à votre SGI. Il est payé à "
                     "l'achat ET à la vente.") / 100
            unitaire = prix * (1 + frais)
            actions = int(somme // unitaire) if unitaire > 0 else 0
            depense = actions * unitaire
            equilibre = prix * (1 + frais) / (1 - frais) if frais < 1 else prix
            r = st.columns(4)
            _stat(r[0], "Actions achetées", f"{actions:,}".replace(",", " "),
                  f"pour {pedagogie.montant(depense)} frais compris",
                  (BLEU, CYAN), "🧾", 1)
            _stat(r[1], "Prix pour ne rien perdre",
                  pedagogie.montant(equilibre),
                  f"à la revente, soit {_pct(equilibre / prix - 1, signe=True)}",
                  (ORANGE, AMBRE), "⚖️", 2)
            _stat(r[2], "Demain, au plus bas", pedagogie.montant(
                  prix * (1 - LIMITE_SEANCE)), "−7,5 % : la baisse maximale "
                  "autorisée en une séance", ("#e11d48", "#fb7185"), "🧱", 3)
            _stat(r[3], "Demain, au plus haut", pedagogie.montant(
                  prix * (1 + LIMITE_SEANCE)), "+7,5 % : la hausse maximale "
                  "autorisée en une séance", ("#059669", "#34d399"), "🚀", 4)
            if actions == 0:
                st.warning("Cette somme ne suffit pas pour acheter une seule "
                           "action à ce prix, frais compris.")
            st.caption("💡 Conseil de prudence : passez un ordre « à cours "
                       "limité » (vous fixez le prix maximum à l'achat, ou "
                       "minimum à la vente), surtout sur une action peu "
                       "échangée.")

        par_an = fondamentaux[(fondamentaux["ticker"] == choix)
                              & (fondamentaux["indicateur"] == "dividende")]
        versements = dividendes[dividendes["ticker"] == choix] \
            if not dividendes.empty else pd.DataFrame()
        if not par_an.empty:
            _titre("💰 Les dividendes versés",
                   "Le dividende net (après impôt) d'une action, au titre de "
                   "chaque année — source : sikafinance.")
            par_an = par_an.assign(annee=par_an["date"].str[:4])
            st.altair_chart(
                alt.Chart(par_an).mark_bar(cornerRadiusTopLeft=10,
                                           cornerRadiusTopRight=10, size=46)
                .encode(
                    x=alt.X("annee:N", title=None, axis=alt.Axis(labelAngle=0)),
                    y=alt.Y("valeur:Q", title="FCFA net par action"),
                    color=alt.Color("annee:N", legend=None, scale=alt.Scale(
                        range=[VIOLET, BLEU, CYAN, HAUSSE, AMBRE, ORANGE, ROSE])),
                    tooltip=[alt.Tooltip("annee:N", title="Exercice"),
                             alt.Tooltip("valeur:Q", title="Dividende net (FCFA)",
                                         format=",.0f")])
                .properties(height=260), width="stretch")
        if not versements.empty:
            dernier_v = versements.sort_values("date_detachement").iloc[-1]
            st.info(f"📅 Dernier détachement connu : le "
                    f"**{pedagogie.jour(dernier_v['date_detachement'])}**, "
                    f"{pedagogie.montant(dernier_v['montant'])} par action "
                    "selon brvm.org. Ce montant peut différer du dividende net "
                    "ci-dessus : brvm.org annonce parfois le montant avant "
                    "impôt, ou un versement en plusieurs fois. Pour toucher un "
                    "dividende, il faut détenir l'action **avant** le jour du "
                    "détachement — la vendre juste avant, c'est y renoncer.")
        elif par_an.empty:
            st.info("Aucun dividende connu pour cette société dans l'archive.")

        # --- La prévision, en dernier : c'est le calcul le plus long ------
        _titre("🔮 Et dans les mois qui viennent ?",
               "L'avis du modèle de prévision, à un mois et à un trimestre — "
               "un indice, pas une promesse.")
        devins = {h: prevoir(cours, referentiel, CLE, h) for h in HORIZONS}
        # Trois issues par échéance : un avis sur cette action, le silence
        # d'un devin qui a échoué, ou rien — l'action n'est pas notée.
        avis, silences = {}, {}
        for horizon, devin in devins.items():
            if not devin["pret"]:
                continue
            if devin["echoue"]:
                silences[horizon] = devin
                continue
            ligne = devin["probas"][devin["probas"]["ticker"] == choix]
            if not ligne.empty:
                avis[horizon] = (ligne.iloc[0], len(devin["probas"]))
        if not any(devin["pret"] for devin in devins.values()):
            st.info("Pas encore assez d'historique pour une prévision.")
        elif not avis and not silences:
            st.info(f"Pas de prévision pour {choix} : le modèle ne note que "
                    "les actions échangées à la dernière séance, et dont "
                    "l'historique est assez long.")
        else:
            colonnes = st.columns(len(HORIZONS))
            for i, (colonne, horizon) in enumerate(zip(colonnes, HORIZONS),
                                                   start=1):
                echeance = f'{HORIZONS[horizon]["bouton"]} · {horizon} séances'
                if horizon in silences:
                    colonne.markdown(
                        f'<div class="carte anime d{i}" style="border-left:8px '
                        f'solid {STABLE};background:linear-gradient(120deg,'
                        f'{_rgba(STABLE, .14)},{SURFACE} 60%)">'
                        f'<div class="echeance">{echeance}</div>'
                        '<div class="meteo"><span class="emoji">🤐</span>'
                        '<div><h3>Le devin se tait</h3>'
                        f'<p>{_phrase(_silence(silences[horizon]))} : il ne '
                        'donne pas d\'avis à cette échéance tant que c\'est '
                        'le cas.</p></div></div></div>',
                        unsafe_allow_html=True)
                    continue
                if horizon not in avis:
                    colonne.info(f"{echeance} : pas de prévision à cette "
                                 "échéance.")
                    continue
                ligne, notees = avis[horizon]
                rang = int(ligne.name) + 1
                symbole, mot_meteo, teinte_m = _meteo_prevision(
                    float(ligne["rang_combine"]))
                colonne.markdown(
                    f'<div class="carte anime d{i}" style="border-left:8px '
                    f'solid {teinte_m};background:linear-gradient(120deg,'
                    f'{_rgba(teinte_m, .14)},{SURFACE} 60%)">'
                    f'<div class="echeance">{echeance}</div>'
                    '<div class="meteo"><span class="emoji">'
                    f'{symbole}</span><div><h3>{mot_meteo}</h3>'
                    f'<p><b>{pedagogie.ordinal(rang)}</b> sur {notees} au '
                    'classement du modèle. Il estime à '
                    f'<b>{_pct(ligne["probabilite"])}</b> ses chances de faire '
                    'mieux que la moitié des actions du marché.</p></div></div>'
                    f'{_regle_piece(float(ligne["probabilite"]))}</div>',
                    unsafe_allow_html=True)
            # La réserve de l'onglet Prédictions vaut aussi ici : sans elle, une
            # carte ☀️ au trimestre se lirait comme un avis aussi solide que
            # celui du mois.
            fragiles = [HORIZONS[h]["un"] for h, devin in devins.items()
                        if h in avis and devin["avantage"].get("dates")
                        and not devin["avantage"].get("significatif")]
            phrases = []
            if avis:
                phrases.append("Une pièce de monnaie ferait 50 %. Le modèle ne "
                               "s'en écarte que de quelques points : c'est un "
                               "léger penchant, pas une certitude.")
            if len(avis) > 1:
                phrases.append("Il est entraîné à part pour chaque échéance, "
                               "d'où deux avis qui peuvent différer.")
            if fragiles:
                jointes = " et d'".join(fragiles)
                phrases.append(f"À l'échéance d'{jointes}, même l'avance de ses "
                               "favorites n'est pas démontrée.")
            phrases.append("Tous les détails dans l'onglet 🔮 Prédictions.")
            st.caption(" ".join(phrases))

        _legende(
            "**Les 100 000 FCFA** : ce qu'aurait donné un achat il y a 1 mois, "
            "1 an ou 5 ans, au prix seul (sans dividendes ni frais).",
            "**La fiche** : ✅ point fort, 🟡 correct, ⚠️ point de vigilance, "
            "ℹ️ simple information. Aucun point ne suffit à décider seul.",
            "**Facile à revendre ?** : le montant échangé un jour ordinaire "
            "(médiane des 60 dernières séances). Sous "
            f"{pedagogie.montant(SEUIL_LIQUIDITE)}, revendre peut être lent.",
            "**Prix agité ?** : l'écart habituel du prix sur "
            "une semaine, mesuré sur un an, comparé à l'action typique.",
            "**Prix pour ne rien perdre** : le prix de revente qui rembourse "
            "exactement vos frais d'achat et de vente.",
            "**±7,5 %** : la BRVM interdit à un prix de varier de plus de 7,5 % "
            "en une séance.",
            "**La météo de la prévision** : ☀️ dans le tiers le mieux placé "
            "par le modèle, ⛅ dans le tiers du milieu, 🌧️ dans le dernier "
            "tiers. La règle colorée place l'action entre 40 % et 60 % de "
            "chances, autour du 🪙 50 % d'un pile ou face.",
            "**Le mois / le trimestre qui vient** : les 20 ou 60 prochaines "
            "séances de bourse à partir de la dernière clôture, et non le "
            "mois du calendrier.",
            "**🤐 Le devin se tait** : à une échéance où il n'a pas fait ses "
            "preuves sur les années qu'il n'avait jamais vues, il ne donne "
            "pas d'avis plutôt qu'un avis qu'il ne peut pas défendre.",
        )


# --- 🔮 Prédictions ---------------------------------------------------------
if onglets[2].open:
    with onglets[2]:
        # Toute la page suit l'échéance choisie : le bilan, la météo, l'avance
        # et les frais d'un mois ne se lisent pas avec ceux d'un trimestre.
        choisi = st.segmented_control(
            "Prévoir pour", list(HORIZONS),
            format_func=lambda h: HORIZONS[h]["bouton"],
            default=HORIZON_DEFAUT, required=True, key="horizon",
            persist_state="session", label_visibility="collapsed")
        mots = HORIZONS[choisi]
        devin = prevoir(cours, referentiel, CLE, choisi)
        if not devin["pret"]:
            st.info(
                "🔮 Le devin a besoin de plus d'historique : "
                f"{devin.get('lignes', 0)} observations sur les "
                f"{devin.get('minimum', 0)} nécessaires.")
        else:
            horizon = devin["horizon"]
            probas = devin["probas"]
            periodes = devin["periodes"]
            avantage = devin["avantage"]
            echoue = devin["echoue"]
            precision = float(periodes["precision"].mean())
            annees_gagnees = int((periodes["precision"] > 0.5).sum())
            calibree = bool(probas["calibree"].all()) if not probas.empty else False

            _html(
                '<div class="oracle anime">'
                '<div><span class="boule">🔮</span></div>'
                '<div style="flex:1;min-width:260px">'
                '<h3>La boule de cristal… honnête</h3>'
                '<p>Notre « devin » est un modèle statistique entraîné sur '
                'onze ans de séances. Il ne devine pas les prix : il classe les '
                f'actions selon leurs chances de <b>faire mieux que la moitié '
                f'du marché</b> pendant {_horizon_en_mots(horizon)}. '
                'Prévoir la bourse, c\'est presque jouer à pile ou face — et '
                + ('voici exactement ce qu\'il vaut face à une pièce.' if echoue
                   else 'voici exactement de combien il fait mieux qu\'une '
                   'pièce.')
                + '</p></div><div><span class="piece">🪙</span></div></div>')

            # LE GARDE-FOU. Quand le modèle échoue à sa porte de production,
            # `prevoir` ne rend aucune probabilité : la météo, le favori et le
            # piège des frais disparaissent de cette échéance, et le bilan
            # reste — c'est lui qui montre pourquoi. Voir `prevoir`.
            if echoue:
                st.warning(
                    f"**À l'échéance d'{mots['un']}, le devin se tait.** "
                    f"{_phrase(_silence(devin))}. Plutôt que d'afficher un "
                    "classement qu'il ne peut pas défendre, il ne donne pas de "
                    "météo à cette échéance tant que c'est le cas ; son bilan "
                    "ci-dessous montre pourquoi.")
            if devin.get("motif"):
                st.info(devin["motif"])
            if not calibree and not echoue:
                st.warning("Calibrage indisponible : les pourcentages ci-dessous "
                           "sont des rangs, pas des probabilités.")

            _titre("🎯 Le devin a-t-il eu raison par le passé ?",
                   "Testé honnêtement : chaque année, il n'avait jamais vu les "
                   "séances sur lesquelles on le juge.")
            c = st.columns(4)
            _stat(c[0], "Bonnes réponses", _pct(precision),
                  "en moyenne · une pièce : 50 %", (VIOLET, BLEU), "🎯", 1)
            _stat(c[1], "Années au-dessus de 50 %", "",
                  f"sur {len(periodes)} années de test", ("#059669", "#34d399"),
                  "🏆", 2, nombre=annees_gagnees)
            demontree = bool(avantage.get("significatif"))
            if avantage.get("dates"):
                sens = ("de mieux que le marché" if avantage["avantage"] >= 0
                        else "d'écart avec le marché")
                _stat(c[2], "Avance de ses 10 favorites",
                      _pct(avantage["avantage"], signe=True),
                      f"{sens}, par {mots['unite']}, en moyenne"
                      + ("" if demontree or echoue else " — pas démontrée"),
                      (CYAN, TURQUOISE), "🚀", 3)
            else:
                _stat(c[2], "Avance de ses favorites", "—",
                      "pas encore mesurable", (CYAN, TURQUOISE), "🚀", 3)
            aller_retour = 2 * FRAIS_PAR_SENS / 100
            _stat(c[3], "Frais d'un aller-retour", f"≈ {_pct(aller_retour)}",
                  "achat + revente, chez une SGI", ("#e11d48", "#fb7185"), "💸", 4)

            # Plus l'échéance est longue, moins l'archive contient de périodes
            # indépendantes pour juger : une quarantaine de trimestres en onze
            # ans. L'avance peut alors rester positive sans sortir de sa marge
            # d'erreur — c'est le cas au trimestre sur l'archive d'octobre
            # 2026 —, et l'afficher sans le dire la ferait passer pour acquise.
            if avantage.get("dates") and not demontree and not echoue:
                st.warning(
                    f"**À l'échéance d'{mots['un']}, l'avance des favorites "
                    "n'est pas démontrée.** Le bilan ne repose que sur "
                    f"{avantage.get('blocs', 0)} {mots['unites']} "
                    "indépendants, et l'écart mesuré "
                    f"({_pct(avantage['avantage'], signe=True)}) reste dans sa "
                    "marge d'erreur (± "
                    f"{_pct(2 * avantage.get('erreur_type', float('nan')))}) : "
                    "il peut n'être que du hasard.")

            precisions = periodes.assign(
                annee=periodes["periode"].str[-10:-6],
                juste=periodes["precision"] > 0.5)
            # Les barres partent de la ligne des 50 % : au-dessus, le devin
            # bat la pièce ; en dessous, il fait moins bien qu'elle. L'axe
            # s'élargit plutôt que de couper une barre qui en sortirait : au
            # trimestre, la pire année frôle déjà les 46 %.
            bas = min(0.46, float(precisions["precision"].min()) - 0.01)
            haut = max(0.58, float(precisions["precision"].max()) + 0.01)
            barres = alt.Chart(precisions).transform_calculate(
                piece="0.5").mark_bar(size=34, clip=True).encode(
                x=alt.X("annee:N", title="année de test",
                        axis=alt.Axis(labelAngle=0)),
                y=alt.Y("precision:Q", title="bonnes réponses",
                        scale=alt.Scale(domain=[bas, haut], zero=False),
                        axis=alt.Axis(format=".0%", tickCount=6)),
                y2="piece:Q",
                color=alt.condition(alt.datum.precision > 0.5,
                                    alt.value(HAUSSE), alt.value(BAISSE)),
                tooltip=[alt.Tooltip("periode:N", title="Période"),
                         alt.Tooltip("precision:Q", title="Bonnes réponses",
                                     format=".1%")])
            piece = alt.Chart(pd.DataFrame({"y": [0.5]})).mark_rule(
                color=ENCRE, strokeDash=[6, 4], strokeWidth=2).encode(y="y:Q")
            etiquette = alt.Chart(pd.DataFrame(
                {"y": [0.5], "t": ["🪙 pile ou face"]})).mark_text(
                align="left", dx=4, dy=-8, color=ENCRE, fontWeight="bold",
                fontSize=13).encode(y="y:Q", x=alt.value(0), text="t:N")
            st.altair_chart((barres + piece + etiquette).properties(height=300),
                            width="stretch")
            st.caption(
                f"Chaque barre : la part de fois où le devin a eu raison en "
                f"disant si une action ferait mieux ou moins bien que la "
                f"moitié du marché sur {horizon} séances. Au-dessus du "
                "pointillé, il bat la pièce de monnaie ; en dessous, il fait moins "
                "bien qu'elle. L'axe est resserré pour que les écarts se "
                "voient : ils sont petits.")

            # Le devin qui se tait n'a ni météo, ni favori, ni frais à
            # faire payer : ces sections supposent un classement à suivre.
            if not echoue:
                # --- La météo de l'échéance choisie -------------------------
                _titre(f"🌦️ La météo du devin pour {_horizon_en_mots(horizon)}",
                       "Les actions échangées à la dernière séance, rangées en "
                       "trois groupes égaux selon l'avis du modèle. C'est un "
                       "classement relatif : même les ☀️ restent autour de 50 %.")
                colonnes = st.columns(3)
                groupes = [
                    ("☀️", "Plutôt favorable", HAUSSE, lambda r: r >= 2 / 3),
                    ("⛅", "Neutre", AMBRE, lambda r: 1 / 3 <= r < 2 / 3),
                    ("🌧️", "Plutôt défavorable", BAISSE, lambda r: r < 1 / 3)]
                for i, (symbole, mot, teinte_g, regle) in enumerate(groupes):
                    membres = probas[probas["rang_combine"].map(regle)]
                    puces = "".join(
                        f'<span class="puce-valeur" title="{html.escape(_nom(t))}" '
                        f'style="background:{_rgba(teinte_g, .14)};color:{teinte_g}">'
                        f'{html.escape(t)} · {_pct(p)}</span>'
                        for t, p in zip(membres["ticker"], membres["probabilite"]))
                    colonnes[i].markdown(
                        f'<div class="carte anime d{i + 1}" style="border-top:6px '
                        f'solid {teinte_g};background:linear-gradient(180deg,'
                        f'{_rgba(teinte_g, .12)},{SURFACE} 55%)">'
                        f'<div style="font-size:2.4rem">{symbole}</div>'
                        f'<div style="font-weight:800;font-size:1.15rem">{mot}</div>'
                        f'<div style="color:{DOUX};font-size:.85rem;'
                        f'margin-bottom:.4rem">{len(membres)} actions</div>'
                        f'{puces}</div>', unsafe_allow_html=True)

                if not probas.empty:
                    meilleure = probas.iloc[0]
                    pire = probas.iloc[-1]
                    st.write("")
                    _html(
                        '<div class="carte anime">'
                        f'<b>🥇 Le favori du devin : {html.escape(meilleure["ticker"])}'
                        f'</b> ({html.escape(_nom(meilleure["ticker"]))}), avec '
                        f'<b>{_pct(meilleure["probabilite"])}</b> de chances. '
                        f'Le moins bien placé, {html.escape(pire["ticker"])}, en a '
                        f'<b>{_pct(pire["probabilite"])}</b>. Entre le premier et le '
                        'dernier, l\'écart tient en quelques points : <b>même le '
                        'favori perd presque une fois sur deux</b>.'
                        f'{_regle_piece(float(meilleure["probabilite"]))}</div>')

                    with st.expander("📊 Le détail, action par action"):
                        detail = probas.assign(
                            nom=probas["ticker"].map(_nom),
                            meteo=probas["rang_combine"].map(
                                lambda r: " ".join(_meteo_prevision(r)[:2])))
                        st.altair_chart(
                            alt.Chart(detail).mark_bar(
                                cornerRadiusEnd=6, height=12).encode(
                                x=alt.X("probabilite:Q", title="chances de faire "
                                        "mieux que la moitié du marché",
                                        scale=alt.Scale(domain=[0.4, 0.6]),
                                        axis=alt.Axis(format=".0%")),
                                y=alt.Y("ticker:N", sort="-x", title=None,
                                        axis=alt.Axis(labelOverlap=False)),
                                color=alt.Color("rang_combine:Q", legend=None,
                                                scale=alt.Scale(range=[
                                                    BAISSE, AMBRE, HAUSSE])),
                                tooltip=[alt.Tooltip("ticker:N", title="Symbole"),
                                         alt.Tooltip("nom:N", title="Société"),
                                         alt.Tooltip("probabilite:Q",
                                                     title="Chances", format=".1%"),
                                         alt.Tooltip("meteo:N", title="Météo")])
                            .properties(height=max(260, 17 * len(detail)))
                            + alt.Chart(pd.DataFrame({"x": [0.5]})).mark_rule(
                                color=ENCRE, strokeDash=[6, 4]).encode(x="x:Q"),
                            width="stretch")
                        st.dataframe(
                            detail[["ticker", "nom", "meteo", "probabilite",
                                    "incertitude"]],
                            width="stretch", hide_index=True,
                            column_config={
                                "ticker": st.column_config.TextColumn("Symbole"),
                                "nom": st.column_config.TextColumn("Société"),
                                "meteo": st.column_config.TextColumn("Météo"),
                                "probabilite": st.column_config.NumberColumn(
                                    "Chances", format="percent"),
                                "incertitude": st.column_config.NumberColumn(
                                    "± incertitude", format="percent",
                                    help="De combien l'estimation bougerait avec "
                                         "un autre historique. L'incertitude du "
                                         "marché lui-même est bien plus grande."),
                            })

                # --- Le piège des frais -------------------------------------
                _titre("🪤 Le piège des frais",
                       "Pourquoi suivre le devin à la lettre ferait perdre de "
                       "l'argent.")
                g, d = st.columns(2)
                _stat(g, "Sans aucun frais",
                      f"{_pct(mots['sans_frais'], signe=True)} / an",
                      "de mieux que le marché, en suivant ses favorites chaque "
                      f"{mots['unite']}", ("#059669", "#34d399"), "😃", 1)
                _stat(d, "Avec des frais réalistes (1,5 % par opération)",
                      f"{_pct(mots['avec_frais'], signe=True)} / an",
                      "de moins bien que le marché : les frais dévorent l'avance",
                      ("#e11d48", "#fb7185"), "😱", 2)
                if avantage.get("dates") and avantage.get("avantage", 0) > 0:
                    a_rembourser = max(1, round(aller_retour / avantage["avantage"]))
                    duree = (f"{a_rembourser} "
                             + (mots["unite"] if a_rembourser == 1
                                else mots["unites"]))
                    st.write("")
                    _html(
                        '<div class="lecon anime">'
                        '<b>🧮 Le calcul qui tue :</b> ses favorites prennent en '
                        f'moyenne <b>{_pct(avantage["avantage"], signe=True)}</b> '
                        f'd\'avance sur le marché en {mots["un"]}. Un achat suivi '
                        f'd\'une revente coûte environ <b>{_pct(aller_retour)}</b>. '
                        f'Il faudrait donc environ <b>{duree}</b> '
                        'd\'avance pour rembourser les frais d\'une seule '
                        'opération… alors que la prévision ne vaut que pour '
                        f'{mots["un"]}.</div>')
                st.caption(
                    "Les deux rendements annuels viennent du rejeu de la stratégie "
                    "— le modèle de cette échéance, ses favorites rachetées chaque "
                    f"{mots['unite']} — sur le prix seul (hors dividendes), en "
                    "moyenne sur plusieurs calendriers, sur l'archive arrêtée au "
                    f"{ARCHIVE_DU_REJEU} (détails et commandes pour le refaire dans "
                    "docs/technique.md). L'avance mesurée plus haut compte chaque "
                    "séance, au prix du jour de la décision ; le rejeu, lui, "
                    "achète à la séance suivante et seulement une fois par "
                    f"{mots['unite']}, comme on le ferait vraiment : il en garde "
                    "moins. Le reste de la page est recalculé sur les données du "
                    "jour.")

                _titre("🤔 Alors, à quoi sert le devin ?")
                c = st.columns(3)
                usages = [
                    ("✅", "Un indice de plus", "Pour départager deux actions qui "
                     "vous plaisent pour d'autres raisons (dividende, facilité de "
                     "revente).", HAUSSE),
                    ("🚫", "Pas un signal d'achat", "Acheter et vendre chaque "
                     f"{mots['unite']} selon ses favorites coûte plus en frais que "
                     "ça ne rapporte.", BAISSE),
                    ("🧘", "La patience paie mieux", "Sur ce marché, ce qui rapporte "
                     "régulièrement, ce sont les dividendes d'actions gardées "
                     "longtemps.", VIOLET),
                ]
                for i, (emo, quoi, texte, teinte_u) in enumerate(usages):
                    c[i].markdown(
                        f'<div class="carte mot anime d{i + 1}" style="'
                        f'border-left-color:{teinte_u};background:linear-gradient('
                        f'120deg,{_rgba(teinte_u, .12)},{SURFACE} 70%)">'
                        f'<div style="font-size:2rem">{emo}</div><h4>{quoi}</h4>'
                        f'<p>{texte}</p></div>', unsafe_allow_html=True)

            _legende(
                "**Faire mieux que la moitié du marché** : sur la période, "
                "l'action monte plus (ou baisse moins) que l'action du milieu "
                "du classement. Une action peut « faire mieux » et baisser, si "
                "tout le marché baisse davantage.",
                "**Bonnes réponses** : la part de fois où le devin a eu raison "
                "sur ce point, testée sur des années qu'il n'avait jamais vues.",
                "**Chances** : estimées à partir de ce qui s'est réellement "
                "produit par le passé pour les actions classées au même rang. "
                "C'est pour cela qu'elles restent proches de 50 %.",
                "**Météo** ☀️ / ⛅ / 🌧️ : le tiers du classement du devin où "
                "se trouve l'action. C'est un classement *relatif* : il y a "
                "toujours un tiers d'actions ☀️, même quand tout le marché "
                "baisse.",
                "**Avance de ses 10 favorites** : ce que les dix actions les "
                "mieux classées (parmi celles qui s'échangent assez) ont gagné "
                f"de plus que la moyenne du marché, par {mots['unite']}. "
                "« Pas démontrée » : l'écart reste dans sa marge d'erreur, il "
                "peut n'être que du hasard.",
                "**± incertitude** : de combien l'estimation bougerait si "
                "l'historique avait été un peu différent.",
                "**Le mois / le trimestre qui vient** : les 20 ou 60 prochaines "
                "séances de bourse à partir de la dernière clôture, et non le "
                "mois du calendrier. Le devin est entraîné à part pour chaque "
                "échéance : son bilan, sa météo et ses frais changent avec "
                "elle.",
                "**🤐 Le devin se tait** : à une échéance où il n'a pas fait "
                "ses preuves sur les années qu'il n'avait jamais vues, il ne "
                "donne pas de météo plutôt qu'une météo qu'il ne peut pas "
                "défendre. Son bilan reste affiché : c'est lui qui dit pourquoi.",
            )


# --- 💰 Dividendes ----------------------------------------------------------
if onglets[3].open:
    with onglets[3]:
        _html(
            '<div class="lecon anime"><b>💡 Le secret de la BRVM : '
            'les dividendes.</b><br>Chaque année, beaucoup de sociétés cotées '
            'reversent une partie de leurs bénéfices à leurs actionnaires. Sur '
            'ce marché, c\'est la partie <b>la plus régulière</b> du gain : '
            'en général 7 à 10 % du prix de l\'action par an ces dernières '
            'années, alors que les prix, eux, montent et descendent sans '
            'prévenir.</div>')

        rendements = fondamentaux[fondamentaux["indicateur"] == "rendement"]
        if rendements.empty:
            st.info("Aucun rendement de dividende en archive pour l'instant.")
        else:
            # Le rendement typique, exercice par exercice.
            typique = (rendements.groupby("date")["valeur"].median()
                       .reset_index())
            typique["annee"] = typique["date"].str[:4]
            _titre("📊 Le rendement typique, année après année",
                   "Rendement médian : la moitié des sociétés font mieux, "
                   "l'autre moitié moins bien.")
            c = st.columns(len(typique))
            palette = [(BLEU, CYAN), (VIOLET, ROSE), (ORANGE, AMBRE),
                       ("#059669", "#34d399"), ("#e11d48", "#fb7185")]
            for i, (colonne, ligne) in enumerate(zip(c, typique.itertuples())):
                _stat(colonne, f"Exercice {ligne.annee}",
                      _pct(ligne.valeur / 100), "de rendement médian",
                      palette[i % len(palette)], "💰", i + 1)

            exercice = rendements["date"].max()
            recent = (rendements[rendements["date"] == exercice]
                      .assign(nom=lambda t: t["ticker"].map(_nom),
                              secteur=lambda t: t["ticker"].map(secteurs_par_valeur))
                      .sort_values("valeur", ascending=False))
            _titre(f"🏆 Les plus généreuses — exercice {exercice[:4]}",
                   "Dividende de l'année divisé par le prix de l'action.")
            tete = recent.head(15)
            st.altair_chart(
                alt.Chart(tete).mark_bar(cornerRadiusEnd=8, height=20).encode(
                    x=alt.X("valeur:Q", title="rendement du dividende (%)"),
                    y=alt.Y("ticker:N", sort="-x", title=None,
                            axis=alt.Axis(labelOverlap=False)),
                    color=alt.Color("valeur:Q", legend=None, scale=alt.Scale(
                        range=[AMBRE, ORANGE, ROSE, VIOLET])),
                    tooltip=[alt.Tooltip("ticker:N", title="Symbole"),
                             alt.Tooltip("nom:N", title="Société"),
                             alt.Tooltip("valeur:Q", title="Rendement (%)",
                                         format=".2f"),
                             alt.Tooltip("secteur:N", title="Secteur")])
                .properties(height=max(260, 28 * len(tete))), width="stretch")
            st.caption("⚠️ Un rendement très élevé peut aussi venir d'un prix "
                       "qui s'est effondré, ou d'un versement exceptionnel. "
                       "Regardez toujours la fiche de la société avant de "
                       "conclure.")

        if not dividendes.empty:
            _titre("📅 Les derniers versements",
                   "Les dix détachements les plus récents, montants annoncés "
                   "par brvm.org (parfois avant impôt : ils peuvent différer "
                   "du dividende net des fiches).")
            derniers_v = (dividendes.sort_values("date_detachement",
                                                 ascending=False).head(10))
            couleurs_v = [VIOLET, BLEU, CYAN, HAUSSE, AMBRE, ORANGE, ROSE,
                          TURQUOISE, "#6366f1", "#e11d48"]
            for debut in range(0, len(derniers_v), 5):
                colonnes = st.columns(5)
                for i, v in enumerate(derniers_v.iloc[debut:debut + 5].itertuples()):
                    teinte_v = couleurs_v[(debut + i) % len(couleurs_v)]
                    colonnes[i].markdown(
                        f'<div class="carte anime d{i + 1}" style="border-top:'
                        f'5px solid {teinte_v};margin-bottom:1rem;text-align:'
                        f'center"><div style="font-weight:800;color:{teinte_v};'
                        f'font-size:1.1rem">{_texte(v.ticker)}</div>'
                        f'<div style="color:{DOUX};font-size:.75rem;'
                        f'min-height:2.2em">{html.escape(_nom(v.ticker))}</div>'
                        f'<div style="font-size:1.25rem;font-weight:800">'
                        f'{pedagogie.montant(v.montant)}</div>'
                        f'<div style="color:{DOUX};font-size:.8rem">par action, '
                        f'le {pedagogie.jour(v.date_detachement)}</div></div>',
                        unsafe_allow_html=True)

        # Le calculateur : la question que se pose vraiment un débutant.
        _titre("🧮 Combien rapporterait mon épargne ?",
               "Une estimation à partir du dernier dividende net connu.")
        tous_div = (fondamentaux[fondamentaux["indicateur"] == "dividende"]
                    .sort_values("date").groupby("ticker").last())
        prix_jour = (cours[cours["date"] == derniere]
                     .set_index("ticker")["cloture"])
        candidates = sorted(set(tous_div.index) & set(prix_jour.dropna().index))
        if candidates:
            with st.container(border=True):
                g, d = st.columns(2)
                societe = g.selectbox(
                    "Société", candidates,
                    format_func=lambda t: f"{t} — {_nom(t)}",
                    key="calc_societe")
                somme = d.number_input("Somme investie (FCFA)", min_value=10_000,
                                       max_value=1_000_000_000, value=500_000,
                                       step=50_000, key="calc_somme")
                p = float(prix_jour[societe])
                div = float(tous_div.loc[societe, "valeur"])
                annee_div = str(tous_div.loc[societe, "date"])[:4]
                # Les frais d'achat se paient dès le départ : on achète moins
                # d'actions que la somme divisée par le prix.
                unitaire = p * (1 + FRAIS_PAR_SENS / 100)
                actions = int(somme // unitaire) if unitaire > 0 else 0
                gain = actions * div
                r = st.columns(3)
                _stat(r[0], "Actions achetées", f"{actions:,}".replace(",", " "),
                      f"à {pedagogie.montant(p)} l'une, frais d'achat compris",
                      (BLEU, CYAN), "🧾", 1)
                _stat(r[1], "Dividende par an", pedagogie.montant(gain),
                      f"{pedagogie.montant(div)} net par action (exercice "
                      f"{annee_div})", ("#059669", "#34d399"), "💵", 2)
                _stat(r[2], "Rendement", _pct(gain / somme if somme else 0),
                      "de la somme investie", (VIOLET, ROSE), "📈", 3)
                st.caption("Dividende net d'impôt, tel que publié par "
                           "sikafinance. Rien ne garantit qu'il sera le même "
                           "l'an prochain : il dépend des bénéfices de la "
                           "société.")

        _legende(
            "**Rendement du dividende** : le dividende de l'année divisé par le "
            "prix de l'action. 8 % = 8 000 FCFA par an pour 100 000 FCFA "
            "investis.",
            "**Dividende net** : ce qui arrive réellement sur votre compte, "
            "après l'impôt prélevé à la source. Les montants annoncés par "
            "brvm.org sont parfois bruts (avant impôt) : de petits écarts "
            "entre les deux sont normaux.",
            "**Exercice** : l'année comptable dont les bénéfices sont "
            "distribués. Le versement a lieu l'année suivante.",
            "**Détachement** : le jour où le dividende quitte l'action pour "
            "votre compte. Le prix baisse d'autant ce jour-là : ce n'est pas "
            "une perte.",
            "**Couleurs des barres** : plus la barre est chaude (vers le rose "
            "et le violet), plus le rendement est élevé.",
        )


# --- 🎓 Comprendre ----------------------------------------------------------
LEXIQUE = [
    ("Action", "📄", "Un petit morceau d'une entreprise. En posséder, c'est en "
     "être un peu propriétaire.", BLEU),
    ("BRVM", "🌍", "Bourse Régionale des Valeurs Mobilières : la bourse "
     "commune aux huit pays de l'UEMOA, installée à Abidjan.", VIOLET),
    ("Séance", "🔔", "Une journée de bourse — environ 250 par an, ni week-ends "
     "ni jours fériés.", CYAN),
    ("Prix de clôture", "🏁", "Le prix de l'action à la fin de la séance. "
     "C'est celui qu'affiche cette application.", VIOLET),
    ("Variation", "↕️", "L'écart entre le prix de clôture du jour et celui de "
     "la séance précédente, en pourcentage.", HAUSSE),
    ("Dividende", "💰", "La part du bénéfice que la société reverse chaque "
     "année à ses actionnaires.", HAUSSE),
    ("Rendement", "📈", "Le dividende divisé par le prix de l'action. 8 % veut "
     "dire 8 000 FCFA par an pour 100 000 investis.", AMBRE),
    ("Détachement", "✂️", "Le jour où le dividende est versé. Le prix baisse "
     "d'autant ce jour-là : ce n'est pas une perte.", ORANGE),
    ("Exercice", "📒", "L'année comptable d'une société. Le dividende d'un "
     "exercice est versé l'année suivante.", AMBRE),
    ("SGI", "🏦", "Société de Gestion et d'Intermédiation : l'intermédiaire "
     "agréé par qui il faut passer pour acheter ou vendre.", ROSE),
    ("Compte-titres", "🗂️", "Le compte ouvert chez une SGI où sont rangées "
     "vos actions.", ROSE),
    ("Ordre à cours limité", "🎚️", "Un ordre où vous fixez le prix maximum "
     "d'achat (ou minimum de vente). Il protège des mauvaises surprises.",
     BLEU),
    ("Frais", "💸", "Ce que vous payez à chaque achat et vente : courtage, "
     "commissions, taxes. Environ 3 % pour un aller-retour.", BAISSE),
    ("Aller-retour", "🔁", "Un achat suivi d'une revente. Les frais se paient "
     "deux fois.", BAISSE),
    ("Liquidité", "💧", "La facilité à acheter ou revendre. Une action peu "
     "liquide peut être difficile à revendre au prix voulu.", TURQUOISE),
    ("Volatilité", "🎢", "L'ampleur habituelle des mouvements du prix. Plus "
     "elle est forte, plus le prix peut monter ou chuter vite.", ORANGE),
    ("Limite de ±7,5 %", "🧱", "Sur la BRVM, un prix ne peut pas monter ni "
     "baisser de plus de 7,5 % en une seule séance.", VIOLET),
    ("Secteur", "🧭", "La famille de métiers d'une société : banque, "
     "télécoms, énergie…", CYAN),
    ("Médiane", "⚖️", "La valeur du milieu : la moitié fait mieux, l'autre "
     "moitié moins bien. Moins trompeuse qu'une moyenne.", DOUX),
    ("Prédiction", "🔮", "Ici : l'estimation des chances qu'une action fasse "
     "mieux que la moitié du marché, pas le prix futur.", VIOLET),
    ("Probabilité", "🎲", "Un pourcentage de chances. 52 % veut dire : sur 100 "
     "situations semblables, environ 52 se sont bien passées.", BLEU),
    ("Pire chute", "🪂", "La plus forte baisse depuis un plus haut. Elle "
     "montre le risque qu'on a réellement dû supporter.", BAISSE),
    ("Diversifier", "🧺", "Répartir son argent sur plusieurs actions et "
     "secteurs, pour ne pas tout perdre si une société va mal.", HAUSSE),
    ("Capitalisation", "🏢", "La valeur totale d'une société en bourse : prix "
     "d'une action × nombre d'actions.", BLEU),
]

if onglets[4].open:
    with onglets[4]:
        _titre("🌍 La BRVM, c'est quoi ?")
        _html(
            '<div class="carte anime"><p style="font-size:1.05rem;line-height:1.7;'
            'margin:0">La <b>Bourse Régionale des Valeurs Mobilières</b> est la '
            'bourse commune à huit pays d\'Afrique de l\'Ouest. Elle est '
            'installée à Abidjan. On y achète et on y vend des <b>actions</b> : '
            'de petits morceaux de grandes entreprises comme Sonatel, Orange CI '
            'ou la SGBCI.</p>'
            '<div style="font-size:2rem;margin-top:.8rem;letter-spacing:.3rem">'
            '🇧🇯 🇧🇫 🇨🇮 🇬🇼 🇲🇱 🇳🇪 🇸🇳 🇹🇬</div></div>')

        _titre("🚀 Acheter sa première action, en 6 étapes")
        etapes = [
            ("Choisir une SGI", "Un intermédiaire agréé par le régulateur du "
             "marché (l'AMF-UMOA). Comparez leurs frais : ils varient.", BLEU),
            ("Ouvrir un compte-titres", "Avec une pièce d'identité et un "
             "justificatif de domicile. C'est là que seront rangées vos "
             "actions.", CYAN),
            ("Déposer de l'argent", "Commencez avec une somme que vous "
             "n'aurez pas besoin de récupérer avant plusieurs années.",
             VIOLET),
            ("Bien choisir", "Regardez la fiche de l'action dans cette "
             "application : dividendes, facilité de revente, pire chute.",
             ROSE),
            ("Passer un ordre", "Dites quelle action, combien, et à quel prix "
             "maximum (« ordre à cours limité »).", ORANGE),
            ("Patienter", "L'ordre s'exécute quand un vendeur accepte votre "
             "prix. Ensuite, encaissez les dividendes chaque année.", HAUSSE),
        ]
        for debut in range(0, len(etapes), 3):
            colonnes = st.columns(3)
            for i, (titre, texte, teinte_e) in enumerate(etapes[debut:debut + 3]):
                colonnes[i].markdown(
                    f'<div class="carte etape anime d{i + 1}" '
                    f'style="margin-bottom:1rem"><div class="num" style="'
                    f'background:linear-gradient(135deg,{teinte_e},'
                    f'{_rgba(teinte_e, .6)})">{debut + i + 1}</div><div>'
                    f'<h4>{titre}</h4><p>{texte}</p></div></div>',
                    unsafe_allow_html=True)
        st.caption("Pour vendre, c'est le même chemin : un ordre de vente à "
                   "votre SGI, de préférence à cours limité.")

        _titre("📌 Trois règles à connaître")
        regles = [
            ("🏁", "Le prix de clôture fait foi",
             "Le prix bouge pendant la séance, mais c'est le prix de fin de "
             "séance qui sert de référence — c'est lui que montre cette "
             "application.", BLEU),
            ("🧱", "±7,5 % maximum par séance",
             "Un prix ne peut ni monter ni baisser de plus de 7,5 % en une "
             "séance. Une forte chute peut donc s'étaler sur plusieurs jours.",
             VIOLET),
            ("💸", "Des frais à chaque passage",
             "Acheter puis revendre coûte environ 2,5 à 3,5 %, et passe "
             "obligatoirement par une SGI.", ORANGE),
        ]
        c = st.columns(3)
        for i, (emo, titre, texte, teinte_r) in enumerate(regles):
            c[i].markdown(
                f'<div class="carte mot anime d{i + 1}" style="border-left-color:'
                f'{teinte_r};background:linear-gradient(120deg,{_rgba(teinte_r, .12)},'
                f'{SURFACE} 70%)"><div style="font-size:2rem">{emo}</div>'
                f'<h4>{titre}</h4><p>{texte}</p></div>', unsafe_allow_html=True)

        _titre("🧠 Ce que onze ans de données nous apprennent")
        _html(
            '<div class="lecon anime" style="background:linear-gradient(120deg,'
            f'{VIOLET},{BLEU})"><b>Personne ne sait prédire les prix avec '
            'certitude.</b><br>Des centaines de méthodes ont été testées sur '
            'l\'historique depuis 2015. La meilleure — le devin de l\'onglet '
            '🔮 Prédictions — fait un peu mieux qu\'une pièce de monnaie, mais '
            'pas assez pour payer les frais si on la suit, chaque mois comme '
            'chaque trimestre. Ce qui '
            'rapporte de façon régulière, ce sont les <b>dividendes</b> '
            'd\'actions gardées longtemps.</div>')

        _titre("📖 Le glossaire",
               f"{len(LEXIQUE)} mots expliqués simplement. Tapez un mot pour "
               "le retrouver.")
        cherche = st.text_input("Chercher un mot", placeholder="🔍 ex. : "
                                "dividende, SGI, volatilité…",
                                label_visibility="collapsed",
                                key="glossaire").strip().lower()
        trouves = [m for m in LEXIQUE
                   if not cherche or cherche in m[0].lower()
                   or cherche in m[2].lower()]
        if not trouves:
            st.info("Aucun mot ne correspond. Essayez un autre terme.")
        for debut in range(0, len(trouves), 4):
            c = st.columns(4)
            for i, (mot, emo, definition, teinte_l) in enumerate(
                    trouves[debut:debut + 4]):
                c[i].markdown(
                    f'<div class="carte mot anime d{i + 1}" '
                    f'style="border-left-color:{teinte_l};margin-bottom:1rem">'
                    f'<h4 style="color:{teinte_l} !important">{emo} {mot}</h4>'
                    f'<p>{definition}</p></div>', unsafe_allow_html=True)

        _titre("🎨 Les couleurs et symboles de l'application")
        symboles = [
            ("▲", "Hausse", "Le prix a monté.", HAUSSE),
            ("▼", "Baisse", "Le prix a baissé.", BAISSE),
            ("●", "Stable", "Le prix n'a pas bougé.", STABLE),
            ("✅", "Point fort", "Dans la fiche d'une action.", HAUSSE),
            ("🟡", "Correct", "Ni force, ni faiblesse.", AMBRE),
            ("⚠️", "Vigilance", "Un risque à connaître avant d'acheter.", BAISSE),
            ("☀️⛅🌧️", "Météo", "Du marché du jour, ou de la prévision.", BLEU),
            ("🪙", "Pile ou face", "50 % : le hasard, la référence à battre.",
             VIOLET),
        ]
        for debut in range(0, len(symboles), 4):
            c = st.columns(4)
            for i, (signe, mot, texte, teinte_s) in enumerate(
                    symboles[debut:debut + 4]):
                c[i].markdown(
                    f'<div class="carte anime d{i + 1}" style="margin-bottom:1rem;'
                    f'display:flex;gap:.8rem;align-items:center">'
                    f'<div style="font-size:1.6rem;color:{teinte_s};'
                    f'font-weight:800;min-width:2.2rem;text-align:center">'
                    f'{signe}</div><div><b>{mot}</b><div style="color:{DOUX};'
                    f'font-size:.85rem">{texte}</div></div></div>',
                    unsafe_allow_html=True)

        st.warning("**Ceci n'est pas un conseil en investissement.** Cette "
                   "application décrit ce qui s'est passé et donne des "
                   "estimations prudentes ; elle ne dit pas ce qui va se "
                   "passer. Les données viennent de brvm.org et sont archivées "
                   "chaque soir de séance. Avant tout achat, parlez-en à votre "
                   "SGI.")
