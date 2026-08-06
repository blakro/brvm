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
import pytest  # noqa: E402

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


def _cote_plate(dates, ticker="AAA", cloture=100.0):
    """Une valeur au cours constant, cotée aux dates données."""
    return pd.DataFrame([{"date": d, "ticker": ticker, "cloture": cloture,
                          "volume_titres": 10.0, "volume_fcfa": 1_000.0}
                         for d in dates])


def test_le_rendement_courant_compte_douze_mois_calendaires():
    """La fenêtre glissante est ]date − 365 jours, date], bornes comprises
    comme écrit — et en jours CALENDAIRES, pas en séances.

    Les deux bornes se testent parce qu'elles se trompent silencieusement :
    un détachement compté un jour trop tôt, ou gardé un jour de trop, ne
    déplace le rendement que d'une séance sur trois cents. Rien ne le
    montrerait à l'écran, et le signal de retour à la moyenne qui s'en
    nourrit changerait pourtant de sens.
    """
    dates = ["2024-06-01", "2024-06-02", "2025-06-01", "2025-06-02"]
    detache = pd.DataFrame([{"ticker": "AAA",
                             "date_detachement": "2024-06-02",
                             "montant": 5.0}])
    rendement = dividende.rendement_courant(_cote_plate(dates), detache)["AAA"]

    # La veille du détachement : rien n'est encore versé.
    assert rendement["2024-06-01"] == 0.0
    # Le jour même : compté, 5 FCFA sur un cours de 100.
    assert rendement["2024-06-02"] == pytest.approx(0.05)
    # Trois cent soixante-quatre jours plus tard : encore dans la fenêtre.
    assert rendement["2025-06-01"] == pytest.approx(0.05)
    # Trois cent soixante-cinq : il en sort, la borne étant stricte.
    assert rendement["2025-06-02"] == 0.0


def test_le_rendement_courant_additionne_les_detachements_de_la_fenetre():
    """Deux acomptes dans les douze mois font un rendement, pas deux.

    Plusieurs sociétés de la cote versent un acompte puis un solde ; ne
    retenir que le dernier détachement afficherait la moitié du rendement
    réel.
    """
    dates = ["2024-03-01", "2024-09-01", "2024-09-02"]
    detache = pd.DataFrame([
        {"ticker": "AAA", "date_detachement": "2024-03-01", "montant": 4.0},
        {"ticker": "AAA", "date_detachement": "2024-09-01", "montant": 6.0},
    ])
    rendement = dividende.rendement_courant(_cote_plate(dates), detache)["AAA"]

    assert rendement["2024-03-01"] == pytest.approx(0.04)
    assert rendement["2024-09-01"] == pytest.approx(0.10)
    assert rendement["2024-09-02"] == pytest.approx(0.10)


def test_une_valeur_sans_dividende_connu_rend_zero_et_non_du_vide():
    """Colonne à zéro, pas de NaN et pas de colonne absente : l'appelant
    parcourt toutes les valeurs, et une colonne manquante le ferait
    tomber au lieu de lui dire « aucun dividende connu »."""
    dates = ["2024-03-01", "2024-09-01"]
    cours = pd.concat([_cote_plate(dates), _cote_plate(dates, "BBB")])
    detache = pd.DataFrame([{"ticker": "AAA",
                             "date_detachement": "2024-03-01",
                             "montant": 4.0}])
    rendement = dividende.rendement_courant(cours, detache)

    assert list(rendement.columns) == ["AAA", "BBB"]
    assert (rendement["BBB"] == 0.0).all()


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


# --------------------------------------------------------------------
# Le détachement daté
# --------------------------------------------------------------------

def _cours(prix_par_ticker, debut="2020-01-01"):
    dates = pd.bdate_range(debut, periods=len(next(iter(prix_par_ticker.values()))))
    lignes = []
    for t, serie in prix_par_ticker.items():
        for d, c in zip(dates, serie):
            lignes.append({"date": d.strftime("%Y-%m-%d"), "ticker": t,
                           "cloture": c, "volume_fcfa": 1e6})
    return pd.DataFrame(lignes)


def test_le_dividende_est_credite_le_jour_du_detachement():
    """Et rapporté au cours de la VEILLE, pas à celui du jour.

    Le cours du jour du détachement est déjà amputé du dividende :
    diviser par lui surestimerait le rendement.
    """
    cours = _cours({"AAAA": [100, 100, 90, 90, 90]})
    dates = sorted(cours["date"].unique())
    div = pd.DataFrame([{"ticker": "AAAA", "date_detachement": dates[2],
                         "montant": 10.0, "exercice": "2019"}])
    table, couverts = dividende.detachements(cours, div)
    # Crédité sur la séance du détachement, rapporté au cours de cette
    # séance-là tel qu'il figure à l'index — 10/90.
    assert table.loc[dates[2], "AAAA"] == pytest.approx(10 / 90)
    assert (table.drop(index=dates[2])["AAAA"] == 0).all()
    assert couverts == {("AAAA", "2019")}


