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

from brvm import backtest, db, dividende, features, prediction, scoring
from brvm.config import DEFAUTS
from brvm.ingestion import brvm_org

st.set_page_config(page_title="BRVM", page_icon="📈", layout="wide")


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

POLICE = 'system-ui, -apple-system, "Segoe UI", sans-serif'


@alt.theme.register("brvm", enable=True)
def _theme() -> alt.theme.ThemeConfig:
    """Chrome discret : la grille et les axes ne concurrencent pas les
    marques qui portent la donnée. Traits pleins, jamais pointillés — un
    pointillé se lit comme une projection ou un seuil."""
    return alt.theme.ThemeConfig({
        "background": SURFACE,
        "view": {"stroke": "transparent"},
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


# --- Données --------------------------------------------------------------

@st.cache_data(ttl=900)
def charger_archive():
    return (db.charger_archive("cours"), db.charger_archive("referentiel"),
            db.charger_archive("dividendes"))


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


cours, referentiel, dividendes = charger_archive()
if referentiel.empty:
    referentiel = brvm_org.referentiel_amorce()

st.title("Bourse Régionale des Valeurs Mobilières")

direct, echec = (None, None)
if cours.empty:
    direct, echec = lire_en_direct()

entete_1, entete_2 = st.columns([3, 1])
with entete_2:
    if st.button("Actualiser depuis brvm.org", width="stretch"):
        lire_en_direct.clear()
        direct, echec = lire_en_direct()

if direct is not None and not direct.empty:
    cours = (pd.concat([cours, direct], ignore_index=True)
             .drop_duplicates(subset=["date", "ticker"], keep="last"))
    entete_1.success(
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
filtre_1, filtre_2 = st.columns([3, 2])
with filtre_1:
    secteurs = st.multiselect(
        "Secteurs", secteurs_connus, default=secteurs_connus,
        help="Cadre l'ensemble du tableau de bord.",
    )
with filtre_2:
    recherche = st.text_input("Rechercher", placeholder="Symbole ou société")

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

    tuiles = st.columns(4)
    tuiles[0].metric("Séance", derniere)
    tuiles[1].metric("Variation médiane",
                     "—" if connues.empty else f"{connues.median():+.2%}")
    # Largeur du marché : une médiane positive portée par trois valeurs ne
    # dit pas la même chose qu'une hausse partagée.
    tuiles[2].metric(
        "Hausses / baisses",
        "—" if connues.empty
        else f"{int((connues > 0).sum())} / {int((connues < 0).sum())}",
    )
    tuiles[3].metric("Valeurs affichées", f"{jour['ticker'].nunique()}",
                     delta=(None if len(retenus) == len(referentiel)
                            else f"{len(retenus) - len(referentiel)} filtrées"))

    if not connues.empty:
        st.subheader(f"Variation de la séance du {derniere}")
        classees = jour.dropna(subset=["variation"]).sort_values("variation")
        st.altair_chart(
            alt.Chart(classees)
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
            .properties(height=max(280, 22 * len(classees))),
            width="stretch",
        )
    else:
        st.info("Une seule séance en base : aucune variation calculable.")

    colonnes = ["ticker", "nom", "secteur", "cloture"]
    if not connues.empty:
        colonnes.append("variation")
    colonnes += ["volume_titres", "volume_fcfa"]
    st.dataframe(
        jour[colonnes].sort_values("ticker"), width="stretch", hide_index=True,
        column_config={
            "ticker": st.column_config.TextColumn("Symbole"),
            "nom": st.column_config.TextColumn("Société"),
            "secteur": st.column_config.TextColumn("Secteur"),
            "cloture": st.column_config.NumberColumn("Clôture", format="%.0f"),
            "variation": st.column_config.NumberColumn("Var.", format="%+.2f%%"),
            "volume_titres": st.column_config.NumberColumn("Titres", format="%.0f"),
            "volume_fcfa": st.column_config.NumberColumn("FCFA", format="%.0f"),
        },
    )
    _telecharger(jour[colonnes], f"brvm_{derniere}.csv", "dl_marche")


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
    faits[0].metric(
        "Clôture", f"{dernier['cloture']:,.0f}".replace(",", " "),
        delta=(f"{serie['cloture'].iloc[-1] / serie['cloture'].iloc[-2] - 1:+.2%}"
               if len(serie) >= 2 else None),
    )
    faits[1].metric(
        "Volume (FCFA)",
        f"{dernier['volume_fcfa']:,.0f}".replace(",", " ")
        if pd.notna(dernier["volume_fcfa"]) else "—",
    )
    faits[2].metric("Dividendes connus", f"{len(div_valeur)}")

    if len(serie) >= 2:
        st.altair_chart(
            alt.Chart(serie)
            .mark_line(strokeWidth=2, color=SERIE_1)
            .encode(
                x=alt.X("date:T", title=None,
                        axis=alt.Axis(format="%d/%m/%y", tickCount=8)),
                # Format SI (« 22k ») : « 22,000 » est une convention
                # anglaise, et l'app affiche « 14 229 » juste au-dessus.
                y=alt.Y("cloture:Q", title="clôture (FCFA)",
                        scale=alt.Scale(zero=False),
                        axis=alt.Axis(format="~s")),
                tooltip=[
                    alt.Tooltip("date:T", title="Séance", format="%d/%m/%Y"),
                    alt.Tooltip("cloture:Q", title="Clôture", format=",.0f"),
                    alt.Tooltip("volume_titres:Q", title="Titres", format=",.0f"),
                ],
            )
            # Une série de plusieurs années ne se lit pas d'un bloc.
            .properties(height=320).interactive(),
            width="stretch",
        )
        st.caption("Molette pour zoomer, glisser pour parcourir.")
    else:
        st.info(f"Une seule séance en base pour {choix} : pas d'historique à "
                "tracer. Le graphique apparaîtra dès la deuxième.")

    if not div_valeur.empty:
        st.subheader("Dividendes")
        st.dataframe(div_valeur.sort_values("date_detachement", ascending=False),
                     width="stretch", hide_index=True)

    _telecharger(serie, f"{choix}.csv", "dl_valeur")


# --- Classement -----------------------------------------------------------
with onglets[2]:
    st.caption(
        "Momentum « 12-1 », filtré par liquidité et neutralisé par secteur. "
        "**Les pondérations n'ont été calibrées sur rien** : une liste de "
        "valeurs à examiner, pas un signal validé."
    )
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
            "momentum": st.slider("Poids du momentum", -1.0, 1.0, 0.5, 0.05),
            "tendance": st.slider("Poids de la tendance", -1.0, 1.0, 0.3, 0.05),
            "volatilite": st.slider("Poids de la volatilité", -1.0, 1.0, -0.2, 0.05),
        }

    reglages = {"analyse": {**DEFAUTS["analyse"],
                            "volume_median_min_fcfa": seuil},
                "ponderations": poids}
    classement = scoring.noter(features.calculer(cours_filtre, reglages),
                               referentiel_filtre, reglages)

    if classement.empty:
        st.info(
            f"Aucune valeur classée. {seances} séance"
            f"{'s' if seances > 1 else ''} en base ; le momentum en demande "
            f"{reglages['analyse']['fenetre_momentum'] + 1}. Un momentum "
            "calculé sur moins aurait l'apparence d'un momentum sans rien "
            "mesurer — d'où le refus plutôt qu'une approximation."
        )
    else:
        tete = classement.head(combien)
        st.altair_chart(
            alt.Chart(tete)
            .mark_bar(cornerRadiusEnd=4, height=16, color=SERIE_1)
            .encode(
                x=alt.X("score:Q", title="score"),
                y=alt.Y("ticker:N", sort="-x", title=None,
                        axis=alt.Axis(labelOverlap=False)),
                tooltip=[
                    alt.Tooltip("ticker:N", title="Symbole"),
                    alt.Tooltip("nom:N", title="Société"),
                    alt.Tooltip("score:Q", title="Score", format=".1f"),
                    alt.Tooltip("momentum:Q", title="Momentum", format="+.1%"),
                    alt.Tooltip("secteur:N", title="Secteur"),
                ],
            )
            .properties(height=max(220, 24 * len(tete))),
            width="stretch",
        )
        st.dataframe(tete, width="stretch", hide_index=True)
        _telecharger(classement, "classement.csv", "dl_classement")


# --- Prédiction -----------------------------------------------------------
with onglets[3]:
    st.caption(
        "Probabilité de **surperformer le marché sur trois mois** — pas de "
        "prévoir un cours. La BRVM cote par fixing, avec une limite de "
        "±7,5 % : un modèle entraîné sur le lendemain apprendrait "
        "« demain ≈ aujourd'hui » et produirait un backtest inexécutable."
    )
    validation = prediction.valider(cours_filtre, referentiel=referentiel_filtre)

    if validation["periodes"].empty:
        st.info(prediction.expliquer(validation))
    else:
        mesures = st.columns(3)
        mesures[0].metric("IC du modèle", f"{validation['ic']:+.3f}")
        mesures[1].metric("IC du composite", f"{validation['ic_composite']:+.3f}")
        mesures[2].metric("Écart", f"{validation['ecart']:+.3f}")

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
        st.dataframe(validation["periodes"], width="stretch", hide_index=True)

        probable = prediction.predire(cours_filtre, referentiel=referentiel_filtre)
        if not probable.empty:
            probable = probable.merge(referentiel[["ticker", "nom", "secteur"]],
                                      on="ticker", how="left")
            tete = probable.head(15)
            st.altair_chart(
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


# --- Backtest -------------------------------------------------------------
with onglets[4]:
    bt = st.columns(3)
    positions = bt[0].slider("Positions en portefeuille", 3, 20, 10)
    frais = bt[1].number_input("Frais par passage (%)", 0.0, 5.0, 1.0, 0.1)
    impact = bt[2].number_input("Impact de marché (%)", 0.0, 5.0, 0.5, 0.1)

    resultat = backtest.backtester(
        cours_filtre, referentiel_filtre,
        {"analyse": DEFAUTS["analyse"], "ponderations": DEFAUTS["ponderations"],
         "backtest": {**DEFAUTS["backtest"], "positions": positions,
                      "frais_pourcent": frais, "impact_pourcent": impact}},
    )

    if resultat["etapes"].empty:
        st.info(backtest.expliquer(resultat))
    else:
        m = st.columns(4)
        m[0].metric("Stratégie", f"{resultat['rendement_total']:+.1%}")
        m[1].metric("Référence", f"{resultat['reference_total']:+.1%}")
        m[2].metric("Perte max.", f"{resultat['perte_max']:.1%}")
        m[3].metric("Coût cumulé", f"{resultat['cout_cumule']:.1%}")

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

        st.altair_chart(
            (lignes + points + etiquettes).properties(
                height=360,
                padding={"right": 150, "left": 5, "top": 5, "bottom": 5}),
            width="stretch",
        )
        st.caption("La référence est l'univers éligible équipondéré : c'est "
                   "elle qu'il faut battre, pas zéro.")
        st.dataframe(resultat["etapes"], width="stretch", hide_index=True)
        _telecharger(resultat["etapes"], "backtest.csv", "dl_backtest")

    st.warning("**Trois biais survivent et ne sont pas corrigeables ici :** "
               + " ; ".join(resultat["avertissements"]) + ".")


# --- Données --------------------------------------------------------------
with onglets[5]:
    etat = st.columns(3)
    etat[0].metric("Séances en base", f"{seances}")
    etat[1].metric("Dividendes en base", f"{len(dividendes)}")
    etat[2].metric("Sociétés au référentiel", f"{len(referentiel)}")

    st.subheader("Répartition sectorielle")
    if referentiel_filtre["secteur"].notna().any():
        comptes = (referentiel_filtre.groupby("secteur").size()
                   .reset_index(name="sociétés"))
        st.altair_chart(
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
