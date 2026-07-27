"""Ingestion depuis brvm.org — cote du jour et référentiel des sociétés.

Ce module est fragile par construction : il dépend de la mise en page d'un
site tiers, qui change sans préavis. Toute la fragilité est donc concentrée
dans les deux dictionnaires en tête de fichier, `SELECTEURS` et
`ALIAS_COLONNES`. Quand brvm.org change, c'est le seul endroit à corriger.

Trois partis pris, qui expliquent la forme du code
--------------------------------------------------

1. UN SÉLECTEUR CSS N'EST PAS UNE VÉRITÉ, C'EST UNE HYPOTHÈSE. Plutôt que
   de parier sur une seule classe, on essaie plusieurs candidats puis, si
   aucun ne donne un tableau reconnaissable, on retombe sur une recherche
   structurelle : parmi tous les tableaux de la page, on retient celui dont
   l'en-tête correspond au plus grand nombre de colonnes connues. Un site
   qui renomme ses classes CSS renomme rarement « Symbole » et « Volume »
   le même jour.

2. LES COLONNES SONT RECONNUES PAR LEUR INTITULÉ, PAS PAR LEUR POSITION.
   Se fier à l'ordre des colonnes est le moyen le plus sûr d'écrire des
   volumes dans la colonne des cours le jour où une colonne est insérée.

3. ÉCHEC BRUYANT. Aucune fonction de ce module ne renvoie de données
   partielles en silence. S'il manque une colonne indispensable ou la date
   de séance, on lève `SourceIllisible`. Une table vide est un incident
   visible ; une table à moitié fausse se propage jusqu'au backtest.

Vérifier sans réseau
--------------------
`verifier()` et `lire_cote()` acceptent un chemin de fichier. Quand le
réseau n'est pas disponible là où tourne le code — runner GitHub Actions
bloqué, poste sans accès direct — on enregistre la page ailleurs et on
diagnostique hors ligne :

    curl -sL https://www.brvm.org/fr/cours-actions/0 -o cote.html
    python -c "from brvm.ingestion import brvm_org; print(brvm_org.verifier('cote.html'))"
"""

from __future__ import annotations

import re
import time
import unicodedata
from datetime import datetime
from io import StringIO
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

from .. import db
from ..config import RACINE, charger

# ---------------------------------------------------------------------------
# TOUT CE QUI CASSE QUAND LE SITE CHANGE — 1/2 : où regarder
# ---------------------------------------------------------------------------
# `tableaux` est une liste de candidats essayés dans l'ordre. Le dernier
# recours est la recherche structurelle décrite en tête de fichier : on ne
# la déclare pas ici, elle s'applique automatiquement si aucun candidat ne
# produit un tableau reconnaissable.
SELECTEURS = {
    "cote": {
        "url": "https://www.brvm.org/fr/cours-actions/0",
        "tableaux": [
            "table.views-table",
            "div.view-content table",
            "#block-system-main table",
            "table",
        ],
        # brvm.org pagine ses vues. On s'arrête dès qu'une page n'apporte
        # plus de ticker nouveau, ce plafond n'est qu'un garde-fou contre
        # une pagination circulaire.
        "pages_max": 10,
        "motif_page": "https://www.brvm.org/fr/cours-actions/{page}",
    },
    "societes": {
        "url": "https://www.brvm.org/fr/societes-cotees/0",
        "tableaux": [
            "table.views-table",
            "div.view-content table",
            "#block-system-main table",
            "table",
        ],
        "pages_max": 10,
        "motif_page": "https://www.brvm.org/fr/societes-cotees/{page}",
    },
}

