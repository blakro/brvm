"""Lecture de l'historique sikafinance.

CE QUE CES TESTS COUVRENT, ET CE QU'ILS NE COUVRENT PAS
-------------------------------------------------------
La fixture reprend les VALEURS d'une capture réelle de SDSC (mars 2026) ;
son BALISAGE est reconstruit, le site n'étant pas joignable depuis
l'environnement de développement. Ces tests valident donc le lecteur — la
reconnaissance des colonnes par leur intitulé, la conversion des nombres
et des dates, l'ordre chronologique, les deux contrôles de qualité — et
non la mise en page du site, qui devra être confrontée à une vraie page
avant le premier rapatriement.

C'est une limite réelle, et c'est aussi la raison pour laquelle la couche
réseau tient en une fonction : quand la mise en page démentira la
fixture, il n'y aura qu'un endroit à corriger.

Les deux contrôles de qualité valent d'être relus, parce qu'ils viennent
de la donnée et non d'une précaution générale :

  - la clôture est vérifiée contre la variation annoncée par la source,
    deux colonnes indépendantes qui doivent retomber l'une sur l'autre ;
  - une séance dont le volume est rigoureusement identique à celui de la
    veille est signalée. Observé les 19 et 20 mars 2026 : la même
    transaction publiée deux fois.

    python tests/test_sikafinance.py
    pytest tests/test_sikafinance.py
"""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

import pandas as pd  # noqa: E402

from brvm.ingestion import sikafinance  # noqa: E402
from brvm.ingestion.brvm_org import SourceIllisible  # noqa: E402

CAPTURE = RACINE / "tests" / "donnees" / "sikafinance_sdsc.html"


def _table() -> pd.DataFrame:
    return sikafinance.lire_tableau(
        CAPTURE.read_text(encoding="utf-8"), "SDSC")


# --- Lecture --------------------------------------------------------------

def test_les_colonnes_sont_reconnues_par_leur_intitule():
    """Jamais par leur position : une colonne insérée en tête décalerait
    tout un rapatriement sans rien déclencher."""
    table = _table()
    attendues = {"date", "ticker", "cloture", "bas", "haut", "ouverture",
                 "volume_titres", "volume_fcfa", "variation"}
    assert attendues <= set(table.columns)
    assert len(table) == 10


def test_les_nombres_a_espaces_ne_perdent_pas_leurs_milliers():
    """« 20 643 040 » lu 20643040, et non 20 : c'est l'erreur qui passe
    tous les contrôles en aval parce qu'elle reste un nombre plausible."""
    table = _table()
    ligne = table[table["date"] == "2026-03-19"].iloc[0]
    assert ligne["volume_fcfa"] == 20_643_040
    assert ligne["volume_titres"] == 11_729
    assert ligne["cloture"] == 1_700


def test_les_dates_passent_en_iso_et_dans_l_ordre():
    """Le site publie du plus récent au plus ancien, en JJ/MM/AAAA. Tout
    le reste du projet suppose l'inverse, et un momentum calculé sur une
    série à l'envers a l'air d'un momentum."""
    table = _table()
    assert table["date"].iloc[0] == "2026-03-18"
    assert table["date"].iloc[-1] == "2026-03-31"
    assert table["date"].is_monotonic_increasing


def test_une_page_sans_tableau_d_historique_est_refusee():
    """Le silence serait pire : un rapatriement qui rend zéro ligne sans
    rien dire se confond avec une valeur qui n'a pas coté."""
    try:
        sikafinance.lire_tableau("<html><body><p>rien</p></body></html>", "X")
    except SourceIllisible as erreur:
        assert "Date" in str(erreur) and "Clôture" in str(erreur)
    else:
        raise AssertionError("une page sans tableau doit lever")


# --- Contrôles de qualité -------------------------------------------------

def test_la_cloture_concorde_avec_la_variation_annoncee():
    """Le contrôle qui autorise à faire confiance à la colonne Clôture."""
    assert sikafinance.coherence(_table()) == []


def test_un_decalage_de_colonnes_est_attrape():
    """La protection ne vaut que si elle se déclenche. On décale les
    clôtures d'un cran : les variations annoncées ne suivent pas."""
    table = _table()
    table["cloture"] = table["cloture"].shift(1).fillna(1000.0)
    ecarts = sikafinance.coherence(table)
    assert len(ecarts) >= 8, ecarts


