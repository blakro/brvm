"""Lecture de l'historique sikafinance.

CE QUE CES TESTS COUVRENT, ET CE QU'ILS NE COUVRENT PAS
-------------------------------------------------------
Deux chemins sont testés : l'API JSON, qui est le chemin principal, et le
tableau HTML, gardé au cas où une API non documentée fermerait.

Les VALEURS des fixtures viennent d'une capture réelle de SDSC (mars
2026) ; leur FORME est reconstruite, le service n'étant joignable ni
depuis l'environnement de développement ni depuis les tests. Ces tests
valident donc le lecteur — reconnaissance des champs par leur nom,
conversion des nombres et des dates, ordre chronologique, découpage en
fenêtres, contrôles de qualité — et non la forme réelle des réponses.

C'est une limite réelle, et c'est la raison d'être de `brvm sonder` :
un appel, et deux questions tranchées pour de bon.

Trois contrôles valent d'être relus, parce qu'ils viennent de la donnée
et non d'une précaution générale :

  - la clôture est vérifiée contre la variation annoncée par la source,
    deux colonnes indépendantes qui doivent retomber l'une sur l'autre ;
  - « plus bas » <= clôture <= « plus haut » est violé huit fois sur dix
    dans le HTML. La sonde dira si l'API fait de même ;
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

import json  # noqa: E402

from brvm.ingestion import sikafinance  # noqa: E402
from brvm.ingestion.brvm_org import SourceIllisible  # noqa: E402

DONNEES = RACINE / "tests" / "donnees"
CAPTURE = DONNEES / "sikafinance_sdsc.html"
REPONSE = DONNEES / "sikafinance_sdsc.json"
MENU = DONNEES / "sikafinance_menu.html"


def _table() -> pd.DataFrame:
    return sikafinance.lire_tableau(
        CAPTURE.read_text(encoding="utf-8"), "SDSC")


def _api() -> pd.DataFrame:
    return sikafinance.lire_json(
        json.loads(REPONSE.read_text(encoding="utf-8")), "SDSC")


# --- L'API JSON, chemin principal -----------------------------------------

def test_la_reponse_de_l_api_se_lit_par_le_nom_des_champs():
    """Jamais par leur position : une clé ajoutée en tête décalerait un
    rapatriement entier sans que rien ne le signale."""
    table = _api()
    assert {"date", "ticker", "cloture", "ouverture", "haut", "bas",
            "volume"} <= set(table.columns)
    assert len(table) == 12
    assert table["date"].is_monotonic_increasing
    assert table["date"].iloc[0] == "2026-01-01"
    assert table["cloture"].iloc[0] == 1515.0


def test_une_reponse_vide_ne_leve_pas():
    """Une valeur qui n'a pas coté du trimestre est un cas normal, pas une
    panne : elle doit rendre vide sans interrompre les 46 autres."""
    assert sikafinance.lire_json({"lst": []}, "X").empty
    assert sikafinance.lire_json({}, "X").empty


def test_une_reponse_aux_champs_inconnus_est_refusee():
    """Le silence serait pire : zéro ligne sans explication se confond avec
    une valeur qui n'a pas coté."""
    try:
        sikafinance.lire_json({"lst": [{"machin": 1, "truc": 2}]}, "X")
    except SourceIllisible as erreur:
        assert "Date" in str(erreur)
    else:
        raise AssertionError("des champs inconnus doivent lever")


def test_le_temoin_tranche_ce_que_mesure_le_volume():
    """Le mécanisme qui a évité l'erreur d'un facteur 1 700.

    L'API rend un seul « Volume » ; son ordre de grandeur suggérait des
    francs. Le témoin — une séance dont les deux nombres sont connus par
    ailleurs — a répondu « titres ». Sans lui, le pari le plus naturel
    était le mauvais.
    """
    temoin = pd.DataFrame([{
        "date": sikafinance.TEMOIN["date"], "ticker": "SDSC",
        "cloture": 1700.0, "volume": 11_729.0,
    }])
    assert "volume_titres" in sikafinance.temoin(temoin)


def test_le_temoin_le_dit_quand_il_ne_peut_pas_trancher():
    """Ni l'un ni l'autre : il doit le dire, pas choisir le plus proche."""
    egare = pd.DataFrame([{
        "date": sikafinance.TEMOIN["date"], "ticker": "SDSC",
        "cloture": 1700.0, "volume": 42.0,
    }])
    assert "ne correspond" in sikafinance.temoin(egare)


def test_le_volume_va_dans_la_colonne_que_la_sonde_a_designee():
    """Par défaut des titres — établi, pas supposé. Le paramètre reste
    pour corriger sans toucher au code si le service changeait d'avis, et
    `None` écarte le volume plutôt que de le ranger au hasard."""
    retenu = sikafinance.retenir(_api())
    assert retenu["volume_titres"].iloc[0] == 8286
    assert "volume_fcfa" not in retenu.columns

    force = sikafinance.retenir(_api(), "volume_fcfa")
    assert force["volume_fcfa"].iloc[0] == 8286

    sans = sikafinance.retenir(_api(), None)
    assert "volume_titres" not in sans.columns and "volume" not in sans.columns


