"""BRVM — la bourse d'Afrique de l'Ouest, expliquée simplement.

Point d'entrée de Streamlit Community Cloud. L'app ne lit que les CSV
versionnés du dépôt (`data/`) et, sur demande, la cote du jour sur
brvm.org. Elle n'écrit rien.

Quatre onglets, pensés pour quelqu'un qui découvre la bourse :

1. Aujourd'hui  — ce qui s'est passé à la dernière séance ;
2. Une action   — la fiche d'une société, son cours, ses dividendes ;
3. Dividendes   — ce qui rapporte vraiment sur ce marché ;
4. Comprendre   — la BRVM et ses mots, en quelques cartes.

Les analyses statistiques avancées (classement, prédiction, backtest)
restent disponibles en ligne de commande : `brvm --help`.
"""

from __future__ import annotations

import html

import altair as alt
import pandas as pd
import streamlit as st

from brvm import db, pedagogie
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
VIOLET, BLEU, CYAN, ORANGE, ROSE, AMBRE = (
    "#8b5cf6", "#3b82f6", "#06b6d4", "#f97316", "#ec4899", "#f59e0b")

if SOMBRE:
    FOND, SURFACE, ENCRE, DOUX = "#0b1020", "#141a2e", "#f1f5f9", "#94a3b8"
    BORDURE = "rgba(255,255,255,0.08)"
else:
    FOND, SURFACE, ENCRE, DOUX = "#f6f7fb", "#ffffff", "#0f172a", "#64748b"
    BORDURE = "rgba(15,23,42,0.08)"

SECTEURS = {
    "Services Financiers": ("🏦", "#6366f1"),
    "Télécommunications": ("📡", "#06b6d4"),
    "Consommation de Base": ("🛒", "#f59e0b"),
    "Consommation Discrétionnaire": ("🛍️", "#ec4899"),
    "Industriels": ("🏭", "#8b5cf6"),
    "Energie": ("⚡", "#f97316"),
    "Services Publics": ("💡", "#14b8a6"),
}


def _secteur(nom) -> tuple[str, str]:
    return SECTEURS.get(nom, ("🏢", BLEU))


def _rgba(couleur: str, alpha: float) -> str:
    c = couleur.lstrip("#")
    r, v, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{v},{b},{alpha})"


def _sens(valeur) -> int:
    if valeur is None or valeur != valeur or valeur == 0:
        return 0
    return 1 if valeur > 0 else -1


def _couleur(valeur) -> str:
    return {1: HAUSSE, -1: BAISSE, 0: STABLE}[_sens(valeur)]


def _fleche(valeur) -> str:
    return {1: "▲", -1: "▼", 0: "●"}[_sens(valeur)]


def _pastille(valeur) -> str:
    """« ▲ +2,1 % » dans une pastille colorée."""
    c = _couleur(valeur)
    return (f'<span class="pastille" style="background:{_rgba(c, .14)};'
            f'color:{c}">{_fleche(valeur)} {pedagogie.pourcentage(valeur)}</span>')


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
  padding: 1.1rem 1.25rem; height: 100%;
  box-shadow: 0 10px 30px -18px rgba(15,23,42,.35);
  transition: transform .25s ease, box-shadow .25s ease;
}}
.carte:hover {{ transform: translateY(-4px);
               box-shadow: 0 18px 40px -18px rgba(15,23,42,.45); }}