def test_un_rendement_impossible_ecarte_toute_l_ere_qui_le_precede():
    """La coupure de 2018 : montants d'époque contre cours archivés.

    CFAC verse 2 032 en 2017 puis 9,9 en 2018 ; la SGBC 5 837 puis 585.
    Reconstituer un facteur par société à partir du saut reviendrait à
    déduire la donnée de l'anomalie qu'elle explique. On refuse.
    """
    cours = _cours({"AAAA": [100] * 12})
    dates = sorted(cours["date"].unique())
    div = pd.DataFrame([
        {"ticker": "AAAA", "date_detachement": dates[1], "montant": 200.0,
         "exercice": "2018"},   # 200 % — impossible
        {"ticker": "AAAA", "date_detachement": dates[4], "montant": 5.0,
         "exercice": "2019"},   # 5 % — plausible, mais AVANT la frontière ?
        {"ticker": "AAAA", "date_detachement": dates[8], "montant": 8.0,
         "exercice": "2020"},   # 8 % — après, retenu
    ])
    table, couverts = dividende.detachements(cours, div)
    assert table.loc[dates[1], "AAAA"] == 0      # écarté : impossible
    assert table.loc[dates[4], "AAAA"] == pytest.approx(0.05)  # après la frontière
    assert table.loc[dates[8], "AAAA"] == pytest.approx(0.08)
    assert ("AAAA", "2018") not in couverts


def test_une_societe_saine_ne_perd_rien():
    cours = _cours({"AAAA": [100] * 6})
    dates = sorted(cours["date"].unique())
    div = pd.DataFrame([{"ticker": "AAAA", "date_detachement": d,
                         "montant": 7.0, "exercice": "2020"}
                        for d in (dates[1], dates[3])])
    table, _ = dividende.detachements(cours, div)
    assert (table["AAAA"] > 0).sum() == 2


def test_pas_de_double_compte_entre_calendrier_et_fondamentaux():
    """Un exercice connu des deux côtés serait compté deux fois, et le
    rendement total gonflerait sans que rien ne le dise."""
    cours = _cours({"AAAA": [100] * 10})
    dates = sorted(cours["date"].unique())
    annee = dates[0][:4]
    div = pd.DataFrame([{"ticker": "AAAA", "date_detachement": dates[3],
                         "montant": 8.0, "exercice": annee}])
    fonda = pd.DataFrame([{"ticker": "AAAA", "date": f"{annee}-12-31",
                           "indicateur": "rendement", "valeur": 8.0}])
    total = dividende.accroissement(cours, fonda, div)["AAAA"].sum()
    assert total == pytest.approx(0.08), "l'exercice a été compté deux fois"
    # Sans calendrier, le repli s'applique et rend le même total.
    etale = dividende.accroissement(cours, fonda)["AAAA"].sum()
    assert etale == pytest.approx(0.08)


def test_la_couverture_ne_se_compte_pas_en_seances_creditees():
    """Depuis le détachement daté, le dividende ne touche qu'une séance
    par an. Compter les séances créditées ferait chuter la couverture
    alors qu'on en sait plus — la mesure punirait le progrès."""
    cours = _cours({"AAAA": [100] * 260})
    dates = sorted(cours["date"].unique())
    annee = dates[0][:4]
    div = pd.DataFrame([{"ticker": "AAAA", "date_detachement": dates[100],
                         "montant": 8.0, "exercice": annee}])
    c = dividende.couverture(cours, pd.DataFrame(), div)
    assert c["exercices"] == [annee]
    assert c["part"] > 0.9, "la couverture a été comptée en séances créditées"


def test_la_couverture_ne_flatte_pas_non_plus():
    """Le piège symétrique, trouvé en rendant l'app. Compter les séances
    dont l'EXERCICE est connu annonçait 95 % là où trois sociétés sur
    trente-cinq avaient un dividende : un exercice comptait pour couvert
    dès la première. La mesure porte donc sur les couples (séance,
    société), et une seule société couverte sur quatre donne 25 %."""
    cours = _cours({t: [100] * 260 for t in ("AAAA", "BBBB", "CCCC", "DDDD")})
    dates = sorted(cours["date"].unique())
    annee = dates[0][:4]
    div = pd.DataFrame([{"ticker": "AAAA", "date_detachement": dates[100],
                         "montant": 8.0, "exercice": annee}])
    c = dividende.couverture(cours, pd.DataFrame(), div)
    assert c["part"] == pytest.approx(0.25, abs=0.01), \
        "un exercice a compté pour couvert au-delà de la société qui le porte"


def test_la_couverture_ignore_ce_que_le_garde_fou_refuse():
    """Compter un détachement écarté pour cause d'échelle gonflerait la
    couverture de ce qu'on vient précisément de refuser."""
    cours = _cours({"AAAA": [100] * 260})
    dates = sorted(cours["date"].unique())
    div = pd.DataFrame([{"ticker": "AAAA", "date_detachement": dates[100],
                         "montant": 200.0, "exercice": dates[0][:4]}])
    c = dividende.couverture(cours, pd.DataFrame(), div)
    assert c["part"] == 0.0 and c["exercices"] == []
