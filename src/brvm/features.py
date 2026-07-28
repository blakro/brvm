"""Traits calculés sur les séries de cours, en vue du scoring.

Rien ici ne décide d'acheter quoi que ce soit : ce module transforme une
table de cours en quelques nombres par valeur, et `scoring.py` les combine.

UN HISTORIQUE INSUFFISANT DONNE NaN, JAMAIS UNE APPROXIMATION. Calculer un
momentum « sur ce qu'on a » quand on a trois semaines produit un nombre qui
a l'air d'un momentum, se classe comme un momentum, et ne mesure rien. Les
fenêtres sont donc strictes : en deçà, la valeur sort du classement au lieu
d'y entrer au hasard.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import charger

# Séances de bourse par an, pour annualiser la volatilité. La BRVM cote du
# lundi au vendredi hors jours fériés — 250 est l'ordre de grandeur usuel.
SEANCES_PAR_AN = 250


def serie(cours: pd.DataFrame, colonne: str = "cloture") -> pd.DataFrame:
    """Table de cours → matrice dates × tickers.

    Les dates sont au format ISO, donc l'ordre alphabétique est l'ordre
    chronologique ; inutile de convertir en datetime pour trier.
    """
    if cours.empty:
        return pd.DataFrame()
    table = cours.pivot_table(
        index="date", columns="ticker", values=colonne, aggfunc="last"
    )
    return table.sort_index()


def momentum(prix: pd.DataFrame, fenetre: int, saut: int) -> pd.Series:
    """Rendement sur `fenetre` séances, en sautant les `saut` dernières.

    LE SAUT N'EST PAS UN DÉTAIL DE CONVENTION. Le momentum à un an et le
    retournement à un mois sont deux effets opposés : une valeur qui vient
    de bondir de 20 % en trois semaines tend à rendre une partie de ce
    mouvement. Mesurer jusqu'à aujourd'hui mélange les deux et achète les
    hausses les plus fraîches, qui sont les plus fragiles. D'où la fenêtre
    de t-250 à t-20, et non de t-250 à t.
    """
    if len(prix) < fenetre + 1:
        return pd.Series(np.nan, index=prix.columns)
    debut = prix.iloc[-(fenetre + 1)]
    fin = prix.iloc[-(saut + 1)]
    return (fin / debut - 1).where(debut > 0)


def tendance(prix: pd.DataFrame, courte: int, longue: int) -> pd.Series:
    """Écart entre moyenne mobile courte et longue, en proportion.

    Positif quand le cours récent domine le cours de fond. Redondant avec
    le momentum par construction, mais sur un horizon plus court : c'est ce
    qui distingue une hausse encore vivante d'une hausse qui s'essouffle.
    """
    if len(prix) < longue:
        return pd.Series(np.nan, index=prix.columns)
    moyenne_courte = prix.iloc[-courte:].mean()
    moyenne_longue = prix.iloc[-longue:].mean()
    return (moyenne_courte / moyenne_longue - 1).where(moyenne_longue > 0)


def volatilite(prix: pd.DataFrame, fenetre: int) -> pd.Series:
    """Écart-type annualisé des rendements quotidiens.

    Calculé en logarithmes : sur des séries qui peuvent doubler, les
    rendements arithmétiques rendent la hausse et la baisse asymétriques.
    """
    if len(prix) < fenetre + 1:
        return pd.Series(np.nan, index=prix.columns)
    rendements = np.log(prix.iloc[-(fenetre + 1):]).diff().iloc[1:]
    return rendements.std() * np.sqrt(SEANCES_PAR_AN)


def liquidite(cours: pd.DataFrame, fenetre: int) -> pd.Series:
    """Volume médian échangé, en FCFA.

    La médiane et non la moyenne : une seule transaction de bloc suffirait
    à faire passer pour liquide une valeur qui ne s'échange jamais.

    LES MANQUANTS VALENT ZÉRO, ET C'EST VOULU. Une séance sans ligne pour
    un ticker est une séance sans échange, pas une donnée absente. La
    compter comme inconnue relèverait la médiane des valeurs les moins
    traitées — exactement celles que le filtre doit écarter.
    """
    volumes = serie(cours, "volume_fcfa")
    if volumes.empty:
        return pd.Series(dtype=float)
    return volumes.iloc[-fenetre:].fillna(0).median()


DEFAUTS_FENETRES = {
    "fenetre_momentum": 250, "saut_momentum": 20,
    "fenetre_volatilite": 60, "fenetre_liquidite": 60,
    "moyenne_courte": 20, "moyenne_longue": 100,
}

TRAITS = ["momentum", "tendance", "volatilite", "liquidite"]


def _fenetres(reglages: dict | None) -> dict[str, int]:
    conf = (reglages or charger()).get("analyse", {})
    return {cle: int(conf.get(cle, defaut))
            for cle, defaut in DEFAUTS_FENETRES.items()}


def traits_glissants(
    cours: pd.DataFrame, reglages: dict | None = None
) -> dict[str, pd.DataFrame]:
    """Tous les traits, à TOUTES les dates : {trait: matrice dates × tickers}.

    POURQUOI CETTE FONCTION EXISTE. Les traits étaient recalculés de zéro
    pour chaque date, avec un pivot complet à chaque tour. Mesuré sur des
    séries fabriquées : 0,96 s pour 150 séances, 4,37 s pour 250, 9,75 s
    pour 400 — une croissance quadratique qui donnait plusieurs minutes sur
    dix ans de cotation, à chaque chargement de l'onglet Prédiction et à
    chaque mouvement de curseur. Le coût devenait prohibitif exactement au
    moment où le projet réussit.

    Les mêmes quantités se calculent ici en une passe glissante sur la
    matrice entière. `calculer` n'est plus qu'une lecture de la dernière
    ligne, ce qui garantit que les deux chemins ne peuvent pas diverger.
    """
    f = _fenetres(reglages)
    prix = serie(cours)
    if prix.empty:
        return {trait: pd.DataFrame() for trait in [*TRAITS, "cloture"]}

    # Momentum : cours en t-saut rapporté au cours en t-fenetre. `shift`
    # décale d'autant de LIGNES, ce qui correspond aux séances puisque la
    # matrice est indexée par date de cotation.
    debut = prix.shift(f["fenetre_momentum"])
    fin = prix.shift(f["saut_momentum"])
    mom = (fin / debut - 1).where(debut > 0)

    courte = prix.rolling(f["moyenne_courte"]).mean()
    longue = prix.rolling(f["moyenne_longue"]).mean()
    tend = (courte / longue - 1).where(longue > 0)

    # `rolling(n).std()` sur les log-rendements porte sur n écarts, soit les
    # n+1 cours de la version ponctuelle. Même estimateur (ddof=1).
    rendements = np.log(prix).diff()
    vol = rendements.rolling(f["fenetre_volatilite"]).std() * np.sqrt(SEANCES_PAR_AN)

    # `min_periods=1` reproduit `iloc[-fenetre:]`, qui prenait ce qui
    # existait quand l'historique était plus court que la fenêtre.
    volumes = serie(cours, "volume_fcfa").reindex(
        index=prix.index, columns=prix.columns
    ).fillna(0)
    liq = volumes.rolling(f["fenetre_liquidite"], min_periods=1).median()

    return {"cloture": prix, "momentum": mom, "tendance": tend,
            "volatilite": vol, "liquidite": liq}


def calculer(cours: pd.DataFrame, reglages: dict | None = None) -> pd.DataFrame:
    """Tous les traits, à la dernière date disponible, un ticker par ligne."""
    matrices = traits_glissants(cours, reglages)
    if matrices["cloture"].empty:
        return pd.DataFrame(columns=["cloture", *TRAITS])

    dates = matrices["cloture"].index
    traits = pd.DataFrame(
        {nom: matrice.iloc[-1] for nom, matrice in matrices.items()}
    )
    traits.index.name = "ticker"
    traits.attrs["date"] = str(dates[-1])
    traits.attrs["seances"] = len(dates)
    return traits[["cloture", *TRAITS]]
