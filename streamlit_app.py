"""Tableau de bord BRVM — point d'entrée de Streamlit Community Cloud.

L'app ne lit que les CSV versionnés du dépôt : pas de base sur le
conteneur, pas d'écriture, pas d'état. Un hébergeur gratuit redémarre le
conteneur quand il veut et son disque ne survit pas ; y stocker quoi que ce
soit donnerait une app qui affiche des données introuvables ailleurs. Les
données arrivent par l'action `ingestion.yml` ; l'app lit et calcule.

PARTIS PRIS DE VISUALISATION
----------------------------
- Paire divergente bleu ↔ rouge, jamais vert/rouge : la confusion
  vert-rouge est le déficit visuel le plus répandu. Les deux modes ont été
  validés au script — séparation en vision déficiente et contraste au fond.
- Le mode sombre est une palette CHOISIE, pas un inversement automatique :
  les mêmes teintes, reprises à des pas adaptés à un fond sombre.
- Le texte ne porte jamais la couleur d'une série. L'identité vient de la
  marque colorée posée à côté — un point en bout de courbe — parce qu'une
  teinte claire est illisible en texte sur le fond.
- Un seul rang de filtres, au-dessus des onglets, cadre tout ce qu'il
  concerne : le lecteur n'a pas à se demander quel réglage s'applique où.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from brvm import (backtest, db, dividende, features, pedagogie, prediction,
                  scoring)
from brvm.config import DEFAUTS
from brvm.ingestion import brvm_org

st.set_page_config(page_title="BRVM — cours et analyse",
                   page_icon="📈", layout="wide")


# --- Palette --------------------------------------------------------------

def _sombre() -> bool:
    """Thème actif côté navigateur, si Streamlit sait le dire."""
    try:
        return getattr(st.context.theme, "type", "light") == "dark"
    except Exception:  # noqa: BLE001 — hors runtime, ou version ancienne
        return False


SOMBRE = _sombre()

# Validées par scripts/validate_palette.js dans les deux modes : séparation
# en protanopie ΔE 21,6 (clair) / 19,2 (sombre) pour la paire divergente,
# 24,7 / 26,8 pour les deux séries du backtest.
if SOMBRE:
    HAUSSE, BAISSE = "#3987e5", "#e66767"
    SERIE_1, SERIE_2 = "#3987e5", "#d95926"
    ENCRE, ENCRE_DOUCE = "#ffffff", "#c3c2b7"
    GRILLE, AXE, SURFACE = "#2c2c2a", "#383835", "#1a1a19"
else:
    HAUSSE, BAISSE = "#2a78d6", "#e34948"
    SERIE_1, SERIE_2 = "#2a78d6", "#eb6834"
    ENCRE, ENCRE_DOUCE = "#0b0b0b", "#52514e"
    GRILLE, AXE, SURFACE = "#e1e0d9", "#c3c2b7", "#fcfcfb"

# Le plan de page est un cran SOUS la surface des cartes. C'est ce
# décalage — et pas la couleur — qui fait qu'un tableau de bord paraît
# construit plutôt que posé à plat : les cartes flottent au-dessus du
# plan, et la hiérarchie se lit avant qu'on ait lu un mot.
PLAN = "#0d0d0d" if SOMBRE else "#f9f9f7"
MUET = "#898781"
BORDURE = "rgba(255,255,255,0.10)" if SOMBRE else "rgba(11,11,11,0.10)"
# Statut : jamais réutilisé pour une série, toujours accompagné d'un mot.
BON, ALERTE, GRAVE, CRITIQUE = "#0ca30c", "#fab219", "#ec835a", "#d03b3b"

POLICE = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def _habiller() -> None:
    """Le système visuel, injecté une fois.

    Streamlit rend des blocs empilés sur un fond uni : correct, et plat.
    Trois choses suffisent à en faire un tableau de bord — un plan de page
    sous des cartes, une échelle typographique, et de l'air. Tout le reste
    ci-dessous n'est que l'application de ces trois-là.
    """
    st.markdown(f"""<style>
    :root {{
      --plan: {PLAN}; --surface: {SURFACE}; --bordure: {BORDURE};
      --encre: {ENCRE}; --encre-douce: {ENCRE_DOUCE}; --muet: {MUET};
      --serie-1: {SERIE_1}; --hausse: {HAUSSE}; --baisse: {BAISSE};
    }}
    .stApp {{ background: var(--plan); }}
    .block-container {{ padding-top: 2.2rem; max-width: 1420px; }}

    /* Échelle typographique : trois tailles, pas sept. */
    h1 {{ font-size: 1.9rem !important; font-weight: 650 !important;
         letter-spacing: -0.02em; margin-bottom: .1rem !important; }}
    h2 {{ font-size: 1.05rem !important; font-weight: 600 !important;
         letter-spacing: .01em; text-transform: uppercase;
         color: var(--muet) !important; margin-top: 2rem !important; }}
    h3 {{ font-size: .95rem !important; font-weight: 600 !important; }}

    /* La carte : un anneau d'un pixel, jamais une ombre portée. Une ombre
       simule une profondeur que l'écran n'a pas ; l'anneau se contente de
       délimiter. */
    .carte {{
      background: var(--surface); border: 1px solid var(--bordure);
      border-radius: 12px; padding: 1rem 1.15rem; height: 100%;
    }}
    .tuile-label {{
      font-size: .72rem; font-weight: 600; letter-spacing: .06em;
      text-transform: uppercase; color: var(--muet); margin-bottom: .35rem;
    }}
    /* Chiffres proportionnels : `tabular-nums` donne à chaque chiffre la
       largeur d'un zéro, et « 121 » paraît alors distendu en grande
       taille. Le tabulaire est réservé aux colonnes. */
    .tuile-valeur {{
      font-size: 1.85rem; font-weight: 650; line-height: 1.05;
      color: var(--encre); letter-spacing: -0.02em;
    }}
    .tuile-delta {{ font-size: .82rem; font-weight: 600; margin-top: .3rem; }}
    .tuile-note {{ font-size: .75rem; color: var(--muet); margin-top: .3rem; }}
    .hausse {{ color: var(--hausse); }} .baisse {{ color: var(--baisse); }}

    /* Le héros : un seul par vue, et il porte le chiffre qui résume. */
    .heros {{ font-size: 3.4rem; font-weight: 680; line-height: 1;
             letter-spacing: -0.03em; color: var(--encre); }}

    /* Onglets : une barre, pas des boutons. */
    .stTabs [data-baseweb="tab-list"] {{
      gap: 1.6rem; border-bottom: 1px solid var(--bordure);
    }}
    .stTabs [data-baseweb="tab"] {{
      padding: .4rem 0 .7rem 0; font-weight: 550; font-size: .93rem;
    }}
    .stTabs [data-baseweb="tab-highlight"] {{ height: 2px; }}

    /* Le chrome recule : la donnée est la seule chose autorisée à être
       bruyante. */
    [data-testid="stDataFrame"] {{ border-radius: 10px; }}
    [data-testid="stExpander"] details {{
      border: 1px solid var(--bordure) !important; border-radius: 10px;
      background: var(--surface);
    }}
    hr {{ border-color: var(--bordure); }}

    /* Le conteneur bordé natif, habillé comme les tuiles pour que tout
       le tableau de bord soit fait du même matériau. */
    [data-testid="stVerticalBlockBorderWrapper"] {{
      background: var(--surface); border: 1px solid var(--bordure);
      border-radius: 12px; padding: 1rem 1.15rem;
    }}
    </style>""", unsafe_allow_html=True)


def _etincelle(valeurs, largeur=112, hauteur=30) -> str:
    """Sparkline SVG : douze points de contexte à côté d'un chiffre.

    Une valeur seule ne dit pas si elle sort de l'ordinaire. La courbe
    n'a ni axe ni graduation — ce n'est pas un graphique, c'est une
    texture qui répond à « et avant ? ». Le dernier point porte l'accent,
    le reste est en gris : c'est là que le lecteur regarde.
    """
    points = [v for v in valeurs if v == v]
    if len(points) < 2:
        return ""
    bas, haut = min(points), max(points)
    etendue = (haut - bas) or 1
    pas = largeur / (len(points) - 1)
    marge = 3
    chemin = " ".join(
        f"{i * pas:.1f},"
        f"{marge + (hauteur - 2 * marge) * (1 - (v - bas) / etendue):.1f}"
        for i, v in enumerate(points)
    )
    fin = chemin.split(" ")[-1]
    monte = points[-1] >= points[0]
    couleur = HAUSSE if monte else BAISSE
    return (
        f'<svg width="{largeur}" height="{hauteur}" viewBox="0 0 {largeur} '
        f'{hauteur}" fill="none" style="display:block;margin-top:.45rem">'
        f'<polyline points="{chemin}" stroke="{MUET}" stroke-width="1.5" '
        f'stroke-linejoin="round" stroke-linecap="round" opacity="0.55"/>'
        # L'anneau à la couleur de la surface détache le point de la
        # courbe là où ils se croisent.
        f'<circle cx="{fin.split(",")[0]}" cy="{fin.split(",")[1]}" r="3.2" '
        f'fill="{couleur}" stroke="{SURFACE}" stroke-width="2"/></svg>'
    )


def _carte_secteur(colonne, nom: str, variation, valeurs: int,
                   part_hausse: float) -> None:
    """Un secteur en une carte : nom, variation médiane, largeur interne.

    C'est la première lecture que fait un professionnel devant un marché —
    quel secteur porte la séance ? — et l'app ne la permettait pas : elle
    alignait 47 valeurs et jamais les sept secteurs.

    La barre dit la part de valeurs en hausse À L'INTÉRIEUR du secteur.
    Une médiane positive portée par une valeur sur sept ne dit pas la même
    chose qu'une hausse partagée, et le chiffre seul ne l'avoue pas.
    """
    signe = 0 if variation is None or variation != variation else (
        1 if variation > 0 else -1 if variation < 0 else 0)
    couleur = HAUSSE if signe > 0 else BAISSE if signe < 0 else MUET
    colonne.markdown(
        f'<div class="carte" style="padding:.75rem .85rem">'
        f'<div class="tuile-label" style="font-size:.65rem;line-height:1.25;'
        f'min-height:2.2em">{nom}</div>'
        f'<div style="font-size:1.15rem;font-weight:650;color:{couleur};'
        f'letter-spacing:-.01em">{pedagogie.pourcentage(variation)}</div>'
        # Piste et remplissage du même bleu, deux pas d'écart : l'état se
        # lit sur toute la barre, pas seulement sur la partie pleine.
        f'<div style="display:flex;height:4px;border-radius:2px;'
        f'background:{GRILLE};margin-top:.5rem;overflow:hidden">'
        f'<div style="flex:{max(part_hausse, 0.001)} 0 0;background:{HAUSSE}">'
        f'</div><div style="flex:{max(1 - part_hausse, 0.001)} 0 0"></div></div>'
        f'<div class="tuile-note" style="margin-top:.35rem;font-size:.7rem">'
        f'{valeurs} valeur{"s" if valeurs > 1 else ""} · '
        f'{part_hausse:.0%} en hausse</div></div>',
        unsafe_allow_html=True)


def _panneau(titre: str = "", note: str = ""):
    """Un graphique posé sur une surface, pas flottant sur le plan.

    Même décalage que pour les tuiles : une carte sous le tracé le fait
    paraître construit plutôt qu'inséré. Le graphique reste sur fond
    transparent — c'est la carte qui porte la surface, et une seule des
    deux doit le faire.

    Bâti sur le conteneur bordé de Streamlit plutôt que sur un sélecteur
    CSS remontant l'arbre : la structure du DOM de Streamlit change d'une
    version à l'autre, un `:has(> div > div > …)` casserait sans bruit à
    la première mise à jour.
    """
    boite = st.container(border=True)
    if titre:
        boite.markdown(f'<div class="tuile-label">{titre}</div>',
                       unsafe_allow_html=True)
    if note:
        boite.markdown(f'<div class="tuile-note" style="margin:0 0 .4rem">'
                       f'{note}</div>', unsafe_allow_html=True)
    return boite


def _tuile(colonne, label: str, valeur: str, delta: str = "",
           sens: int = 0, note: str = "", etincelle: str = "") -> None:
    """Une tuile : intitulé, valeur, écart signé, contexte. Dans cet ordre.

    Le contrat vient de la référence de conception — `label`, `value`,
    `delta`, `trend` — et l'ordre n'est pas décoratif : on lit ce que
    c'est, puis combien, puis si c'est inhabituel.
    """
    classe = "hausse" if sens > 0 else "baisse" if sens < 0 else ""
    morceaux = [f'<div class="tuile-label">{label}</div>',
                f'<div class="tuile-valeur">{valeur}</div>']
    if delta:
        morceaux.append(f'<div class="tuile-delta {classe}">{delta}</div>')
    if note:
        morceaux.append(f'<div class="tuile-note">{note}</div>')
    if etincelle:
        morceaux.append(etincelle)
    colonne.markdown(f'<div class="carte">{"".join(morceaux)}</div>',
                     unsafe_allow_html=True)


@alt.theme.register("brvm", enable=True)
def _theme() -> alt.theme.ThemeConfig:
    """Chrome discret : la grille et les axes ne concurrencent pas les
    marques qui portent la donnée. Traits pleins, jamais pointillés — un
    pointillé se lit comme une projection ou un seuil."""
    return alt.theme.ThemeConfig({
        "background": "transparent",   # la carte porte la surface
        "view": {"stroke": "transparent"},
        "padding": {"left": 4, "right": 4, "top": 8, "bottom": 4},
        "axis": {
            "labelColor": ENCRE_DOUCE, "titleColor": ENCRE_DOUCE,
            "gridColor": GRILLE, "domainColor": AXE, "tickColor": AXE,
            "labelFontSize": 12, "titleFontSize": 12,
        },
        "legend": {"labelColor": ENCRE, "titleColor": ENCRE_DOUCE},
        "font": POLICE,
    })


def _telecharger(donnees: pd.DataFrame, nom: str, cle: str) -> None:
    """Bouton d'export : un tableau à l'écran doit pouvoir en sortir."""
    st.download_button(
        "Télécharger en CSV", donnees.to_csv(index=False).encode("utf-8"),
        file_name=nom, mime="text/csv", key=cle,
    )


def _glossaire(*termes: str) -> None:
    """Les mots de l'onglet, en bas de l'onglet.

    Un glossaire relégué dans une page à part n'est ouvert par personne :
    il faut quitter ce qu'on lisait pour aller chercher le mot, et revenir.
    Chaque onglet porte donc les siens, et eux seuls.
    """
    with st.expander("Les mots de cet onglet"):
        st.markdown(pedagogie.glossaire(*termes))


def _attente(titre: str, disponible: int, requis: int, pourquoi: str,
             unite: str = "séance") -> None:
    """Un refus affiché comme un compteur qui avance, pas comme une panne.

    « Aucune valeur classée » se lit comme un bug. Une barre au dixième,
    assortie du mois où le premier résultat tombera, se lit pour ce qu'elle
    est : l'archive n'a pas encore l'âge requis, et elle vieillit.
    """
    etat = pedagogie.attente(disponible, requis, derniere, unite)
    boite = st.container(border=True)
    # La jauge est dessinée à la main plutôt que confiée à `st.progress` :
    # celle de Streamlit occupe toute la largeur en pleine saturation, et
    # une attente n'a pas à crier. Piste et remplissage du même bleu à
    # deux pas d'écart, pour que l'état se lise sur toute la barre.
    boite.markdown(
        f'<div class="tuile-label">{titre} — en attente de données</div>'
        f'<div style="display:flex;align-items:baseline;gap:.6rem;'
        f'margin:.25rem 0 .6rem">'
        f'<div style="font-size:1.6rem;font-weight:650;color:{ENCRE}">'
        f'{etat["disponible"]}</div>'
        f'<div style="color:{MUET};font-size:.95rem">sur '
        f'{etat["requis"]} {unite}s nécessaires</div></div>'
        f'<div style="display:flex;height:6px;border-radius:3px;'
        f'background:{GRILLE};overflow:hidden">'
        f'<div style="flex:{max(etat["part"], 0.004)} 0 0;'
        f'background:{SERIE_1}"></div>'
        f'<div style="flex:{max(1 - etat["part"], 0.004)} 0 0"></div></div>'
        f'<div class="tuile-note" style="margin-top:.6rem">{etat["phrase"]}'
        f'</div>'
        f'<div class="tuile-note" style="margin-top:.5rem;line-height:1.5">'
        f'{pourquoi}</div>',
        unsafe_allow_html=True)


# --- Données --------------------------------------------------------------

@st.cache_data(ttl=900)
def charger_archive():
    return (db.charger_archive("cours"), db.charger_archive("referentiel"),
            db.charger_archive("dividendes"), db.charger_archive("fondamentaux"))


@st.cache_data(ttl=900, show_spinner="Lecture de brvm.org…")
def lire_en_direct():
    """Séance publiée, lue sur le site. (cote, erreur) — l'un vaut None.

    L'app ne doit pas dépendre de l'action planifiée pour montrer quelque
    chose. Affiché seulement, jamais archivé : hors clôture, la colonne
    « Cours Clôture » du site porte le dernier cours traité.
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

