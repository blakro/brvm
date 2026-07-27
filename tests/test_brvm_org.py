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
# Seconde capture du même jour, prise après la clôture (« Séance fermée »
# affiché, cote horodatée 15:15). Elle est le témoin des comportements qui
# ne se voient pas en séance : ingestion autorisée, et incohérence des
# colonnes du site qui persiste séance close.
PAGE_CLOTURE = RACINE / "tests" / "donnees" / "cote_brvm_20260727_cloture.html"
# La réponse réelle de /fr/societes-cotees/0 : une 404 habillée du thème
# complet, tableaux latéraux compris. C'est elle qui a démasqué l'URL.
PAGE_404 = RACINE / "tests" / "donnees" / "societes_404_20260727.html"
# /fr/emetteurs/societes-cotees : la page des sociétés existe bel et bien,
# mais en fiches et sans symbole boursier. Elle est le témoin de la raison
# pour laquelle le référentiel ne peut pas en venir.
PAGE_FICHES = RACINE / "tests" / "donnees" / "societes_fiches_20260727.html"

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


def test_la_cote_tient_en_une_requete():
    """La cote n'est pas paginée, et le segment final n'est pas un numéro.

    Le piège corrigé le 27/07/2026 : `/fr/cours-actions/{n}` a été pris
    pour une pagination alors que `n` est un identifiant de secteur (194
    « Consommation de Base » … 200 « Télécommunications », 0 valant
    « Toutes »). Boucler dessus interrogeait des vues filtrées au hasard,
    et une vue sectorielle prise pour une page suivante ajouterait à la
    cote du jour un sous-ensemble déjà lu.
    """
    appels = []

    def faux_telechargement(url):
        appels.append(url)
        return PAGE_CLOTURE.read_text(encoding="utf-8", errors="replace")

    with _telechargement(faux_telechargement):
        cote = brvm_org.lire_cote()

    assert appels == ["https://www.brvm.org/fr/cours-actions/0"], appels
    assert len(cote) == 47 and cote["ticker"].nunique() == 47
    assert cote["date"].nunique() == 1


def test_arret_si_une_page_n_apporte_rien_de_neuf():
    """Le garde-fou reste utile si brvm.org se met un jour à paginer.

    On relève `pages_max` à la main : sans l'arrêt sur ticker déjà vu, une
    vue qui sert la même page quel que soit le numéro serait téléchargée
    autant de fois que le plafond l'autorise.
    """
    appels = []

    def faux_telechargement(url):
        appels.append(url)
        return PAGE_CLOTURE.read_text(encoding="utf-8", errors="replace")

    origine = brvm_org.SELECTEURS["cote"]["pages_max"]
    brvm_org.SELECTEURS["cote"]["pages_max"] = 5
    try:
        with _telechargement(faux_telechargement):
            cote = brvm_org.lire_cote()
    finally:
        brvm_org.SELECTEURS["cote"]["pages_max"] = origine

    assert len(appels) == 2, f"{len(appels)} requêtes pour une vue non paginée"
    assert len(cote) == 47


def test_page_de_cloture_ingerable():
    """Séance fermée : l'ingestion doit passer, là où la capture de 12:45
    est refusée. C'est le pendant de `test_refus_pendant_la_seance`."""
    r = brvm_org.verifier(PAGE_CLOTURE)
    assert r["ok"] is True, r.get("echec")
    assert r["date_seance"] == "2026-07-27"
    # 15:15 vient de « Dernière mise à jour » (#block-tools-date-maj), pas
    # de la bannière du site qui affichait 15:25 : deux horodatages
    # cohabitent sur la page et seul le premier date la cote.
    assert r["heure_mise_a_jour"] == "15:15"
    assert r["lignes_exploitables"] == 47

    with _telechargement(lambda url: PAGE_CLOTURE.read_text(encoding="utf-8", errors="replace")):
        assert brvm_org.ingerer_jour() == 47