# ---------------------------------------------------------------------------
# TOUT CE QUI CASSE QUAND LE SITE CHANGE — 2/2 : comment nommer les colonnes
# ---------------------------------------------------------------------------
# Clé = nom interne (celui du schéma de la base). Valeur = intitulés
# rencontrés dans l'en-tête du tableau, en minuscules et sans accents ; la
# comparaison est faite sur ces formes normalisées, et un alias correspond
# s'il est contenu dans l'intitulé.
#
# Ordre important : les alias les plus spécifiques d'abord. « cours veille »
# doit être testé avant « cours », sinon la clôture de la veille se retrouve
# enregistrée comme clôture du jour — une erreur d'un jour sur toute la
# série, invisible à l'œil et fatale pour le momentum.
ALIAS_COLONNES = {
    "ticker": ["symbole", "symbol", "ticker", "code isin", "code"],
    "nom": ["nom de la societe", "denomination", "libelle", "societe", "nom"],
    "secteur": ["secteur d activite", "secteur", "branche", "activite"],
    "veille": ["cours veille", "cloture precedente", "cours precedent", "veille"],
    "ouverture": ["cours ouverture", "premier cours", "ouverture"],
    "haut": ["plus haut", "cours le plus haut", "haut"],
    "bas": ["plus bas", "cours le plus bas", "bas"],
    "cloture": ["cours cloture", "dernier cours", "cours du jour", "cloture", "cours"],
    "volume_titres": ["volume de titres", "titres echanges", "quantite", "volume"],
    "volume_fcfa": ["valeur transigee", "capitaux", "montant", "valeur"],
    "variation": ["variation"],
}

# Colonnes sans lesquelles une ligne de cote ne vaut rien. Le reste est un
# bonus : la BRVM ne publie pas systématiquement haut/bas.
REQUISES_COTE = ["ticker", "cloture"]
REQUISES_REFERENTIEL = ["ticker", "nom"]

# Colonnes du schéma `cours`, dans l'ordre attendu par depot.PRECISION.
COLONNES_COURS = [
    "date", "ticker", "ouverture", "haut", "bas",
    "cloture", "volume_titres", "volume_fcfa",
]


class SourceIllisible(RuntimeError):
    """La page a été reçue mais sa structure n'est pas exploitable."""


# --- Normalisation --------------------------------------------------------

def _normaliser(texte: object) -> str:
    """Minuscules, sans accents, sans ponctuation, espaces compactés.

    Les en-têtes de brvm.org mêlent majuscules, accents, espaces insécables
    et parenthèses (« Cours clôture (FCFA) »). Comparer les formes brutes
    reviendrait à réécrire ALIAS_COLONNES à chaque retouche de mise en page.
    """
    s = unicodedata.normalize("NFKD", str(texte))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-zA-Z0-9]+", " ", s).lower()
    return re.sub(r"\s+", " ", s).strip()


def _nombre(valeur: object) -> float:
    """Convertit un nombre au format francophone en flottant.

    brvm.org écrit « 12 345,50 » avec des espaces insécables comme
    séparateur de milliers. `pd.to_numeric` ne sait pas lire cela, et une
    conversion ratée qui renvoie 12.0 au lieu de 12345.50 passerait tous
    les contrôles de cohérence.
    """
    if valeur is None or (isinstance(valeur, float) and pd.isna(valeur)):
        return float("nan")
    s = str(valeur)
    s = s.replace("\xa0", " ").replace(" ", " ")
    s = re.sub(r"[^\d,.\-]", "", s)
    if s in {"", "-", "--"}:
        return float("nan")
    # Format francophone : la virgule est décimale, le point est un
    # séparateur de milliers résiduel.
    s = s.replace(".", "").replace(",", ".") if "," in s else s.replace(" ", "")
    try:
        return float(s)
    except ValueError:
        return float("nan")


# --- Accès réseau ---------------------------------------------------------

def _telecharger(url: str) -> str:
    conf = charger().get("ingestion", {})
    entetes = {
        "User-Agent": conf.get("user_agent", "brvm-conseil/0.1"),
        "Accept-Language": "fr-FR,fr;q=0.9",
    }
    reponse = requests.get(url, headers=entetes, timeout=30)
    reponse.raise_for_status()
    # Le serveur annonce parfois un encodage erroné ; sans cela les noms de
    # sociétés arrivent en mojibake et ne correspondent plus au référentiel.
    if reponse.encoding is None or reponse.encoding.lower() == "iso-8859-1":
        reponse.encoding = reponse.apparent_encoding
    time.sleep(float(conf.get("delai_entre_requetes_s", 1.5)))
    return reponse.text


def _obtenir_html(source: str | Path | None, url: str) -> str:
    """Une page, qu'elle vienne du réseau ou d'un fichier enregistré."""
    if source is None:
        return _telecharger(url)
    chemin = Path(source)
    if not chemin.exists():
        raise SourceIllisible(f"fichier introuvable : {chemin}")
    return chemin.read_text(encoding="utf-8", errors="replace")


# --- Reconnaissance du tableau -------------------------------------------

