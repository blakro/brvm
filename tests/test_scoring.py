"""Le classement : filtre de liquidité, pondérations, neutralisation.

Ce que ces tests protègent tient en une phrase : un classement est une
liste ORDONNÉE, et personne ne remarque qu'un ordre est faux. Un trait qui
compte à l'envers, un secteur qui rafle la tête, un filtre qui laisse
passer une valeur qu'on ne peut pas vendre — rien de tout cela ne lève
d'exception ni ne produit un chiffre absurde. Ça produit un classement
plausible et faux.
"""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

import pandas as pd  # noqa: E402

from brvm import scoring  # noqa: E402

REGLAGES = {
    "analyse": {"volume_median_min_fcfa": 1_000_000, "min_par_secteur": 5},
    "ponderations": {"momentum": 0.5, "tendance": 0.3, "volatilite": -0.2},
}


def traits(**colonnes) -> pd.DataFrame:
    """Un tableau de traits, indexé par ticker comme le rend `features`."""
    n = len(next(iter(colonnes.values())))
    base = {"momentum": [0.0] * n, "tendance": [0.0] * n,
            "volatilite": [0.1] * n, "liquidite": [1e7] * n,
            "cloture": [1000.0] * n}
    base.update(colonnes)
    # L'index s'appelle « ticker » : c'est la forme que rend
    # `features.calculer`, et un montage qui s'en écarte testerait autre
    # chose que ce que le code reçoit en vrai.
    index = pd.Index([f"T{i:02d}" for i in range(n)], name="ticker")
    return pd.DataFrame(base, index=index)


# --------------------------------------------------------------------
# Le filtre de liquidité
# --------------------------------------------------------------------

def test_une_valeur_sous_le_seuil_est_ecartee():
    """Une valeur qui ne s'échange pas ne se vend pas non plus : la
    recommander reviendrait à proposer une position dont on ne sortira
    pas."""
    t = traits(momentum=[0.5, 0.4], liquidite=[1e3, 1e7])
    classement = scoring.noter(t, None, REGLAGES)
    assert list(classement["ticker"]) == ["T01"]


def test_une_liquidite_manquante_vaut_zero_et_ecarte():
    t = traits(momentum=[0.5, 0.4], liquidite=[float("nan"), 1e7])
    assert list(scoring.noter(t, None, REGLAGES)["ticker"]) == ["T01"]


def test_aucun_eligible_rend_un_tableau_vide_aux_bonnes_colonnes():
    """Le cas normal tant que l'historique est court : un tableau vide,
    pas une exception — c'est `cli` qui l'explique à l'utilisateur."""
    t = traits(momentum=[0.5, 0.4], liquidite=[1.0, 2.0])
    vide = scoring.noter(t, None, REGLAGES)
    assert vide.empty and list(vide.columns) == scoring.COLONNES


def test_traits_vides_rendent_un_tableau_vide():
    assert scoring.noter(pd.DataFrame(), None, REGLAGES).empty


# --------------------------------------------------------------------
# Le sens des pondérations — l'erreur qui ne se voit pas
# --------------------------------------------------------------------

def test_le_momentum_compte_dans_le_bon_sens():
    t = traits(momentum=[0.9, 0.5, 0.1])
    assert list(scoring.noter(t, None, REGLAGES)["ticker"]) == \
        ["T00", "T01", "T02"]


def test_la_volatilite_penalise():
    """Son poids est négatif : à momentum égal, la valeur la plus agitée
    doit finir derrière. Un signe inversé produirait un classement
    parfaitement plausible et exactement à l'envers."""
    t = traits(momentum=[0.5, 0.5, 0.5], volatilite=[0.05, 0.20, 0.50])
    assert list(scoring.noter(t, None, REGLAGES)["ticker"]) == \
        ["T00", "T01", "T02"]


def test_le_rang_suit_l_ordre_du_tableau():
    t = traits(momentum=[0.1, 0.9, 0.5])
    classement = scoring.noter(t, None, REGLAGES)
    assert list(classement["rang"]) == [1, 2, 3]
    assert classement["rang"].is_monotonic_increasing


# --------------------------------------------------------------------
# La neutralisation sectorielle
# --------------------------------------------------------------------

def _referentiel(secteurs: dict[str, str]) -> pd.DataFrame:
    return pd.DataFrame({"ticker": list(secteurs),
                         "nom": [f"Société {t}" for t in secteurs],
                         "secteur": list(secteurs.values())})


def test_un_secteur_porte_par_une_tendance_commune_ne_rafle_pas_la_tete():
    """Sans neutralisation, un secteur en vogue occuperait tout le haut du
    classement et le portefeuille serait un pari sectoriel déguisé en
    sélection de valeurs.

    Le momentum varie À L'INTÉRIEUR de chaque secteur : avec des secteurs
    parfaitement homogènes, recentrer égalise tous les scores et l'ordre
    devient un départage arbitraire — le test ne prouverait rien. Ici, le
    meilleur des industriels doit passer devant le moins bon des
    bancaires, alors qu'il a un momentum quatre fois plus faible.
    """
    banques = [1.0, 0.95, 0.90, 0.85, 0.80]
    industrie = [0.20, 0.15, 0.10, 0.05, 0.00]
    t = traits(momentum=banques + industrie)
    secteurs = {f"T{i:02d}": ("Banques" if i < 5 else "Industrie")
                for i in range(10)}
    classement = scoring.noter(t, _referentiel(secteurs), REGLAGES)

    rang = dict(zip(classement["ticker"], classement["rang"]))
    assert rang["T05"] < rang["T04"], (
        "le meilleur industriel reste derrière le moins bon bancaire : "
        "la neutralisation sectorielle n'a pas joué")
    assert len(set(classement.head(5)["secteur"])) > 1


def test_un_secteur_trop_peu_peuple_reste_note_face_au_marche():
    """« Services Publics » compte deux sociétés : recentrer sur deux
    membres reviendrait à leur donner un score nul par construction."""
    t = traits(momentum=[0.9, 0.8] + [0.1] * 6)
    secteurs = {f"T{i:02d}": ("Public" if i < 2 else "Industrie")
                for i in range(8)}
    classement = scoring.noter(t, _referentiel(secteurs), REGLAGES)
    assert list(classement.head(2)["ticker"]) == ["T00", "T01"]


def test_sans_referentiel_le_classement_tient_quand_meme():
    t = traits(momentum=[0.9, 0.5, 0.1])
    classement = scoring.noter(t, None, REGLAGES)
    assert len(classement) == 3
    assert classement["secteur"].isna().all()


def test_le_nom_vient_du_referentiel_quand_il_existe():
    t = traits(momentum=[0.9, 0.1])
    ref = _referentiel({"T00": "Banques", "T01": "Banques"})
    classement = scoring.noter(t, ref, REGLAGES).set_index("ticker")
    assert classement.loc["T00", "nom"] == "Société T00"
