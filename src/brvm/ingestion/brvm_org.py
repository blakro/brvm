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
        # La date ne figure ni dans le tableau ni dans un titre : elle est
        # dans un bloc « Dernière mise à jour » posé au-dessus de la vue.
        "date": ["section.block-tools", ".block-tools", ".region-content"],
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

# Mois écrits en toutes lettres — brvm.org date ses pages en français long
# (« Lundi, 27 juillet, 2026 - 12:45 »), jamais en numérique.
MOIS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10,
    "novembre": 11, "decembre": 12,
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


def _en_dataframe(balise) -> pd.DataFrame | None:
    """Un <table> en DataFrame de chaînes, sans aucune conversion.

    Écrit à la main plutôt que confié à `pandas.read_html`, qui devine le
    type des colonnes : il lit « -0,32 » comme l'entier -32, en prenant la
    virgule décimale française pour un séparateur de milliers. Les cours
    BRVM sont aujourd'hui entiers, ce qui masque le problème — mais le jour
    où une colonne porte des décimales, « 245,80 » devient 24580 et le
    contrôle des cours aberrants ne voit rien passer. La conversion est
    faite ensuite, et seulement par `_nombre`.
    """
    entete = [c.get_text(" ", strip=True) for c in balise.select("thead th")]
    lignes_html = balise.select("tbody tr") or balise.find_all("tr")

    if not entete:
        premiere = lignes_html[0] if lignes_html else None
        if premiere is None:
            return None
        entete = [c.get_text(" ", strip=True) for c in premiere.find_all(["th", "td"])]
        lignes_html = lignes_html[1:]

    lignes = []
    for tr in lignes_html:
        cellules = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        # Une ligne dont le nombre de cellules diffère de l'en-tête est
        # une ligne de total, de titre ou de colspan : l'aligner de force
        # décalerait les colonnes.
        if len(cellules) == len(entete) and any(cellules):
            lignes.append(cellules)

    if not entete or not lignes:
        return None
    return pd.DataFrame(lignes, columns=entete, dtype=str)


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
        tableau = _en_dataframe(balise)
        if tableau is not None and not tableau.empty:
            tableaux.append(tableau)
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


def _sans_accents(texte: str) -> str:
    forme = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in forme if not unicodedata.combining(c))


