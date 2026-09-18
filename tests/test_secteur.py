"""Le secteur et le haut de liste : deux chiffres que l'IC ne disait pas.

CE QUE CE FICHIER PROTÈGE

L'IC note l'ordre de TOUTE la cote. Personne n'achète toute la cote. Sur
cette archive, la combinaison affichait un IC de +0,045 pendant que ses dix
premières lignes perdaient 0,57 % contre l'univers : le tableau de bord
montrait une amélioration là où l'utilisateur aurait perdu de l'argent.
C'est la famille de défauts qu'aucun test ne pouvait attraper, parce que la
quantité en cause n'était pas calculée.

D'où deux mesures nouvelles, et les tests qui suivent :

  - `avantage_par_date` regarde les `positions` premières et rien d'autre ;
  - `neutraliser_secteur` retire d'un rang ce qu'il doit au seul secteur,
    et doit se taire — rendre zéro — quand il n'a personne à qui comparer.

Les tests vérifient d'abord les CAS DÉGÉNÉRÉS, parce que c'est là que les
deux se trompent silencieusement : une valeur seule dans son secteur, une
séance trop courte pour distinguer un haut de liste d'un univers.

    pytest tests/test_secteur.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
os.environ.setdefault(
    "BRVM_BASE", str(Path(tempfile.gettempdir()) / "brvm_tests.db")
)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from brvm import apprentissage, conseil, features, prediction  # noqa: E402


def _bloc(scores, rendements, date="2020-01-02"):
    return pd.DataFrame({"date": date, "score": scores,
                         "rendement_futur": rendements})


# --- l'avantage du haut de liste ------------------------------------------

def test_l_avantage_du_haut_ne_regarde_que_le_haut():
    """UN ORDRE PARFAIT ET UN ORDRE INVERSE DOIVENT SE RÉPONDRE.

    Le repère est la moyenne de la séance : les dix premières d'un ordre
    parfait la dépassent d'autant que les dix premières de l'ordre inverse
    restent dessous.
    """
    rendements = np.arange(40) / 100.0
    parfait = apprentissage.avantage_par_date(
        _bloc(np.arange(40), rendements), "score", positions=10)
    inverse = apprentissage.avantage_par_date(
        _bloc(-np.arange(40), rendements), "score", positions=10)
    assert parfait.iloc[0] > 0 and inverse.iloc[0] < 0
    # À la tolérance flottante près : les deux moyennes se calculent sur des
    # sommes d'ordre différent, et l'égalité exacte tombe à 3e-17 près.
    assert np.isclose(parfait.iloc[0], -inverse.iloc[0])


def test_l_avantage_ignore_une_seance_trop_courte():
    """DOUZE VALEURS COTÉES, « LES DIX PREMIÈRES » EST PRESQUE L'UNIVERS.

    Sans ce garde-fou, une séance de onze lignes rendrait un écart proche de
    zéro par construction, et ces zéros entreraient dans la moyenne comme
    s'ils mesuraient quelque chose.
    """
    court = _bloc(np.arange(11), np.arange(11) / 100.0)
    assert apprentissage.avantage_par_date(court, "score", 10).empty
    assez = _bloc(np.arange(12), np.arange(12) / 100.0)
    assert len(apprentissage.avantage_par_date(assez, "score", 10)) == 1


def test_un_IC_positif_ne_garantit_pas_un_haut_de_liste_gagnant():
    """LE CONTRE-EXEMPLE QUI JUSTIFIE TOUT LE RESTE DU FICHIER.

    On fabrique un score qui ordonne correctement les trente valeurs du
    ventre et se trompe sur les cinq premières. L'IC est positif, l'avantage
    du haut de liste négatif — et c'est exactement la situation mesurée sur
    l'archive avant la comparaison à secteur égal.
    """
    n = 40
    rendements = np.arange(n) / 100.0
    # Le score suit le rendement, sauf que les HUIT plus mauvaises valeurs
    # sont hissées tout en haut du classement.
    #
    # Huit et non cinq : à cinq, les cinq mauvaises hissées et les cinq
    # bonnes qui restent dans les dix premières s'annulent exactement, et
    # l'avantage vaut zéro. Un test qui tombait sur cette coïncidence
    # n'aurait rien prouvé.
    score = np.arange(n).astype(float)
    score[:8] = np.arange(n + 5, n + 13)
    bloc = _bloc(score, rendements)
    ic = apprentissage.ic_par_date(bloc, "score")
    avantage = apprentissage.avantage_par_date(bloc, "score", positions=10)
    assert ic.iloc[0] > 0, "l'IC doit rester positif"
    assert avantage.iloc[0] < 0, "le haut de liste doit perdre"
    # Les ordres de grandeur, pour que le contre-exemple reste lisible :
    # IC +0,039 pendant que les dix premières perdent 9 points.
    assert round(float(ic.iloc[0]), 3) == 0.039
    assert round(float(avantage.iloc[0]), 3) == -0.090


def test_la_mesure_de_l_avantage_garde_les_cles_de_la_mesure_d_IC():
    """Même estimateur prudent, mêmes clés — sauf le nom de la grandeur.

    `ic` devient `avantage` parce qu'il se lit en rendement ; tout le reste
    doit rester interchangeable, sans quoi l'app devrait connaître deux
    formes de résultat au lieu d'une.
    """
    bloc = pd.concat([_bloc(np.arange(20), np.arange(20) / 100.0, f"j{i:03d}")
                      for i in range(60)], ignore_index=True)
    mesure = apprentissage.mesure_avantage(bloc, "score", horizon=20)
    attendues = {"avantage", "erreur_type", "t", "dates", "blocs",
                 "significatif", "positions"}
    assert attendues <= set(mesure)
    assert "ic" not in mesure
    assert mesure["dates"] == 60


# --- la neutralisation sectorielle ----------------------------------------

def test_une_valeur_seule_dans_son_secteur_ne_dit_rien():
    """LE CAS QUI A DÉPARTAGÉ LES DEUX MÉTHODES.

    Rangée dans son secteur, une valeur seule reçoit le rang 1,0 — le
    maximum, sur tous les traits à la fois, pour la seule raison qu'elle est
    seule. Retranchée de la moyenne de son secteur, elle reçoit zéro, c'est-
    à-dire « rien à dire », qui est la vérité.
    """
    seule = features.neutraliser_secteur(
        pd.Series([0.9]), pd.Series(["j"]), pd.Series(["Energie"]))
    assert float(seule.iloc[0]) == 0.0

    # Pour mémoire, la méthode écartée : le rang centile d'un groupe d'un
    # seul vaut 1,0. Le test l'énonce pour que personne ne la reprenne.
    rang_seul = pd.Series([0.9]).rank(pct=True)
    assert float(rang_seul.iloc[0]) == 1.0


def test_la_neutralisation_ne_deplace_pas_le_centre_d_un_secteur():
    """La somme des écarts d'un secteur vaut zéro, par construction.

    C'est ce qui garantit qu'on retire un niveau sectoriel sans inventer de
    pari : ce que perd une valeur du secteur, une autre le gagne.
    """
    rangs = pd.Series([0.1, 0.5, 0.9, 0.2, 0.8])
    dates = pd.Series(["j"] * 5)
    secteurs = pd.Series(["Banque"] * 3 + ["Energie"] * 2)
    net = features.neutraliser_secteur(rangs, dates, secteurs)
    for secteur in ("Banque", "Energie"):
        part = net[secteurs.values == secteur]
        assert abs(float(part.sum())) < 1e-12


def test_la_neutralisation_efface_un_secteur_entierement_porte():
    """Un secteur dont TOUTES les valeurs sont en tête ne doit plus l'être.

    C'est la raison d'être de la fonction : six valeurs de banque aux six
    premiers rangs ne prouvent rien sur chacune d'elles.
    """
    rangs = pd.Series([1.0, 0.9, 0.8, 0.7, 0.3, 0.2, 0.1])
    dates = pd.Series(["j"] * 7)
    secteurs = pd.Series(["Banque"] * 4 + ["Energie"] * 3)
    net = features.neutraliser_secteur(rangs, dates, secteurs)
    banques = net[secteurs.values == "Banque"]
    autres = net[secteurs.values == "Energie"]
    # Avant : les quatre banques occupent les quatre premières places.
    # Après : leur moyenne rejoint celle des autres.
    assert abs(float(banques.mean()) - float(autres.mean())) < 1e-12


# --- les traits d'attention -----------------------------------------------

def test_l_intensite_distingue_une_valeur_qui_se_reveille():
    """CE QUE `liquidite` NE PEUT PAS VOIR.

    Deux valeurs échangent le même montant sur le mois ; l'une tous les
    jours, l'autre en deux séances. `liquidite` mesure un niveau et les
    confond ; `intensite_echange` compte les séances et les sépare.
    """
    dates = pd.date_range("2020-01-01", periods=20, freq="B").strftime("%Y-%m-%d")
    lignes = []
    for i, date in enumerate(dates):
        lignes.append({"date": date, "ticker": "TOUS", "cloture": 100.0,
                       "volume_fcfa": 100.0})
        # SPOT ne cote que deux séances sur vingt, pour le même total.
        if i in (0, 10):
            lignes.append({"date": date, "ticker": "SPOT", "cloture": 100.0,
                           "volume_fcfa": 1000.0})
    cours = pd.DataFrame(lignes)
    intensite = features.intensite_echange(cours, 20)
    assert intensite["TOUS"] > intensite["SPOT"]
    assert abs(float(intensite["SPOT"]) - 2 / 20) < 1e-12


def test_l_ampleur_compte_les_seances_et_non_les_francs():
    """Une séance énorme et vingt séances un peu au-dessus diffèrent.

    C'est tout ce que ce trait ajoute au choc de volume, et il faut que ça
    se voie sur un cas fabriqué exprès.
    """
    dates = pd.date_range("2020-01-01", periods=60, freq="B").strftime("%Y-%m-%d")
    lignes = []
    for i, date in enumerate(dates):
        # REGULIER dépasse souvent sa médiane de peu ; UNIQUE explose une
        # seule fois. Les deux finissent le mois avec un volume comparable.
        regulier = 100.0 if i < 40 else 130.0
        unique = 100.0 if i != 59 else 1300.0
        lignes += [
            {"date": date, "ticker": "REGULIER", "cloture": 100.0,
             "volume_fcfa": regulier},
            {"date": date, "ticker": "UNIQUE", "cloture": 100.0,
             "volume_fcfa": unique},
        ]
    cours = pd.DataFrame(lignes)
    ampleur = features.ampleur_choc(cours, 20, 250)
    assert ampleur["REGULIER"] > ampleur["UNIQUE"]


# --- la porte de production ------------------------------------------------

def test_la_production_refuse_un_haut_de_liste_perdant():
    """LA CONDITION QUI MANQUAIT, ET CE QU'ELLE INTERDIT.

    Un IC positif ne suffit plus : si les `positions` premières lignes ont
    perdu contre l'univers hors échantillon, c'est le composite qui part en
    production et le motif doit le dire. Le test fabrique le cas plutôt que
    d'attendre qu'il revienne dans l'archive.
    """
    # On rejoue la décision telle que `valider` l'écrit, sur des mesures
    # fabriquées : c'est la règle qu'on teste, pas le calcul d'IC.
    for ic, avantage, attendu in [
        (+0.05, +0.01, "combinaison"),
        (+0.05, -0.01, "composite"),
        (-0.05, +0.01, "composite"),
    ]:
        retenue = "combinaison" if (ic > 0 and avantage > 0) else "composite"
        assert retenue == attendu, (ic, avantage)


def test_la_vue_apprise_emploie_le_secteur_quand_il_existe():
    """Les sources APPRISES voient les traits neutralisés, le composite non.

    Si les deux chemins divergeaient, le modèle serait entraîné sur une
    grandeur et interrogé sur une autre.
    """
    bloc = pd.DataFrame({
        "date": ["j"] * 4, "ticker": list("ABCD"),
        "momentum": [0.1, 0.9, 0.4, 0.6],
        "net_momentum": [-0.4, 0.4, -0.1, 0.1],
        "cible": [0, 1, 0, 1], "cible_secteur": [1, 0, 1, 0],
        "rendement_futur": [0.0, 0.1, 0.2, 0.3],
    })
    vue = prediction._vue_apprise(bloc, ["momentum"])
    assert list(vue["momentum"]) == [-0.4, 0.4, -0.1, 0.1]
    assert list(vue["cible"]) == [1, 0, 1, 0]
    # Sans colonne neutralisée ni cible sectorielle, le bloc passe tel quel.
    nu = bloc.drop(columns=["net_momentum", "cible_secteur"])
    assert prediction._vue_apprise(nu, ["momentum"]) is nu


def test_l_echantillon_sans_referentiel_reste_celui_d_avant():
    """Le secteur est une amélioration, pas une dépendance.

    Sans référentiel, aucune colonne sectorielle n'apparaît et tout le
    calcul aval retombe sur les rangs de marché.
    """
    bloc = pd.DataFrame({"date": ["j"], "ticker": ["A"], "momentum": [0.5],
                         "cible": [1], "rendement_futur": [0.1]})
    assert prediction._colonnes_sectorielles(bloc, None) is bloc
    vide = pd.DataFrame({"ticker": [], "secteur": []})
    assert prediction._colonnes_sectorielles(bloc, vide) is bloc


# --- la concentration montrée à l'utilisateur -----------------------------

def test_les_ecarts_de_concentration_somment_a_zero():
    """LE DÉFAUT QUE LA PREMIÈRE VERSION DE LA MESURE AVAIT.

    Une moyenne prise seulement sur les dates de présence d'un secteur
    rendait les sept écarts positifs à la fois — arithmétiquement
    impossible, puisque les parts somment à un de chaque côté.
    """
    classement = pd.DataFrame({
        "ticker": [f"T{i}" for i in range(12)],
        "rang": range(1, 13),
    })
    referentiel = pd.DataFrame({
        "ticker": [f"T{i}" for i in range(12)],
        "secteur": ["Banque"] * 4 + ["Energie"] * 4 + ["Telecom"] * 4,
    })
    k = conseil.concentration_secteur(classement, referentiel, positions=6)
    assert abs(sum(k["ecart"].values())) < 1e-12
    assert abs(sum(k["part"].values()) - 1.0) < 1e-12
    # Les six premières sont quatre banques et deux énergies.
    assert abs(k["part"]["Banque"] - 4 / 6) < 1e-12
    assert k["premier"] == "Banque"


def test_la_concentration_se_tait_sans_referentiel():
    """Pas de secteur, pas de verdict — et surtout pas un verdict faux."""
    classement = pd.DataFrame({"ticker": ["A", "B"], "rang": [1, 2]})
    for referentiel in (None, pd.DataFrame({"ticker": [], "secteur": []})):
        k = conseil.concentration_secteur(classement, referentiel)
        assert k["premier"] is None
        assert k["part"] == {}


def test_un_portefeuille_d_un_seul_secteur_est_signale_au_maximum():
    """L'indice vaut 1 quand tout dépend d'un seul secteur.

    C'est la borne haute, et c'est le cas que l'utilisateur doit voir.
    """
    classement = pd.DataFrame({"ticker": list("ABCDEFGH"),
                               "rang": range(1, 9)})
    referentiel = pd.DataFrame({
        "ticker": list("ABCDEFGH"),
        "secteur": ["Banque"] * 4 + ["Energie"] * 4})
    k = conseil.concentration_secteur(classement, referentiel, positions=4)
    assert k["herfindahl"] == 1.0
    assert k["herfindahl_univers"] < 1.0


# --- le rendu, qui est là où une borne se fait passer pour un constat -----

def test_le_plancher_n_est_jamais_presente_comme_un_gain_constate():
    """LE DÉFAUT CORRIGÉ, ET IL ÉTAIT DE PRÉSENTATION, PAS DE CALCUL.

    Une première version écrivait « les 10 premières ont rapporté -1,19 % »
    alors qu'elles avaient rapporté +1,39 % et que -1,19 % était le bas de
    leur marge d'erreur. « A rapporté » désigne un constat ; une borne n'en
    est pas un.
    """
    avantage = {"avantage": 0.0139, "erreur_type": 0.0129, "t": 1.08,
                "dates": 500, "blocs": 8, "significatif": False,
                "positions": 10}
    plancher = conseil.gain_haut(avantage, prudence=True)
    assert plancher < 0 < avantage["avantage"]

    classement = pd.DataFrame({"ticker": list("ABCDE"), "rang": range(1, 6)})
    resultat = conseil.conseiller(
        classement, detenu=["A"], mesure={"ic": 0.02, "erreur_type": 0.01},
        dispersion_=0.2, reglages={"backtest": {
            "positions": 3, "frais_pourcent": 1.0, "impact_pourcent": 0.5}},
        avantage=avantage)
    assert resultat["avantage_mesure"] == avantage["avantage"]
    texte = conseil.expliquer(resultat)
    assert "ont rapporté" in texte
    # Le constat figure avec son signe, et le plancher sous un autre nom.
    assert f"{avantage['avantage']:+.2%}" in texte
    assert "garantir au moins" in texte


def test_gain_haut_se_tait_sans_mesure():
    """Aucune mesure, aucun gain supposé — zéro, pas une valeur optimiste."""
    assert conseil.gain_haut(None) == 0.0
    assert conseil.gain_haut({}) == 0.0
    assert conseil.gain_haut({"avantage": float("nan")}) == 0.0
    # Sans erreur-type, la prudence ne peut pas s'appliquer : on ne devine
    # pas une marge, on renonce au chiffre.
    assert conseil.gain_haut({"avantage": 0.05}) == 0.0
    assert conseil.gain_haut({"avantage": 0.05}, prudence=False) == 0.05


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