# LE PREMIER ÉCRAN APPARTIENT À LA DONNÉE. Titre, avertissement et bouton
# d'actualisation tiennent sur une seule rangée : auparavant chacun avait
# la sienne, et les onglets commençaient à 410 px du haut sur ordinateur,
# 1 640 px sur téléphone. Un tableau de bord doit montrer un chiffre avant
# de montrer ses réglages.
titre_1, titre_2 = st.columns([4, 1], vertical_alignment="center")
with titre_1:
    st.title("Bourse Régionale des Valeurs Mobilières")
    # L'avertissement reste au-dessus de tout, jamais en légende sous le
    # classement : un tableau ordonné de valeurs se lit comme une liste
    # d'achat si rien ne dit le contraire AVANT qu'on l'ait vu.
    st.caption(
        "Les cours des 47 sociétés cotées à Abidjan, et de quoi les lire. "
        "**Ce n'est pas un conseil d'investissement** : rien ici n'a été "
        "calibré sur quoi que ce soit, et aucun classement affiché n'est un "
        "signal validé."
    )

direct, echec = (None, None)
if cours.empty:
    direct, echec = lire_en_direct()

with titre_2:
    if st.button("↻ Actualiser", width="stretch",
                 help="Relire la cote publiée sur brvm.org, sans rien écrire"):
        lire_en_direct.clear()
        direct, echec = lire_en_direct()