.stat {{ color: #fff; border: none; position: relative; overflow: hidden; }}
.stat .icone {{ position: absolute; right: .7rem; bottom: .4rem;
               font-size: 2.6rem; opacity: .28; filter: grayscale(.2); }}
.stat .label, .stat .valeur, .stat .note {{ position: relative; z-index: 1; }}
.stat .label {{ font-size: .78rem; font-weight: 700; text-transform: uppercase;
               letter-spacing: .06em; opacity: .9; }}
.stat .valeur {{ font-size: 2.2rem; font-weight: 800; line-height: 1.15;
                letter-spacing: -.02em; margin-top: .2rem; }}
.stat .note {{ font-size: .82rem; opacity: .9; margin-top: .2rem; }}

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

.lecon {{ border-radius: 20px; padding: 1.2rem 1.4rem; color: #fff;
         background: linear-gradient(120deg, {ORANGE}, {ROSE});
         box-shadow: 0 18px 40px -20px {_rgba(ROSE, .8)}; }}
.lecon b {{ font-size: 1.15rem; }}

.mot {{ border-left: 6px solid; }}
.mot h4 {{ margin: 0 0 .3rem !important; padding: 0 !important;
          color: {ENCRE}; font-size: 1.05rem !important; }}
.mot p {{ margin: 0; color: {DOUX}; font-size: .92rem; line-height: 1.5; }}

/* --- Onglets : des pilules ------------------------------------------- */
.stTabs [role="tablist"] {{
  gap: .4rem; background: {SURFACE}; padding: .4rem; border-radius: 999px;
  border: 1px solid {BORDURE}; width: fit-content; max-width: 100%;
  overflow-x: auto; box-shadow: 0 8px 24px -16px rgba(15,23,42,.4);
}}
.stTabs [role="tablist"] > *:not([role="tab"]) {{ display: none; }}
.stTabs [role="tablist"]::after, .stTabs [role="tablist"]::before {{ display: none; }}
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
        f'<div class="carte stat anime d{delai}" style="background:'
        f'linear-gradient(135deg,{couleurs[0]},{couleurs[1]});'
        f'box-shadow:0 16px 36px -18px {couleurs[0]}">'
        f'<span class="icone">{icone}</span>'
        f'<div class="label">{label}</div>'
        f'<div class="valeur">{contenu}</div>'
        f'<div class="note">{note}</div></div>',
        unsafe_allow_html=True)


# Thème des graphiques : fond transparent, grille discrète, police ronde.
@alt.theme.register("brvm_couleurs", enable=True)
def _theme_graphiques() -> alt.theme.ThemeConfig:
    return alt.theme.ThemeConfig({
        "background": "transparent",
        "view": {"stroke": "transparent"},
        "font": "Plus Jakarta Sans, system-ui, sans-serif",
        "axis": {"labelColor": DOUX, "titleColor": DOUX, "gridColor": BORDURE,
                 "domain": False, "tickColor": BORDURE, "labelFontSize": 12},
        "legend": {"labelColor": ENCRE, "titleColor": DOUX},
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

with haut_1:
    _html(
        '<div class="bandeau anime"><div style="display:flex;gap:1.1rem;'
        'align-items:center;position:relative;z-index:1">'
        '<span class="emoji">📈</span><div>'
        '<h1>La Bourse d\'Afrique de l\'Ouest</h1>'
        f'<p>Les {len(referentiel)} sociétés cotées à la BRVM, '
        'expliquées simplement.</p></div></div>'
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
           "dividendes": "💰 Dividendes", "comprendre": "🎓 Comprendre"}
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


def _seance(table: pd.DataFrame) -> pd.DataFrame:
    """Dernière séance, avec la variation face à la précédente."""
    jour = table[table["date"] == derniere].copy()
    if len(dates) >= 2:
        veille = (table[table["date"] == dates[-2]]
                  .set_index("ticker")["cloture"])
        jour["variation"] = jour["cloture"] / jour["ticker"].map(veille) - 1
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
            f'<div class="nom"><b>{html.escape(str(ligne.ticker))}</b>'
            f'<small>{html.escape(str(ligne.nom or ""))}</small>'
            f'<div class="jauge" style="margin-top:.35rem"><div style="'
            f'width:{max(part, .04):.0%};background:linear-gradient(90deg,'
            f'{_rgba(couleur, .5)},{couleur});animation-delay:{.1 * i:.1f}s">'
            f'</div></div></div>{_pastille(ligne.variation)}</div>')
    return "".join(morceaux)


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
                f'font-weight:700;color:{ENCRE};margin-bottom:.5rem">'
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

        _titre("📋 Toutes les actions de la séance")
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
                    "Variation", format="percent"),
                "volume_fcfa": st.column_config.NumberColumn(
                    "Échangé (FCFA)", format="localized"),
            })


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
            format_func=lambda t: f"{t} — {noms.get(t, '')}",
            key="valeur", persist_state="session")
        if st.query_params.get("valeur") != choix:
            st.query_params["valeur"] = choix

        serie = cours[cours["ticker"] == choix].sort_values("date")
        dernier = serie.iloc[-1]
        prix = float(dernier["cloture"])
        variation = (prix / serie["cloture"].iloc[-2] - 1
                     if len(serie) >= 2 else None)
        emo, teinte = _secteur(secteurs_par_valeur.get(choix))
        nom = str(noms.get(choix, choix))

        _html(
            f'<div class="carte anime" style="margin-top:.6rem;border-left:8px '
            f'solid {teinte};background:linear-gradient(120deg,'
            f'{_rgba(teinte, .16)},{SURFACE} 65%)">'
            '<div style="display:flex;flex-wrap:wrap;gap:1rem;'
            'align-items:center;justify-content:space-between">'
            f'<div><div style="font-size:2.4rem">{emo}</div>'
            f'<div style="font-size:1.6rem;font-weight:800;color:{ENCRE}">'
            f'{html.escape(nom)}</div>'
            f'<div style="color:{DOUX};font-weight:600">{choix} · '
            f'{html.escape(str(secteurs_par_valeur.get(choix) or "secteur inconnu"))}'
            '</div></div>'
            '<div style="text-align:right">'
            f'<div style="color:{DOUX};font-size:.85rem;font-weight:700">'
            f'PRIX D\'UNE ACTION</div>'
            f'<div style="font-size:2.6rem;font-weight:800;color:{ENCRE};'
            f'line-height:1.1">{pedagogie.montant(prix)}</div>'
            + (_pastille(variation) + f' <span style="color:{DOUX}">'
               'sur la séance</span>' if variation is not None else "")
            + '</div></div></div>')

        # Ce qu'aurait fait 100 000 FCFA placés il y a 1 mois, 1 an, 5 ans.
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
        st.caption("Hors dividendes et hors frais : c'est l'évolution du prix "
                   "seul.")

        if len(serie) >= 2:
            _titre("📈 L'évolution du prix")
            periodes = {"1 mois": 21, "6 mois": 125, "1 an": 250,
                        "5 ans": 1250, "Tout": None}
            periode = st.segmented_control(
                "Période", list(periodes), default="1 an",
                key="periode", label_visibility="collapsed") or "1 an"
            n = periodes[periode]
            vue = serie.tail(n) if n else serie
            couleur = (HAUSSE if vue["cloture"].iloc[-1] >= vue["cloture"].iloc[0]
                       else BAISSE)
            vue = vue.assign(jour=pd.to_datetime(vue["date"]))
            survol = alt.selection_point(nearest=True, on="pointermove",
                                         fields=["jour"], empty=False)
            base = alt.Chart(vue).encode(
                x=alt.X("jour:T", title=None),
                y=alt.Y("cloture:Q", title="prix (FCFA)",
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
                         alt.Tooltip("cloture:Q", title="Prix", format=",.0f")]
            ).add_params(survol)
            point = base.mark_point(size=120, filled=True, color=couleur,
                                    stroke="white", strokeWidth=2
                                    ).transform_filter(survol)
            st.altair_chart((aire + capteur + point).properties(height=340),
                            width="stretch")

        par_an = fondamentaux[(fondamentaux["ticker"] == choix)
                              & (fondamentaux["indicateur"] == "dividende")]
        if not par_an.empty:
            _titre("💰 Les dividendes versés",
                   "Ce que la société a versé à ses actionnaires, pour une "
                   "action, chaque année.")
            par_an = par_an.assign(annee=par_an["date"].str[:4])
            st.altair_chart(
                alt.Chart(par_an).mark_bar(cornerRadiusTopLeft=10,
                                           cornerRadiusTopRight=10, size=46)
                .encode(
                    x=alt.X("annee:N", title=None, axis=alt.Axis(labelAngle=0)),
                    y=alt.Y("valeur:Q", title="FCFA par action"),
                    color=alt.Color("annee:N", legend=None, scale=alt.Scale(
                        range=[VIOLET, BLEU, CYAN, HAUSSE, AMBRE, ORANGE, ROSE])),
                    tooltip=[alt.Tooltip("annee:N", title="Exercice"),
                             alt.Tooltip("valeur:Q", title="Dividende (FCFA)",
                                         format=",.0f")])
                .properties(height=260), width="stretch")
            dernier_div = float(par_an.sort_values("date")["valeur"].iloc[-1])
            if prix > 0:
                st.info(f"💡 Au prix actuel, le dernier dividende "
                        f"({pedagogie.montant(dernier_div)} par action) "
                        f"représente **{pedagogie.pourcentage(dernier_div / prix, signe=False)}** "
                        "du prix de l'action. C'est son **rendement**.")
        else:
            st.info("Aucun dividende connu pour cette société dans l'archive.")


