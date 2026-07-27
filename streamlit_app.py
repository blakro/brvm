"""Tableau de bord BRVM — point d'entrée de Streamlit Community Cloud.

L'app ne lit que les CSV versionnés du dépôt : pas de base sur le
conteneur, pas d'écriture, pas d'état. Un hébergeur gratuit redémarre le
conteneur quand il veut et son disque ne survit pas ; y stocker quoi que ce
soit donnerait une app qui affiche des données introuvables ailleurs.

Le pipeline reste l'action GitHub `ingestion.yml` : elle ingère, réécrit
les CSV et les commite. L'app ne fait que lire et calculer.

Les couleurs suivent une paire divergente bleu ↔ rouge plutôt que le
vert/rouge boursier habituel : la confusion vert-rouge est le déficit
visuel le plus répandu, et le signe est de toute façon écrit dans les
tableaux à côté.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from brvm import backtest, db, features, prediction, scoring
from brvm.config import DEFAUTS
from brvm.ingestion import brvm_org

# --- Palette validée (validate_palette.js, mode clair) --------------------
HAUSSE = "#2a78d6"      # bleu — pôle positif de la paire divergente
BAISSE = "#e34948"      # rouge — pôle négatif
NEUTRE = "#f0efec"
SERIE_1 = "#2a78d6"
SERIE_2 = "#eb6834"     # orange, slot 2 : ΔE 24.7 face au bleu en protanopie
ENCRE = "#0b0b0b"
ENCRE_DOUCE = "#52514e"
GRILLE = "#e1e0d9"
SURFACE = "#fcfcfb"

st.set_page_config(page_title="BRVM", page_icon="📈", layout="wide")


@alt.theme.register("brvm", enable=True)
def _theme() -> alt.theme.ThemeConfig:
    """Chrome discret : la grille et les axes ne doivent pas concurrencer
    les marques qui portent la donnée."""
    return alt.theme.ThemeConfig({
        "background": SURFACE,
        "view": {"stroke": "transparent"},
        "axis": {
            "labelColor": ENCRE_DOUCE, "titleColor": ENCRE_DOUCE,
            "gridColor": GRILLE, "domainColor": "#c3c2b7",
            "tickColor": "#c3c2b7", "labelFontSize": 12, "titleFontSize": 12,
        },
        "legend": {"labelColor": ENCRE, "titleColor": ENCRE_DOUCE},
        "font": 'system-ui, -apple-system, "Segoe UI", sans-serif',
    })


@st.cache_data(ttl=900)
def charger_archive():
    """CSV versionnés → DataFrames. Relu au plus tous les quarts d'heure.

    La cote ne bouge qu'une fois par jour ; relire le fichier à chaque
    interaction ne servirait qu'à ralentir les curseurs.
    """
    return db.charger_archive("cours"), db.charger_archive("referentiel")


@st.cache_data(ttl=900, show_spinner="Lecture de brvm.org…")
def lire_en_direct():
    """Séance publiée, lue sur le site. (cote, erreur) — l'un des deux vaut None.

    L'app ne doit pas dépendre de l'action planifiée pour montrer quelque
    chose : celle-ci peut n'avoir jamais tourné, ou ne pas atteindre le site
    depuis les adresses de GitHub. Quand elle a du retard, l'app va chercher
    la séance elle-même.

    Attention : hors clôture, la colonne « Cours Clôture » de brvm.org porte
    le dernier cours traité. C'est bon à afficher, jamais à archiver — d'où
    l'étiquette « provisoire » et l'absence totale d'écriture ici.
    """
    try:
        return brvm_org.lire_cote(), None
    except Exception as erreur:  # noqa: BLE001 — le motif est l'information utile
        # Le type suffit à orienter (réseau, page illisible, refus) ; la pile
        # complète d'une erreur réseau fait trois lignes de bruit à l'écran.
        detail = str(erreur).split("\n")[0][:110]
        return None, f"{type(erreur).__name__} — {detail}"


cours, referentiel = charger_archive()
if referentiel.empty:
    referentiel = brvm_org.referentiel_amorce()

st.title("Bourse Régionale des Valeurs Mobilières")

# Un archive absente ne doit pas donner une page vide : on tente le site.
direct, echec = (None, None)
if cours.empty:
    direct, echec = lire_en_direct()

barre_1, barre_2 = st.columns([3, 1])
with barre_2:
    if st.button("Actualiser depuis brvm.org", width="stretch"):
        lire_en_direct.clear()
        direct, echec = lire_en_direct()

if direct is not None and not direct.empty:
    heure = direct.attrs.get("heure_mise_a_jour")
    cours = (
        pd.concat([cours, direct], ignore_index=True)
        .drop_duplicates(subset=["date", "ticker"], keep="last")
    )
    barre_1.success(
        f"Séance du {direct['date'].iloc[0]} lue à l'instant sur brvm.org "
        f"(mise à jour du site : {heure or 'inconnue'}). "
        "Affichée seulement — l'archive du dépôt n'est pas modifiée."
    )

if cours.empty:
    st.warning(
        "**Aucune donnée.** L'archive `data/cours.csv` est vide et brvm.org "
        "n'a pas répondu"
        + (f" — {echec}." if echec else ".")
        + " L'archive se remplit quand l'action `ingestion.yml` tourne, "
        "chaque jour ouvré à 16 h UTC ; les workflows planifiés ne "
        "s'exécutent que sur la branche par défaut du dépôt."
    )
    st.stop()

seances = cours["date"].nunique()
derniere = cours["date"].max()

haut_1, haut_2, haut_3 = st.columns(3)
haut_1.metric("Dernière séance", derniere)
haut_2.metric("Séances en base", f"{seances}")
haut_3.metric("Sociétés suivies", f"{cours['ticker'].nunique()}")

if echec and not cours.empty:
    st.caption(f"brvm.org injoignable ({echec}) — affichage de l'archive.")

onglets = st.tabs(["Cote du jour", "Classement", "Prédiction", "Backtest",
                   "Données"])


# --- Cote du jour ---------------------------------------------------------
with onglets[0]:
    jour = cours[cours["date"] == derniere].copy()
    veille = cours["date"].sort_values().unique()
    if len(veille) >= 2:
        precedent = cours[cours["date"] == veille[-2]].set_index("ticker")["cloture"]
        jour["variation"] = jour["ticker"].map(precedent)
        jour["variation"] = jour["cloture"] / jour["variation"] - 1
    else:
        jour["variation"] = pd.NA

    jour = jour.merge(referentiel[["ticker", "nom", "secteur"]], on="ticker",
                      how="left")

    if jour["variation"].notna().any():
        st.subheader(f"Variation de la séance du {derniere}")
        classees = jour.dropna(subset=["variation"]).sort_values("variation")
        graphe = (
            alt.Chart(classees)
            .mark_bar(cornerRadiusEnd=4, height=14)
            .encode(
                # Axe en haut : le graphique fait plusieurs écrans de haut,
                # une échelle reléguée en bas obligerait à faire l'aller-retour
                # pour lire une barre.
                x=alt.X("variation:Q", title="variation",
                        axis=alt.Axis(format="+.1%", orient="top")),
                # `labelOverlap=False` : sans cela Vega masque un libellé sur
                # deux dès que les lignes se resserrent, et la moitié des
                # barres devient impossible à rattacher à une société.
                y=alt.Y("ticker:N", sort=alt.SortField("variation", "descending"),
                        title=None, axis=alt.Axis(labelOverlap=False)),
                # Divergent : le signe porte la couleur, et il est aussi
                # écrit dans l'infobulle et dans le tableau ci-dessous.
                color=alt.condition(
                    alt.datum.variation >= 0,
                    alt.value(HAUSSE), alt.value(BAISSE),
                ),
                tooltip=[
                    alt.Tooltip("ticker:N", title="Symbole"),
                    alt.Tooltip("nom:N", title="Société"),
                    alt.Tooltip("cloture:Q", title="Clôture", format=",.0f"),
                    alt.Tooltip("variation:Q", title="Variation", format="+.2%"),
                    alt.Tooltip("secteur:N", title="Secteur"),
                ],
            )
            .properties(height=max(280, 22 * len(classees)))
        )
        st.altair_chart(graphe, width="stretch")
    else:
        st.info(
            "Une seule séance en base : aucune variation calculable. "
            "Il en faut deux."
        )

    # La colonne de variation n'est affichée que si elle existe : remplie de
    # « None » sur toute la hauteur, elle occupe la place d'une donnée en
    # laissant croire à une valeur nulle plutôt qu'à une valeur incalculable.
    colonnes = ["ticker", "nom", "secteur", "cloture"]
    if jour["variation"].notna().any():
        colonnes.append("variation")
    colonnes += ["volume_titres", "volume_fcfa"]

    st.dataframe(
        jour[colonnes].sort_values("ticker"),
        width="stretch", hide_index=True,
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


# --- Classement -----------------------------------------------------------
with onglets[1]:
    st.caption(
        "Momentum « 12-1 », filtré par liquidité et neutralisé par secteur. "
        "**Les pondérations n'ont été calibrées sur rien** : ce classement "
        "est une liste de valeurs à examiner, pas un signal validé."
    )

    reglages_1, reglages_2 = st.columns([1, 2])
    with reglages_1:
        seuil = st.number_input(
            "Volume médian minimal (FCFA)", min_value=0, step=100_000,
            value=int(DEFAUTS["analyse"]["volume_median_min_fcfa"]),
            help="Une valeur qui ne s'échange pas ne se vend pas non plus.",
        )
        combien = st.slider("Lignes affichées", 5, 47, 15)
    with reglages_2:
        poids = {
            "momentum": st.slider("Poids du momentum", -1.0, 1.0, 0.5, 0.05),
            "tendance": st.slider("Poids de la tendance", -1.0, 1.0, 0.3, 0.05),
            "volatilite": st.slider("Poids de la volatilité", -1.0, 1.0, -0.2,
                                    0.05),
        }

    reglages = {
        "analyse": {**DEFAUTS["analyse"], "volume_median_min_fcfa": seuil},
        "ponderations": poids,
    }
    traits = features.calculer(cours, reglages)
    classement = scoring.noter(traits, referentiel, reglages)

    if classement.empty:
        st.info(
            f"Aucune valeur classée. {seances} séance{'s' if seances > 1 else ''} "
            f"en base ; le momentum "
            f"en demande {reglages['analyse']['fenetre_momentum'] + 1}. "
            "Un momentum calculé sur moins aurait l'apparence d'un momentum "
            "sans rien mesurer — d'où le refus plutôt qu'une approximation."
        )
    else:
        tete = classement.head(combien)
        st.altair_chart(
            alt.Chart(tete)
            .mark_bar(cornerRadiusEnd=4, height=16, color=SERIE_1)
            .encode(
                x=alt.X("score:Q", title="score"),
                y=alt.Y("ticker:N", sort="-x", title=None),
                tooltip=[
                    alt.Tooltip("ticker:N", title="Symbole"),
                    alt.Tooltip("nom:N", title="Société"),
                    alt.Tooltip("score:Q", title="Score", format=".1f"),
                    alt.Tooltip("momentum:Q", title="Momentum", format="+.1%"),
                    alt.Tooltip("secteur:N", title="Secteur"),
                ],
            )
            .properties(height=max(220, 22 * len(tete))),
            width="stretch",
        )
        st.dataframe(tete, width="stretch", hide_index=True)


# --- Prédiction -----------------------------------------------------------
with onglets[2]:
    st.caption(
        "Probabilité de **surperformer le marché sur trois mois** — pas de "
        "prévoir un cours, pas de deviner si la place monte. La BRVM cote "
        "par fixing, avec une limite de ±7,5 % et des lignes qui "
        "s'échangent parfois quelques fois par semaine : un modèle entraîné "
        "sur le lendemain apprend « demain ≈ aujourd'hui » et produit un "
        "backtest brillant et inexécutable."
    )

    validation = prediction.valider(cours)
    if validation["periodes"].empty:
        st.info(prediction.expliquer(validation))
    else:
        mesures = st.columns(3)
        mesures[0].metric("IC du modèle", f"{validation['ic']:+.3f}")
        mesures[1].metric("IC du score composite",
                          f"{validation['ic_composite']:+.3f}")
        mesures[2].metric("Écart", f"{validation['ecart']:+.3f}")

        if validation["ecart"] <= 0:
            st.warning(
                "**Le modèle ne bat pas le score composite.** C'est le cas "
                "le plus fréquent sur ce marché, et ce n'est pas un défaut "
                "du code : c'est le composite — onglet Classement — qui doit "
                "partir en production. L'apprentissage n'ajouterait qu'un "
                "risque de surajustement."
            )
        elif validation["ic"] > 0.30:
            st.error(
                f"**IC de {validation['ic']:.3f} — anormalement élevé.** "
                "Sur ce type de problème, un IC exploitable vaut 0,02 à "
                "0,05. Cherchez la fuite avant d'y croire."
            )

        st.dataframe(validation["periodes"], width="stretch", hide_index=True)

        classement_ml = prediction.predire(cours)
        if not classement_ml.empty:
            classement_ml = classement_ml.merge(
                referentiel[["ticker", "nom", "secteur"]], on="ticker",
                how="left")
            st.altair_chart(
                alt.Chart(classement_ml.head(15))
                .mark_bar(cornerRadiusEnd=4, height=16, color=SERIE_1)
                .encode(
                    x=alt.X("probabilite:Q", title="probabilité de surperformer",
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
                .properties(height=max(220, 22 * 15)),
                width="stretch",
            )

    st.warning(
        "**Ce que ces chiffres ne disent pas.** " + " ; ".join(
            validation["avertissements"]) + "."
    )


# --- Backtest -------------------------------------------------------------
with onglets[3]:
    bt_1, bt_2, bt_3 = st.columns(3)
    with bt_1:
        positions = st.slider("Positions en portefeuille", 3, 20, 10)
    with bt_2:
        frais = st.number_input("Frais par passage (%)", 0.0, 5.0, 1.0, 0.1)
    with bt_3:
        impact = st.number_input("Impact de marché (%)", 0.0, 5.0, 0.5, 0.1)

    reglages_bt = {
        "analyse": DEFAUTS["analyse"],
        "ponderations": DEFAUTS["ponderations"],
        "backtest": {**DEFAUTS["backtest"], "positions": positions,
                     "frais_pourcent": frais, "impact_pourcent": impact},
    }
    resultat = backtest.backtester(cours, referentiel, reglages_bt)

    if resultat["etapes"].empty:
        st.info(backtest.expliquer(resultat))
    else:
        mesures = st.columns(4)
        mesures[0].metric("Stratégie", f"{resultat['rendement_total']:+.1%}")
        mesures[1].metric("Référence", f"{resultat['reference_total']:+.1%}")
        mesures[2].metric("Perte max.", f"{resultat['perte_max']:.1%}")
        mesures[3].metric("Coût cumulé", f"{resultat['cout_cumule']:.1%}")

        courbes = resultat["etapes"].melt(
            id_vars="date_sortie", value_vars=["valeur", "valeur_reference"],
            var_name="serie", value_name="valeur_part",
        ).replace({"valeur": "Stratégie",
                   "valeur_reference": "Référence équipondérée"})

        couleurs = alt.Color(
            "serie:N", title=None,
            scale=alt.Scale(domain=["Stratégie", "Référence équipondérée"],
                            range=[SERIE_1, SERIE_2]),
            # Légende en bas : à droite, elle occupait la marge où les
            # étiquettes de bout de courbe viennent s'écrire, et les deux se
            # superposaient en bouillie.
            legend=alt.Legend(orient="bottom", direction="horizontal"),
        )
        base = alt.Chart(courbes).encode(
            # Format numérique : Vega libelle les dates en anglais par défaut
            # (« Thu 15 »), ce qui jurerait dans une interface française.
            x=alt.X("date_sortie:T", title=None,
                    axis=alt.Axis(format="%d/%m/%y", tickCount=8)),
            y=alt.Y("valeur_part:Q", title="valeur d'une part",
                    scale=alt.Scale(zero=False)),
            color=couleurs,
        )
        lignes = base.mark_line(strokeWidth=2).encode(
            tooltip=[
                alt.Tooltip("date_sortie:T", title="Date", format="%d/%m/%Y"),
                alt.Tooltip("serie:N", title="Série"),
                alt.Tooltip("valeur_part:Q", title="Valeur", format=".3f"),
            ],
        )
        # Étiquettes directes en bout de courbe : la légende seule oblige à
        # faire l'aller-retour entre le graphique et sa clé.
        derniers = courbes.loc[courbes.groupby("serie")["date_sortie"].idxmax()]
        etiquettes = (
            alt.Chart(derniers)
            .mark_text(align="left", dx=6, fontSize=12)
            .encode(x="date_sortie:T", y="valeur_part:Q", text="serie:N",
                    color=couleurs)
        )
        st.altair_chart(
            # Marge droite réservée : « Référence équipondérée » est long, et
            # sans elle l'étiquette sortirait du cadre.
            (lignes + etiquettes)
            .properties(height=360, padding={"right": 150, "left": 5,
                                             "top": 5, "bottom": 5}),
            width="stretch",
        )
        st.caption("La référence est l'univers éligible équipondéré : "
                   "c'est elle qu'il faut battre, pas zéro.")

    st.warning(
        "**Trois biais survivent à ce backtest et ne sont pas corrigeables "
        "avec ces données :** "
        + " ; ".join(resultat["avertissements"]) + "."
    )


# --- Données --------------------------------------------------------------
with onglets[4]:
    st.subheader("Répartition sectorielle")
    if not referentiel.empty and referentiel["secteur"].notna().any():
        comptes = (referentiel.groupby("secteur").size()
                   .reset_index(name="sociétés"))
        st.altair_chart(
            alt.Chart(comptes)
            .mark_bar(cornerRadiusEnd=4, height=20, color=SERIE_1)
            .encode(
                # `tickMinStep=1` : un décompte de sociétés n'a pas de
                # demi-unité, et un axe qui en affiche invente une précision
                # qui n'existe pas.
                x=alt.X("sociétés:Q", title="sociétés",
                        axis=alt.Axis(tickMinStep=1, format="d")),
                # `labelLimit` relevé : par défaut Vega tronque à 180 px, ce
                # qui réduisait « Consommation de Base » et « Consommation
                # Discrétionnaire » au même « Consommation d… ».
                y=alt.Y("secteur:N", sort="-x", title=None,
                        axis=alt.Axis(labelLimit=220)),
                tooltip=[alt.Tooltip("secteur:N", title="Secteur"),
                         alt.Tooltip("sociétés:Q", title="Sociétés")],
            )
            .properties(height=260),
            width="stretch",
        )
    else:
        st.info("Référentiel vide ou sans secteur.")

    st.subheader("Couverture de l'archive")
    par_date = cours.groupby("date").size().reset_index(name="lignes")
    st.dataframe(par_date.tail(30), width="stretch", hide_index=True)

    st.caption(
        "Source : brvm.org, ingéré par l'action `ingestion.yml` et versionné "
        "dans `data/cours.csv`. L'app ne lit que ce fichier — elle n'écrit "
        "rien et ne conserve aucun état."
    )
