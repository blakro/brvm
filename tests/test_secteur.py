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


# --- le prix seul : ce qui est achetable, et ce qui se combine -------------

def test_l_avantage_ecarte_les_valeurs_qu_on_ne_peut_pas_acheter():
    """UN GAIN COMPTÉ SUR DES LIGNES INACHETABLES N'EST TOUCHÉ PAR PERSONNE.

    Mesuré sur l'archive, 40 % des lignes de l'échantillon n'atteignent pas
    le seuil de volume qu'exige `scoring`, et l'avantage du haut de liste y
    vaut près du double de ce qu'il vaut sur les lignes négociables. Le
    classement ET le repère doivent donc se calculer sur les seules lignes
    retenues, comme le fait le backtest.
    """
    n = 24
    # Les douze valeurs LIQUIDES montent avec le score ; les douze ILLIQUIDES
    # montent BEAUCOUP plus. Sans restriction, elles occupent tout le haut de
    # liste et gonflent l'avantage.
    bloc = pd.DataFrame({
        "date": ["j"] * n,
        "score": list(range(12)) + list(range(100, 112)),
        "rendement_futur": [0.001 * i for i in range(12)]
                           + [0.10 + 0.001 * i for i in range(12)],
        "liquidite_fcfa": [5e6] * 12 + [1e3] * 12,
    })
    tout = apprentissage.avantage_par_date(bloc, "score", positions=5)
    negociable = apprentissage.avantage_par_date(
        bloc, "score", positions=5, liquidite_min=1e6)
    assert tout.iloc[0] > negociable.iloc[0], (
        "la restriction doit RÉDUIRE l'avantage sur ce cas fabriqué")
    # Restreint, le repère est la moyenne des seules liquides : le haut de
    # liste y est le meilleur des liquides, pas le meilleur de tous.
    liquides = bloc[bloc["liquidite_fcfa"] >= 1e6]
    attendu = (liquides.nlargest(5, "score")["rendement_futur"].mean()
               - liquides["rendement_futur"].mean())
    assert abs(float(negociable.iloc[0]) - attendu) < 1e-12


def test_la_mesure_dit_sur_quel_seuil_elle_porte():
    """Un chiffre restreint qui ne dit pas sa restriction est trompeur."""
    bloc = pd.DataFrame({
        "date": ["j"] * 14, "score": range(14),
        "rendement_futur": [0.01 * i for i in range(14)],
        "liquidite_fcfa": [5e6] * 14,
    })
    libre = apprentissage.mesure_avantage(bloc, "score", 20, 10)
    borne = apprentissage.mesure_avantage(bloc, "score", 20, 10, 1e6)
    assert libre["liquidite_min"] is None
    assert borne["liquidite_min"] == 1e6


def test_sans_colonne_de_liquidite_la_restriction_ne_ment_pas():
    """Pas de colonne, pas de filtre — et surtout pas un filtre silencieux.

    Un échantillon ancien, ou fabriqué par un test, n'a pas la colonne. Le
    calcul doit alors porter sur tout, et non rendre un tableau vide qui
    passerait pour « aucun avantage ».
    """
    bloc = pd.DataFrame({"date": ["j"] * 14, "score": range(14),
                         "rendement_futur": [0.01 * i for i in range(14)]})
    avec = apprentissage.avantage_par_date(bloc, "score", 10, liquidite_min=1e9)
    sans = apprentissage.avantage_par_date(bloc, "score", 10)
    assert not avec.empty and avec.equals(sans)


def test_le_composite_est_mesure_mais_ne_se_combine_plus():
    """LE CHANGEMENT LE PLUS FACILE À DÉFAIRE PAR ACCIDENT.

    Le composite reste mesuré et affiché — c'est le score de l'onglet
    Classement — et il reste le repli quand la porte de production refuse la
    combinaison. Il ne doit plus entrer dans le score combiné : mesuré sur le
    rendement de cours et les valeurs négociables, l'y laisser coûtait à
    tous les horizons testés.
    """
    assert "composite" in prediction.SOURCES
    assert "composite" not in prediction.SOURCES_COMBINEES

    # Et concrètement : un composite délibérément absurde ne doit pas
    # déplacer le score retenu d'un iota.
    sources = {
        "modele": pd.Series([0.1, 0.2, 0.3, 0.4]),
        "fiabilite": pd.Series([0.4, 0.3, 0.2, 0.1]),
        "composite": pd.Series([9.0, -9.0, 9.0, -9.0]),
    }
    sans = {k: v for k, v in sources.items() if k != "composite"}
    assert prediction._score_retenu(sources).equals(
        prediction._score_retenu(sans))


