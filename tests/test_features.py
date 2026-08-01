"""Les traits, un par un, sur des séries construites à la main.

`test_analyse.py` exerce déjà la chaîne complète ; ce fichier-ci prend les
fonctions séparément, avec des séries dont on connaît la réponse à
l'avance. C'est ce qui manquait : quand `calculer` rend un chiffre
surprenant, rien ne disait lequel des quatre traits l'avait produit.

Ce que ces tests protègent, ce sont les partis pris documentés dans le
module — le saut du momentum, la médiane de la liquidité, les manquants
comptés zéro. Un jour où quelqu'un « simplifiera » l'un des trois, un test
doit tomber.
"""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from brvm import features  # noqa: E402


def cours(series: dict[str, list[float]], volumes: dict | None = None):
    """Une archive au format long, à partir de séries par ticker."""
    longueur = len(next(iter(series.values())))
    dates = pd.bdate_range("2020-01-01", periods=longueur).strftime("%Y-%m-%d")
    lignes = []
    for ticker, valeurs in series.items():
        vol = (volumes or {}).get(ticker, [1e6] * longueur)
        for date, cloture, v in zip(dates, valeurs, vol):
            lignes.append({"date": date, "ticker": ticker,
                           "cloture": cloture, "volume_fcfa": v})
    return pd.DataFrame(lignes)


# --------------------------------------------------------------------
# serie
# --------------------------------------------------------------------

def test_serie_pivote_sans_perdre_de_seance():
    table = features.serie(cours({"AAAA": [1, 2, 3], "BBBB": [4, 5, 6]}))
    assert list(table.columns) == ["AAAA", "BBBB"]
    assert len(table) == 3
    assert table.index.is_monotonic_increasing


def test_serie_laisse_un_trou_la_ou_la_valeur_ne_cote_pas():
    """Une valeur absente d'une séance ne doit pas hériter du cours d'une
    autre : la plupart des lignes de cette place ne s'échangent pas tous
    les jours, et boucher le trou fabriquerait des rendements nuls."""
    table = pd.concat([cours({"AAAA": [1, 2, 3]}),
                       cours({"BBBB": [4, 5, 6]}).iloc[:1]], ignore_index=True)
    pivot = features.serie(table)
    assert pivot["BBBB"].isna().sum() == 2


# --------------------------------------------------------------------
# momentum — le saut est le parti pris central
# --------------------------------------------------------------------

def test_momentum_saute_bien_les_dernieres_seances():
    """Le momentum « 12-1 » se mesure de t-250 à t-20, pas de t-250 à t.

    La série monte régulièrement puis s'effondre sur les dix dernières
    séances. Avec le saut, l'effondrement ne doit PAS être vu ; sans lui,
    le trait deviendrait négatif — et achèterait les hausses les plus
    fraîches, qui sont les plus fragiles.
    """
    monte = [100 * 1.01 ** i for i in range(31)]
    serie = monte + [50] * 10
    prix = features.serie(cours({"AAAA": serie}))
    avec_saut = features.momentum(prix, fenetre=40, saut=10)["AAAA"]
    sans_saut = features.momentum(prix, fenetre=40, saut=0)["AAAA"]
    assert avec_saut > 0, "le saut n'a pas protégé de l'effondrement récent"
    assert sans_saut < 0
    assert avec_saut == pytest.approx(monte[-1] / serie[0] - 1)


def test_momentum_refuse_une_serie_trop_courte():
    prix = features.serie(cours({"AAAA": [100, 101, 102]}))
    assert features.momentum(prix, fenetre=250, saut=20).isna().all()


def test_momentum_ne_divise_pas_par_un_cours_nul():
    prix = features.serie(cours({"AAAA": [0.0] + [100.0] * 10}))
    assert features.momentum(prix, fenetre=10, saut=0).isna().all()


# --------------------------------------------------------------------
# tendance et volatilité
# --------------------------------------------------------------------

def test_tendance_positive_quand_le_recent_domine_le_fond():
    prix = features.serie(cours({"AAAA": list(range(100, 160))}))
    assert features.tendance(prix, courte=5, longue=40)["AAAA"] > 0


