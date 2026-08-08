"""Le contrôle doit attraper la séance fantôme SANS attraper le reste.

Les cas négatifs comptent plus que les positifs ici. Un détecteur qui
signale une division du nominal ou un détachement de dividende serait
retiré du pipeline au bout de trois faux positifs, et l'archive
retomberait sans surveillance.
"""

from __future__ import annotations

import pandas as pd
import pytest

from brvm import db, qualite


def serie(cours: list[float], ticker: str = "AAAA") -> pd.DataFrame:
    """Une série quotidienne à partir d'une liste de clôtures."""
    dates = pd.bdate_range("2020-01-01", periods=len(cours)).strftime("%Y-%m-%d")
    return pd.DataFrame({
        "date": dates,
        "ticker": ticker,
        "cloture": cours,
        "volume_titres": [100.0] * len(cours),
    })


# --------------------------------------------------------------------
# Ce qui doit être attrapé
# --------------------------------------------------------------------

def test_attrape_le_doublement_isole():
    """Le cas ONTBF : le cours vaut la moitié de la veille et du lendemain."""
    suspects = qualite.pics_isoles(serie([6790, 3395, 6750]))
    assert len(suspects) == 1
    ligne = suspects.iloc[0]
    assert ligne["cloture"] == 3395
    assert ligne["facteur"] == pytest.approx(0.5)
    assert ligne["precedent"] == 6790 and ligne["suivant"] == 6750


def test_attrape_le_facteur_dix_et_le_facteur_cinq():
    """Les cas SAFC (÷10) et UNXC (×5)."""
    bas = qualite.pics_isoles(serie([274.29, 27.14, 274.29]))
    haut = qualite.pics_isoles(serie([1700, 8500, 1640]))
    assert bas.iloc[0]["facteur"] == pytest.approx(0.1)
    assert haut.iloc[0]["facteur"] == pytest.approx(5.0)


def test_les_valeurs_sont_traitees_separement():
    """Le voisinage se prend au sein d'un ticker, jamais d'un ticker à
    l'autre : les lignes se suivent dans le fichier, pas dans le marché."""
    table = pd.concat([serie([100, 100, 100], "AAAA"),
                       serie([200, 100, 200], "BBBB")], ignore_index=True)
    suspects = qualite.pics_isoles(table)
    assert list(suspects["ticker"]) == ["BBBB"]


def test_plusieurs_pics_dans_la_meme_serie():
    suspects = qualite.pics_isoles(serie([100, 50, 100, 100, 50, 100]))
    assert len(suspects) == 2


# --------------------------------------------------------------------
# Ce qui ne doit PAS être attrapé — la partie qui compte
# --------------------------------------------------------------------

def test_ignore_une_division_du_nominal():
    """Le cours tombe de moitié ET Y RESTE. C'est une opération sur titre,
    pas une erreur : la signaler serait crier sur une donnée juste."""
    assert qualite.pics_isoles(serie([1000, 1000, 500, 500, 500])).empty


def test_ignore_un_detachement_de_dividende():
    """Une baisse de 10 % le jour du détachement franchit la limite de
    ±7,5 % en toute légitimité — le prix de référence est ajusté."""
    assert qualite.pics_isoles(serie([1000, 1000, 900, 905, 910])).empty


def test_ignore_un_mouvement_ordinaire():
    assert qualite.pics_isoles(serie([1000, 1030, 995, 1010])).empty


def test_ignore_un_facteur_non_entier():
    """×1,7 n'est pas une erreur de saisie reconnaissable : hors signature,
    donc hors contrôle. Mieux vaut manquer que se tromper."""
    assert qualite.pics_isoles(serie([1000, 1700, 1000])).empty


def test_les_bords_sont_hors_controle():
    """Une ligne sans deux voisines n'est pas jugeable. Elle n'est pas non
    plus innocentée : elle est simplement hors de portée du contrôle."""
    assert qualite.pics_isoles(serie([50, 100, 100])).empty
    assert qualite.pics_isoles(serie([100, 100, 50])).empty


def test_serie_vide_ou_sans_cloture():
    assert qualite.pics_isoles(pd.DataFrame()).empty
    assert list(qualite.pics_isoles(pd.DataFrame()).columns) == qualite.COLONNES
    assert qualite.pics_isoles(pd.DataFrame({"date": [], "ticker": []})).empty