# Replié par défaut, et ce n'est pas un détail : changer d'onglet ne relance
# pas le script côté Streamlit, donc un dépliant ouvert le reste sur les six
# onglets et leur mange le premier écran.
with st.expander("Première visite ? Comment lire cette app, et trois choses "
                 "à savoir sur la BRVM"):
    st.markdown(
        """
**Ce que fait cette app.** Elle lit chaque jour la cote publiée par
brvm.org, la conserve, et propose quelques lectures de cet historique.
Elle n'exécute aucun ordre et ne vous connaît pas.

**Par où commencer.**

1. **Marché** — ce qui s'est passé à la dernière séance : qui monte, qui
   baisse, combien s'est échangé.
2. **Valeur** — la fiche d'une société : son cours, son historique, ses
   dividendes. Le plus utile si vous avez déjà un nom en tête.
3. **Classement**, **Prédiction**, **Backtest** — des lectures outillées de
   l'historique. Elles demandent des années de cotation et refusent de
   répondre tant qu'elles ne les ont pas : ce refus est le fonctionnement
   normal, pas une panne.

**Trois choses à savoir sur ce marché avant de lire le reste.**

- La BRVM ne cote pas en continu. Les ordres sont regroupés et **un seul
  cours est fixé par séance**.
- Un cours ne peut ni monter ni baisser de **plus de 7,5 % par séance**.
- Acheter puis revendre coûte **2,5 à 3,5 %** entre courtage, commissions
  et taxes, et passe obligatoirement par une SGI. Un écart de performance
  inférieur à ce montant ne se récupère pas.
"""
    )

if direct is not None and not direct.empty:
    cours = (pd.concat([cours, direct], ignore_index=True)
             .drop_duplicates(subset=["date", "ticker"], keep="last"))
    st.success(
        f"Séance du {direct['date'].iloc[0]} lue à l'instant "
        f"(site mis à jour à {direct.attrs.get('heure_mise_a_jour') or '?'}). "
        "Affichée seulement — l'archive du dépôt n'est pas modifiée."
    )

if cours.empty:
    st.warning(
        "**Aucune donnée.** L'archive `data/cours.csv` est vide et brvm.org "
        "n'a pas répondu" + (f" — {echec}." if echec else ".")
        + " L'archive se remplit quand l'action `ingestion.yml` tourne, "
        "chaque jour ouvré à 16 h UTC."
    )
    st.stop()

if echec:
    st.caption(f"brvm.org injoignable ({echec}) — affichage de l'archive.")

seances = cours["date"].nunique()
derniere = cours["date"].max()
dates_triees = sorted(cours["date"].unique())


# --- Filtre unique, au-dessus de tout ce qu'il cadre ----------------------

secteurs_connus = sorted(referentiel["secteur"].dropna().unique())

# LE FILTRE SE REPLIE. Sept puces de secteur occupaient deux lignes
# pleines pour dire « tout est sélectionné », c'est-à-dire rien. La
# pastille annonce l'état en trois mots et n'ouvre le détail qu'au clic ;
# la place gagnée revient à la donnée.
filtre_1, filtre_2 = st.columns([1, 2], vertical_alignment="bottom")
with filtre_1:
    choisis = st.session_state.get("secteurs", secteurs_connus)
    resume = ("tous les secteurs" if len(choisis) == len(secteurs_connus)
              else f"{len(choisis)} secteur{'s' if len(choisis) > 1 else ''}"
              if choisis else "aucun secteur")
    with st.popover(f"⚟  {resume}", width="stretch"):
        secteurs = st.multiselect(
            "Secteurs", secteurs_connus, default=secteurs_connus,
            key="secteurs", label_visibility="collapsed",
            help="Cadre l'ensemble du tableau de bord.",
        )
with filtre_2:
    recherche = st.text_input(
        "Rechercher", placeholder="Symbole ou société",
        label_visibility="collapsed")

retenus = (set(referentiel[referentiel["secteur"].isin(secteurs)]["ticker"])
           if secteurs else set(referentiel["ticker"]))
if recherche:
    motif = recherche.strip().lower()
    retenus &= set(referentiel[
        referentiel["ticker"].str.lower().str.contains(motif, na=False)
        | referentiel["nom"].str.lower().str.contains(motif, na=False)
    ]["ticker"])

cours_filtre = cours[cours["ticker"].isin(retenus)]
if cours_filtre.empty:
    st.warning("Aucune valeur ne correspond à ce filtre.")
    st.stop()
referentiel_filtre = referentiel[referentiel["ticker"].isin(retenus)]

onglets = st.tabs(["Marché", "Valeur", "Classement", "Prédiction",
                   "Backtest", "Données"])


def _variations(table: pd.DataFrame) -> pd.DataFrame:
    """Dernière séance, avec la variation face à la précédente."""
    jour = table[table["date"] == derniere].copy()
    if len(dates_triees) >= 2:
        veille = table[table["date"] == dates_triees[-2]].set_index("ticker")["cloture"]
        jour["variation"] = jour["cloture"] / jour["ticker"].map(veille) - 1
    else:
        jour["variation"] = pd.NA
    return jour.merge(referentiel[["ticker", "nom", "secteur"]], on="ticker",
                      how="left")