def test_la_seance_republiee_est_signalee():
    """19 et 20 mars 2026 : 11 729 titres et 20 643 040 FCFA deux jours de
    suite. Sur un marché où une valeur peut ne pas coter, c'est la même
    transaction publiée deux fois — pas deux échanges égaux au franc."""
    signales = sikafinance.seances_repetees(_table())
    assert len(signales) == 1
    assert "2026-03-20" in signales[0]


def test_un_volume_nul_repete_n_est_pas_signale():
    """Deux séances sans échange se suivent tout le temps sur ce marché :
    les signaler noierait le vrai cas sous le bruit."""
    table = pd.DataFrame({
        "date": ["2026-01-05", "2026-01-06", "2026-01-07"],
        "ticker": "X", "cloture": [100.0, 100.0, 100.0],
        "volume_titres": [0.0, 0.0, 0.0], "volume_fcfa": [0.0, 0.0, 0.0],
    })
    assert sikafinance.seances_repetees(table) == []


def test_seules_les_colonnes_verifiables_partent_en_base():
    """« plus bas » dépasse la clôture sur huit séances des dix observées.
    Une colonne dont on ne sait pas ce qu'elle mesure ne s'écrit pas :
    elle serait indiscernable d'une vraie une fois en base."""
    retenu = sikafinance.retenir(_table())
    assert list(retenu.columns) == [
        "date", "ticker", "cloture", "volume_titres", "volume_fcfa"]
    for abandonnee in ("bas", "haut", "ouverture", "variation"):
        assert abandonnee not in retenu.columns


def test_l_incoherence_du_plus_bas_est_bien_dans_la_source():
    """Le constat sur lequel repose la décision ci-dessus, gardé sous test
    pour que personne ne « répare » le tri sans revoir la donnée."""
    table = _table()
    sous_le_bas = table[table["cloture"] < table["bas"]]
    assert len(sous_le_bas) == 8, len(sous_le_bas)


# --- Découpage en fenêtres ------------------------------------------------

def test_les_fenetres_couvrent_sans_trou_ni_recouvrement():
    """Un recouvrement ferait ingérer deux fois la même séance ; un trou
    créerait un vide au milieu de l'historique, invisible jusqu'au jour
    où un momentum tombe dessus."""
    tranches = sikafinance.fenetres("2024-01-01", "2024-12-31")
    assert tranches[0][0] == "2024-01-01"
    assert tranches[-1][1] == "2024-12-31"
    for (_, fin), (debut_suivant, _) in zip(tranches, tranches[1:]):
        veille = pd.Timestamp(debut_suivant) - pd.Timedelta(days=1)
        assert veille.date().isoformat() == fin


def test_aucune_fenetre_ne_depasse_trois_mois():
    """La contrainte du site. La dépasser rendrait des pages tronquées
    sans que rien ne le dise."""
    tranches = sikafinance.fenetres("2019-02-15", "2026-07-27")
    for debut, fin in tranches:
        jours = (pd.Timestamp(fin) - pd.Timestamp(debut)).days
        assert 0 <= jours <= 92, (debut, fin, jours)


def test_une_periode_courte_tient_en_une_fenetre():
    assert sikafinance.fenetres("2026-01-01", "2026-02-15") == [
        ("2026-01-01", "2026-02-15")]


def test_une_periode_a_l_envers_est_refusee():
    try:
        sikafinance.fenetres("2026-06-01", "2026-01-01")
    except ValueError as erreur:
        assert "envers" in str(erreur)
    else:
        raise AssertionError("une période inversée doit lever")


def test_le_29_fevrier_ne_fait_pas_tomber_le_decoupage():
    """Le quantième de départ n'existe pas toujours trois mois plus tard —
    31 janvier, 30 novembre, 29 février."""
    for depart in ("2024-02-29", "2024-01-31", "2023-11-30", "2024-08-31"):
        tranches = sikafinance.fenetres(depart, "2025-06-30")
        assert tranches[0][0] == depart
        assert tranches[-1][1] == "2025-06-30"


def test_le_symbole_suffixe_le_ticker():
    assert sikafinance.symbole("SDSC") == "SDSC.ci"


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
