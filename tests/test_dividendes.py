"""Lecture des dividendes, et l'appariement qui décide de tout.

CE QUI EST TESTÉ, ET POURQUOI DANS CET ORDRE
--------------------------------------------
Les fixtures reprennent les en-têtes et les lignes relevés par la sonde du
28/07/2026 sur les vraies pages (run 30363700815) ; leur balisage est
reconstruit, les hôtes étant refusés depuis l'environnement de
développement. Ce qui est validé est donc la lecture, pas la mise en page.

Trois choses, par ordre de dégât potentiel :

1. L'APPARIEMENT NOM → TICKER. C'est ici qu'une erreur coûterait le plus
   cher : attribuer le dividende de BANK OF AFRICA BENIN à la BIIC Bénin
   ne se verrait jamais, aucun contrôle en aval n'étant capable de le
   rattraper. La règle est donc de REFUSER dès que deux candidats
   correspondent, et les tests vérifient les refus autant que les
   réussites.

2. LE BON TABLEAU. Sur brvm.org, les dividendes sont dans le TROISIÈME
   tableau de la page ; les deux premiers sont les Top 5 et Flop 5 du
   jour. Un lecteur qui prendrait le premier venu lirait des variations de
   cours en croyant lire des dividendes.

3. LE TABLEAU PLURIANNUEL de sikafinance, quatre exercices en une page,
   qui est ce que ces sources ont de plus précieux.

    python tests/test_dividendes.py
    pytest tests/test_dividendes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

import pandas as pd  # noqa: E402

from brvm.ingestion import dividendes  # noqa: E402
from brvm.ingestion.brvm_org import SourceIllisible  # noqa: E402

DONNEES = RACINE / "tests" / "donnees"
SIKA = (DONNEES / "sikafinance_dividendes.html").read_text(encoding="utf-8")
BRVM = (DONNEES / "brvm_dividendes.html").read_text(encoding="utf-8")

REFERENTIEL = pd.DataFrame({
    "ticker": ["CIEC", "SLBC", "SNTS", "SDSC", "BOAB", "BOAC", "BOAS",
               "BICB", "NTLC"],
    "nom": ["CIE COTE D'IVOIRE", "SOLIBRA COTE D'IVOIRE", "SONATEL SENEGAL",
            "AFRICA GLOBAL LOGISTICS COTE D'IVOIRE", "BANK OF AFRICA BENIN",
            "BANK OF AFRICA COTE D'IVOIRE", "BANK OF AFRICA SENEGAL",
            "BANQUE INTERNATIONALE POUR L'INDUSTRIE ET LE COMMERCE DU BENIN",
            "NESTLE COTE D'IVOIRE"],
})


# --- L'appariement --------------------------------------------------------

def test_le_suffixe_pays_n_empeche_pas_l_appariement():
    """« SONATEL SN » et « SONATEL SENEGAL » sont la même société."""
    trouve, absents = dividendes.rapprocher(
        ["SONATEL SN", "SOLIBRA CI", "CIE CI"], REFERENTIEL)
    assert trouve == {"SONATEL SN": "SNTS", "SOLIBRA CI": "SLBC",
                      "CIE CI": "CIEC"}
    assert absents == []


def test_un_nom_tronque_est_retrouve_par_prefixe():
    """La source écrit « AFRICA GLOBAL LOGIST », le référentiel
    « AFRICA GLOBAL LOGISTICS COTE D'IVOIRE »."""
    trouve, _ = dividendes.rapprocher(["AFRICA GLOBAL LOGIST"], REFERENTIEL)
    assert trouve == {"AFRICA GLOBAL LOGIST": "SDSC"}


def test_le_pays_reste_distinctif_quand_il_identifie():
    """Le défaut que ce test verrouille : retirer le pays des deux côtés
    d'emblée effaçait ce qui sépare BANK OF AFRICA BENIN de ses sœurs, et
    le nom pourtant EXACT n'était plus apparié."""
    trouve, absents = dividendes.rapprocher(["BANK OF AFRICA BENIN"],
                                            REFERENTIEL)
    assert trouve == {"BANK OF AFRICA BENIN": "BOAB"}
    assert absents == []


def test_un_nom_ambigu_est_refuse_plutot_qu_attribue():
    """LE TEST LE PLUS IMPORTANT DU MODULE. « BANK OF AFRICA » sans pays
    désigne quatre sociétés. Un dividende attribué à la mauvaise ne se
    verrait jamais — mieux vaut une ligne absente, qui se voit."""
    trouve, absents = dividendes.rapprocher(["BANK OF AFRICA"], REFERENTIEL)
    assert trouve == {}
    assert absents == ["BANK OF AFRICA"]