# --- Marché ---------------------------------------------------------------
with onglets[0]:
    jour = _variations(cours_filtre)
    connues = jour["variation"].dropna()

    # LE HÉROS : un seul chiffre par vue, celui qui résume la séance. Ici
    # la capitalisation échangée — c'est la mesure d'activité du marché,
    # et la seule qui se lise sans contexte.
    echange = jour["volume_fcfa"].sum(skipna=True)
    heros_1, heros_2 = st.columns([2, 3])
    with heros_1:
        recentes = (cours_filtre.groupby("date")["volume_fcfa"].sum()
                    .tail(12).tolist())
        st.markdown(
            f'<div class="tuile-label">Échangé le {pedagogie.jour(derniere)}'
            f'</div><div class="heros">{pedagogie.montant(echange)}</div>'
            f'<div class="tuile-note">12 dernières séances</div>'
            + _etincelle(recentes, largeur=180, hauteur=34),
            unsafe_allow_html=True)
    with heros_2:
        if not connues.empty:
            hausses = int((connues > 0).sum())
            baisses = int((connues < 0).sum())
            stables = len(connues) - hausses - baisses
            # La largeur du marché en une barre : une médiane positive
            # portée par trois valeurs ne dit pas la même chose qu'une
            # hausse partagée, et un empilement le montre sans le dire.
            total = max(1, len(connues))
            segments = [(hausses, HAUSSE, "en hausse"),
                        (stables, MUET, "stables"),
                        (baisses, BAISSE, "en baisse")]
            # `flex` ET NON `width` : dans une rangée flex, une largeur en
            # pourcentage n'est qu'une base que le conteneur réajuste, et
            # les segments s'affichaient à des proportions fausses — 17,
            # 2 et 28 valeurs rendues comme 45 %, 5 % et 48 % au lieu de
            # 36 %, 4 % et 60 %. Une barre de répartition qui ment sur la
            # répartition est pire qu'une absence de barre.
            barre = "".join(
                f'<div style="flex:{n} 0 0;background:{c};height:12px;'
                f'border-radius:3px" title="{n} {m}"></div>'
                for n, c, m in segments if n
            )
            st.markdown(
                '<div class="tuile-label">Largeur du marché</div>'
                # Le trou de 2 px à la couleur du plan sépare les segments :
                # c'est le vide qui distingue, jamais un contour.
                f'<div style="display:flex;gap:2px;margin-top:.55rem">{barre}</div>'
                f'<div class="tuile-note">{hausses} en hausse · '
                f'{stables} stables · {baisses} en baisse, '
                f'sur {len(connues)} valeurs</div>',
                unsafe_allow_html=True)

    st.write("")
    tuiles = st.columns(4)
    _tuile(tuiles[0], "Séance", pedagogie.jour(derniere),
           note=f"{seances} séances en archive")
    mediane = None if connues.empty else connues.median()
    _tuile(tuiles[1], "Variation médiane", pedagogie.pourcentage(mediane),
           sens=0 if mediane is None else (1 if mediane > 0 else -1),
           note="sur les valeurs ayant coté")
    # Douze séances de contexte derrière le chiffre du jour : une valeur
    # seule ne dit pas si elle sort de l'ordinaire.
    plus_traitee = jour.loc[jour["volume_fcfa"].idxmax()] \
        if jour["volume_fcfa"].notna().any() else None
    _tuile(tuiles[2], "Plus échangée",
           "—" if plus_traitee is None else str(plus_traitee["ticker"]),
           note=("aucun échange"
                 if plus_traitee is None else
                 f"{pedagogie.montant(plus_traitee['volume_fcfa'])} · "
                 f"{(plus_traitee['volume_fcfa'] / echange):.0%} du marché"))
    _tuile(tuiles[3], "Valeurs suivies", f"{jour['ticker'].nunique()}",
           note=("toutes les sociétés cotées"
                 if len(retenus) == len(referentiel)
                 else f"{len(referentiel) - len(retenus)} écartées par le filtre"))

    # --- Les secteurs, avant le détail ------------------------------------
    if not connues.empty and jour["secteur"].notna().any():
        st.markdown("## Par secteur")
        par_secteur = (
            jour.dropna(subset=["variation", "secteur"])
            .groupby("secteur")
            .agg(variation=("variation", "median"),
                 valeurs=("ticker", "size"),
                 hausses=("variation", lambda v: float((v > 0).mean())))
            .sort_values("variation", ascending=False)
            .reset_index()
        )
        # Les sept secteurs de la BRVM tiennent sur une rangée ; au-delà,
        # ce serait une grille et le rang cesserait de se lire.
        cartes = st.columns(max(1, len(par_secteur)))
        for colonne, ligne in zip(cartes, par_secteur.itertuples()):
            _carte_secteur(colonne, ligne.secteur, ligne.variation,
                           int(ligne.valeurs), float(ligne.hausses))
        st.write("")

    # Les tuiles disent la même chose, mais il faut les lire ensemble pour
    # l'entendre. La phrase le fait à la place du lecteur.
    if connues.empty:
        st.markdown(
            f"À la séance du **{pedagogie.jour(derniere)}**, "
            f"{jour['ticker'].nunique()} valeurs sont cotées et il s'est "
            f"échangé {pedagogie.montant(echange)}. Aucune variation n'est "
            "calculable : il n'y a qu'une séance en archive, donc rien à "
            "quoi comparer. La deuxième suffira."
        )
    else:
        hausses, baisses = int((connues > 0).sum()), int((connues < 0).sum())
        stables = len(connues) - hausses - baisses
        st.markdown(
            f"À la séance du **{pedagogie.jour(derniere)}**, sur "
            f"{len(connues)} valeurs : **{hausses} montent**, "
            f"**{baisses} baissent**, "
            + (f"{stables} sont inchangées" if stables != 1
               else "1 est inchangée")
            + f". Il s'est échangé {pedagogie.montant(echange)} en tout."
        )

    if not connues.empty:
        classees = jour.dropna(subset=["variation"]).sort_values("variation")
        # TÊTE ET QUEUE PLUTÔT QUE TOUT. Quarante-sept lignes à 22 px font
        # plus de mille pixels : le graphique n'était jamais vu en entier,
        # et son milieu — les valeurs qui n'ont presque pas bougé — est
        # justement ce qu'on ne regarde pas. Les extrêmes tiennent dans un
        # écran ; le reste s'ouvre au clic, et le tableau plus bas porte
        # toujours les 47.
        tout_montrer = st.toggle(
            f"Afficher les {len(classees)} valeurs", value=False,
            key="marche_tout",
            help="Par défaut, les dix plus fortes hausses et les dix plus "
                 "fortes baisses.")
        if tout_montrer or len(classees) <= 20:
            visibles, note = classees, f"{len(classees)} valeurs"
        else:
            visibles = pd.concat([classees.head(10), classees.tail(10)])
            note = (f"dix plus fortes baisses et dix plus fortes hausses, "
                    f"sur {len(classees)} valeurs")
        panneau = _panneau(
            f"Variation de la séance du {pedagogie.jour(derniere)}", note)
        panneau.altair_chart(
            alt.Chart(visibles)
            .mark_bar(cornerRadiusEnd=4, height=14)
            .encode(
                # Axe en haut : le graphique fait plusieurs écrans, une
                # échelle en bas obligerait à l'aller-retour.
                x=alt.X("variation:Q", title="variation",
                        axis=alt.Axis(format="+.1%", orient="top")),
                # labelOverlap=False : sinon Vega masque un libellé sur deux
                # et la moitié des barres devient inidentifiable.
                y=alt.Y("ticker:N", sort=alt.SortField("variation", "descending"),
                        title=None, axis=alt.Axis(labelOverlap=False)),
                color=alt.condition(alt.datum.variation >= 0,
                                    alt.value(HAUSSE), alt.value(BAISSE)),
                tooltip=[
                    alt.Tooltip("ticker:N", title="Symbole"),
                    alt.Tooltip("nom:N", title="Société"),
                    alt.Tooltip("cloture:Q", title="Clôture", format=",.0f"),
                    alt.Tooltip("variation:Q", title="Variation", format="+.2%"),
                    alt.Tooltip("secteur:N", title="Secteur"),
                ],
            )
            .properties(height=max(240, 22 * len(visibles))),
            width="stretch",
        )
    colonnes = ["ticker", "nom", "secteur", "cloture"]
    if not connues.empty:
        colonnes.append("variation")
    colonnes += ["volume_titres", "volume_fcfa"]

    tableau = jour[colonnes].sort_values("ticker").copy()
    # Trente séances de contexte DANS le tableau : sans elles, chaque ligne
    # est un instantané et rien ne dit si la valeur du jour est ordinaire.
    # C'est aussi ce qui distingue une grille d'un terminal.
    fenetre = cours_filtre[cours_filtre["date"] > dates_triees[-30]] \
        if len(dates_triees) > 30 else cours_filtre
    trente = (fenetre.sort_values("date").groupby("ticker")["cloture"]
              .apply(list).to_dict())
    tableau["tendance"] = tableau["ticker"].map(trente)
    ordre = ["ticker", "nom", "secteur", "tendance", "cloture"]
    ordre += [c for c in colonnes if c not in ordre]

    st.dataframe(
        tableau[ordre], width="stretch", hide_index=True,
        column_config={
            "ticker": st.column_config.TextColumn("Symbole"),
            "nom": st.column_config.TextColumn("Société"),
            "secteur": st.column_config.TextColumn("Secteur"),
            "tendance": st.column_config.LineChartColumn(
                "30 séances", width="small",
                help="Clôtures des trente dernières séances. Sans axe : "
                     "c'est une texture, pas un graphique."),
            # `format="percent"` et non « %+.2f%% » : le format printf ne
            # multiplie pas par cent, et affichait « -0,02 % » là où la
            # valeur baissait de 2 %. Cent fois trop petit, sans rien qui
            # le signale — le graphique juste au-dessus disait autre chose.
            "cloture": st.column_config.NumberColumn("Clôture",
                                                     format="localized"),
            "variation": st.column_config.NumberColumn("Var.",
                                                       format="percent"),
            # « localized » suit la locale du lecteur : un francophone lit
            # « 1 042 625 » et non « 1,042,625 ».
            "volume_titres": st.column_config.NumberColumn("Titres",
                                                           format="localized"),
            # Une barre en cellule : on compare les lignes à l'œil au lieu
            # de lire sept chiffres et de les ordonner de tête.
            "volume_fcfa": st.column_config.ProgressColumn(
                "Échangé (FCFA)", format="localized", min_value=0,
                max_value=float(tableau["volume_fcfa"].max() or 1)),
        },
    )
    # L'export garde les colonnes chiffrées : une liste de clôtures ne se
    # met pas dans un CSV.
    _telecharger(jour[colonnes], f"brvm_{derniere}.csv", "dl_marche")
    _glossaire("fixing", "limite", "liquidite")