def test_coherence_variation_reste_partielle_apres_cloture():
    """Le site est incohérent avec lui-même, séance close comprise.

    Documenté pour qu'un futur lecteur ne « corrige » pas les alias en
    croyant à une colonne mal reconnue : sur cette capture, 9 lignes ayant
    toutes échangé ne se réconcilient ni depuis la veille ni depuis
    l'ouverture. Le seuil est un signal de tendance, pas un invariant.
    """
    html = PAGE_CLOTURE.read_text(encoding="utf-8", errors="replace")
    tableau, corr = brvm_org._meilleur_tableau(html, "cote", brvm_org.REQUISES_COTE)
    message = brvm_org._coherence_variation(tableau, corr)
    assert message == "23/47 lignes où clôture/veille-1 redonne la variation publiée"


def test_refus_pendant_la_seance():
    """Séance ouverte, « Cours Clôture » porte le dernier cours traité.
    L'enregistrer figerait un provisoire que rien ne viendrait corriger."""
    page = PAGE.read_text(encoding="utf-8", errors="replace")
    with _telechargement(lambda url: page):
        try:
            brvm_org.ingerer_jour()
        except brvm_org.SourceIllisible as erreur:
            assert "provisoires" in str(erreur)
        else:
            raise AssertionError("l'ingestion aurait dû être refusée à 12:45")


# --- Référentiel ----------------------------------------------------------
#
# La page societes-cotees n'a jamais été observée : l'environnement de
# développement n'atteint pas brvm.org (le proxy de sortie refuse l'hôte).
# Ces tests ne valident donc PAS les sélecteurs de cette page ; ils
# verrouillent ce qui est vérifiable sans elle — la reconnaissance des
# intitulés, l'arrêt de la pagination, et la dégradation quand la page
# n'est pas exploitable. Le jour où une capture de societes-cotees est
# disponible, elle remplace le témoin de la cote dans le premier test.


def test_referentiel_lit_ticker_nom_et_secteur():
    """Le témoin de la cote porte « Symbole » et « Nom » : à défaut de la
    page des sociétés, il exerce toute la chaîne du référentiel."""
    ref = brvm_org.lire_referentiel(PAGE)
    assert list(ref.columns) == ["ticker", "nom", "secteur"]
    assert len(ref) == 47 and ref["ticker"].nunique() == 47
    assert ref["ticker"].str.fullmatch(r"[A-Z]{2,6}").all()
    # Aucune colonne secteur sur ce témoin : le repli doit laisser vide,
    # jamais deviner — scoring.py applique alors la pondération par défaut.
    assert ref["secteur"].isna().all()
    assert ref.set_index("ticker").loc["BICC", "nom"] == "BICI COTE D'IVOIRE"


def test_referentiel_reconnait_les_entetes_plausibles():
    """Le piège attendu : « Code ISIN » capté comme ticker.

    L'ISIN et le symbole cohabitent sur les pages de sociétés. Si l'ISIN
    l'emporte, le référentiel ne se raccorde plus à la cote — aucune ligne
    ne se joint, et le scoring travaille sur un univers vide.
    """
    for entete, attendu in [
        (["Symbole", "Nom de la société", "Secteur d'activité"], "Symbole"),
        (["Code ISIN", "Symbole", "Dénomination sociale"], "Symbole"),
        (["Ticker", "Société", "Branche"], "Ticker"),
    ]:
        corr = brvm_org._correspondance(entete)
        assert all(c in corr for c in brvm_org.REQUISES_REFERENTIEL), entete
        assert corr["ticker"] == attendu, f"{entete} : ticker ← {corr.get('ticker')}"

    # Sans colonne de symbole, mieux vaut échouer que joindre sur le nom.
    corr = brvm_org._correspondance(["Société", "Secteur d'activité"])
    assert "ticker" not in corr


