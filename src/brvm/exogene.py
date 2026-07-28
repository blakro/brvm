"""Variables exogènes : commodités, changes, taux — et leur bon usage.

LE PIÈGE QUI REND CE MODULE NÉCESSAIRE
---------------------------------------
Le cours du caoutchouc à une date donnée est LE MÊME pour les 47 sociétés
cotées. Versé tel quel dans un modèle de classement transversal, il a une
variance nulle à l'intérieur de chaque séance : il ne peut pas distinguer
une valeur d'une autre, et n'apporte donc rigoureusement rien à l'ordre
prédit. Un modèle l'ingérerait sans broncher, l'IC ne bougerait pas, et on
conclurait à tort que les commodités n'expliquent rien.

Elles expliquent beaucoup, mais par SECTEUR. Le caoutchouc pèse sur la
SAPH et la SOGB, pas sur une banque. La variable utile n'est donc pas
« cours du caoutchouc » mais son PRODUIT avec l'appartenance sectorielle :

    caoutchouc(t-L) × 1[la valeur est en Consommation de Base]

Cette colonne-là varie bien à l'intérieur d'une séance — elle vaut le cours
pour les neuf valeurs agro et zéro pour les autres — et c'est elle que le
modèle peut exploiter.

LES RETARDS NE SONT PAS UN RÉGLAGE FIN
---------------------------------------
Une hausse du caoutchouc n'atteint pas le cours de la SAPH le lendemain :
elle passe d'abord dans les marges, puis dans des résultats publiés
trimestriellement. Un à trois mois de retard sont l'hypothèse de travail,
et c'est pour cela que ce projet vise un horizon trimestriel plutôt que
journalier.

CALENDRIERS DIFFÉRENTS
----------------------
Les séries exogènes ne cotent pas les mêmes jours que la BRVM — jours
fériés distincts, publications mensuelles pour les taux. Elles sont donc
alignées sur le calendrier de la cote par report de la dernière valeur
connue, jamais par interpolation : interpoler inventerait une valeur que
personne n'observait à cette date, et cette valeur inventée serait, elle,
influencée par l'avenir.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import charger


def serie_large(exogenes: pd.DataFrame) -> pd.DataFrame:
    """Table longue (date, serie, valeur) → matrice dates × séries."""
    if exogenes is None or exogenes.empty:
        return pd.DataFrame()
    large = exogenes.pivot_table(
        index="date", columns="serie", values="valeur", aggfunc="last"
    )
    return large.sort_index()


def aligner(exogenes: pd.DataFrame, dates: list[str]) -> pd.DataFrame:
    """Séries exogènes reportées sur le calendrier de la cote.

    Report de la dernière valeur connue (`ffill`), jamais d'interpolation :
    interpoler entre deux publications mensuelles fabriquerait des valeurs
    intermédiaires que personne n'observait — et qui dépendraient de la
    publication SUIVANTE, donc du futur.
    """
    large = serie_large(exogenes)
    if large.empty or not dates:
        return pd.DataFrame(index=pd.Index(dates, name="date"))

    toutes = sorted(set(large.index) | set(dates))
    return large.reindex(toutes).ffill().reindex(dates)


def variations(
    alignees: pd.DataFrame, fenetre: int, retard: int
) -> pd.DataFrame:
    """Variation de chaque série sur `fenetre` séances, décalée de `retard`.

    C'est la variation qui porte l'information, pas le niveau : un cours du
    caoutchouc de 1 500 ne dit rien en soi, sa hausse de 20 % en trois mois
    dit quelque chose. Le décalage garantit en outre qu'à la date t on
    n'utilise que ce qui était publié en t-retard.
    """
    if alignees.empty:
        return alignees
    variation = alignees / alignees.shift(fenetre) - 1
    return variation.shift(retard).replace([np.inf, -np.inf], np.nan)


def interactions(
    variations_exo: pd.DataFrame,
    secteurs: pd.Series,
    correspondance: dict[str, str],
) -> pd.DataFrame:
    """Croise chaque série exogène avec le secteur qu'elle concerne.

    `secteurs` : ticker → secteur. `correspondance` : série → secteur.
    Renvoie une table indexée (date, ticker), une colonne par série
    retenue, valant la variation de la série pour les valeurs du secteur
    visé et zéro ailleurs.

    Zéro et non NaN pour les autres secteurs : l'absence d'effet est une
    information, tandis qu'un NaN ferait tomber la ligne entière au
    nettoyage et retirerait la valeur du classement.
    """
    if variations_exo.empty or secteurs.empty:
        return pd.DataFrame()

    utiles = {s: sec for s, sec in correspondance.items()
              if s in variations_exo.columns and (secteurs == sec).any()}
    if not utiles:
        return pd.DataFrame()

    blocs = []
    for date, ligne in variations_exo.iterrows():
        bloc = pd.DataFrame(index=secteurs.index)
        for serie, secteur in utiles.items():
            valeur = ligne.get(serie)
            appartient = (secteurs == secteur).astype(float)
            bloc[f"exo_{serie}"] = (
                0.0 if pd.isna(valeur) else float(valeur)
            ) * appartient
        bloc["date"] = date
        bloc["ticker"] = secteurs.index
        blocs.append(bloc)

    return pd.concat(blocs, ignore_index=True)


def traits(
    exogenes: pd.DataFrame,
    dates: list[str],
    referentiel: pd.DataFrame,
    reglages: dict | None = None,
) -> pd.DataFrame:
    """Colonnes exogènes prêtes à joindre au panel, indexées (date, ticker).

    Renvoie un tableau vide — et non une erreur — quand aucune série n'est
    en base : c'est l'état normal du projet aujourd'hui, et le modèle doit
    tourner sans.
    """
    conf = reglages or charger()
    bloc = conf.get("exogenes", {})
    fenetre = int(bloc.get("fenetre_variation", 60))
    retard = int(bloc.get("retard", 40))
    correspondance = bloc.get("correspondance", {})

    if referentiel is None or referentiel.empty or not correspondance:
        return pd.DataFrame()

    alignees = aligner(exogenes, dates)
    if alignees.empty or alignees.dropna(how="all").empty:
        return pd.DataFrame()

    secteurs = referentiel.set_index("ticker")["secteur"].dropna()
    return interactions(variations(alignees, fenetre, retard),
                        secteurs, correspondance)


def couverture(exogenes: pd.DataFrame) -> pd.DataFrame:
    """Ce qu'on a en base, par série : nombre de points et bornes.

    Sert au diagnostic — une série d'un an ne peut pas nourrir un retard de
    trois mois sur une fenêtre de trois mois, et mieux vaut le voir avant
    de s'étonner de colonnes vides.
    """
    if exogenes is None or exogenes.empty:
        return pd.DataFrame(columns=["serie", "points", "debut", "fin"])
    resume = exogenes.groupby("serie")["date"].agg(["count", "min", "max"])
    resume.columns = ["points", "debut", "fin"]
    return resume.reset_index()