# --- Valeur ---------------------------------------------------------------
with onglets[1]:
    noms = referentiel.set_index("ticker")["nom"]
    choix = st.selectbox(
        "Valeur", sorted(cours_filtre["ticker"].unique()),
        format_func=lambda t: f"{t} — {noms.get(t, '')}",
    )

    serie = cours_filtre[cours_filtre["ticker"] == choix].sort_values("date")
    fiche = referentiel[referentiel["ticker"] == choix]
    dernier = serie.iloc[-1]

    div_valeur = (dividendes[dividendes["ticker"] == choix]
                  if not dividendes.empty else pd.DataFrame())

    # Le secteur est un libellé, pas une mesure : dans une tuile il se fait
    # tronquer — « Consommation Dis… » ne distingue plus les deux secteurs
    # de consommation. Il passe donc en légende, où il tient en entier.
    st.caption(
        f"**{fiche['nom'].iloc[0] if not fiche.empty else choix}** · "
        f"{fiche['secteur'].iloc[0] if not fiche.empty else 'secteur inconnu'}"
    )

    faits = st.columns(3)
    variation = (dernier["cloture"] / serie["cloture"].iloc[-2] - 1
                 if len(serie) >= 2 else None)
    # Douze séances de contexte : un cours seul ne dit pas s'il sort de
    # l'ordinaire.
    _tuile(faits[0], "Clôture", pedagogie.montant(dernier["cloture"]),
           delta=pedagogie.pourcentage(variation) + " sur la séance"
                 if variation is not None else "",
           sens=0 if variation is None else (1 if variation > 0 else -1),
           etincelle=_etincelle(serie["cloture"].tail(12).tolist()))
    # Même arrondi que la phrase juste en dessous : deux écritures du même
    # montant à trois lignes d'écart donnent à croire à deux montants.
    _tuile(faits[1], "Volume échangé",
           pedagogie.montant(dernier["volume_fcfa"]),
           note="sur la dernière séance")
    _tuile(faits[2], "Dividendes connus", f"{len(div_valeur)}",
           note="détachements datés en archive")

    # La même information en toutes lettres. Trois tuiles se lisent vite
    # quand on sait quoi y chercher ; sinon ce sont trois nombres nus.
    morceaux = [
        f"**{fiche['nom'].iloc[0] if not fiche.empty else choix}** vaut "
        f"{pedagogie.montant(dernier['cloture'])} à la clôture du "
        f"{pedagogie.jour(derniere)}"
    ]
    if len(serie) >= 2:
        veille = serie["cloture"].iloc[-2]
        if pd.notna(veille) and veille > 0:
            morceaux.append(
                "soit "
                + pedagogie.pourcentage(dernier["cloture"] / veille - 1)
                + " sur la séance"
            )
    # Reculs en séances : un mois, un trimestre, un an de cotation.
    for pas, mot in [(21, "un mois"), (63, "trois mois"), (250, "un an")]:
        if len(serie) > pas:
            passe = serie["cloture"].iloc[-1 - pas]
            if pd.notna(passe) and passe > 0:
                morceaux.append(
                    pedagogie.pourcentage(dernier["cloture"] / passe - 1)
                    + f" sur {mot}"
                )
    volume = dernier["volume_fcfa"]
    morceaux.append(
        "aucun échange lors de cette séance" if pd.isna(volume) or volume == 0
        else f"{pedagogie.montant(volume)} échangés dans la séance"
    )
    st.markdown(", ".join(morceaux) + ".")

    if len(serie) >= 2:
        # LE CURSEUR EST LE POINT, PAS L'ORNEMENT. Sur 2 876 séances, un
        # point fait moins d'un demi-pixel de large : viser une infobulle
        # est impossible, et une courbe sans lecture ponctuelle n'est
        # qu'une silhouette. La sélection porte sur l'abscisse la plus
        # proche du curseur, quelle que soit la hauteur de la souris.
        survol = alt.selection_point(nearest=True, on="pointermove",
                                     fields=["date"], empty=False)
        base_cours = alt.Chart(serie).encode(
            x=alt.X("date:T", title=None,
                    axis=alt.Axis(format="%d/%m/%y", tickCount=8)),
            # Format SI (« 22k ») : « 22,000 » est une convention
            # anglaise, et l'app affiche « 14 229 » juste au-dessus.
            y=alt.Y("cloture:Q", title="clôture (FCFA)",
                    scale=alt.Scale(zero=False),
                    axis=alt.Axis(format="~s")),
        )
        infobulle = [
            alt.Tooltip("date:T", title="Séance", format="%d/%m/%Y"),
            alt.Tooltip("cloture:Q", title="Clôture", format=",.0f"),
            alt.Tooltip("volume_titres:Q", title="Titres", format=",.0f"),
        ]
        # La zone de capture est transparente et couvre toute la hauteur :
        # une cible de survol doit être plus grande que la marque.
        capteur = (base_cours.mark_rule(strokeWidth=24, opacity=0)
                   .encode(tooltip=infobulle).add_params(survol))
        trait = base_cours.mark_rule(color=MUET, strokeWidth=1).transform_filter(survol)
        point = (base_cours.mark_point(size=80, filled=True, color=SERIE_1,
                                       stroke=SURFACE, strokeWidth=2)
                 .transform_filter(survol))
        _panneau(f"{choix} — cours de clôture",
                 f"{len(serie)} séances, {serie['date'].iloc[0]} → "
                 f"{serie['date'].iloc[-1]}").altair_chart(
            (base_cours.mark_line(strokeWidth=2, color=SERIE_1)
             + capteur + trait + point)
            # Une série de plusieurs années ne se lit pas d'un bloc.
            .properties(height=320),
            width="stretch",
        )
        st.caption("Survolez la courbe pour lire une séance.")
    else:
        st.info(f"Une seule séance en base pour {choix} : pas d'historique à "
                "tracer. Le graphique apparaîtra dès la deuxième.")

    mesures = fondamentaux[fondamentaux["ticker"] == choix] \
        if not fondamentaux.empty else pd.DataFrame()
    if not mesures.empty:
        st.subheader("Dividendes par exercice")
        large = (mesures.pivot_table(index="date", columns="indicateur",
                                     values="valeur", aggfunc="first")
                 .reset_index().sort_values("date", ascending=False))
        large["date"] = large["date"].str[:4]
        st.dataframe(
            large, width="stretch", hide_index=True,
            column_config={
                "date": st.column_config.TextColumn("Exercice"),
                "dividende": st.column_config.NumberColumn(
                    "Dividende net", format="%.2f", help="Par action, en FCFA."),
                "rendement": st.column_config.NumberColumn(
                    "Rendement", format="%.2f %%"),
            },
        )
        st.caption(
            "Un exercice absent du tableau est un exercice sans versement "
            "publié — pas un dividende nul : « n'a pas versé » et « on ne "
            "sait pas » ne sont pas la même chose."
        )

    if not div_valeur.empty:
        st.subheader("Détachements à venir")
        st.dataframe(div_valeur.sort_values("date_detachement", ascending=False),
                     width="stretch", hide_index=True)

    _telecharger(serie, f"{choix}.csv", "dl_valeur")
    _glossaire("dividende", "rendement", "liquidite", "sgi")


