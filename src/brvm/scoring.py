"""Classement des valeurs à partir des traits calculés par `features`.

AVERTISSEMENT QUI VAUT PLUS QUE LE CODE
---------------------------------------
Les pondérations de `config.PONDERATIONS` n'ont été calibrées sur rien. Ce
module sait combiner des traits en un classement reproductible ; il ne sait
pas si ce classement gagne de l'argent, et personne ne le saura avant
d'avoir plusieurs années de séances en base et un backtest honnête —
frais et impact de marché compris, qui sont considérables sur une place où
certaines lignes ne s'échangent pas tous les jours.

Traitez la sortie comme une liste de valeurs à examiner, pas comme un ordre
d'achat.

TROIS CHOIX DE MÉTHODE
----------------------

1. RANGS PLUTÔT QUE Z-SCORES. Sur 47 valeurs dont certaines bondissent de
   7 % en une séance, une seule aberration déplace la moyenne et l'écart
   type, donc le score de toutes les autres. Le rang centile est insensible
   à l'amplitude des extrêmes.

2. FILTRE DE LIQUIDITÉ AVANT NOTATION, PAS APRÈS. Une valeur illiquide
   écartée après coup aurait quand même servi à calculer les rangs des
   autres. Elle est retirée de l'univers d'abord.

3. NEUTRALISATION SECTORIELLE QUAND LE SECTEUR EST PEUPLÉ. Comparer une
   banque à une autre banque a du sens ; comparer les deux seules sociétés
   de services publics entre elles n'en a aucun. En deçà d'un effectif
   minimal, la valeur est notée face au marché entier — c'est la
   « pondération par défaut » que reçoivent aussi les valeurs sans secteur.
"""

from __future__ import annotations

import pandas as pd

from . import features

from .config import charger

COLONNES = ["ticker", "nom", "secteur", "cloture", "momentum", "tendance",
            "volatilite", "liquidite", "score", "rang"]


def _rangs(valeurs: pd.Series) -> pd.Series:
    """Rang centile dans [0, 1], 1 pour la meilleure valeur.

    `pct=True` répartit les ex æquo à leur rang moyen, ce qui évite qu'un
    groupe de valeurs identiques soit départagé par l'ordre alphabétique.
    """
    return valeurs.rank(pct=True, na_option="keep")


def noter(
    traits: pd.DataFrame,
    referentiel: pd.DataFrame | None = None,
    reglages: dict | None = None,
) -> pd.DataFrame:
    """Traits → classement. Une ligne par valeur retenue, la meilleure d'abord.

    Renvoie un tableau vide — et non une erreur — quand aucune valeur n'est
    éligible : c'est le cas normal tant que l'historique est trop court, et
    `cli.py` l'explique alors à l'utilisateur.
    """
    conf = reglages or charger()
    analyse = conf.get("analyse", {})
    poids = conf.get("ponderations", {})
    seuil = float(analyse.get("volume_median_min_fcfa", 0))
    min_secteur = int(analyse.get("min_par_secteur", 5))

    if traits.empty:
        return pd.DataFrame(columns=COLONNES)

    univers = traits.copy()
    univers["liquidite"] = univers["liquidite"].fillna(0)

    # 1. Filtre de liquidité, avant toute notation.
    univers = univers[univers["liquidite"] >= seuil]

    # 2. Un trait manquant est éliminatoire : mieux vaut ne pas classer une
    #    valeur que la classer sur la moitié des critères.
    #
    #    L'ÉLIGIBILITÉ NE DÉPEND PAS DES PONDÉRATIONS, et c'est un défaut
    #    corrigé. Elle se jugeait auparavant sur les seuls traits notés :
    #    changer un poids changeait donc l'univers, et deux pondérations
    #    n'étaient plus comparables. Le symptôme était visible sans être
    #    lu — la référence équipondérée, censée être la même pour toutes,
    #    variait de 0,9 % à 5,1 % l'an d'une pondération à l'autre.
    #
    #    Une valeur est classable si elle est MESURABLE, pas si le jeu de
    #    poids du moment touche par hasard les colonnes qu'elle a.
    mesurables = [t for t in features.TRAITS if t in univers.columns]
    univers = univers.dropna(subset=mesurables)
    traits_notes = [t for t in poids if t in univers.columns]
    if univers.empty:
        return pd.DataFrame(columns=COLONNES)

    # 3. Score brut : somme pondérée des rangs centiles, ramenée sur 100.
    total = sum(abs(p) for p in poids.values()) or 1.0
    brut = sum(
        poids[t] * _rangs(univers[t]) for t in traits_notes
    ) / total
    univers["score"] = (brut + 0.5) * 100  # les poids négatifs recentrent

    # 4. Neutralisation sectorielle.
    univers = _rattacher_secteur(univers, referentiel)
    univers["score"] = _neutraliser(univers, min_secteur)

    univers = univers.sort_values("score", ascending=False)
    univers["rang"] = range(1, len(univers) + 1)
    univers = univers.reset_index()
    for colonne in ("nom", "secteur"):
        if colonne not in univers.columns:
            univers[colonne] = pd.NA
    return univers[COLONNES]


def _rattacher_secteur(
    univers: pd.DataFrame, referentiel: pd.DataFrame | None
) -> pd.DataFrame:
    if referentiel is None or referentiel.empty:
        univers["secteur"] = pd.NA
        univers["nom"] = pd.NA
        return univers
    ref = referentiel.set_index("ticker")
    univers["secteur"] = univers.index.map(ref["secteur"])
    univers["nom"] = univers.index.map(ref.get("nom", pd.Series(dtype=str)))
    return univers


def _neutraliser(univers: pd.DataFrame, min_secteur: int) -> pd.Series:
    """Recentre le score de chaque secteur suffisamment peuplé.

    Sans cela, un secteur porté par une tendance commune — les bancaires en
    2026, seize valeurs sur quarante-sept — occuperait tout le haut du
    classement, et le portefeuille serait un pari sur un secteur déguisé en
    sélection de valeurs.
    """
    score = univers["score"].copy()
    if "secteur" not in univers or univers["secteur"].isna().all():
        return score

    moyenne_marche = score.mean()
    for secteur, groupe in univers.groupby("secteur", dropna=True):
        if len(groupe) < min_secteur:
            continue  # trop peu de membres : noté face au marché entier
        score.loc[groupe.index] += moyenne_marche - groupe["score"].mean()
    return score


def expliquer(classement: pd.DataFrame, n: int = 10) -> str:
    """Rendu texte des `n` premières lignes, pour la ligne de commande."""
    if classement.empty:
        return ("Aucune valeur classée : historique trop court ou filtre de "
                "liquidité trop haut. Lancez « brvm etat » pour voir combien "
                "de séances sont en base.")
    entete = f"{'#':>3}  {'ticker':<7} {'score':>6}  {'mom.':>7} {'tend.':>7} {'vol.':>6}  secteur"
    lignes = [entete, "-" * len(entete)]
    for r in classement.head(n).itertuples():
        secteur = "—" if pd.isna(r.secteur) else r.secteur
        lignes.append(
            f"{r.rang:>3}  {r.ticker:<7} {r.score:>6.1f}  "
            f"{r.momentum:>6.1%} {r.tendance:>6.1%} {r.volatilite:>5.1%}  {secteur}"
        )
    return "\n".join(lignes)
