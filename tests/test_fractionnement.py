"""Fractionnements d'actions : les reconnaître, et seulement eux.

Le cas d'origine est SNTS, le 26/10/2026 : une action devenue dix, et une
analyse qui y lisait un krach de 89 %. Les cas NÉGATIFS comptent autant
que lui. Une détection qui prendrait un gros détachement de dividende ou
une séance fantôme pour un fractionnement réécrirait à tort tout le passé
d'une valeur — et l'ajustement n'écrivant rien sur disque, personne ne le
verrait dans un diff.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from brvm import cli, db, dividende, fractionnement, qualite


def serie(cours: list[float], ticker: str = "AAAA",
          debut: str = "2026-01-01") -> pd.DataFrame:
    """Une série quotidienne à partir d'une liste de clôtures."""
    dates = pd.bdate_range(debut, periods=len(cours)).strftime("%Y-%m-%d")
    return pd.DataFrame({
        "date": dates, "ticker": ticker,
        "ouverture": cours, "haut": cours, "bas": cours, "cloture": cours,
        "volume_titres": [100.0] * len(cours),
        "volume_fcfa": [100.0 * c for c in cours],
    })


AVANT = [43000, 43500, 43200, 43850, 43900, 43850]
APRES = [4700, 4425, 4200, 4150, 4350, 4150, 4300]


def snts() -> pd.DataFrame:
    """Le profil SNTS : 43 850 la veille, 4 700 le jour même."""
    return serie(AVANT + APRES, "SNTS")


# --------------------------------------------------------------------
# Le rapport
# --------------------------------------------------------------------

def test_le_rapport_de_snts_est_dix():
    """43 850 → 4 700 : la bande admet 9 et 10, le plus rond l'emporte."""
    assert fractionnement.rapport_probable(43850, 4700) == 10


@pytest.mark.parametrize("precedent, cloture, attendu", [
    (8100, 4050, 2),       # ONTBF, 05/02/2018
    (9000, 4300, 2),       # PALC, 06/11/2017
    (30000, 9800, 3),
    (1000, 10100, 0.1),    # regroupement de dix en une
])
def test_rapports_reconnus(precedent, cloture, attendu):
    assert fractionnement.rapport_probable(precedent, cloture) \
        == pytest.approx(attendu)


@pytest.mark.parametrize("precedent, cloture", [
    (3760, 2185),          # FTSC, détachement de 1 320 FCFA le 26/09/2025
    (1000, 930),           # une séance ordinaire à la limite
    (1000, 600),           # -40 % : ni un mouvement, ni un rapport entier
    (0, 100), (100, 0),
])
def test_rapports_refuses(precedent, cloture):
    assert fractionnement.rapport_probable(precedent, cloture) is None


# --------------------------------------------------------------------
# La détection
# --------------------------------------------------------------------

def test_detecte_le_fractionnement_de_snts():
    trouves = fractionnement.detecter(snts())
    assert len(trouves) == 1
    e = trouves.iloc[0]
    assert (e["ticker"], e["date"], e["rapport"]) == \
        ("SNTS", snts()["date"].iloc[len(AVANT)], 10)
    assert e["origine"] == "détecté"


def test_le_soir_meme_il_est_applique_mais_a_confirmer():
    """La séance du fractionnement est la dernière de l'archive : rien ne
    l'a encore confirmée, mais l'app aurait sinon affiché un krach."""
    trouves = fractionnement.detecter(serie(AVANT + [4700], "SNTS"))
    assert len(trouves) == 1
    assert trouves.iloc[0]["origine"] == "détecté, à confirmer"


def test_ignore_la_seance_fantome():
    """Moitié de la veille ET du lendemain : c'est `qualite` qui s'en
    charge, pas un fractionnement."""
    assert fractionnement.detecter(
        serie([6790, 6800, 6810, 3400, 6750, 6760, 6770])).empty


def test_ignore_le_fantome_de_deux_seances_et_son_retour():
    """ONTBF, décembre 2015 : 12 900, puis deux séances à 6 450, puis
    12 990. Ni la chute ni le retour — qui passerait sinon pour un
    regroupement — ne sont des fractionnements."""
    assert fractionnement.detecter(
        serie([12900, 12900, 12900, 6450, 6450, 12990, 13500, 13400])).empty


def test_ignore_un_gros_detachement_de_dividende():
    assert fractionnement.detecter(
        serie([4605, 4385, 4060, 3760, 2185, 2345, 2520, 2705])).empty