# --- Classement -----------------------------------------------------------
with onglets[2]:
    st.caption(
        "Momentum « 12-1 », filtré par liquidité et neutralisé par secteur. "
        "**Les pondérations n'ont été calibrées sur rien** : une liste de "
        "valeurs à examiner, pas un signal validé."
    )
    # Repliés : six curseurs en tête d'onglet, c'est un pupitre dont un
    # lecteur qui découvre le sujet ne peut pas connaître les bons réglages,
    # et qui modifient silencieusement le classement affiché en dessous. Les
    # valeurs par défaut sont celles de la configuration du projet.
    with st.expander("Réglages avancés"):
        reg_1, reg_2 = st.columns([1, 2])
        with reg_1:
            seuil = st.number_input(
                "Volume médian minimal (FCFA)", min_value=0, step=100_000,
                value=int(DEFAUTS["analyse"]["volume_median_min_fcfa"]),
                help="Une valeur qui ne s'échange pas ne se vend pas non plus.",
            )
            combien = st.slider("Lignes affichées", 5, 47, 15)
        with reg_2:
            poids = {
                "momentum":
                    st.slider("Poids du momentum", -1.0, 1.0, 0.5, 0.05),
                "tendance":
                    st.slider("Poids de la tendance", -1.0, 1.0, 0.3, 0.05),
                "volatilite":
                    st.slider("Poids de la volatilité", -1.0, 1.0, -0.2, 0.05),
            }

    reglages = {"analyse": {**DEFAUTS["analyse"],
                            "volume_median_min_fcfa": seuil},
                "ponderations": poids}
    classement = scoring.noter(features.calculer(cours_filtre, reglages),
                               referentiel_filtre, reglages)

    if classement.empty:
        _attente(
            "Classement",
            seances, reglages["analyse"]["fenetre_momentum"] + 1,
            "Le momentum se mesure sur un an de cotation. Calculé sur moins, "
            "il aurait toutes les apparences d'un momentum sans rien "
            "mesurer — d'où le refus plutôt qu'une approximation. "
            "L'archive gagne une séance par jour ouvré.",
        )
    else:
        # Le rang est ce qui se comprend sans rien savoir ; le score n'a pas
        # d'unité et ne se compare pas d'un jour à l'autre. `scoring` le
        # calcule déjà — il suffit de le mettre en tête de tableau.
        classement = classement[
            ["rang"] + [c for c in classement.columns if c != "rang"]
        ]
        tete = classement.head(combien)
        total = len(classement)
        st.markdown(
            f"{total} valeurs passent le filtre de liquidité et sont "
            f"classées. En tête : "
            + ", ".join(
                f"**{ligne.ticker}** ({pedagogie.ordinal(ligne.rang)})"
                for ligne in tete.head(3).itertuples()
            )
            + f" sur {total}. Le score n'a pas d'unité — seul l'ordre compte."
        )
        # POINTS ET NON BARRES. Une barre part obligatoirement de zéro, et
        # sur des scores compris entre 90 et 111 les quinze barres
        # paraissent identiques. Tronquer l'axe pour « voir la
        # différence » exagérerait des écarts que le score ne prétend pas
        # porter — il n'a pas d'unité, seul son ordre compte. Le point,
        # lui, ne réclame pas de ligne de base : il situe sans quantifier.
        base_score = alt.Chart(tete).encode(
            y=alt.Y("ticker:N", sort="-x", title=None,
                    axis=alt.Axis(labelOverlap=False)),
            x=alt.X("score:Q", title="score (sans unité)",
                    scale=alt.Scale(zero=False, nice=True)),
        )
        _panneau("Score composite",
                 f"{len(tete)} premières sur {total} classées · "
                 "aucun des traits qui le composent ne bat le hasard").altair_chart(
            (base_score.mark_rule(color=GRILLE, strokeWidth=1)
             .encode(x2=alt.X2("minimum:Q"))
             .transform_calculate(minimum=str(float(tete["score"].min())))
             + base_score
            .mark_point(size=110, filled=True, color=SERIE_1,
                        stroke=SURFACE, strokeWidth=2)
            .encode(
                tooltip=[
                    alt.Tooltip("rang:Q", title="Rang"),
                    alt.Tooltip("ticker:N", title="Symbole"),
                    alt.Tooltip("nom:N", title="Société"),
                    alt.Tooltip("score:Q", title="Score", format=".1f"),
                    alt.Tooltip("momentum:Q", title="Momentum", format="+.1%"),
                    alt.Tooltip("secteur:N", title="Secteur"),
                ],
            )).properties(height=max(240, 26 * len(tete))),
            width="stretch",
        )
        st.dataframe(
            tete, width="stretch", hide_index=True,
            column_config={
                "rang": st.column_config.NumberColumn(
                    "Rang", format="%d", help=f"Sur {total} valeurs classées."),
                "ticker": st.column_config.TextColumn("Symbole"),
                "nom": st.column_config.TextColumn("Société"),
                "secteur": st.column_config.TextColumn("Secteur"),
                "cloture": st.column_config.NumberColumn(
                    "Clôture", format="%.0f", help="En FCFA."),
                # Les traits sont des proportions : les afficher en 0,5733
                # oblige le lecteur à faire la conversion de tête.
                "momentum": st.column_config.NumberColumn(
                    "Momentum", format="percent",
                    help="Hausse accumulée sur l'année, dernier mois exclu."),
                "tendance": st.column_config.NumberColumn(
                    "Tendance", format="percent",
                    help="Écart entre moyenne courte et moyenne longue."),
                "volatilite": st.column_config.NumberColumn(
                    "Volatilité", format="percent",
                    help="Ampleur habituelle des écarts, en rythme annuel."),
                "liquidite": st.column_config.NumberColumn(
                    "Liquidité", format="localized",
                    help="Montant médian échangé par séance, en FCFA."),
                "score": st.column_config.NumberColumn(
                    "Score", format="%.1f",
                    help="Sans unité : seul l'ordre qu'il produit compte."),
            },
        )
        _telecharger(classement, "classement.csv", "dl_classement")

    # LE RENDEMENT PASSE DEVANT, ET C'EST LA DONNÉE QUI L'A DÉCIDÉ. Sur
    # les quatre exercices connus, le dividende médian vaut 7 à 10 % par
    # an, tous les ans ; le cours, lui, va de -1,6 % à +61,4 %. Le
    # classement par momentum ordonne le quart bruyant du rendement, et
    # aucun trait de prix ne bat le hasard sur 11,5 ans.
    st.subheader("Rendement du dividende")
    rendements = fondamentaux[fondamentaux["indicateur"] == "rendement"]
    if rendements.empty:
        st.info(
            "Aucun rendement en archive. `brvm dividendes` lit les "
            "calendriers de brvm.org et de sikafinance, et le tableau "
            "pluriannuel de ce dernier."
        )
    else:
        dernier_exercice = rendements["date"].max()
        recent = (rendements[rendements["date"] == dernier_exercice]
                  .merge(referentiel_filtre[["ticker", "nom", "secteur"]],
                         on="ticker", how="inner")
                  .sort_values("valeur", ascending=False))
        st.markdown(
            f"Exercice **{dernier_exercice[:4]}**, {len(recent)} sociétés. "
            f"Rendement médian **{pedagogie.pourcentage(recent['valeur'].median() / 100, signe=False)}** — "
            "à comparer aux 2,8 % l'an que rapporte le cours seul sur onze "
            "ans. **Sur ce marché, le dividende est l'essentiel du "
            "rendement**, et le classement ci-dessus n'en tient aucun compte."
        )
        if not recent.empty:
            tete = recent.head(15)
            _panneau(f"Rendement du dividende — exercice {dernier_exercice[:4]}",
                     "la part du rendement qui existe réellement sur ce "
                     "marché").altair_chart(
                alt.Chart(tete)
                .mark_bar(cornerRadiusEnd=4, height=16, color=SERIE_2)
                .encode(
                    x=alt.X("valeur:Q", title="rendement du dividende (%)"),
                    y=alt.Y("ticker:N", sort="-x", title=None,
                            axis=alt.Axis(labelOverlap=False)),
                    tooltip=[
                        alt.Tooltip("ticker:N", title="Symbole"),
                        alt.Tooltip("nom:N", title="Société"),
                        alt.Tooltip("valeur:Q", title="Rendement",
                                    format=".2f"),
                        alt.Tooltip("secteur:N", title="Secteur"),
                    ],
                )
                .properties(height=max(220, 24 * len(tete))),
                width="stretch",
            )
            st.dataframe(
                recent[["ticker", "nom", "secteur", "valeur"]],
                width="stretch", hide_index=True,
                column_config={
                    "ticker": st.column_config.TextColumn("Symbole"),
                    "nom": st.column_config.TextColumn("Société"),
                    "secteur": st.column_config.TextColumn("Secteur"),
                    "valeur": st.column_config.NumberColumn(
                        "Rendement", format="%.2f %%",
                        help="Dividende de l'exercice rapporté au cours."),
                },
            )
            _telecharger(recent, "rendements.csv", "dl_rendements")
        st.caption(
            "Quatre exercices seulement sont publiés : c'est assez pour "
            "voir que le dividende domine, beaucoup trop peu pour mesurer "
            "s'il prédit quoi que ce soit — quatre dates ne font pas une "
            "validation."
        )

    _glossaire("momentum", "tendance", "volatilite", "liquidite", "score",
               "rang", "dividende", "rendement", "frais")