# --------------------------------------------------------------------
# Le retrait
# --------------------------------------------------------------------

def test_retirer_efface_les_bonnes_lignes():
    table = serie([100, 50, 100, 101, 102])
    suspects = qualite.pics_isoles(table)
    propre = qualite.retirer(table, suspects)
    assert len(propre) == len(table) - 1
    assert 50 not in list(propre["cloture"])


def test_retirer_sans_suspect_ne_touche_a_rien():
    table = serie([100, 101, 102])
    propre = qualite.retirer(table, qualite.pics_isoles(table))
    pd.testing.assert_frame_equal(propre, table)


def test_retirer_se_fie_a_la_cle_pas_a_l_index():
    """`pics_isoles` trie ; un retrait par index effacerait autre chose.

    Le piège est silencieux : l'archive garderait le bon nombre de lignes
    et aurait perdu les mauvaises.
    """
    table = pd.concat([serie([100, 100, 100], "ZZZZ"),
                       serie([200, 100, 200], "AAAA")], ignore_index=True)
    suspects = qualite.pics_isoles(table)
    propre = qualite.retirer(table, suspects)
    assert len(propre) == 5
    assert list(propre[propre["ticker"] == "ZZZZ"]["cloture"]) == [100, 100, 100]


def test_le_controle_est_idempotent():
    """Retirer puis recontrôler ne doit plus rien signaler — sinon chaque
    passage raboterait l'archive d'une couche."""
    table = serie([100, 50, 100, 101, 102])
    propre = qualite.retirer(table, qualite.pics_isoles(table))
    assert qualite.pics_isoles(propre).empty


# --------------------------------------------------------------------
# La suppression en base — le piège qui a réellement mordu
# --------------------------------------------------------------------

def test_effacer_cours_survit_a_l_aller_retour(tmp_path):
    """Nettoyer le seul CSV ne suffit PAS, et l'échec est silencieux.

    `enregistrer` est un INSERT OR REPLACE : une ligne absente du CSV
    reste dans la base, et le premier `exporter` la réécrit dans le CSV.
    La correction disparaît sans message, avec le bon nombre de lignes
    partout sauf là où on regarde.
    """
    base = tmp_path / "essai.db"
    table = serie([100, 50, 100, 101, 102])
    db.enregistrer(table, "cours", base)

    suspects = qualite.pics_isoles(table)
    assert len(suspects) == 1

    # Sans suppression : la base garde le fantôme.
    db.enregistrer(qualite.retirer(table, suspects), "cours", base)
    assert len(db.lire("cours", base)) == len(table)

    assert db.effacer_cours(suspects, base) == 1
    apres = db.lire("cours", base)
    assert len(apres) == len(table) - 1
    assert 50 not in list(apres["cloture"])


def test_effacer_cours_sans_cle_ne_fait_rien(tmp_path):
    base = tmp_path / "essai.db"
    db.enregistrer(serie([100, 101, 102]), "cours", base)
    assert db.effacer_cours(pd.DataFrame(), base) == 0
    assert len(db.lire("cours", base)) == 3


# --------------------------------------------------------------------
# Le désaccord entre les deux sources de dividendes
# --------------------------------------------------------------------

def test_desaccords_signale_le_facteur_deux():
    """Le cas réel : brvm.org annonce 684 pour BOAC 2023, sikafinance 342.

    Un facteur aussi rond désigne une convention qui diffère — montant
    total contre acompte, brut contre net — pas une faute de saisie.
    """
    div = pd.DataFrame([
        {"ticker": "BOAC", "date_detachement": "2024-04-25",
         "montant": 684.0, "exercice": 2023},
    ])
    fonda = pd.DataFrame([
        {"ticker": "BOAC", "date": "2023-12-31",
         "indicateur": "dividende", "valeur": 342.0},
    ])
    e = qualite.desaccords(div, fonda)
    assert len(e) == 1
    assert e.iloc[0]["ecart"] == pytest.approx(1.0)