def test_l_api_rend_un_ohlc_coherent():
    """Le constat de la sonde, mis sous test : sur les séances réelles
    rendues par l'API, « plus bas » <= clôture <= « plus haut » tient
    partout, là où le HTML le viole huit fois sur dix. C'est ce qui
    autorise ces colonnes à entrer en base."""
    assert sikafinance.ohlc_incoherent(_api()) == []


def test_l_ohlc_du_html_reste_signale_comme_faux():
    """La protection doit rester capable de se déclencher : c'est le
    tableau HTML qui déforme, et un retour à ce chemin ne doit pas faire
    entrer ses colonnes en base sans qu'on le sache."""
    assert len(sikafinance.ohlc_incoherent(_table())) == 8


def test_l_ohlc_entre_en_base():
    """Le schéma `cours` attendait ces colonnes ; elles ne servaient à
    rien tant que la seule source connue les rendait fausses."""
    retenu = sikafinance.retenir(_api())
    for colonne in ("ouverture", "haut", "bas", "cloture"):
        assert colonne in retenu.columns


# --- Le menu des symboles -------------------------------------------------

def test_les_suffixes_pays_se_lisent_dans_le_menu():
    """La BRVM cote des émetteurs de plusieurs pays : SONATEL est
    sénégalaise, ONATEL burkinabè. Supposer « .ci » partout ferait échouer
    ces valeurs-là sans qu'on sache pourquoi."""
    suffixes = sikafinance.lire_symboles(MENU.read_text(encoding="utf-8"))
    assert suffixes["SDSC"] == ".ci"
    assert suffixes["SNTS"] == ".sn"
    assert suffixes["BOAB"] == ".bj"
    assert suffixes["ONTBF"] == ".bf"
    assert sikafinance.symbole("SNTS", suffixes) == "SNTS.sn"


def test_les_indices_ne_sont_pas_pris_pour_des_actions():
    """BRVMC et SIKAAG sont des indices : les demander à l'API
    d'historique des actions ne rendrait rien d'exploitable."""
    suffixes = sikafinance.lire_symboles(MENU.read_text(encoding="utf-8"))
    assert not any(t.startswith(("BRVM", "SIKA")) for t in suffixes)
    assert len(suffixes) == 5


def test_un_menu_absent_est_refuse():
    try:
        sikafinance.lire_symboles("<html><body>rien</body></html>")
    except SourceIllisible as erreur:
        assert "dpShares" in str(erreur)
    else:
        raise AssertionError("un menu absent doit lever")


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


def test_la_variation_ne_part_pas_en_base():
    """Elle a servi à vérifier la clôture ; elle se recalcule à partir
    d'elle. La stocker créerait deux vérités pour un seul fait, et rien ne
    dirait laquelle croire le jour où elles divergeraient."""
    retenu = sikafinance.retenir(_table())
    assert "variation" not in retenu.columns
    assert set(retenu.columns) <= set(sikafinance.RETENUES)


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


def test_aucune_fenetre_ne_depasse_le_pas_admis():
    """La contrainte du service. La dépasser rendrait des réponses
    tronquées sans que rien ne le dise — 89 jours plutôt que « trois mois
    calendaires », qui peut faire 92 jours d'août à octobre."""
    tranches = sikafinance.fenetres("2019-02-15", "2026-07-27")
    for debut, fin in tranches:
        jours = (pd.Timestamp(fin) - pd.Timestamp(debut)).days
        assert 0 <= jours < sikafinance.PAS_JOURS, (debut, fin, jours)


def test_une_periode_courte_tient_en_une_fenetre():
    assert sikafinance.fenetres("2026-01-01", "2026-02-15") == [
        ("2026-01-01", "2026-02-15")]


def test_une_seule_journee_donne_une_seule_fenetre():
    assert sikafinance.fenetres("2026-03-19", "2026-03-19") == [
        ("2026-03-19", "2026-03-19")]


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
    assert sikafinance.symbole("SNTS", {"SNTS": ".sn"}) == "SNTS.sn"


def test_le_volume_generique_ne_mange_pas_les_deux_colonnes_du_html():
    """`_correspondance` attribue chaque colonne une seule fois, dans
    l'ordre d'ALIAS. Le générique « volume » placé avant les spécifiques
    avalait « Volume Titres », et la colonne des titres disparaissait sans
    un mot — le genre de perte qu'on ne remarque qu'une fois la base
    remplie."""
    table = _table()
    assert table["volume_titres"].iloc[1] == 11_729
    assert table["volume_fcfa"].iloc[1] == 20_643_040
    assert "volume" not in table.columns


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