def _correspondance(entete: list[str]) -> dict[str, str]:
    """Associe chaque colonne du tableau à un nom interne.

    Renvoie {nom_interne: intitulé d'origine}. Une colonne d'origine n'est
    attribuée qu'une fois : sur une page où « Cours veille » et « Cours
    clôture » coexistent, le premier alias qui gagne verrouille la colonne.
    """
    normalises = {colonne: _normaliser(colonne) for colonne in entete}
    trouve: dict[str, str] = {}
    pris: set[str] = set()

    for interne, alias in ALIAS_COLONNES.items():
        for motif in alias:
            for colonne, norme in normalises.items():
                if colonne in pris:
                    continue
                if norme == motif or motif in norme:
                    trouve[interne] = colonne
                    pris.add(colonne)
                    break
            if interne in trouve:
                break
    return trouve


def _tableaux_candidats(html: str, cle: str) -> list[pd.DataFrame]:
    """Tableaux de la page, sélecteurs déclarés d'abord, tous ensuite."""
    soup = BeautifulSoup(html, "html.parser")
    vus: list[str] = []
    tableaux: list[pd.DataFrame] = []

    balises = []
    for selecteur in SELECTEURS[cle]["tableaux"]:
        balises.extend(soup.select(selecteur))
    balises.extend(soup.find_all("table"))  # filet structurel

    for balise in balises:
        brut = str(balise)
        if brut in vus:
            continue
        vus.append(brut)
        try:
            # Analyseur par défaut (lxml) : `flavor="bs4"` imposerait
            # html5lib en dépendance supplémentaire sans rien apporter ici.
            lus = pd.read_html(StringIO(brut))
        except ValueError:
            continue  # balise <table> sans ligne exploitable
        tableaux.extend(t for t in lus if not t.empty)
    return tableaux