# --- Prédiction -----------------------------------------------------------
with onglets[3]:
    st.caption(
        "Probabilité de **surperformer le marché sur trois mois** — pas de "
        "prévoir un cours. La BRVM cote par fixing, avec une limite de "
        "±7,5 % : un modèle entraîné sur le lendemain apprendrait "
        "« demain ≈ aujourd'hui » et produirait un backtest inexécutable."
    )
    validation = prediction.valider(cours_filtre, referentiel=referentiel_filtre)

    if validation.get("motif"):
        # L'apprentissage manque, le reste de l'app tient debout. On le dit
        # sans dramatiser : le composite est la référence, et elle est là.
        st.warning(prediction.expliquer(validation))
        st.caption(
            "Le classement composite reste disponible dans l'onglet "
            "**Classement** — c'est lui qui part en production quand le "
            "modèle appris ne le devance pas."
        )
    elif validation["periodes"].empty:
        _attente(
            "Prédiction",
            validation["lignes"], validation["lignes_minimum"],
            "Une observation, c'est une valeur à une date, avec son sort "
            "connu trois mois plus tard. Chaque séance en apporte une "
            "quarantaine — mais il faut d'abord un an de cotation avant que "
            "la première soit calculable.",
            unite="observation",
        )
    else:
        # L'IC se cite de mémoire, son incertitude non : la tuile porte
        # donc l'intervalle en légende, là où le chiffre ne peut pas
        # partir sans lui.
        m, c = validation["mesure"], validation["mesure_composite"]
        # L'intervalle passe en légende et non en `delta` : Streamlit dessine
        # une flèche devant un delta, et une incertitude n'a pas de sens de
        # variation — « ↑ ± 0,117 » se lit comme une hausse.
        mesures = st.columns(3)
        # L'intervalle passe en note et non en écart : Streamlit dessine
        # une flèche devant un delta, et une incertitude n'a pas de sens
        # de variation.
        _tuile(mesures[0], "IC du modèle", f"{validation['ic']:+.3f}",
               note=f"± {2 * m['erreur_type']:.3f} · t = {m['t']:+.1f} · "
                    + ("significatif" if m["significatif"]
                       else "indiscernable du hasard"))
        _tuile(mesures[1], "IC du composite",
               f"{validation['ic_composite']:+.3f}",
               note=f"± {2 * c['erreur_type']:.3f} · t = {c['t']:+.1f} · "
                    + ("significatif" if c["significatif"]
                       else "indiscernable du hasard"))
        _tuile(mesures[2], "Écart", f"{validation['ecart']:+.3f}",
               sens=1 if validation["ecart"] > 0 else -1,
               note="le modèle moins le composite")
        st.caption(
            f"L'intervalle couvre deux erreurs-types, calculées sur "
            f"{m['dates_independantes']} périodes **disjointes** et non sur "
            f"les {m['dates']} dates de test : avec un horizon de "
            f"{validation['horizon']} séances, deux dates voisines "
            "racontent la même histoire. Les compter comme indépendantes "
            "multiplie la certitude apparente par huit."
        )

        # Le constat le plus important de l'onglet, et il ne tient pas
        # dans une tuile : sur quoi le classement repose-t-il vraiment ?
        traits_mesures = validation.get("traits_mesures") or {}
        if traits_mesures:
            table = pd.DataFrame([
                {"trait": pedagogie.LIBELLES.get(t, t), "IC": mes["ic"],
                 "± 2 erreurs-types": 2 * mes["erreur_type"],
                 "t": mes["t"],
                 "verdict": "significatif" if mes["significatif"]
                            else "indiscernable du hasard"}
                for t, mes in traits_mesures.items()
            ])
            if not table.empty and not table["verdict"].eq("significatif").any():
                st.error(
                    "**Aucun trait ne se distingue du hasard.** Le "
                    "classement reste une description du marché — qui a "
                    "monté, qui s'échange — mais rien ici n'autorise à en "
                    "attendre un rendement."
                )
            with st.expander("Ce que vaut chaque trait, pris séparément"):
                st.dataframe(
                    table, width="stretch", hide_index=True,
                    column_config={
                        "trait": st.column_config.TextColumn("Trait"),
                        "IC": st.column_config.NumberColumn(format="%+.3f"),
                        "± 2 erreurs-types":
                            st.column_config.NumberColumn(format="%.3f"),
                        "t": st.column_config.NumberColumn(format="%+.1f"),
                        "verdict": st.column_config.TextColumn("Verdict"),
                    },
                )

        if validation["ecart"] <= 0:
            st.warning(
                "**Le modèle ne bat pas le score composite.** C'est le cas le "
                "plus fréquent sur ce marché : c'est le composite — onglet "
                "Classement — qui doit partir en production."
            )
        elif validation["ic"] > 0.30:
            st.error(
                f"**IC de {validation['ic']:.3f} — anormalement élevé.** "
                "Un IC exploitable vaut 0,02 à 0,05. Cherchez la fuite."
            )
        st.dataframe(
            validation["periodes"], width="stretch", hide_index=True,
            column_config={
                "periode": st.column_config.TextColumn("Période de test"),
                "lignes_entrainement": st.column_config.NumberColumn(
                    "Appris sur", format="localized",
                    help="Observations d'entraînement, étiquettes "
                         "recouvrantes purgées."),
                "lignes_test": st.column_config.NumberColumn(
                    "Testé sur", format="localized"),
                "ic_modele": st.column_config.NumberColumn(
                    "IC du modèle", format="%+.3f"),
                "ic_composite": st.column_config.NumberColumn(
                    "IC du composite", format="%+.3f"),
                "precision": st.column_config.NumberColumn(
                    "Précision", format="percent",
                    help="Part des paris justes. Trompeuse seule : "
                         "c'est l'IC qui compte."),
            },
        )

        probable = prediction.predire(cours_filtre, referentiel=referentiel_filtre)
        if not probable.empty:
            probable = probable.merge(referentiel[["ticker", "nom", "secteur"]],
                                      on="ticker", how="left")
            tete = probable.head(15)
            _panneau("Probabilité de surperformer le marché",
                     "à trois mois, quinze premières").altair_chart(
                alt.Chart(tete)
                .mark_bar(cornerRadiusEnd=4, height=16, color=SERIE_1)
                .encode(
                    x=alt.X("probabilite:Q",
                            title="probabilité de surperformer",
                            axis=alt.Axis(format=".0%")),
                    y=alt.Y("ticker:N", sort="-x", title=None,
                            axis=alt.Axis(labelOverlap=False)),
                    tooltip=[
                        alt.Tooltip("ticker:N", title="Symbole"),
                        alt.Tooltip("nom:N", title="Société"),
                        alt.Tooltip("probabilite:Q", title="Probabilité",
                                    format=".1%"),
                        alt.Tooltip("secteur:N", title="Secteur"),
                    ],
                )
                .properties(height=max(220, 24 * len(tete))),
                width="stretch",
            )
            # Jumeau tabulaire : une infobulle ne doit jamais être le seul
            # accès à une valeur.
            st.dataframe(probable, width="stretch", hide_index=True)
            _telecharger(probable, "prediction.csv", "dl_prediction")

    st.warning("**Ce que ces chiffres ne disent pas.** "
               + " ; ".join(validation["avertissements"]) + ".")

    st.subheader("Rendement du dividende")
    st.caption("Télécoms et services publics : retour à la moyenne du "
               "rendement, sans apprentissage. Cinq valeurs ne font pas un "
               "échantillon d'apprentissage.")
    cibles = list(referentiel_filtre[
        referentiel_filtre["secteur"].isin(
            ["Télécommunications", "Services Publics"])]["ticker"])
    st.code(dividende.expliquer(
        dividende.signal(cours_filtre, dividendes, tickers=cibles)), language=None)

    _glossaire("ic", "score", "rendement", "frais")