def test_ignore_une_rechute_qui_ne_tient_pas():
    """Une clôture mal transcrite un soir, corrigée le lendemain : la
    détection cesse d'elle-même d'ajuster."""
    assert fractionnement.detecter(
        serie(AVANT + [4385, 43900, 44000], "SNTS")).empty


def test_detecte_un_regroupement():
    trouves = fractionnement.detecter(serie([100, 101, 100, 1010, 1000, 990]))
    assert len(trouves) == 1 and trouves.iloc[0]["rapport"] == pytest.approx(0.1)


def test_detection_independante_par_valeur():
    """Le saut d'une valeur ne se lit pas contre la veille d'une autre."""
    cours = pd.concat([snts(), serie([4000] * len(AVANT + APRES), "AUTRE")])
    trouves = fractionnement.detecter(cours.sample(frac=1, random_state=1))
    assert list(trouves["ticker"]) == ["SNTS"]


# --------------------------------------------------------------------
# Le registre
# --------------------------------------------------------------------

def test_le_registre_l_emporte_sans_ajuster_deux_fois():
    """Déclaré au jour officiel, un vendredi où la valeur n'a pas coté ;
    détecté à la première séance échangée. Un seul événement."""
    cours = snts()
    officiel = cours["date"].iloc[len(AVANT)]
    cours = cours[cours["date"] != officiel]
    detectes = fractionnement.detecter(cours)
    assert list(detectes["date"]) == [cours["date"].iloc[len(AVANT)]]

    registre = pd.DataFrame([{"ticker": "SNTS", "date": officiel,
                              "rapport": 10.0, "note": ""}])
    liste = fractionnement.evenements(cours, registre)
    assert len(liste) == 1 and liste.iloc[0]["origine"] == "registre"
    ajuste = fractionnement.ajuster(cours, registre=registre)["cours"]
    # Une seule division par dix : tout reste autour de 4 300, rien n'est
    # tombé vers 430.
    assert ajuste["cloture"].between(4000, 4500).all()


def test_un_rapport_de_un_fait_taire_la_detection():
    cours = snts()
    registre = pd.DataFrame([{"ticker": "SNTS",
                              "date": cours["date"].iloc[len(AVANT)],
                              "rapport": 1.0, "note": "pas un fractionnement"}])
    assert fractionnement.evenements(cours, registre).empty
    ajuste = fractionnement.ajuster(cours, registre=registre)
    pd.testing.assert_frame_equal(ajuste["cours"], cours)


def test_le_registre_couvre_ce_que_la_detection_ne_voit_pas():
    """Trois pour deux : pas un entier, donc déclaré à la main."""
    cours = serie([3000, 3000, 3000, 2000, 2000, 2000])
    assert fractionnement.detecter(cours).empty
    registre = pd.DataFrame([{"ticker": "AAAA", "date": cours["date"].iloc[3],
                              "rapport": 1.5, "note": ""}])
    ajuste = fractionnement.ajuster(cours, registre=registre)["cours"]
    assert list(ajuste["cloture"]) == [2000.0] * 6


# --------------------------------------------------------------------
# L'ajustement
# --------------------------------------------------------------------

def test_ajuste_le_passe_et_pas_le_present():
    cours = snts()
    ajuste = fractionnement.ajuster(cours)["cours"]
    n = len(AVANT)
    # La veille devient le prix de référence publié par la BRVM : 4 385.
    assert ajuste["cloture"].iloc[n - 1] == pytest.approx(4385)
    assert ajuste["ouverture"].iloc[n - 1] == pytest.approx(4385)
    assert list(ajuste["cloture"].iloc[n:]) == APRES
    # Dix fois plus d'actions pour le même argent.
    assert ajuste["volume_titres"].iloc[n - 1] == pytest.approx(1000)
    assert ajuste["volume_titres"].iloc[n] == pytest.approx(100)
    pd.testing.assert_series_equal(ajuste["volume_fcfa"], cours["volume_fcfa"])
    # L'original n'est pas touché : l'archive reste brute.
    assert cours["cloture"].iloc[n - 1] == 43850


def test_la_variation_du_jour_redevient_vraie():
    """+7,18 % sur le prix de référence ajusté, et non -89 %."""
    ajuste = fractionnement.ajuster(snts())["cours"]
    variation = ajuste["cloture"].pct_change().iloc[len(AVANT)]
    assert variation == pytest.approx(4700 / 4385 - 1)