def test_une_societe_inconnue_est_signalee_pas_devinee():
    trouve, absents = dividendes.rapprocher(["SOCIETE FANTOME SA"],
                                            REFERENTIEL)
    assert trouve == {} and absents == ["SOCIETE FANTOME SA"]


def test_un_referentiel_vide_n_apparie_rien():
    trouve, absents = dividendes.rapprocher(["CIE CI"], pd.DataFrame())
    assert trouve == {} and absents == ["CIE CI"]


# --- Le bon tableau -------------------------------------------------------

def test_les_dividendes_de_brvm_ne_sont_pas_le_top_5():
    """Ils sont dans le troisième tableau ; les deux premiers portent les
    plus fortes hausses et baisses du jour. Prendre le premier tableau
    venu ferait lire des variations de cours."""
    lu = dividendes.lire_dividendes(BRVM)
    assert set(lu["nom"]) == {"CIE CI", "SOLIBRA CI"}
    assert "Top 5" not in lu.columns and "variation" not in lu.columns
    ligne = lu[lu["nom"] == "SOLIBRA CI"].iloc[0]
    assert ligne["montant"] == 2127          # « 2 127 », espace comprise
    assert ligne["date_detachement"] == "2026-07-29"
    assert ligne["date_paiement"] == "2026-08-04"
    assert ligne["exercice"] == "2025"


def test_le_calendrier_de_sikafinance_se_lit_aussi():
    """La colonne s'appelle « Nom » — l'alias manquait, et la source
    entière était muette pour un mot oublié."""
    lu = dividendes.lire_dividendes(SIKA)
    assert len(lu) == 3
    ligne = lu[lu["nom"] == "CIE CI"].iloc[0]
    assert ligne["montant"] == 234.0
    assert ligne["date_detachement"] == "2026-07-27"
    assert abs(ligne["rendement"] - 4.46) < 1e-9


def test_une_page_sans_dividendes_est_refusee():
    """Le silence serait pire : zéro ligne sans explication se confond
    avec une semaine sans détachement."""
    try:
        dividendes.lire_dividendes("<html><body><p>rien</p></body></html>")
    except SourceIllisible as erreur:
        assert "détachement" in str(erreur)
    else:
        raise AssertionError("une page sans dividendes doit lever")


# --- Le tableau pluriannuel -----------------------------------------------

def test_les_quatre_exercices_deviennent_des_lignes():
    """Format long parce qu'il n'y a PAS de date de détachement dans ce
    tableau : le ranger dans `dividendes`, dont la clé porte cette date,
    obligerait à en fabriquer une."""
    lu = dividendes.lire_historique(SIKA)
    boa = lu[lu["nom"] == "BANK OF AFRICA BENIN"]
    assert set(boa["date"]) == {"2022-12-31", "2023-12-31",
                                "2024-12-31", "2025-12-31"}
    assert set(boa["indicateur"]) == {"dividende", "rendement"}
    div_2024 = boa[(boa["date"] == "2024-12-31")
                   & (boa["indicateur"] == "dividende")]
    assert float(div_2024["valeur"].iloc[0]) == 468.0
    rend_2024 = boa[(boa["date"] == "2024-12-31")
                    & (boa["indicateur"] == "rendement")]
    assert abs(float(rend_2024["valeur"].iloc[0]) - 14.72) < 1e-9


def test_un_exercice_sans_dividende_ne_fabrique_pas_de_zero():
    """AFRICA GLOBAL LOGISTICS n'a rien versé en 2025 : la source écrit
    « - ». Un zéro serait une information fausse — « la société n'a pas
    versé » et « on ne sait pas » ne sont pas la même chose."""
    lu = dividendes.lire_historique(SIKA)
    agl = lu[lu["nom"] == "AFRICA GLOBAL LOGIST"]
    assert "2025-12-31" not in set(agl["date"])
    assert len(agl) == 6                     # trois exercices × deux mesures


def test_le_tableau_pluriannuel_manquant_est_refuse():
    try:
        dividendes.lire_historique(BRVM)
    except SourceIllisible as erreur:
        assert "Div." in str(erreur)
    else:
        raise AssertionError("brvm.org n'a pas de tableau pluriannuel")


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