def test_desaccords_additionne_les_acomptes_avant_de_comparer():
    """Deux versements dans l'exercice contre un total annoncé : c'est le
    versement de l'exercice qui se compare, pas chaque ligne isolée."""
    div = pd.DataFrame([
        {"ticker": "AAAA", "date_detachement": "2024-04-25",
         "montant": 60.0, "exercice": 2023},
        {"ticker": "AAAA", "date_detachement": "2024-10-25",
         "montant": 40.0, "exercice": 2023},
    ])
    fonda = pd.DataFrame([{"ticker": "AAAA", "date": "2023-12-31",
                           "indicateur": "dividende", "valeur": 100.0}])
    assert qualite.desaccords(div, fonda).empty


def test_desaccords_tolere_un_arrondi():
    div = pd.DataFrame([{"ticker": "AAAA", "date_detachement": "2024-04-25",
                         "montant": 101.0, "exercice": 2023}])
    fonda = pd.DataFrame([{"ticker": "AAAA", "date": "2023-12-31",
                           "indicateur": "dividende", "valeur": 100.0}])
    assert qualite.desaccords(div, fonda).empty


def test_desaccords_ignore_ce_qu_une_seule_source_connait():
    """Un exercice absent d'un côté n'est pas un désaccord : c'est une
    absence, et la signaler noierait les vraies divergences."""
    div = pd.DataFrame([{"ticker": "AAAA", "date_detachement": "2018-04-25",
                         "montant": 900.0, "exercice": 2017}])
    fonda = pd.DataFrame([{"ticker": "AAAA", "date": "2023-12-31",
                           "indicateur": "dividende", "valeur": 100.0}])
    assert qualite.desaccords(div, fonda).empty


def test_desaccords_sans_source_rend_un_tableau_aux_bonnes_colonnes():
    vide = qualite.desaccords(pd.DataFrame(), pd.DataFrame())
    assert vide.empty and list(vide.columns) == qualite.COLONNES_SOURCES


# --------------------------------------------------------------------
# Les variations hors de la limite de séance
# --------------------------------------------------------------------

def test_un_mouvement_bride_par_la_limite_n_est_pas_un_depassement():
    """Les cours se cotent en francs entiers : un mouvement plafonné
    arrondit et peut ressortir à 7,52 % sans avoir franchi la limite.
    Les compter noierait les vrais dépassements sous cinq fois leur
    nombre — 411 alertes au lieu de 193 sur l'archive réelle."""
    table = serie([1000.0, 1075.0, 1000.0])   # exactement +7,5 % puis retour
    assert qualite.limites(table).empty


def test_une_vraie_rupture_est_signalee():
    table = serie([1000.0, 500.0, 500.0])
    hors = qualite.limites(table)
    assert len(hors) == 1
    assert hors.iloc[0]["variation"] == pytest.approx(-0.5)


def test_la_saison_des_detachements_est_nommee():
    """Le prix de référence est ajusté du dividende au détachement : une
    baisse de 10 % y est régulière et n'a rien d'une anomalie."""
    dates = pd.bdate_range("2020-06-01", periods=3).strftime("%Y-%m-%d")
    table = pd.DataFrame([
        {"date": d, "ticker": "AAAA", "cloture": c, "volume_titres": 1.0}
        for d, c in zip(dates, [1000.0, 880.0, 880.0])])
    hors = qualite.limites(table)
    assert hors.iloc[0]["cause_probable"].startswith("saison")


def test_un_trou_prime_sur_la_saison():
    """Un mois sans échange explique la variation quelle que soit la
    période : la limite relie deux séances consécutives, pas deux blocs."""
    table = pd.DataFrame([
        {"date": "2020-06-01", "ticker": "AAAA", "cloture": 1000.0,
         "volume_titres": 1.0},
        {"date": "2020-07-15", "ticker": "AAAA", "cloture": 880.0,
         "volume_titres": 1.0},
    ])
    assert qualite.limites(table).iloc[0]["cause_probable"].startswith("séance")


def test_limites_sur_une_archive_vide():
    vide = qualite.limites(pd.DataFrame())
    assert vide.empty and list(vide.columns) == qualite.COLONNES_LIMITES