def _date_seance(html: str) -> tuple[str, str | None]:
    """Date et heure du bloc « Dernière mise à jour », au format ISO.

    Jamais de repli sur la date du jour. Le site sert la dernière séance
    cotée, qui n'est pas celle d'aujourd'hui un lundi férié ou avant le
    fixing — et une ligne datée d'un jour non coté fausse tous les
    décalages J → J+1 sans déclencher aucun contrôle.

    Renvoie (date ISO, heure « HH:MM » ou None). L'heure sert à distinguer
    une séance close d'une cotation encore en cours : voir `ingerer_jour`.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Uniquement les blocs déclarés, jamais la page entière. Elle porte
    # plusieurs horodatages — sur la page du 27/07/2026, le bloc de la cote
    # affichait 12:45 et un autre bloc 13:01 — et rien ne garantit que le
    # premier rencontré soit celui de la séance. Chercher partout finit un
    # jour par dater une séance avec la date d'un communiqué.
    zones = []
    for selecteur in SELECTEURS["cote"].get("date", []):
        zones.extend(e.get_text(" ", strip=True) for e in soup.select(selecteur))

    for zone in zones:
        texte = _sans_accents(zone)
        trouve = re.search(
            r"(\d{1,2})\s*,?\s+(" + "|".join(MOIS) + r")\s*,?\s+(\d{4})",
            texte,
            re.IGNORECASE,
        )
        if trouve:
            jour, mois, annee = trouve.group(1), trouve.group(2).lower(), trouve.group(3)
            date = datetime(int(annee), MOIS[mois], int(jour))
        else:
            trouve = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", texte)
            if not trouve:
                continue
            jour, mois, annee = (int(x) for x in trouve.groups())
            date = datetime(annee, mois, jour)

        heure = re.search(r"(\d{1,2}):(\d{2})", texte[trouve.end():])
        return date.strftime("%Y-%m-%d"), (heure.group(0) if heure else None)

    raise SourceIllisible(
        "date de séance introuvable sur la page. Refus d'ingérer : une "
        "date supposée corromprait la série sans être détectable. "
        "Le bloc attendu est « Dernière mise à jour : … » ; "
        "ajustez SELECTEURS['cote']['date']."
    )


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
    morceaux, date, heure, connus = [], None, None, set()
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
        if date is None:
            date, heure = _date_seance(html)
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

    # brvm.org publie le volume en titres, pas en FCFA. Or c'est bien en
    # FCFA que s'exprime le filtre de liquidité (`volume_median_min_fcfa`),
    # et features.liquidite() remplace les manquants par zéro : laisser la
    # colonne vide écarterait silencieusement TOUTES les valeurs du
    # scoring. On reconstitue donc volume × clôture. C'est une
    # approximation — le vrai montant échangé se calcule au cours de
    # chaque transaction, pas au cours de clôture — mais l'ordre de
    # grandeur est juste, et c'est un ordre de grandeur que le seuil teste.
    manque = cote["volume_fcfa"].isna()
    cote.loc[manque, "volume_fcfa"] = (
        cote.loc[manque, "volume_titres"] * cote.loc[manque, "cloture"]
    )

    cote["date"] = date
    # Une valeur non traitée de la séance apparaît avec un volume nul et
    # aucun cours : la garder produirait un faux point de série.
    cote = cote.dropna(subset=["cloture"])
    cote = cote[cote["cloture"] > 0]
    cote = cote[COLONNES_COURS].drop_duplicates(subset=["date", "ticker"])
    cote.attrs["heure_mise_a_jour"] = heure
    return cote


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


def _coherence_variation(tableau: pd.DataFrame, corr: dict[str, str]) -> str | None:
    """La variation publiée se retrouve-t-elle à partir de veille et clôture ?

    Contrôle croisé gratuit : la page publie à la fois les deux cours et
    leur variation. Si `clôture / veille - 1` ne redonne pas la variation
    affichée, c'est que les trois colonnes ne décrivent pas le même
    instant — ce qui arrive quand la page est consultée séance ouverte,
    les colonnes ne se rafraîchissant pas au même rythme.

    Diagnostic seulement, jamais bloquant : la variation n'est pas
    enregistrée, et faire échouer l'ingestion sur elle empêcherait une
    ingestion d'après clôture par ailleurs saine.
    """
    if not {"veille", "variation"} <= set(corr):
        return None

    d = _renommer(tableau, corr)
    for colonne in ("veille", "cloture", "variation"):
        d[colonne] = d[colonne].map(_nombre)
    d = d.dropna(subset=["veille", "cloture", "variation"])
    d = d[d["veille"] > 0]
    if d.empty:
        return None

    ecart = ((d["cloture"] / d["veille"] - 1) * 100 - d["variation"]).abs()
    concordantes = int((ecart < 0.01).sum())
    return f"{concordantes}/{len(d)} lignes où clôture/veille-1 redonne la variation publiée"


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
    if "volume_fcfa" in manquantes and "volume_titres" in corr:
        resultat["volume_fcfa"] = "reconstitué : volume × clôture"
    resultat["lignes"] = len(tableau)

    try:
        resultat["date_seance"], resultat["heure_mise_a_jour"] = _date_seance(html)
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

    coherence = _coherence_variation(tableau, corr)
    if coherence:
        resultat["coherence_variation"] = coherence

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
    """Enregistre la séance publiée. Renvoie le nombre de lignes écrites.

    Refuse d'écrire tant que la séance du jour n'est pas close : avant la
    clôture, la colonne « Cours Clôture » de brvm.org porte le dernier
    cours traité, pas le cours de clôture. L'enregistrer figerait une
    valeur provisoire dans une série que rien ne viendra corriger — le
    cron de 16 h UTC passe bien après, ce garde-fou ne le gêne pas.
    """
    cote = lire_cote()
    date = str(cote["date"].iloc[0])
    heure = cote.attrs.get("heure_mise_a_jour")
    limite = str(charger().get("ingestion", {}).get("heure_cloture_seance", "15:00"))

    aujourdhui = datetime.now().strftime("%Y-%m-%d")
    if date == aujourdhui and heure is not None and heure < limite:
        raise SourceIllisible(
            f"séance du {date} mise à jour à {heure}, avant la clôture "
            f"({limite}) : les cours affichés sont provisoires. Relancez "
            "après la clôture, ou ajustez ingestion.heure_cloture_seance."
        )

    n = db.enregistrer(cote, "cours")
    _journaliser("cote", n, "ok", f"séance du {date} (maj {heure or 'inconnue'})")
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