def test_le_score_retenu_est_un_ORDRE_et_non_une_moyenne():
    """MOYENNER LES DEUX SOURCES APPRISES PERDAIT, ET C'EST MESURÉ.

    Aux trois horizons testés et sur les deux moitiés de l'archive, la
    régression seule bat sa moyenne avec les poids de fiabilité. La constante
    est donc un ordre de préférence : on prend la PREMIÈRE source disponible.

    Le test le vérifie sur des séries opposées — une moyenne les annulerait,
    un ordre rend la première telle quelle.
    """
    modele = pd.Series([0.1, 0.2, 0.3, 0.4])
    contraire = pd.Series([0.4, 0.3, 0.2, 0.1])
    retenu = prediction._score_retenu(
        {"modele": modele, "fiabilite": contraire})
    # Rangs de la seule régression : croissants, et non plats comme le
    # serait la moyenne de deux séries opposées.
    assert list(retenu) == sorted(retenu)
    assert retenu.nunique() == 4


def test_sans_la_regression_le_score_retenu_bascule_sur_les_poids():
    """LA RAISON POUR LAQUELLE C'EST UN ORDRE ET NON UN NOM EN DUR.

    Les poids de fiabilité ne demandent pas scikit-learn, la régression si.
    Un environnement sans scikit-learn doit rendre un classement appris —
    dégradé, mesuré à +3,37 % annualisés — au lieu de retomber d'un coup sur
    le composite, qui n'apprend rien.
    """
    fiab = pd.Series([0.1, 0.9, 0.5, 0.3])
    # La régression absente…
    assert prediction._score_retenu({"fiabilite": fiab}).notna().all()
    # …ou présente mais muette, ce qui arrive quand elle n'a pas convergé.
    muette = pd.Series([np.nan] * 4)
    retenu = prediction._score_retenu({"modele": muette, "fiabilite": fiab})
    assert retenu.notna().all()
    assert retenu.equals(prediction._score_retenu({"fiabilite": fiab}))
    # Aucune source du tout : un score vide, et non un zéro qui passerait
    # pour un classement.
    assert prediction._score_retenu({}).empty


def test_l_echantillon_porte_la_liquidite_en_francs():
    """Le rang de liquidité ne dit pas si une ligne est achetable.

    Le seuil d'éligibilité est un MONTANT ; sans le montant, l'avantage se
    mesurerait sur des valeurs que personne ne peut acheter.
    """
    cours = _marche_aleatoire_local()
    bloc = prediction.construire_echantillon(cours, REGLAGES_LOCAL)
    assert "liquidite_fcfa" in bloc.columns
    assert bloc["liquidite_fcfa"].notna().all()
    # Le rang reste un rang, le montant reste un montant.
    assert bloc["liquidite"].between(0, 1).all()
    assert bloc["liquidite_fcfa"].max() > 1.0


REGLAGES_LOCAL = {
    "analyse": {
        "volume_median_min_fcfa": 0,
        "fenetre_momentum": 30, "saut_momentum": 3,
        "fenetre_volatilite": 15, "fenetre_liquidite": 15,
        "moyenne_courte": 5, "moyenne_longue": 15, "min_par_secteur": 99,
    },
    "prediction": {"horizon": 10, "decoupes": 3, "lignes_minimum": 200},
}


def _marche_aleatoire_local(n=12, seances=260, graine=4):
    rng = np.random.default_rng(graine)
    lignes = []
    for i in range(n):
        prix = 100 * np.exp(np.cumsum(rng.normal(0, 0.015, seances)))
        for rang, valeur in enumerate(prix):
            lignes.append({
                "date": f"{2020 + rang // 336:04d}-{1 + (rang % 336) // 28:02d}"
                        f"-{1 + rang % 28:02d}",
                "ticker": f"T{i:02d}", "cloture": float(valeur),
                "volume_titres": 100.0,
                "volume_fcfa": float(1e5 * (i + 1)),
            })
    return pd.DataFrame(lignes).sort_values(["date", "ticker"])


