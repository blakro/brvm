"""La persistance : schémas déclarés, fusion non destructrice, aller-retour.

Trois propriétés seulement sont testées ici, et ce sont les trois qui ont
déjà cassé pour de vrai :

1. Réécrire une séance ne la duplique pas. C'est ce qui permet de
   réingérer un jour après avoir corrigé un sélecteur.

2. La fusion se joue COLONNE PAR COLONNE. Une source qui ne connaît que
   la clôture ne doit pas effacer l'OHLC d'une source qui le connaît —
   cette erreur a supprimé 47 lignes d'archive avant d'être vue.

3. L'aller-retour CSV → base → CSV ne change rien. Sans quoi un diff de
   quinze mille lignes rend toute revue impossible et masquerait une
   vraie altération.
"""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from brvm import db  # noqa: E402


def seance(date="2026-07-27", ticker="AAAA", **colonnes) -> pd.DataFrame:
    base = {"date": date, "ticker": ticker, "ouverture": 100.0,
            "haut": 105.0, "bas": 99.0, "cloture": 102.0,
            "volume_titres": 10.0, "volume_fcfa": 1020.0}
    base.update(colonnes)
    return pd.DataFrame([base])


# --------------------------------------------------------------------
# Écriture
# --------------------------------------------------------------------

def test_reecrire_une_seance_ne_la_duplique_pas(tmp_path):
    """La clé est (date, ticker) et l'écriture un INSERT OR REPLACE :
    réingérer le même jour corrige la ligne au lieu de l'ajouter."""
    base = tmp_path / "essai.db"
    db.enregistrer(seance(cloture=100.0), "cours", base)
    db.enregistrer(seance(cloture=110.0), "cours", base)
    lu = db.lire("cours", base)
    assert len(lu) == 1
    assert lu.iloc[0]["cloture"] == 110.0


def test_une_colonne_absente_est_ecrite_a_null(tmp_path):
    """L'appelant n'a pas à connaître le schéma exact : ajouter une
    colonne au scraper ne doit pas casser l'écriture avant migration."""
    base = tmp_path / "essai.db"
    partiel = pd.DataFrame([{"date": "2026-07-27", "ticker": "AAAA",
                             "cloture": 102.0}])
    db.enregistrer(partiel, "cours", base)
    lu = db.lire("cours", base)
    assert lu.iloc[0]["cloture"] == 102.0
    assert pd.isna(lu.iloc[0]["ouverture"])


def test_une_table_inconnue_est_refusee(tmp_path):
    """Plutôt qu'une table créée à la volée, sans clé ni types : une
    colonne vide arrive en TEXT un jour et en REAL le lendemain."""
    with pytest.raises(db.SchemaInconnu):
        db.enregistrer(seance(), "inventee", tmp_path / "essai.db")


def test_un_dataframe_vide_n_ecrit_rien(tmp_path):
    assert db.enregistrer(pd.DataFrame(), "cours", tmp_path / "essai.db") == 0


# --------------------------------------------------------------------
# La fusion — l'erreur qui a effacé 47 lignes
# --------------------------------------------------------------------

def test_la_fusion_se_joue_colonne_par_colonne():
    """brvm.org ne publie pas l'OHLC ; sikafinance oui. Une fusion au
    niveau de la LIGNE laissait la source pauvre écraser la riche, et
    47 lignes d'archive ont disparu avant qu'on le voie."""
    connu = seance(ouverture=100.0, haut=105.0, bas=99.0, cloture=102.0)
    nouveau = seance(ouverture=float("nan"), haut=float("nan"),
                     bas=float("nan"), cloture=103.0)
    fusion, comblees = db.fusionner_cours(connu, nouveau)
    ligne = fusion.iloc[0]
    assert ligne["cloture"] == 102.0, "la valeur connue a été écrasée"
    assert ligne["haut"] == 105.0, "l'OHLC connu a été effacé"
    assert comblees == 0, "aucune case n'était à combler"


def test_la_fusion_complete_les_trous_sans_rien_perdre():
    connu = seance(haut=float("nan"))
    nouveau = seance(haut=107.0)
    fusion, comblees = db.fusionner_cours(connu, nouveau)
    assert fusion.iloc[0]["haut"] == 107.0
    assert comblees == 1, "le comptage des cases comblées ne suit pas"


def test_la_fusion_ajoute_les_seances_inconnues():
    connu = seance(date="2026-07-27")
    nouveau = seance(date="2026-07-28")
    fusion, _ = db.fusionner_cours(connu, nouveau)
    assert len(fusion) == 2


# --------------------------------------------------------------------
# La suppression — la seule du projet
# --------------------------------------------------------------------

def test_effacer_cours_retire_par_cle(tmp_path):
    base = tmp_path / "essai.db"
    db.enregistrer(pd.concat([seance(date="2026-07-27"),
                              seance(date="2026-07-28")]), "cours", base)
    cles = pd.DataFrame([{"date": "2026-07-27", "ticker": "AAAA"}])
    assert db.effacer_cours(cles, base) == 1
    assert list(db.lire("cours", base)["date"]) == ["2026-07-28"]


# --------------------------------------------------------------------
# L'aller-retour
# --------------------------------------------------------------------

def test_l_aller_retour_par_la_base_ne_change_rien(tmp_path, monkeypatch):
    """Un export qui réécrit des lignes inchangées rend toute revue
    impossible : c'est dans un diff de quinze mille lignes qu'une vraie
    altération passerait inaperçue."""
    base = tmp_path / "essai.db"
    archive = tmp_path / "cours.csv"
    monkeypatch.setattr(db, "chemin_archive", lambda table: archive)

    lignes = pd.concat([seance(date=f"2026-07-{j:02d}", cloture=100.0 + j)
                        for j in range(20, 28)], ignore_index=True)
    lignes.to_csv(archive, index=False)

    db.importer("cours", base)
    db.exporter("cours", base)
    premier = archive.read_text()
    db.importer("cours", base)
    db.exporter("cours", base)
    assert archive.read_text() == premier


def test_resume_compte_ce_qui_est_ecrit(tmp_path):
    base = tmp_path / "essai.db"
    db.enregistrer(seance(), "cours", base)
    assert db.resume(base)["cours"] == 1