def test_deux_fractionnements_se_cumulent():
    cours = serie([8000, 8000, 4000, 4000, 4000, 4000, 400, 400, 400, 400,
                   400, 400])
    ajuste = fractionnement.ajuster(cours)["cours"]
    assert list(ajuste["cloture"]) == [400.0] * 12


def test_ajuste_les_dividendes_detaches_avant():
    cours = snts()
    dividendes = pd.DataFrame([
        {"ticker": "SNTS", "date_detachement": cours["date"].iloc[2],
         "montant": 1740.0, "exercice": 2025.0},
        {"ticker": "SNTS", "date_detachement": cours["date"].iloc[-1],
         "montant": 180.0, "exercice": 2026.0},
    ])
    montants = fractionnement.ajuster(cours, dividendes)["dividendes"]["montant"]
    assert list(montants) == [pytest.approx(174.0), 180.0]


def test_le_rendement_du_dividende_ne_saute_pas():
    """Le symptôme visible : 1 740 FCFA rapportés au prix de l'action
    nouvelle donnaient 40 % de rendement."""
    cours = snts()
    dividendes = pd.DataFrame([{"ticker": "SNTS",
                                "date_detachement": cours["date"].iloc[1],
                                "montant": 1740.0, "exercice": 2025.0}])
    brut = dividende.rendement_courant(cours, dividendes)["SNTS"].iloc[-1]
    assert brut > 0.3
    ajuste = fractionnement.ajuster(cours, dividendes)
    juste = dividende.rendement_courant(
        ajuste["cours"], ajuste["dividendes"])["SNTS"].iloc[-1]
    assert juste == pytest.approx(174 / APRES[-1])


# --------------------------------------------------------------------
# Les fondamentaux : un montant par exercice, sans date de versement
# --------------------------------------------------------------------

def _annuelle(premiere: float, apres: float) -> pd.DataFrame:
    """2025 sur l'ancienne base, fractionnement ×10 au 26/10/2026."""
    jours_25 = pd.bdate_range("2025-01-02", "2025-12-31")
    jours_26 = pd.bdate_range("2026-01-02", "2026-11-03")
    lignes = [{"date": j.strftime("%Y-%m-%d"), "ticker": "SNTS",
               "cloture": premiere} for j in jours_25]
    lignes += [{"date": j.strftime("%Y-%m-%d"), "ticker": "SNTS",
                "cloture": premiere if j < pd.Timestamp("2026-10-26")
                else apres} for j in jours_26]
    return pd.DataFrame(lignes)


def _fonda(dividende_: float, rendement: float | None) -> pd.DataFrame:
    lignes = [{"ticker": "SNTS", "date": "2025-12-31",
               "indicateur": "dividende", "valeur": dividende_}]
    if rendement is not None:
        lignes.append({"ticker": "SNTS", "date": "2025-12-31",
                       "indicateur": "rendement", "valeur": rendement})
    return pd.DataFrame(lignes)


def test_fondamentaux_sur_l_ancienne_base():
    """1 740 FCFA à 7,25 % : le cours implicite est 24 000, celui de
    l'action ancienne. Ramené à l'action nouvelle : 174."""
    ajuste = fractionnement.ajuster(_annuelle(24000, 2400),
                                    fondamentaux=_fonda(1740, 7.25))
    fonda = ajuste["fondamentaux"].set_index("indicateur")["valeur"]
    assert fonda["dividende"] == pytest.approx(174)
    assert fonda["rendement"] == 7.25    # un rapport : inchangé


def test_fondamentaux_deja_republies_ne_sont_pas_ajustes_deux_fois():
    """La source a republié son tableau en actions nouvelles : 174 à
    7,25 % donne un cours implicite de 2 400. Diviser encore par dix
    rendrait 17,4."""
    ajuste = fractionnement.ajuster(_annuelle(24000, 2400),
                                    fondamentaux=_fonda(174, 7.25))
    fonda = ajuste["fondamentaux"].set_index("indicateur")["valeur"]
    assert fonda["dividende"] == pytest.approx(174)