def test_la_page_des_societes_ne_porte_aucun_symbole():
    """Pourquoi le référentiel ne vient pas de /fr/emetteurs/societes-cotees.

    Cette page existe — elle ne renvoie pas 404 — mais rend les sociétés
    en fiches : logo, raison sociale, adresse, téléphone. Aucun symbole,
    donc rien à raccorder à la cote. Le test fige ce constat pour qu'il ne
    soit pas re-tenté à chaque refonte du site : ce n'est pas un problème
    de sélecteur, c'est une donnée absente de la page.
    """
    from bs4 import BeautifulSoup

    html = PAGE_FICHES.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")

    fiches = soup.select(".view-societes .views-row")
    assert len(fiches) == 10, "vue en fiches, 10 par page, paginée en ?page=N"
    contenu = " ".join(str(f) for f in fiches)
    for symbole in ("SNTS", "BOAB", "ABJC", "SGBC", "ETIT"):
        assert symbole not in contenu, f"{symbole} trouvé : la page a changé"

    # Et donc : aucun tableau exploitable comme référentiel.
    try:
        brvm_org.lire_referentiel(PAGE_FICHES)
    except brvm_org.SourceIllisible as erreur:
        assert "ticker" in str(erreur)
    else:
        raise AssertionError("une vue en fiches a produit un référentiel")


def test_referentiel_interroge_la_cote():
    """Le référentiel se lit sur la cote, seule page à publier les symboles.

    `/fr/societes-cotees/0` — l'URL d'origine — renvoie une 404, et la vraie
    page des sociétés n'a pas de symboles. L'une comme l'autre laissaient
    `referentiel()` rendre un tableau vide en silence, et cli.py rester
    indéfiniment sur `referentiel_amorce()` sans que rien n'alerte.
    """
    appels = []

    def faux_telechargement(url):
        appels.append(url)
        return PAGE_CLOTURE.read_text(encoding="utf-8", errors="replace")

    with _telechargement(faux_telechargement):
        ref = brvm_org.lire_referentiel()

    assert appels == ["https://www.brvm.org/fr/cours-actions/0"], appels
    assert len(ref) == 47 and ref["ticker"].nunique() == 47
    assert ref["nom"].str.len().gt(0).all()


def test_une_404_ne_produit_jamais_de_referentiel():
    """Le cas subtil : la 404 de brvm.org n'est pas une page vide.

    Elle sert le thème complet, bandeau de séance et blocs latéraux
    compris — donc trois tableaux (top 5, flop 5, activités du marché) que
    le filet structurel voit passer. Aucun ne porte de colonne de symbole
    ni de nom, et c'est la seule chose qui l'empêche d'être pris pour un
    référentiel de deux sociétés nommées « Top 5 » et « Flop 5 ».
    """
    assert PAGE_404.exists()
    try:
        brvm_org.lire_referentiel(PAGE_404)
    except brvm_org.SourceIllisible as erreur:
        assert "ticker" in str(erreur) and "nom" in str(erreur)
    else:
        raise AssertionError("une page 404 a produit un référentiel")

    assert brvm_org.verifier(PAGE_404)["ok"] is False


def test_referentiel_degrade_sans_planter():
    """Page illisible : `referentiel()` doit rendre un tableau vide, pas
    lever — c'est ce qui laisse cli.py basculer sur `referentiel_amorce()`."""
    with _telechargement(lambda url: "<html><body><ul><li>SONATEL</li></ul></body></html>"):
        ref = brvm_org.referentiel()
    assert ref.empty and list(ref.columns) == ["ticker", "nom", "secteur"]


# --- Outils communs -------------------------------------------------------


class _telechargement:
    """Remplace `_telecharger` le temps d'un test, et le remet en place.

    Un patch laissé en place fuit sur les tests suivants et les fait
    dépendre de leur ordre d'exécution.
    """

    def __init__(self, remplacant):
        self.remplacant = remplacant

    def __enter__(self):
        self.origine = brvm_org._telecharger
        brvm_org._telecharger = self.remplacant
        return self

    def __exit__(self, *_):
        brvm_org._telecharger = self.origine
        return False


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