def _meilleur_tableau(
    html: str, cle: str, requises: list[str]
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Le tableau dont l'en-tête reconnaît le plus de colonnes connues.

    Le nombre de colonnes reconnues départage mieux que n'importe quel
    sélecteur : les pages brvm.org portent aussi des tableaux de mise en
    page et des encarts d'indices, qui ne reconnaissent presque rien.
    """
    meilleur: tuple[int, pd.DataFrame, dict[str, str]] | None = None

    for tableau in _tableaux_candidats(html, cle):
        colonnes = [str(c) for c in tableau.columns]
        corr = _correspondance(colonnes)
        if not all(champ in corr for champ in requises):
            continue
        note = len(corr)
        if meilleur is None or note > meilleur[0]:
            meilleur = (note, tableau, corr)

    if meilleur is None:
        raise SourceIllisible(
            f"aucun tableau de la page ne porte les colonnes {requises}. "
            "Corrigez ALIAS_COLONNES ou SELECTEURS dans "
            "src/brvm/ingestion/brvm_org.py."
        )
    return meilleur[1], meilleur[2]


def _date_seance(html: str) -> str:
    """Date de la séance affichée sur la page, au format ISO.

    Jamais de repli sur la date du jour. Le site sert la dernière séance
    cotée, qui n'est pas celle d'aujourd'hui un lundi férié ou avant le
    fixing — et une ligne datée d'un jour non coté fausse tous les
    décalages J → J+1 sans déclencher aucun contrôle.
    """
    texte = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    autour = re.search(
        r"(?:seance|séance|cours\s+du|au)\s*(?:du|le)?\s*(\d{1,2})[/-](\d{1,2})[/-](\d{4})",
        texte,
        re.IGNORECASE,
    )
    trouve = autour or re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", texte)
    if not trouve:
        raise SourceIllisible(
            "date de séance introuvable sur la page. Refus d'ingérer : une "
            "date supposée corromprait la série sans être détectable."
        )
    jour, mois, annee = (int(x) for x in trouve.groups())
    return datetime(annee, mois, jour).strftime("%Y-%m-%d")


# --- Lecture --------------------------------------------------------------

def _renommer(tableau: pd.DataFrame, corr: dict[str, str]) -> pd.DataFrame:
    """Ne garde que les colonnes reconnues, sous leur nom interne."""
    return tableau[[corr[k] for k in corr]].rename(
        columns={origine: interne for interne, origine in corr.items()}
    )


def _pages(cle: str, source: str | Path | None):
    """HTML de chaque page de la vue paginée, à la demande.

    Générateur, et non liste : l'appelant s'arrête dès qu'une page
    n'apporte plus de ticker nouveau. Sur une vue non paginée, brvm.org
    sert la même page quel que soit le numéro — sans arrêt anticipé on
    téléchargerait dix fois la même chose, pour rien et sans être poli.
    """
    if source is not None:
        yield _obtenir_html(source, "")
        return

    conf = SELECTEURS[cle]
    for numero in range(int(conf.get("pages_max", 1))):
        url = conf.get("motif_page", conf["url"]).format(page=numero)
        try:
            yield _telecharger(url)
        except requests.HTTPError:
            return  # au-delà de la dernière page, le site renvoie 404


def lire_cote(source: str | Path | None = None) -> pd.DataFrame:
    """Cote du jour, prête pour la table `cours`.

    `source` : chemin d'une page enregistrée, pour travailler hors ligne.
    """
    morceaux, date, connus = [], None, set()
    for html in _pages("cote", source):
        try:
            tableau, corr = _meilleur_tableau(html, "cote", REQUISES_COTE)
        except SourceIllisible:
            # Au-delà de la dernière page, le site sert un tableau vide
            # plutôt qu'un 404. C'est une fin de pagination, pas une
            # panne — mais seulement si une page a déjà été lue.
            if morceaux:
                break
            raise
        date = date or _date_seance(html)
        page = _renommer(tableau, corr)
        nouveaux = set(page["ticker"].astype(str)) - connus
        if not nouveaux:
            break  # page déjà vue : la pagination est épuisée
        connus |= nouveaux
        morceaux.append(page)

    if not morceaux:
        raise SourceIllisible("aucune page de cote récupérée")

    cote = pd.concat(morceaux, ignore_index=True)
    cote["ticker"] = cote["ticker"].astype(str).str.strip().str.upper()
    cote = cote[cote["ticker"].str.fullmatch(r"[A-Z]{2,6}")]

    for colonne in ("ouverture", "haut", "bas", "cloture",
                    "volume_titres", "volume_fcfa"):
        cote[colonne] = (
            cote[colonne].map(_nombre) if colonne in cote.columns else float("nan")
        )

    cote["date"] = date
    # Une valeur non traitée de la séance apparaît avec un volume nul et
    # aucun cours : la garder produirait un faux point de série.
    cote = cote.dropna(subset=["cloture"])
    cote = cote[cote["cloture"] > 0]
    return cote[COLONNES_COURS].drop_duplicates(subset=["date", "ticker"])


def lire_referentiel(source: str | Path | None = None) -> pd.DataFrame:
    """Liste des sociétés cotées : ticker, nom, secteur."""
    morceaux, connus = [], set()
    for html in _pages("societes", source):
        try:
            tableau, corr = _meilleur_tableau(html, "societes", REQUISES_REFERENTIEL)
        except SourceIllisible:
            if morceaux:
                break  # fin de pagination, cf. lire_cote
            raise
        page = _renommer(tableau, corr)
        nouveaux = set(page["ticker"].astype(str)) - connus
        if not nouveaux:
            break
        connus |= nouveaux
        morceaux.append(page)

    if not morceaux:
        raise SourceIllisible("aucune page de référentiel récupérée")

    ref = pd.concat(morceaux, ignore_index=True)
    ref["ticker"] = ref["ticker"].astype(str).str.strip().str.upper()
    ref = ref[ref["ticker"].str.fullmatch(r"[A-Z]{2,6}")]
    ref["nom"] = ref["nom"].astype(str).str.strip()
    if "secteur" not in ref.columns:
        # Sans secteur, scoring.py applique la pondération par défaut. C'est
        # dégradé mais exact ; l'inventer serait pire.
        ref["secteur"] = pd.NA
    return ref[["ticker", "nom", "secteur"]].drop_duplicates(subset=["ticker"])


# --- Interface appelée par cli.py ----------------------------------------

def verifier(source: str | Path | None = None) -> dict:
    """Diagnostic des sélecteurs, sans rien écrire en base.

    Renvoie un dictionnaire à plat : `cli.py` en imprime chaque entrée, et
    c'est ce tableau qui dit quoi corriger dans ALIAS_COLONNES.
    """
    resultat: dict[str, object] = {"url": SELECTEURS["cote"]["url"]}
    if source is not None:
        resultat["source"] = str(source)

    try:
        html = _obtenir_html(source, SELECTEURS["cote"]["url"])
    except Exception as erreur:  # noqa: BLE001 — le motif de l'échec est l'information utile
        resultat["ok"] = False
        resultat["echec"] = f"page inaccessible : {type(erreur).__name__}: {erreur}"
        return resultat

    resultat["octets"] = len(html)
    resultat["tableaux_sur_la_page"] = len(_tableaux_candidats(html, "cote"))

    try:
        tableau, corr = _meilleur_tableau(html, "cote", REQUISES_COTE)
    except SourceIllisible as erreur:
        # Les intitulés réellement présents sont la seule chose utile ici :
        # c'est à partir d'eux qu'on complète ALIAS_COLONNES.
        vus = [
            " | ".join(str(c) for c in t.columns)
            for t in _tableaux_candidats(html, "cote")
        ]
        resultat["ok"] = False
        resultat["echec"] = str(erreur)
        resultat["entetes_rencontres"] = " ;; ".join(vus[:5]) or "aucun tableau"
        return resultat

    manquantes = [c for c in COLONNES_COURS if c not in corr and c != "date"]
    resultat["colonnes_reconnues"] = ", ".join(f"{k} ← « {v} »" for k, v in corr.items())
    resultat["colonnes_absentes"] = ", ".join(manquantes) or "aucune"
    resultat["lignes"] = len(tableau)

    try:
        resultat["date_seance"] = _date_seance(html)
    except SourceIllisible as erreur:
        resultat["ok"] = False
        resultat["echec"] = str(erreur)
        return resultat

    # Le test qui compte : la chaîne complète jusqu'au format attendu par
    # la base. Un en-tête reconnu ne garantit pas des nombres lisibles.
    try:
        cote = lire_cote(source) if source is not None else None
    except SourceIllisible as erreur:
        resultat["ok"] = False
        resultat["echec"] = str(erreur)
        return resultat

    if cote is not None:
        resultat["lignes_exploitables"] = len(cote)
        resultat["exemple"] = ", ".join(
            f"{r.ticker}={r.cloture:g}" for r in cote.head(3).itertuples()
        )
        resultat["ok"] = len(cote) >= 15
        if not resultat["ok"]:
            resultat["echec"] = (
                f"{len(cote)} lignes exploitables seulement (la cote compte "
                "~47 valeurs) — cours illisibles ou pagination incomplète"
            )
    else:
        resultat["ok"] = len(tableau) >= 15
        if not resultat["ok"]:
            resultat["echec"] = f"{len(tableau)} lignes seulement sur la page"

    return resultat


def referentiel() -> pd.DataFrame:
    """Référentiel scrapé. Vide en cas d'échec : cli.py bascule alors sur
    `referentiel_amorce()`."""
    try:
        return lire_referentiel()
    except (SourceIllisible, requests.RequestException) as erreur:
        _journaliser("referentiel", 0, "echec", str(erreur))
        return pd.DataFrame(columns=["ticker", "nom", "secteur"])


def referentiel_amorce() -> pd.DataFrame:
    """Référentiel de secours, lu dans `data/referentiel_amorce.csv`.

    Volontairement lu sur disque et non codé en dur : cette liste a été
    constituée de mémoire et doit être remplacée par la cote officielle.
    Un référentiel figé dans le code ne se corrige pas, il se recopie.
    """
    fichier = RACINE / "data" / "referentiel_amorce.csv"
    if not fichier.exists():
        _journaliser("referentiel_amorce", 0, "echec", f"{fichier} absent")
        return pd.DataFrame(columns=["ticker", "nom", "secteur"])
    return pd.read_csv(fichier)


def ingerer_jour() -> int:
    """Enregistre la séance publiée. Renvoie le nombre de lignes écrites."""
    cote = lire_cote()
    n = db.enregistrer(cote, "cours")
    _journaliser("cote", n, "ok", f"séance du {cote['date'].iloc[0]}")
    return n


def _journaliser(source: str, lignes: int, statut: str, message: str = "") -> None:
    """Trace dans `journal_ingestion`, lu par l'onglet « Données ».

    Jamais bloquant : perdre une ligne de journal ne doit pas faire échouer
    une ingestion par ailleurs réussie.
    """
    entree = pd.DataFrame([{
        "horodatage": datetime.now().isoformat(timespec="seconds"),
        "source": source,
        "lignes": lignes,
        "statut": statut,
        "message": message[:500],
    }])
    try:
        db.enregistrer(entree, "journal_ingestion")
    except Exception:  # noqa: BLE001
        pass
