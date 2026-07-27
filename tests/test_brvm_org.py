"""Non-régression du scraper brvm.org, hors ligne.

Le témoin est une capture réelle de https://www.brvm.org/fr/cours-actions/0
prise le 27/07/2026 à 12:45, pendant la séance. Tester contre un fichier
plutôt que contre le site vivant tient à deux contraintes du projet :
GitHub Actions n'atteint pas toujours brvm.org depuis ses adresses de
centre de données, et un test qui dépend du réseau échoue pour des raisons
qui n'ont rien à voir avec le code qu'il prétend vérifier.

Ce que ces tests protègent, ce sont les erreurs déjà commises une fois :
une colonne lue à la place d'une autre, un nombre francophone converti de
travers, une date supposée quand la page n'en donne pas.

    python tests/test_brvm_org.py     # sans dépendance
    pytest tests/test_brvm_org.py     # si pytest est présent
"""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from brvm.ingestion import brvm_org  # noqa: E402

PAGE = RACINE / "tests" / "donnees" / "cote_brvm_20260727.html"

# Relevé à la main dans le HTML du témoin. Ordre des colonnes de la page :
# Symbole, Nom, Volume, Cours veille, Cours Ouverture, Cours Clôture.
# Le volume précède les cours — un analyseur qui se fierait à la position
# des colonnes plutôt qu'à leur intitulé écrirait 895 dans « ouverture ».
ATTENDU = {
    "ABJC": {"ouverture": 3150.0, "cloture": 3135.0, "volume_titres": 895.0},
    "BICB": {"ouverture": 8185.0, "cloture": 7900.0, "volume_titres": 16840.0},
    "BICC": {"ouverture": 28305.0, "cloture": 28700.0, "volume_titres": 768.0},
}


def test_diagnostic_passe_sur_la_page_reelle():
    r = brvm_org.verifier(PAGE)
    assert r["ok"] is True, r.get("echec")
    assert r["lignes"] == 47
    assert r["lignes_exploitables"] == 47
    assert r["date_seance"] == "2026-07-27"
    assert r["heure_mise_a_jour"] == "12:45"


def test_les_colonnes_ne_sont_pas_permutees():
    """Le piège n°1 : « Cours veille » capté par l'alias de la clôture.

    L'erreur décalerait toute la série d'un jour, sans qu'aucun contrôle
    de cohérence ne la voie passer.
    """
    cote = brvm_org.lire_cote(PAGE).set_index("ticker")
    for ticker, valeurs in ATTENDU.items():
        for colonne, attendu in valeurs.items():
            obtenu = cote.loc[ticker, colonne]
            assert obtenu == attendu, f"{ticker}.{colonne} = {obtenu}, attendu {attendu}"


def test_volume_fcfa_reconstitue():
    """brvm.org ne publie pas le volume en FCFA, or le filtre de liquidité
    s'exprime en FCFA et features.liquidite() remplace les manquants par
    zéro : une colonne vide écarterait toutes les valeurs du scoring."""
    cote = brvm_org.lire_cote(PAGE)
    assert cote["volume_fcfa"].notna().all()
    ligne = cote[cote["ticker"] == "ABJC"].iloc[0]
    assert ligne["volume_fcfa"] == ligne["volume_titres"] * ligne["cloture"]


def test_nombres_francophones():
    assert brvm_org._nombre("12 345,50") == 12345.5
    assert brvm_org._nombre("1\xa0234") == 1234.0
    assert brvm_org._nombre("245,80") == 245.8       # jamais 24580
    assert brvm_org._nombre("-0,32") == -0.32        # jamais -32
    for vide in ("-", "", "abc"):
        assert brvm_org._nombre(vide) != brvm_org._nombre(vide)  # NaN


def test_dates_en_toutes_lettres():
    page = PAGE.read_text(encoding="utf-8", errors="replace")
    origine = "Lundi, 27 juillet, 2026 - 12:45"
    for texte, attendu in [
        ("Lundi, 2 février, 2026 - 16:00", "2026-02-02"),
        ("Samedi, 15 août, 2026 - 16:00", "2026-08-15"),
        ("Jeudi, 31 décembre, 2026 - 16:00", "2026-12-31"),
        ("Séance du 27/07/2026 - 16:10", "2026-07-27"),
    ]:
        date, _ = brvm_org._date_seance(page.replace(origine, texte))
        assert date == attendu, f"{texte} lu comme {date}"


def test_echecs_bruyants():
    """Aucune donnée partielle en silence : chaque cas doit se voir."""
    page = PAGE.read_text(encoding="utf-8", errors="replace")

    # Le site renomme ses classes CSS : le filet structurel tient.
    refonte = page.replace('class="table table-hover', 'class="refonte-2027 x')
    assert brvm_org.verifier_texte(refonte)["ok"] is True

    # Le site renomme ses intitulés : échec, en montrant ce qu'il a vu.
    renomme = brvm_org.verifier_texte(page.replace("Symbole", "Mnemo"))
    assert renomme["ok"] is False
    assert "Mnemo" in renomme["entetes_rencontres"]

    # Plus de date de séance : refus, jamais de repli sur aujourd'hui.
    sans_date = brvm_org.verifier_texte(
        page.replace("Lundi, 27 juillet, 2026 - 12:45", "Cours des actions")
    )
    assert sans_date["ok"] is False
    assert "date de séance introuvable" in sans_date["echec"]

    # Page d'erreur du site.
    assert brvm_org.verifier_texte("<html><body><h1>503</h1></body></html>")["ok"] is False


def test_pagination_sans_requete_superflue():
    """La pagination s'arrête à la dernière page utile.

    Deux pièges déjà rencontrés : la vue non paginée sert la même page quel
    que soit le numéro, et la page de fin est un tableau réduit à son
    <thead> — comptée pour une ligne, elle relance une requête pour rien.
    """
    from bs4 import BeautifulSoup

    page = PAGE.read_text(encoding="utf-8", errors="replace")

    def tranche(numero, taille=16):
        soup = BeautifulSoup(page, "html.parser")
        for rang, ligne in enumerate(soup.select("#block-system-main table tbody tr")):
            if not (numero * taille <= rang < (numero + 1) * taille):
                ligne.decompose()
        return str(soup)

    appels = []

    def faux_telechargement(url):
        appels.append(url)
        return tranche(int(url.rstrip("/").rsplit("/", 1)[-1]))

    origine = brvm_org._telecharger
    brvm_org._telecharger = faux_telechargement
    try:
        cote = brvm_org.lire_cote()
    finally:
        brvm_org._telecharger = origine

    assert len(cote) == 47 and cote["ticker"].nunique() == 47
    assert cote["date"].nunique() == 1
    assert len(appels) == 4, f"{len(appels)} requêtes pour 3 pages utiles"


def test_refus_pendant_la_seance():
    """Séance ouverte, « Cours Clôture » porte le dernier cours traité.
    L'enregistrer figerait un provisoire que rien ne viendrait corriger."""
    page = PAGE.read_text(encoding="utf-8", errors="replace")
    brvm_org._telecharger = lambda url: page
    try:
        brvm_org.ingerer_jour()
    except brvm_org.SourceIllisible as erreur:
        assert "provisoires" in str(erreur)
    else:
        raise AssertionError("l'ingestion aurait dû être refusée à 12:45")


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