# --- Backtest -------------------------------------------------------------
with onglets[4]:
    st.caption(
        "Ce qu'aurait donné le classement s'il avait été suivi dans le "
        "passé — frais compris. Un bon résultat ici ne promet rien : il dit "
        "seulement que la règle n'était pas absurde."
    )
    with st.expander("Réglages avancés"):
        bt = st.columns(3)
        positions = bt[0].slider("Positions en portefeuille", 3, 20, 10)
        frais = bt[1].number_input("Frais par passage (%)", 0.0, 5.0, 1.0, 0.1)
        impact = bt[2].number_input("Impact de marché (%)", 0.0, 5.0, 0.5, 0.1)

    resultat = backtest.backtester(
        cours_filtre, referentiel_filtre,
        {"analyse": DEFAUTS["analyse"], "ponderations": DEFAUTS["ponderations"],
         "backtest": {**DEFAUTS["backtest"], "positions": positions,
                      "frais_pourcent": frais, "impact_pourcent": impact}},
        fondamentaux=fondamentaux,
    )

    if resultat["etapes"].empty:
        _attente(
            "Backtest",
            resultat["seances"], resultat["seances_requises"],
            "Il faut un an de cotation avant la première décision, puis une "
            "période à mesurer ensuite. Un backtest plus court ne mesurerait "
            "que le hasard de sa fenêtre.",
        )
    else:
        m = st.columns(4)
        ecart_bt = resultat["rendement_total"] - resultat["reference_total"]
        _tuile(m[0], "Stratégie",
               pedagogie.pourcentage(resultat["rendement_total"]),
               sens=1 if resultat["rendement_total"] > 0 else -1,
               note=f"{pedagogie.pourcentage(resultat['rendement_annualise'])} "
                    "par an")
        _tuile(m[1], "Référence équipondérée",
               pedagogie.pourcentage(resultat["reference_total"]),
               sens=1 if resultat["reference_total"] > 0 else -1,
               note=f"{pedagogie.pourcentage(resultat['reference_annualisee'])} "
                    "par an — c'est elle qu'il faut battre")
        _tuile(m[2], "Perte maximale",
               pedagogie.pourcentage(resultat["perte_max"], signe=False),
               note="plus forte baisse depuis un sommet")
        _tuile(m[3], "Coût cumulé",
               pedagogie.pourcentage(resultat["cout_cumule"], signe=False),
               sens=-1,
               note=f"{resultat['rotation_moyenne']:.0%} de rotation moyenne")

        # Le verdict en toutes lettres : quatre tuiles ne disent pas d'
        # elles-mêmes laquelle des deux courbes gagne, et c'est la seule
        # question que pose cet onglet.
        etapes = resultat["etapes"]
        ecart = resultat["rendement_total"] - resultat["reference_total"]

        # Le dividende n'est pas un détail sur ce marché : il vaut deux à
        # trois fois le rendement du cours. Dire ce qu'il apporte, et sur
        # quelle part de la période il est connu, doit précéder le reste.
        couverture = resultat.get("couverture_dividende")
        if couverture and couverture["part"] > 0:
            st.info(
                "**Dividende compté** sur "
                f"{pedagogie.pourcentage(couverture['part'], signe=False)} "
                f"des séances (exercices {', '.join(couverture['exercices'])}). "
                f"Il apporte {pedagogie.pourcentage(resultat['apport_dividende'])} "
                "au total : sans lui, la stratégie rendrait "
                f"{pedagogie.pourcentage(resultat['rendement_prix_annualise'])} "
                f"l'an au lieu de {pedagogie.pourcentage(resultat['rendement_annualise'])}. "
                "Faute de date de détachement publiée, il est réparti sur "
                "les séances de son exercice plutôt que crédité le jour "
                "même — une correction de niveau, pas de profil."
            )
        st.markdown(
            f"Sur {resultat['rebalancements']} rééquilibrages entre le "
            f"{pedagogie.jour(etapes['date_entree'].iloc[0])} et le "
            f"{pedagogie.jour(etapes['date_sortie'].iloc[-1])}, la stratégie "
            f"rapporte {pedagogie.pourcentage(resultat['rendement_total'])} "
            f"contre {pedagogie.pourcentage(resultat['reference_total'])} "
            "pour la référence — "
            + ("**elle la bat** de " if ecart > 0 else "**elle perd** de ")
            + f"{pedagogie.pourcentage(abs(ecart), signe=False)}. Les frais "
            f"ont coûté {pedagogie.pourcentage(resultat['cout_cumule'], signe=False)} "
            "en cumul."
        )

        courbes = resultat["etapes"].melt(
            id_vars="date_sortie", value_vars=["valeur", "valeur_reference"],
            var_name="serie", value_name="part",
        ).replace({"valeur": "Stratégie",
                   "valeur_reference": "Référence équipondérée"})

        couleurs = alt.Color(
            "serie:N", title=None,
            scale=alt.Scale(domain=["Stratégie", "Référence équipondérée"],
                            range=[SERIE_1, SERIE_2]),
            legend=alt.Legend(orient="bottom", direction="horizontal"),
        )
        base = alt.Chart(courbes).encode(
            x=alt.X("date_sortie:T", title=None,
                    axis=alt.Axis(format="%d/%m/%y", tickCount=8)),
            y=alt.Y("part:Q", title="valeur d'une part",
                    scale=alt.Scale(zero=False)),
            color=couleurs,
        )
        lignes = base.mark_line(strokeWidth=2).encode(
            tooltip=[
                alt.Tooltip("date_sortie:T", title="Date", format="%d/%m/%Y"),
                alt.Tooltip("serie:N", title="Série"),
                alt.Tooltip("part:Q", title="Valeur", format=".3f"),
            ],
        )
        derniers = courbes.loc[courbes.groupby("serie")["date_sortie"].idxmax()]
        # LE POINT PORTE LA COULEUR, LE TEXTE PORTE L'ENCRE. Colorer le texte
        # confierait l'identité à un canal qu'il n'assume pas : une teinte
        # claire est illisible en texte sur le fond. L'anneau de 2 px à la
        # couleur du fond détache le point de la courbe.
        points = (alt.Chart(derniers)
                  .mark_point(size=90, filled=True, stroke=SURFACE, strokeWidth=2)
                  .encode(x="date_sortie:T", y="part:Q", color=couleurs))
        etiquettes = (alt.Chart(derniers)
                      .mark_text(align="left", dx=12, fontSize=12,
                                 color=ENCRE_DOUCE)
                      .encode(x="date_sortie:T", y="part:Q", text="serie:N"))

        _panneau("Valeur d'une part",
                 "stratégie contre univers éligible équipondéré, "
                 "frais et dividende compris").altair_chart(
            (lignes + points + etiquettes).properties(
                height=360,
                padding={"right": 150, "left": 5, "top": 5, "bottom": 5}),
            width="stretch",
        )
        st.caption("La référence est l'univers éligible équipondéré : c'est "
                   "elle qu'il faut battre, pas zéro.")
        st.dataframe(
            etapes, width="stretch", hide_index=True,
            column_config={
                "date_decision": st.column_config.TextColumn(
                    "Décidé le",
                    help="Sur la clôture de cette séance, et rien après."),
                "date_entree": st.column_config.TextColumn(
                    "Acheté le",
                    help="Une séance plus tard : décider et exécuter au même "
                         "cours reviendrait à passer un ordre à un prix déjà "
                         "connu."),
                "date_sortie": st.column_config.TextColumn("Revendu le"),
                "positions": st.column_config.TextColumn("Lignes détenues"),
                "rendement": st.column_config.NumberColumn(
                    "Cours", format="percent"),
                "dividende": st.column_config.NumberColumn(
                    "Dividende", format="percent",
                    help="Accru pendant la détention."),
                "rotation": st.column_config.NumberColumn(
                    "Rotation", format="percent",
                    help="Part du portefeuille remplacée — elle se paie deux "
                         "fois, à la vente et au rachat."),
                "cout": st.column_config.NumberColumn("Coût", format="percent"),
                "valeur": st.column_config.NumberColumn(
                    "Part stratégie", format="%.3f"),
                "valeur_reference": st.column_config.NumberColumn(
                    "Part référence", format="%.3f"),
            },
        )
        _telecharger(resultat["etapes"], "backtest.csv", "dl_backtest")

    st.warning("**Trois biais survivent et ne sont pas corrigeables ici :** "
               + " ; ".join(resultat["avertissements"]) + ".")
    _glossaire("backtest", "reference", "perte_max", "rotation", "frais",
               "survivant")


# --- Données --------------------------------------------------------------
with onglets[5]:
    etat = st.columns(3)
    _tuile(etat[0], "Séances en archive", f"{seances}",
           note=f"{cours['date'].min()} → {cours['date'].max()}")
    _tuile(etat[1], "Dividendes",
           f"{len(dividendes)} + {len(fondamentaux)}",
           note="détachements datés, puis mesures par exercice")
    _tuile(etat[2], "Sociétés au référentiel", f"{len(referentiel)}",
           note=f"{int(referentiel['secteur'].notna().sum())} avec secteur")

    # Visible sans avoir à ouvrir les journaux de l'hébergeur : un onglet
    # bridé s'explique ici plutôt que de laisser croire à un bug.
    st.caption(
        "Modèle appris : "
        + ("**disponible** (scikit-learn installé)."
           if prediction.APPRENTISSAGE_DISPONIBLE else
           "**indisponible** — scikit-learn absent de l'environnement. "
           "Le score composite, lui, ne dépend d'aucune bibliothèque "
           "d'apprentissage et reste calculé.")
    )

    if referentiel_filtre["secteur"].notna().any():
        comptes = (referentiel_filtre.groupby("secteur").size()
                   .reset_index(name="sociétés"))
        _panneau("Répartition sectorielle",
                 f"{len(referentiel_filtre)} sociétés").altair_chart(
            alt.Chart(comptes)
            .mark_bar(cornerRadiusEnd=4, height=20, color=SERIE_1)
            .encode(
                # tickMinStep=1 : un décompte de sociétés n'a pas de
                # demi-unité, et un axe qui en affiche invente une précision.
                x=alt.X("sociétés:Q", title="sociétés",
                        axis=alt.Axis(tickMinStep=1, format="d")),
                # labelLimit relevé : par défaut Vega tronquait
                # « Consommation de Base » et « Consommation Discrétionnaire »
                # au même « Consommation d… ».
                y=alt.Y("secteur:N", sort="-x", title=None,
                        axis=alt.Axis(labelLimit=220)),
                tooltip=[alt.Tooltip("secteur:N", title="Secteur"),
                         alt.Tooltip("sociétés:Q", title="Sociétés")],
            )
            .properties(height=260),
            width="stretch",
        )

    st.subheader("Couverture de l'archive")
    par_date = cours.groupby("date").size().reset_index(name="lignes")
    st.dataframe(par_date.tail(30), width="stretch", hide_index=True)

    st.caption(
        "Source : brvm.org, ingéré par l'action `ingestion.yml` et versionné "
        "dans `data/cours.csv`. L'app ne lit que ces fichiers — elle n'écrit "
        "rien et ne conserve aucun état. Dividendes, fondamentaux et séries "
        "de commodités se chargent par « brvm importer-* »."
    )