# --- 💰 Dividendes ----------------------------------------------------------
if onglets[2].open:
    with onglets[2]:
        _html(
            '<div class="lecon anime"><b>💡 Le secret de la BRVM : '
            'les dividendes.</b><br>Chaque année, les sociétés cotées reversent '
            'une partie de leurs bénéfices à leurs actionnaires. Sur ce marché, '
            'c\'est la partie <b>la plus régulière</b> du gain : 7 à 10 % par an '
            'en moyenne ces dernières années, alors que les prix, eux, montent '
            'et descendent sans prévenir.</div>')

        rendements = fondamentaux[fondamentaux["indicateur"] == "rendement"]
        if rendements.empty:
            st.info("Aucun rendement de dividende en archive pour l'instant.")
        else:
            # Le rendement typique, exercice par exercice.
            typique = (rendements.groupby("date")["valeur"].median()
                       .reset_index())
            typique["annee"] = typique["date"].str[:4]
            _titre("📊 Le rendement typique, année après année",
                   "La moitié des sociétés font mieux, l'autre moitié moins bien.")
            c = st.columns(len(typique))
            palette = [(BLEU, CYAN), (VIOLET, ROSE), (ORANGE, AMBRE),
                       ("#059669", "#34d399"), ("#e11d48", "#fb7185")]
            for i, (colonne, ligne) in enumerate(zip(c, typique.itertuples())):
                _stat(colonne, f"Exercice {ligne.annee}",
                      pedagogie.pourcentage(ligne.valeur / 100, signe=False),
                      "de rendement médian", palette[i % len(palette)], "💰",
                      min(i + 1, 7))

            exercice = rendements["date"].max()
            recent = (rendements[rendements["date"] == exercice]
                      .assign(nom=lambda t: t["ticker"].map(noms),
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
                       "qui s'est effondré. Regardez toujours la fiche de la "
                       "société avant de conclure.")

        # Le calculateur : la question que se pose vraiment un débutant.
        _titre("🧮 Combien rapporterait mon épargne ?",
               "Une estimation à partir du dernier dividende connu.")
        derniers_div = (fondamentaux[fondamentaux["indicateur"] == "dividende"]
                        .sort_values("date").groupby("ticker")["valeur"].last())
        prix_jour = (cours[cours["date"] == derniere]
                     .set_index("ticker")["cloture"])
        candidates = sorted(set(derniers_div.index) & set(prix_jour.index))
        if candidates:
            with st.container(border=True):
                g, d = st.columns(2)
                societe = g.selectbox(
                    "Société", candidates,
                    format_func=lambda t: f"{t} — {noms.get(t, '')}",
                    key="calc_societe")
                somme = d.number_input("Somme investie (FCFA)", 10_000,
                                       100_000_000, 500_000, 50_000,
                                       key="calc_somme")
                p = float(prix_jour[societe])
                div = float(derniers_div[societe])
                actions = int(somme // p) if p > 0 else 0
                gain = actions * div
                r = st.columns(3)
                _stat(r[0], "Actions achetées", f"{actions:,}".replace(",", " "),
                      f"à {pedagogie.montant(p)} l'une", (BLEU, CYAN), "🧾", 1)
                _stat(r[1], "Dividende par an", pedagogie.montant(gain),
                      f"{pedagogie.montant(div)} par action", ("#059669", "#34d399"),
                      "💵", 2)
                _stat(r[2], "Rendement", pedagogie.pourcentage(
                      gain / somme if somme else 0, signe=False),
                      "de la somme investie", (VIOLET, ROSE), "📈", 3)
                st.caption("Estimation brute : avant impôts et frais de courtage "
                           "(2,5 à 3,5 % pour un achat puis une revente), et rien "
                           "ne garantit que le dividende sera le même l'an "
                           "prochain.")


# --- 🎓 Comprendre ----------------------------------------------------------
if onglets[3].open:
    with onglets[3]:
        _titre("🌍 La BRVM, c'est quoi ?")
        _html(
            '<div class="carte anime"><p style="font-size:1.05rem;line-height:1.7;'
            f'color:{ENCRE};margin:0">La <b>Bourse Régionale des Valeurs '
            'Mobilières</b> est la bourse commune à huit pays d\'Afrique de '
            'l\'Ouest. Elle est installée à Abidjan. On y achète et on y vend '
            'des <b>actions</b> : de petits morceaux de grandes entreprises '
            'comme Sonatel, Orange CI ou la SGBCI.</p>'
            '<div style="font-size:2rem;margin-top:.8rem;letter-spacing:.3rem">'
            '🇧🇯 🇧🇫 🇨🇮 🇬🇼 🇲🇱 🇳🇪 🇸🇳 🇹🇬</div></div>')

        _titre("📌 Trois règles à connaître")
        regles = [
            ("🔔", "Un seul prix par jour",
             "Les ordres d'achat et de vente sont regroupés : la bourse fixe "
             "un prix de clôture par séance.", BLEU),
            ("🚧", "±7,5 % maximum",
             "Un prix ne peut ni monter ni baisser de plus de 7,5 % en une "
             "séance.", VIOLET),
            ("💸", "Des frais à chaque passage",
             "Acheter puis revendre coûte environ 2,5 à 3,5 %, et passe "
             "obligatoirement par un intermédiaire agréé (une SGI).", ORANGE),
        ]
        c = st.columns(3)
        for i, (emo, titre, texte, teinte) in enumerate(regles):
            c[i].markdown(
                f'<div class="carte mot anime d{i + 1}" style="border-left-color:'
                f'{teinte};background:linear-gradient(120deg,{_rgba(teinte, .12)},'
                f'{SURFACE} 70%)"><div style="font-size:2rem">{emo}</div>'
                f'<h4>{titre}</h4><p>{texte}</p></div>', unsafe_allow_html=True)

        _titre("🧠 Ce que onze ans de données nous apprennent")
        _html(
            '<div class="lecon anime" style="background:linear-gradient(120deg,'
            f'{VIOLET},{BLEU})"><b>Personne ne sait prédire les prix.</b><br>'
            'Nous avons testé des centaines de méthodes sur l\'historique '
            'depuis 2015 : aucune ne choisit les actions mieux que le hasard '
            'une fois les frais payés. Ce qui rapporte de façon régulière, ce '
            'sont les <b>dividendes</b>. Et changer souvent d\'actions coûte '
            'plus cher que ce que ça rapporte.</div>')

        _titre("📖 Le petit lexique")
        lexique = [
            ("Action", "Un petit morceau d'une entreprise. En posséder, c'est "
             "en être un peu propriétaire.", BLEU),
            ("Séance", "Une journée de bourse — environ 250 par an, ni "
             "week-ends ni jours fériés.", CYAN),
            ("Prix de clôture", "Le prix de l'action à la fin de la séance.",
             VIOLET),
            ("Dividende", "La part du bénéfice que la société reverse chaque "
             "année à ses actionnaires.", HAUSSE),
            ("Rendement", "Le dividende divisé par le prix de l'action. 8 % "
             "veut dire 8 000 FCFA par an pour 100 000 investis.", AMBRE),
            ("Détachement", "Le jour où le dividende est versé. Le prix baisse "
             "d'autant ce jour-là : ce n'est pas une perte.", ORANGE),
            ("SGI", "Société de Gestion et d'Intermédiation : l'intermédiaire "
             "par qui il faut passer pour acheter ou vendre.", ROSE),
            ("Liquidité", "La facilité à acheter ou revendre. Certaines "
             "actions s'échangent très peu : on peut avoir du mal à en "
             "sortir.", "#14b8a6"),
        ]
        for debut in range(0, len(lexique), 4):
            c = st.columns(4)
            for i, (mot, definition, teinte) in enumerate(lexique[debut:debut + 4]):
                c[i].markdown(
                    f'<div class="carte mot anime d{i + 1}" '
                    f'style="border-left-color:{teinte};margin-bottom:1rem">'
                    f'<h4 style="color:{teinte} !important">{mot}</h4>'
                    f'<p>{definition}</p></div>', unsafe_allow_html=True)

        st.warning("**Ceci n'est pas un conseil en investissement.** Cette "
                   "application décrit ce qui s'est passé ; elle ne dit pas ce "
                   "qui va se passer. Les données viennent de brvm.org et sont "
                   "archivées chaque soir de séance.")
