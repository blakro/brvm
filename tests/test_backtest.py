"""Backtest, sur des trajectoires construites pour piéger le moteur.

La question qu'un backtest doit se voir poser n'est pas « combien
rapporte-t-il ? » mais « triche-t-il ? ». Un moteur qui laisse fuir un
regard en avant produit des courbes superbes et des pertes réelles, et rien
dans le résultat ne le trahit — c'est pour cela que ces tests existent et
qu'ils sont écrits avant d'avoir des données.

    python tests/test_backtest.py
    pytest tests/test_backtest.py
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

import pandas as pd  # noqa: E402

from brvm import backtest, dividende  # noqa: E402

# Fenêtres raccourcies : le momentum réel demande 250 séances, ce qui
# obligerait chaque test à fabriquer plusieurs années de cotation pour
# vérifier une mécanique qui ne dépend pas de la longueur.
REGLAGES = {
    "analyse": {
        "volume_median_min_fcfa": 1_000,
        "fenetre_momentum": 40, "saut_momentum": 4,
        "fenetre_volatilite": 20, "fenetre_liquidite": 20,
        "moyenne_courte": 5, "moyenne_longue": 20,
        "min_par_secteur": 99,  # neutralisation désactivée : hors sujet ici
    },
    "ponderations": {"momentum": 1.0},
    "backtest": {
        "positions": 2, "pas_rebalancement": 10, "delai_execution": 1,
        "frais_pourcent": 0.0, "impact_pourcent": 0.0,
    },
}


def _cours(trajectoires: dict[str, list[float]], volume_fcfa: float = 5_000_000):
    lignes = []
    for ticker, prix in trajectoires.items():
        for rang, valeur in enumerate(prix):
            lignes.append({
                "date": f"{2020 + rang // 336:04d}-{1 + (rang % 336) // 28:02d}-"
                        f"{1 + rang % 28:02d}",
                "ticker": ticker,
                "cloture": valeur,
                "volume_titres": 100.0,
                "volume_fcfa": volume_fcfa,
            })
    return pd.DataFrame(lignes).sort_values(["date", "ticker"])


def _plat(n, depart=100.0):
    return [depart] * n


def test_le_moteur_ne_regarde_pas_en_avant():
    """Le test qui justifie tous les autres.

    PIEGE monte régulièrement pendant toute la période d'observation, puis
    s'effondre de moitié juste après la date où le portefeuille est
    constitué. Un moteur qui verrait l'avenir l'éviterait — et sa courbe
    serait superbe.

    Ce qu'on exige ici est donc l'inverse d'une bonne performance : PIEGE
    DOIT être retenu, et le rendement de la période DOIT encaisser le
    krach. Un backtest qui gagne sur ce scénario est un backtest qui ment.
    """
    n = 60
    piege = [100.0 * (1.02 ** i) for i in range(n)]
    krach = 46  # une séance après la décision prise en 44 (entrée en 45)
    for i in range(krach, n):
        piege[i] = piege[krach - 1] * 0.5

    trajectoires = {
        "PIEGE": piege,
        "MOLLE": [100.0 * (1.001 ** i) for i in range(n)],
        "PLATE": _plat(n),
    }
    resultat = backtest.backtester(_cours(trajectoires), None, REGLAGES)
    etapes = resultat["etapes"]
    assert not etapes.empty, "aucun rééquilibrage : le scénario est trop court"

    premiere = etapes.iloc[0]
    assert "PIEGE" in premiere["positions"], (
        "PIEGE n'a pas été retenu alors qu'il dominait au moment du choix — "
        "le classement a vu quelque chose qu'il ne devait pas voir"
    )
    assert premiere["rendement"] < 0, (
        f"rendement {premiere['rendement']:+.1%} : le krach survenu après "
        "l'entrée n'a pas été encaissé"
    )


def test_l_execution_est_retardee_d_une_seance():
    """Décider et acheter au même cours revient à passer un ordre à un prix
    déjà connu. L'entrée doit donc suivre la décision, jamais coïncider."""
    n = 60
    resultat = backtest.backtester(
        _cours({"AAAA": [100.0 + i for i in range(n)],
                "BBBB": [100.0 + 2 * i for i in range(n)]}),
        None, REGLAGES,
    )
    for etape in resultat["etapes"].itertuples():
        assert etape.date_entree > etape.date_decision
        assert etape.date_sortie > etape.date_entree