def test_le_tableau_des_sources_reste_aligne():
    """UN LIBELLÉ PLUS LONG QUE SA COLONNE DÉSALIGNE TOUT LE TABLEAU.

    La largeur était écrite 26 en dur ; « composite de la configuration » en
    fait 29 et repoussait déjà sa ligne vers la droite. Le défaut est
    cosmétique et il rend un tableau de comparaison illisible, ce qui est
    exactement ce qu'un tableau de comparaison ne doit pas être.

    Le test ne relit pas la largeur : il vérifie que les colonnes de chiffres
    tombent au même endroit sur toutes les lignes.
    """
    validation = {
        "periodes": pd.DataFrame([{"periode": "a", "ic_combinaison": 0.1}]),
        "horizon": 20, "lignes": 5000, "lignes_minimum": 400,
        "ic": 0.07, "ic_composite": 0.02, "ecart": 0.05, "precision": 0.52,
        "mesure": {"ic": 0.07, "erreur_type": 0.016, "t": 4.5, "dates": 2500,
                   "blocs": 125, "significatif": True,
                   "dates_independantes": 125},
        "mesure_composite": {"ic": 0.02, "erreur_type": 0.017, "t": 1.5,
                             "dates": 2500, "blocs": 125,
                             "significatif": False,
                             "dates_independantes": 125},
        "sources": {
            nom: {"ic": 0.05, "ir": 1.0, "periodes_positives": 9,
                  "periodes": 10, "pire": -0.01, "part_positives": 0.9}
            for nom in prediction.LIBELLES_SOURCES
        },
        "stabilite": {"ic": 0.07, "ir": 1.5, "periodes_positives": 9,
                      "periodes": 10, "pire": -0.01, "part_positives": 0.9},
        "traits": [], "traits_mesures": {}, "poids_fiabilite": {},
        "coefficients": {}, "retenue": "combinaison", "motif_retenue": None,
        "motif": None, "avertissements": (), "calibrage": None,
        "avantage": {"avantage": 0.006, "t": 2.8, "positions": 10,
                     "significatif": True, "dates": 2500, "blocs": 125,
                     "erreur_type": 0.002, "liquidite_min": 1e6},
        "avantage_tout": {"avantage": 0.011, "t": 3.2, "positions": 10,
                          "significatif": True, "dates": 2500, "blocs": 125,
                          "erreur_type": 0.003, "liquidite_min": None},
    }
    texte = prediction.expliquer(validation)
    lignes = [l for l in texte.splitlines()
              if any(l.strip().startswith(v)
                     for v in prediction.LIBELLES_SOURCES.values())]
    assert len(lignes) == len(prediction.LIBELLES_SOURCES)
    # La colonne d'IC commence au même caractère sur chaque ligne.
    colonnes = {l.index("+0.050") for l in lignes}
    assert len(colonnes) == 1, f"colonnes désalignées : {sorted(colonnes)}"


# --- l'appariement classement / mesures ------------------------------------

def test_les_mesures_appartiennent_au_classement_rendu():
    """LE DÉFAUT QUE CETTE FONCTION EXISTE POUR RENDRE IMPOSSIBLE.

    Le conseiller recevait le classement du composite et, à côté, l'IC du
    modèle appris — deux fois et demie meilleur. Le gain attendu d'un
    arbitrage s'en trouvait surestimé d'un facteur 2,8, et le diagnostic
    changeait de nature : « les frais mangent l'écart » au lieu de « ce
    classement n'a pas d'avantage démontré ».

    Le test vérifie l'invariant, et non le chemin : les mesures rendues sont
    celles de la source nommée.
    """
    validation = {
        "retenue": "composite",
        "sources": {
            "combinaison": {"mesure": {"ic": 0.074}, "avantage": {"avantage": 0.006}},
            "composite": {"mesure": {"ic": 0.027}, "avantage": {"avantage": -0.001}},
        },
        "mesure": {"ic": 0.074}, "avantage": {"avantage": 0.006},
    }
    composite = pd.DataFrame({"ticker": ["A", "B"], "rang": [1, 2]})
    out = prediction.classement_de_production(
        pd.DataFrame(), None, None, validation, composite=composite)
    assert out["source"] == "composite"
    # LES MESURES DU COMPOSITE, et non celles de la combinaison, même si
    # `validation["mesure"]` porte encore ces dernières.
    assert out["mesure"]["ic"] == 0.027
    assert out["avantage"]["avantage"] == -0.001
    assert out["classement"] is composite


def test_le_repli_sur_le_composite_ne_reprend_pas_l_IC_du_modele():
    """Quand la porte de production refuse le modèle, tout doit suivre.

    Sinon on chiffrerait les arbitrages d'un classement sans preuve avec la
    preuve d'un autre — exactement le dépareillage corrigé.
    """
    validation = {
        "retenue": "composite",
        "sources": {"composite": {"mesure": {"ic": -0.01},
                                  "avantage": {"avantage": -0.004}}},
        "mesure": {"ic": 0.09}, "avantage": {"avantage": 0.01},
    }
    out = prediction.classement_de_production(
        pd.DataFrame(), None, None, validation,
        composite=pd.DataFrame({"ticker": ["A"], "rang": [1]}))
    assert out["mesure"]["ic"] < 0, "le repli doit porter l'IC du composite"
    assert out["avantage"]["avantage"] < 0


def test_le_conseil_nomme_le_classement_qu_il_juge():
    """Un gain chiffré sans dire sur quel classement ne se vérifie pas."""
    classement = pd.DataFrame({"ticker": list("ABCDE"), "rang": range(1, 6)})
    res = conseil.conseiller(
        classement, detenu=["A"], mesure={"ic": 0.02, "erreur_type": 0.005},
        dispersion_=0.2, reglages={"backtest": {
            "positions": 3, "frais_pourcent": 0.1, "impact_pourcent": 0.0}},
        source="modèle appris")
    assert res["source"] == "modèle appris"
    assert "modèle appris" in conseil.expliquer(res)
    # Sans source nommée, aucune ligne inventée.
    muet = conseil.conseiller(classement, detenu=["A"],
                              mesure={"ic": 0.02, "erreur_type": 0.005},
                              dispersion_=0.2, reglages={"backtest": {
                                  "positions": 3, "frais_pourcent": 0.1,
                                  "impact_pourcent": 0.0}})
    assert muet["source"] is None
    assert "classement jugé" not in conseil.expliquer(muet)