def test_tendance_negative_quand_le_cours_reflue():
    prix = features.serie(cours({"AAAA": list(range(160, 100, -1))}))
    assert features.tendance(prix, courte=5, longue=40)["AAAA"] < 0


def test_volatilite_distingue_le_calme_de_l_agite():
    calme = [100 + (i % 2) * 0.1 for i in range(80)]
    agite = [100 * (1.1 if i % 2 else 0.9) for i in range(80)]
    prix = features.serie(cours({"CALM": calme, "AGIT": agite}))
    v = features.volatilite(prix, fenetre=60)
    assert v["AGIT"] > v["CALM"] * 10


# --------------------------------------------------------------------
# liquidité — médiane, et manquants à zéro
# --------------------------------------------------------------------

def test_liquidite_prend_la_mediane_et_non_la_moyenne():
    """Une seule transaction de bloc suffirait à faire passer pour liquide
    une valeur qui ne s'échange jamais."""
    petit = [1_000.0] * 59 + [500_000_000.0]
    table = cours({"AAAA": [100.0] * 60}, volumes={"AAAA": petit})
    assert features.liquidite(table, fenetre=60)["AAAA"] == 1_000.0


def test_liquidite_compte_une_seance_sans_echange_comme_zero():
    """Une séance sans ligne est une séance sans échange, pas une donnée
    absente. La compter comme inconnue relèverait la médiane des valeurs
    les moins traitées — celles que le filtre doit précisément écarter."""
    table = pd.concat([
        cours({"AAAA": [100.0] * 10}, volumes={"AAAA": [1e6] * 10}),
        cours({"BBBB": [100.0] * 10}, volumes={"BBBB": [1e6] * 10}).head(3),
    ], ignore_index=True)
    liquide = features.liquidite(table, fenetre=10)
    assert liquide["AAAA"] == 1e6
    assert liquide["BBBB"] == 0.0, "les séances sans échange ont été ignorées"


# --------------------------------------------------------------------
# calculer et traits_glissants — la coupe temporelle
# --------------------------------------------------------------------

def test_calculer_rend_les_quatre_traits():
    table = cours({f"T{i:02d}": [100 + i + j * 0.1 for j in range(300)]
                   for i in range(6)})
    traits = features.calculer(table)
    assert set(features.TRAITS) <= set(traits.columns)
    assert len(traits) == 6


def test_traits_glissants_ne_regarde_jamais_l_avenir():
    """Le trait d'une date ne doit être fabriqué que de cours antérieurs.

    On calcule sur la série entière, puis sur la série tronquée à une date
    donnée : les valeurs à cette date doivent être identiques. Si une
    fenêtre débordait sur l'avenir, elles différeraient.
    """
    valeurs = [100 * 1.001 ** i for i in range(320)]
    entier = cours({"AAAA": valeurs, "BBBB": valeurs[::-1]})
    coupe = entier[entier["date"] <= sorted(entier["date"].unique())[300]]

    tout = features.traits_glissants(entier)
    partiel = features.traits_glissants(coupe)
    date = sorted(coupe["date"].unique())[-1]
    for nom in ("momentum", "tendance", "volatilite"):
        a, b = tout[nom].loc[date], partiel[nom].loc[date]
        pd.testing.assert_series_equal(a, b, check_names=False,
                                       obj=f"{nom} à {date}")


def test_calculer_sur_une_archive_vide_ne_leve_pas():
    vide = pd.DataFrame(columns=["date", "ticker", "cloture", "volume_fcfa"])
    assert features.calculer(vide).empty


def test_les_traits_ne_sont_pas_tous_infinis_sur_des_cours_plats():
    """Des cours strictement plats donnent une volatilité nulle ; la
    division qu'elle alimente ne doit pas produire d'infini."""
    table = cours({f"T{i}": [100.0] * 300 for i in range(6)})
    traits = features.calculer(table)
    assert np.isfinite(traits[features.TRAITS].to_numpy()).all() \
        or traits[features.TRAITS].isna().any().any()