def test_variante_sources_remplace_la_ou_les_sources_divergent():
    """`desaccords` dit QUE les deux sources divergent ; il ne dit pas ce
    que ça coûte. Cette variante permet de refaire le calcul avec l'autre
    jeu — sans quoi « 43 couples divergent » ne veut rien dire pour qui
    lit un rendement total."""
    div = pd.DataFrame([
        {"ticker": "BOAC", "date_detachement": "2024-04-25",
         "montant": 684.0, "exercice": 2023},
        {"ticker": "AAAA", "date_detachement": "2024-04-25",
         "montant": 100.0, "exercice": 2023},
    ])
    fonda = pd.DataFrame([
        {"ticker": "BOAC", "date": "2023-12-31",
         "indicateur": "dividende", "valeur": 342.0},
        {"ticker": "AAAA", "date": "2023-12-31",
         "indicateur": "dividende", "valeur": 100.0},
    ])
    v = qualite.variante_sources(div, fonda).set_index("ticker")
    assert v.loc["BOAC", "montant"] == 342.0, "le désaccord n'a pas été repris"
    assert v.loc["AAAA", "montant"] == 100.0, "une ligne d'accord a bougé"


def test_variante_sources_met_la_somme_sur_le_premier_detachement():
    """sikafinance donne un montant par exercice sans dire comment il se
    répartit : inventer une seconde date fabriquerait de la donnée. Les
    acomptes suivants passent donc à zéro et disparaissent."""
    div = pd.DataFrame([
        {"ticker": "AAAA", "date_detachement": "2024-04-25",
         "montant": 60.0, "exercice": 2023},
        {"ticker": "AAAA", "date_detachement": "2024-10-25",
         "montant": 60.0, "exercice": 2023},
    ])
    fonda = pd.DataFrame([{"ticker": "AAAA", "date": "2023-12-31",
                           "indicateur": "dividende", "valeur": 50.0}])
    v = qualite.variante_sources(div, fonda)
    assert len(v) == 1
    assert v.iloc[0]["montant"] == 50.0
    assert v.iloc[0]["date_detachement"] == "2024-04-25"


def test_variante_sources_rend_l_original_quand_tout_concorde():
    div = pd.DataFrame([{"ticker": "AAAA", "date_detachement": "2024-04-25",
                         "montant": 100.0, "exercice": 2023}])
    fonda = pd.DataFrame([{"ticker": "AAAA", "date": "2023-12-31",
                           "indicateur": "dividende", "valeur": 100.0}])
    pd.testing.assert_frame_equal(qualite.variante_sources(div, fonda), div)


def _archive(dates: list[str]) -> pd.DataFrame:
    """Une archive minimale : une ligne par séance."""
    return pd.DataFrame([{"date": d, "ticker": "AAAA", "cloture": 100.0}
                         for d in dates])


def test_un_trou_dans_l_archive_se_voit():
    """LE DÉFAUT QUI A COÛTÉ UNE SÉANCE. `brvm veille` regardait la
    dernière date et concluait « l'archive avance » — ce qui était vrai, et
    à côté de la question : le 6 août 2026 manquait entre le 5 et le 7,
    l'ingestion ayant été annulée à mi-course.

    Un retard finit par se combler tout seul ; un trou, jamais. Il doit
    donc se voir, sans quoi il ne se voit plus jamais.
    """
    from brvm.cli import _seances_manquantes

    # mercredi, jeudi manquant, vendredi
    trous = _seances_manquantes(_archive(["2026-08-05", "2026-08-07"]))
    assert trous == ["2026-08-06"]


def test_le_week_end_n_est_pas_un_trou():
    """Sans quoi le contrôle signalerait deux jours par semaine et
    s'apprendrait à s'ignorer avant la fin du premier mois."""
    from brvm.cli import _seances_manquantes

    # vendredi puis lundi : le samedi et le dimanche ne comptent pas.
    assert _seances_manquantes(_archive(["2026-08-07", "2026-08-10"])) == []


def test_le_retard_n_est_pas_un_trou():
    """Un trou est BORNÉ par les séances connues. Au-delà de la dernière,
    ce n'est plus une lacune mais du retard, et c'est l'autre moitié de la
    commande qui le mesure — les compter deux fois ferait dire à la veille
    qu'une archive à jour d'hier est trouée."""
    from brvm.cli import _seances_manquantes

    assert _seances_manquantes(_archive(["2020-01-01", "2020-01-02"])) == []


def test_une_archive_vide_n_a_pas_de_trou():
    """Zéro séance n'est pas une archive trouée : c'est une archive vide,
    et le message qui convient n'est pas le même."""
    from brvm.cli import _seances_manquantes

    assert _seances_manquantes(pd.DataFrame()) == []