def test_les_frais_amputent_la_performance():
    """Sur un portefeuille qui tourne, des frais non nuls doivent coûter —
    et ce coût doit se retrouver dans le cumul, pas seulement dans la
    courbe."""
    n = 90
    # Deux valeurs qui alternent en tête, pour forcer de la rotation.
    a = [100.0 * (1.01 if (i // 10) % 2 == 0 else 0.99) ** i for i in range(n)]
    b = [100.0 * (0.99 if (i // 10) % 2 == 0 else 1.01) ** i for i in range(n)]
    cours = _cours({"AAAA": a, "BBBB": b, "CCCC": _plat(n), "DDDD": _plat(n, 50)})

    sans = backtest.backtester(cours, None, REGLAGES)
    chers = {**REGLAGES, "backtest": {**REGLAGES["backtest"],
                                      "frais_pourcent": 2.0,
                                      "impact_pourcent": 1.0}}
    avec = backtest.backtester(cours, None, chers)

    assert sans["cout_cumule"] == 0.0
    assert avec["cout_cumule"] > 0.0, "aucune rotation : le test ne prouve rien"
    assert avec["rendement_total"] < sans["rendement_total"]


def test_sans_rotation_pas_de_frais():
    """Un classement stable ne doit rien coûter après la première entrée.

    C'est le pendant du test précédent : des frais prélevés sur un
    portefeuille qu'on ne touche pas signaleraient un calcul de rotation
    faux, qui pénaliserait toutes les stratégies lentes.
    """
    n = 80
    trajectoires = {
        f"T{i}": [100.0 * (1 + 0.001 * i) ** j for j in range(n)]
        for i in range(1, 5)
    }
    chers = {**REGLAGES, "backtest": {**REGLAGES["backtest"],
                                      "frais_pourcent": 2.0}}
    etapes = backtest.backtester(_cours(trajectoires), None, chers)["etapes"]

    assert len(etapes) > 1
    assert etapes.iloc[0]["cout"] > 0, "la constitution initiale doit coûter"
    assert (etapes.iloc[1:]["rotation"] == 0).all()
    assert (etapes.iloc[1:]["cout"] == 0).all()


def test_la_reference_est_l_univers_equipondere():
    """Battre zéro n'est pas battre le marché.

    Quand toutes les valeurs montent également, la stratégie ne peut pas
    faire mieux que l'univers : les deux courbes doivent se confondre.
    """
    n = 70
    trajectoires = {f"T{i}": [100.0 * (1.005 ** j) for j in range(n)]
                    for i in range(4)}
    resultat = backtest.backtester(_cours(trajectoires), None, REGLAGES)

    assert abs(resultat["rendement_total"] - resultat["reference_total"]) < 1e-9


def test_perte_maximale():
    """Mesurée depuis le sommet, pas depuis le début."""
    courbe = pd.Series([1.0, 1.5, 0.9, 1.2])
    assert abs(backtest._perte_max(courbe) - (0.9 / 1.5 - 1)) < 1e-12


def test_historique_insuffisant_refuse_de_conclure():
    """Le message doit chiffrer ce qui manque, pas dire « erreur »."""
    resultat = backtest.backtester(_cours({"AAAA": _plat(30)}), None, REGLAGES)
    assert resultat["etapes"].empty

    message = backtest.expliquer(resultat)
    assert "30 séances" in message and "nécessaires" in message


def test_les_avertissements_accompagnent_tout_resultat():
    """Un chiffre de performance ne doit jamais circuler seul.

    Biais du survivant et absence de dividendes ne sont pas corrigeables
    ici ; les taire reviendrait à présenter comme mesuré ce qui est
    seulement simulé.
    """
    n = 70
    resultat = backtest.backtester(
        _cours({f"T{i}": [100.0 * (1 + 0.002 * i) ** j for j in range(n)]
                for i in range(4)}), None, REGLAGES,
    )
    rendu = backtest.expliquer(resultat)
    assert "survivant" in rendu and "dividendes" in rendu
    assert "référence" in rendu.lower()


def _marche_regulier(n=200):
    """Quatre valeurs, dérives différentes : de quoi que le classement
    ait quelque chose à ordonner."""
    import numpy as np
    return _cours({
        f"V{i}": list(100 * np.exp(np.arange(n) * (0.0002 * (i + 1))))
        for i in range(4)
    })


def _fondamentaux(tickers, annees, rendement=8.0):
    """Un rendement annuel connu, en pourcentage, comme la source le publie."""
    return pd.DataFrame([
        {"ticker": t, "date": f"{a}-12-31", "indicateur": "rendement",
         "valeur": rendement}
        for t in tickers for a in annees
    ])


def test_le_dividende_s_accroit_sur_les_seances_de_son_exercice():
    """Huit pour cent répartis sur l'année : la somme des accroissements
    d'un exercice doit rendre exactement le rendement publié."""
    cours = _marche_regulier()
    tickers = sorted(cours["ticker"].unique())
    annees = sorted({d[:4] for d in cours["date"]})
    accru = dividende.accroissement(
        cours, _fondamentaux(tickers, annees, rendement=8.0))

    for annee in annees:
        seances = [d for d in accru.index if d.startswith(annee)]
        somme = accru.loc[seances, tickers[0]].sum()
        assert abs(somme - 0.08) < 1e-9, (annee, somme)


def test_un_exercice_inconnu_n_accroit_rien():
    """Zéro et non NaN : une année sans dividende connu n'ajoute rien,
    alors qu'un NaN effacerait aussi le rendement du cours."""
    cours = _marche_regulier()
    accru = dividende.accroissement(cours, pd.DataFrame())
    assert (accru == 0).all().all()
    assert accru.notna().all().all()


def test_le_backtest_avec_dividendes_rend_plus_que_sans():
    """Sur ce marché le dividende vaut 7 à 10 % l'an quand le cours en
    rend 2,8 : l'ignorer ne biaise pas à la marge, cela change l'ordre de
    grandeur."""
    cours = _marche_regulier()
    reglages = REGLAGES
    tickers = sorted(cours["ticker"].unique())
    annees = sorted({d[:4] for d in cours["date"]})

    sans = backtest.backtester(cours, None, reglages)
    avec = backtest.backtester(cours, None, reglages,
                               fondamentaux=_fondamentaux(tickers, annees))
    if sans["etapes"].empty:
        return                                   # historique trop court
    assert avec["rendement_total"] > sans["rendement_total"]
    assert abs(avec["rendement_prix"] - sans["rendement_total"]) < 1e-9
    assert avec["apport_dividende"] > 0


def test_l_avertissement_change_de_nature_au_lieu_de_disparaitre():
    """La correction est partielle et approximée. Remplacer « dividendes
    non pris en compte » par le silence serait pire que l'aveu."""
    cours = _marche_regulier()
    tickers = sorted(cours["ticker"].unique())
    annees = sorted({d[:4] for d in cours["date"]})
    avec = backtest.backtester(cours, None, REGLAGES,
                               fondamentaux=_fondamentaux(tickers, annees))
    joint = " ; ".join(avec["avertissements"])
    assert "date de détachement" in joint
    assert "non pris en compte" not in joint
    assert avec["couverture_dividende"]["part"] > 0


if __name__ == "__main__":
    echecs = 0
    for nom, fonction in sorted(globals().items()):
        if not nom.startswith("test_"):
            continue
        try:
            fonction()
            print(f"  ok    {nom}")
        except AssertionError as erreur:
            echecs += 1
            print(f"  ÉCHEC {nom}\n        {erreur}")
    print(f"\n{'tout passe' if not echecs else f'{echecs} échec(s)'}")
    sys.exit(1 if echecs else 0)
