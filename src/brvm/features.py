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


def calculer(cours: pd.DataFrame, reglages: dict | None = None) -> pd.DataFrame:
    """Tous les traits, à la dernière date disponible, un ticker par ligne."""
    conf = (reglages or charger()).get("analyse", {})
    defauts = {
        "fenetre_momentum": 250, "saut_momentum": 20,
        "fenetre_volatilite": 60, "fenetre_liquidite": 60,
        "moyenne_courte": 20, "moyenne_longue": 100,
    }
    lire = lambda cle: int(conf.get(cle, defauts[cle]))  # noqa: E731

    prix = serie(cours)
    if prix.empty:
        return pd.DataFrame(
            columns=["cloture", "momentum", "tendance", "volatilite", "liquidite"]
        )

    traits = pd.DataFrame(index=prix.columns)
    traits.index.name = "ticker"
    traits["cloture"] = prix.iloc[-1]
    traits["momentum"] = momentum(
        prix, lire("fenetre_momentum"), lire("saut_momentum")
    )
    traits["tendance"] = tendance(
        prix, lire("moyenne_courte"), lire("moyenne_longue")
    )
    traits["volatilite"] = volatilite(prix, lire("fenetre_volatilite"))
    traits["liquidite"] = liquidite(cours, lire("fenetre_liquidite"))
    traits.attrs["date"] = str(prix.index[-1])
    traits.attrs["seances"] = len(prix)
    return traits