def test_fondamentaux_sans_rendement_suivent_le_calendrier():
    """Sans rendement, la date du détachement décide — ici après le
    fractionnement : le montant est déjà en actions nouvelles."""
    dividendes = pd.DataFrame([{"ticker": "SNTS",
                                "date_detachement": "2026-10-30",
                                "montant": 180.0, "exercice": 2025.0}])
    ajuste = fractionnement.ajuster(_annuelle(24000, 2400), dividendes,
                                    _fonda(180, None))
    assert ajuste["fondamentaux"]["valeur"].iloc[0] == pytest.approx(180)
    # Et faute de calendrier, la fin de l'exercice, antérieure : divisé.
    ajuste = fractionnement.ajuster(_annuelle(24000, 2400),
                                    fondamentaux=_fonda(1740, None))
    assert ajuste["fondamentaux"]["valeur"].iloc[0] == pytest.approx(174)


# --------------------------------------------------------------------
# Le contrôle des limites et l'archive réelle
# --------------------------------------------------------------------

def test_les_limites_nomment_le_fractionnement():
    cours = snts()
    hors = qualite.limites(cours, fractionnements=fractionnement.detecter(cours))
    assert list(hors["cause_probable"]) == ["fractionnement d'actions"]


def test_les_limites_retrouvent_un_jour_officiel_sans_cotation():
    """Le jour déclaré n'a pas coté — PALC, fractionnée le 03/11/2017,
    échangée de nouveau le 06/11 : la première séance qui suit porte le
    saut, et c'est elle qui est nommée."""
    cours = serie([9000, 9000, 9000, 4300, 4185, 4175], "PALC",
                  debut="2017-10-30")
    cours = cours[cours["date"] != "2017-11-02"]
    registre = pd.DataFrame([{"ticker": "PALC", "date": "2017-11-02",
                              "rapport": 2.0, "note": ""}])
    hors = qualite.limites(cours, fractionnements=registre)
    assert list(hors["cause_probable"]) == ["fractionnement d'actions"]


def test_l_archive_reelle_connait_le_fractionnement_de_snts():
    """Sur les vraies données : détecté, déclaré, et la veille ajustée
    retombe sur le prix de référence publié par la BRVM."""
    cours = db.charger_archive("cours")
    if cours.empty or cours["date"].max() < "2026-10-26":
        pytest.skip("archive antérieure au fractionnement de SNTS")
    detectes = fractionnement.detecter(cours)
    snts_ = detectes[detectes["ticker"] == "SNTS"]
    assert list(zip(snts_["date"], snts_["rapport"])) == [("2026-10-26", 10)]

    registre = db.charger_archive("fractionnements")
    assert ("SNTS", "2026-10-26") in set(zip(registre["ticker"],
                                             registre["date"]))
    ajuste = fractionnement.ajuster(cours, registre=registre)["cours"]
    veille = ajuste[(ajuste["ticker"] == "SNTS")
                    & (ajuste["date"] == "2026-10-23")]["cloture"]
    assert veille.iloc[0] == pytest.approx(4385)


def test_la_commande_verse_les_detections_au_registre(capsys):
    with tempfile.TemporaryDirectory() as dossier:
        racine = Path(dossier)
        config = racine / "c.toml"
        config.write_text(
            "[base]\n"
            f'chemin = "{(racine / "b.db").as_posix()}"\n'
            f'archive_cours = "{(racine / "cours.csv").as_posix()}"\n'
            f'archive_fractionnements = '
            f'"{(racine / "fractionnements.csv").as_posix()}"\n',
            encoding="utf-8")
        snts().to_csv(racine / "cours.csv", index=False)
        anciens = {k: os.environ.get(k) for k in ("BRVM_CONFIG", "BRVM_BASE")}
        os.environ["BRVM_CONFIG"] = str(config)
        os.environ["BRVM_BASE"] = str(racine / "b.db")
        try:
            assert cli.main(["fractionnements"]) == 0
            assert "absente(s) du registre" in capsys.readouterr().out
            assert not (racine / "fractionnements.csv").exists()

            assert cli.main(["fractionnements", "--enregistrer"]) == 0
            assert "1 ligne(s) versée(s)" in capsys.readouterr().out
            registre = db.charger_archive("fractionnements")
            assert list(registre["ticker"]) == ["SNTS"]
            assert float(registre["rapport"].iloc[0]) == 10

            # Une fois versée, la ligne vient du registre : plus rien à verser.
            assert cli.main(["fractionnements", "--enregistrer"]) == 0
            sortie = capsys.readouterr().out
            assert "registre" in sortie and "versée" not in sortie
            assert len(db.charger_archive("fractionnements")) == 1
        finally:
            for cle, valeur in anciens.items():
                if valeur is None:
                    os.environ.pop(cle, None)
                else:
                    os.environ[cle] = valeur
