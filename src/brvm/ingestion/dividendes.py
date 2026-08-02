"""Dividendes et fondamentaux : trois sources, aucune vérifiée d'ici.

POURQUOI CE MODULE COMPTE
-------------------------
Le balayage de `recherche` a montré que les quatre traits de prix ne
battent pas le hasard sur 11,5 ans, et que le seul effet réel — le
retournement à un mois — est mangé huit fois par les frais. Le dividende
est la dernière piste ouverte, et ce n'est pas un lot de consolation : sur
un marché où les rendements dépassent souvent 5 %, un backtest sur cours
nus se trompe de plus que tout ce qu'on cherche à mesurer.

Il débloque aussi trois des quatre modèles sectoriels recommandés pour ce
marché : retour à la moyenne du rendement pour les télécoms et les
services publics, et le rendement comme facteur du score composite.

TROIS SOURCES, TROIS NATURES
----------------------------
1. brvm.org /fr/esv/paiement-de-dividendes — le calendrier officiel des
   paiements. Source primaire, mais probablement limitée à l'exercice en
   cours : un calendrier n'est pas un historique.

2. sikafinance.com /marches/dividendes — la même information, sur un site
   qui archive. C'est de lui qu'on attend la profondeur.

3. abourse.com /histoActionsJour.html — d'une autre nature, et c'est la
   trouvaille : une photographie PAR SÉANCE portant le dividende net, le
   rendement net et le PER de chaque valeur. Ce n'est pas un calendrier
   mais une série de fondamentaux, exactement ce qui manque au score
   composite. Repérée dans le paquet R de Koffi Fredy Sessie ; comme pour
   l'API d'historique, ce qui est repris est un fait sur le site.

CE QUI N'EST PAS VÉRIFIÉ, ET COMMENT ON LE SAURA
------------------------------------------------
Les trois hôtes sont refusés au CONNECT depuis l'environnement de
développement. Le balisage des tableaux est donc INCONNU : ce module lit
par intitulé de colonne et non par position, avec repli structurel, mais
aucune de ces hypothèses n'a rencontré la vraie page.

`sonder` existe pour cela. Il interroge les trois sources, décrit ce qu'il
trouve — tableaux, en-têtes, premières lignes — et n'écrit rien. C'est son
journal qui dira quels sélecteurs corriger, comme la sonde de sikafinance
a corrigé mes deux hypothèses sur l'API d'historique.
"""

from __future__ import annotations

import hashlib
import re
import time
from datetime import date

import pandas as pd
import requests
from bs4 import BeautifulSoup

from ..config import charger
from .brvm_org import (MOIS, SourceIllisible, _en_dataframe, _nombre,
                       _normaliser)

SOURCES = {
    "brvm.org": {
        "url": "https://www.brvm.org/fr/esv/paiement-de-dividendes",
        "methode": "GET",
        "nature": "calendrier",
    },
    "sikafinance": {
        "url": "https://www.sikafinance.com/marches/dividendes",
        "methode": "GET",
        "nature": "calendrier",
    },
    "abourse": {
        "url": "http://www.abourse.com/histoActionsJour.html",
        "methode": "POST",
        "nature": "fondamentaux",
    },
}

# Intitulés attendus, par colonne interne. Plusieurs variantes parce que
# trois sites ne nomment pas la même chose pareil — « Date de détachement »,
# « Ex-date », « Date ex-dividende ».
# Intitulés relevés sur les vraies pages par la sonde du 28/07/2026 :
#
#   brvm.org     Emetteur | Obligation | Action | Exercice comptable |
#                Date de paiement | Date ex-dividende |
#                Montant du dividende net | Avis
#   sikafinance  Date détachement | Nom | Montant | Rendement
#
# « nom » manquait dans la liste des alias du nom : la colonne « Nom » de
# sikafinance ne correspondait à rien, et le tableau était rejeté faute
# d'identifiant. Une omission d'un mot, et la source entière devient
# muette — c'est pour cela que la sonde existe.
ALIAS_DIVIDENDES = {
    "ticker": ("symbole", "ticker", "code"),
    "nom": ("nom", "societe", "valeur", "emetteur", "libelle"),
    "date_detachement": ("detachement", "ex dividende", "ex date", "date ex"),
    "date_paiement": ("paiement", "mise en paiement"),
    "montant": ("montant du dividende", "dividende net", "montant",
                "dividende"),
    "exercice": ("exercice", "annee"),
    "rendement": ("rendement", "yield"),
}

ALIAS_FONDAMENTAUX = {
    "ticker": ("symbole", "ticker", "code"),
    "dividende_net": ("net income", "dividende net", "net"),
    "rendement_net": ("yield net", "rendement net", "rendement"),
    "per": ("per", "price earning"),
}


def _correspondance(entete, alias) -> dict[str, str]:
    """{nom interne: intitulé d'origine}, une origine attribuée une fois."""
    normalises = {c: _normaliser(c) for c in entete}
    trouve: dict[str, str] = {}
    pris: set[str] = set()
    for interne, motifs in alias.items():
        for motif in motifs:
            for origine, norme in normalises.items():
                if origine in pris:
                    continue
                if norme == motif or motif in norme:
                    trouve[interne] = origine
                    pris.add(origine)
                    break
            if interne in trouve:
                break
    return trouve


def tableaux(html: str) -> list[pd.DataFrame]:
    """Tous les tableaux de la page, en chaînes, sans conversion.

    Sans conversion parce que `pandas.read_html` devine le type et lit
    « 245,80 » comme l'entier 24580 en prenant la virgule décimale pour un
    séparateur de milliers. Sur des montants de dividendes, l'erreur reste
    plausible et ne se voit jamais.
    """
    soupe = BeautifulSoup(html, "html.parser")
    trouves = []
    for balise in soupe.find_all("table"):
        table = _en_dataframe(balise)
        if table is not None and not table.empty:
            trouves.append(table)
    return trouves


def lire_historique(html: str) -> pd.DataFrame:
    """Le tableau large de sikafinance : quatre exercices en une page.

    Relevé par la sonde, et c'est la vraie trouvaille de cette source :

        ''            | Div. 2022 | Rend. 2022 | Div. 2023 | Rend. 2023 | …
        BANK OF AFRICA BENIN |  273 |   10,30 % |       353 |    11,87 % | …

    Trente-huit sociétés, quatre exercices, montant ET rendement. Le
    calendrier ne porte que les détachements à venir ; c'est ici qu'est
    l'histoire.

    Rendu en format long — une ligne par (nom, exercice, indicateur) —
    parce qu'il n'y a PAS de date de détachement dans ce tableau, seulement
    un exercice. Le ranger dans `dividendes`, dont la clé est
    (ticker, date_detachement), obligerait à fabriquer une date. Il va
    donc dans `fondamentaux`, dont le format long l'accueille tel quel.
    """
    for table in tableaux(html):
        colonnes = list(table.columns)
        exercices = {}
        for colonne in colonnes:
            norme = _normaliser(colonne)
            annee = "".join(c for c in norme if c.isdigit())
            if len(annee) != 4:
                continue
            if norme.startswith("div"):
                exercices.setdefault(annee, {})["dividende"] = colonne
            elif norme.startswith("rend"):
                exercices.setdefault(annee, {})["rendement"] = colonne
        if not exercices:
            continue

        # La colonne des noms n'a pas d'intitulé sur cette page : c'est la
        # première qui ne porte ni « Div. » ni « Rend. ».
        prises = {c for m in exercices.values() for c in m.values()}
        restantes = [c for c in colonnes if c not in prises]
        if not restantes:
            continue
        colonne_nom = restantes[0]

        lignes = []
        for _, ligne in table.iterrows():
            nom = str(ligne[colonne_nom]).replace("\xa0", " ").strip()
            if not nom or nom.lower() in {"nan", "-"}:
                continue
            for annee, mesures in exercices.items():
                for indicateur, origine in mesures.items():
                    valeur = _nombre(ligne[origine])
                    if pd.notna(valeur):
                        lignes.append({
                            "nom": nom,
                            # L'exercice se clôt au 31 décembre : la date
                            # situe la mesure sans prétendre à un jour de
                            # détachement qui n'est pas publié ici.
                            "date": f"{annee}-12-31",
                            "indicateur": indicateur,
                            "valeur": valeur,
                        })
        if lignes:
            return pd.DataFrame(lignes)

    raise SourceIllisible(
        "aucun tableau d'historique de dividendes : des colonnes « Div. "
        "AAAA » et « Rend. AAAA » sont attendues"
    )


def lire_dividendes(html: str) -> pd.DataFrame:
    """Le calendrier des détachements, en colonnes internes.

    Exige au minimum un identifiant de valeur, une date de détachement et
    un montant : sans les trois, la ligne ne peut pas rejoindre la table
    `dividendes`, dont la clé est (ticker, date_detachement).
    """
    for table in tableaux(html):
        corr = _correspondance(list(table.columns), ALIAS_DIVIDENDES)
        if not {"date_detachement", "montant"} <= set(corr):
            continue
        if "ticker" not in corr and "nom" not in corr:
            continue

        lu = pd.DataFrame({i: table[o] for i, o in corr.items()})
        lu["montant"] = lu["montant"].map(_nombre)
        if "rendement" in lu.columns:
            lu["rendement"] = lu["rendement"].map(_nombre)
        for colonne in ("date_detachement", "date_paiement"):
            if colonne in lu.columns:
                lu[colonne] = lu[colonne].map(_date)
        lu = lu[lu["montant"].notna()]
        if "date_detachement" in lu.columns:
            lu = lu[lu["date_detachement"] != ""]
        if lu.empty:
            continue
        return lu.reset_index(drop=True)

    raise SourceIllisible(
        "aucun tableau de dividendes reconnaissable : une colonne de date "
        "de détachement et une colonne de montant sont attendues, plus un "
        "symbole ou un nom de société"
    )


def lire_fondamentaux(html: str, date: str) -> pd.DataFrame:
    """Dividende net, rendement et PER d'une séance, en format long.

    Format long — une ligne par (ticker, date, indicateur) — parce que la
    table `fondamentaux` l'est : on ne sait pas encore quels indicateurs
    ces sources publient ni sous quel nom, et une table large obligerait à
    migrer le schéma à chaque découverte.
    """
    for table in tableaux(html):
        corr = _correspondance(list(table.columns), ALIAS_FONDAMENTAUX)
        if "ticker" not in corr:
            continue
        mesures = [c for c in ("dividende_net", "rendement_net", "per")
                   if c in corr]
        if not mesures:
            continue

        lignes = []
        for _, ligne in table.iterrows():
            ticker = str(ligne[corr["ticker"]]).strip()
            # Les lignes de séparation sectorielle portent « SECTEUR - … »
            # dans la colonne du symbole : ce ne sont pas des valeurs.
            if not ticker or ticker.upper().startswith("SECTEUR"):
                continue
            for mesure in mesures:
                valeur = _nombre(ligne[corr[mesure]])
                if pd.notna(valeur):
                    lignes.append({"ticker": ticker, "date": date,
                                   "indicateur": mesure, "valeur": valeur})
        if lignes:
            return pd.DataFrame(lignes)

    raise SourceIllisible(
        "aucun tableau de fondamentaux reconnaissable : un symbole et au "
        "moins un indicateur parmi dividende net, rendement, PER sont "
        "attendus"
    )


# Les deux sources nomment les sociétés, elles ne les codent pas :
# « SONATEL SN », « CIE CI », « AFRICA GLOBAL LOGIST ». L'archive, elle,
# est indexée par ticker. Il faut donc apparier, et c'est l'endroit du
# module où une erreur serait la plus coûteuse : attribuer le dividende de
# la BOA Bénin à la BIIC Bénin ne se verrait jamais.
PAYS = {"ci": "cote d ivoire", "sn": "senegal", "bf": "burkina faso",
        "bj": "benin", "ml": "mali", "ne": "niger", "tg": "togo"}
PREFIXE_MINIMUM = 4


def _sans_pays(nom: str) -> str:
    """« SONATEL SN » → « sonatel ». Le suffixe pays n'aide pas à apparier
    et empêche la comparaison par préfixe."""
    norme = _normaliser(nom)
    for code, complet in PAYS.items():
        for suffixe in (f" {code}", f" {complet}"):
            if norme.endswith(suffixe):
                return norme[: -len(suffixe)].strip()
    return norme


# ---------------------------------------------------------------------------
# LES NOMS QUE LE CALENDRIER OFFICIEL EMPLOIE, ET QUE LE RÉFÉRENTIEL IGNORE
# ---------------------------------------------------------------------------
# Le calendrier de brvm.org remonte à 2018 : il porte donc les raisons
# sociales D'ÉPOQUE, et des sigles. Le référentiel, lui, porte les noms
# d'aujourd'hui. Aucune règle de similarité ne fera le rapprochement entre
# « BOLLORE TRANSPORT & LOGISTICS » et « AFRICA GLOBAL LOGISTICS » : ce
# n'est pas une variante d'écriture, c'est un changement de nom.
#
# CE TABLEAU EST UN JUGEMENT, PAS UNE DÉDUCTION. Chaque ligne a été
# vérifiée contre le référentiel du 27/07/2026 ; elles sont écrites ici
# plutôt que devinées par un algorithme parce qu'un dividende attribué à
# la mauvaise société ne se voit jamais.
#
# LES TROIS CAS ABSENTS SONT ABSENTS EXPRÈS :
#   « TOTAL »          — TTLC (Côte d'Ivoire) ou TTLS (Sénégal) ? Le
#                        calendrier écrit les deux ailleurs. Ambigu, donc
#                        refusé.
#   « AIR LIQUIDE CI » — radiée, absente de la cote. Rien à quoi
#                        l'apparier.
#   nom vide           — une ligne d'en-tête captée par le lecteur.
ALIAS_SOCIETES = {
    # Sigles et abréviations
    "lnb": "LNBB",                    # Loterie Nationale du Bénin
    "biic": "BICB",                   # Banque Int. pour l'Industrie et le Commerce
    "sib": "SIBC",                    # Société Ivoirienne de Banque
    "sodeci": "SDCC",                 # SODE Côte d'Ivoire
    "bicici": "BICC",                 # BICI Côte d'Ivoire
    "sgbci": "SGBC",                  # Société Générale Côte d'Ivoire
    "sgci": "SGBC",                   # idem, autre sigle
    "palmci": "PALC",                 # Palm Côte d'Ivoire
    "eti tg": "ETIT",                 # Ecobank Transnational Incorporated Togo
    # Anciennes raisons sociales
    "bollore transport logistics": "SDSC",   # → Africa Global Logistics
    "crown siem ci": "SEMC",                 # → Eviosys Packaging SIEM
    "total ci": "TTLC",                      # → TotalEnergies Marketing CI
    "total senegal": "TTLS",                 # → TotalEnergies Marketing Sénégal
    "total senegal s a": "TTLS",
    # Bank of Africa, désignée par le code pays à deux lettres
    "bank of africa bn": "BOAB",      # Bénin
    "bank of africa ci": "BOAC",      # Côte d'Ivoire
    "bank of africa bf": "BOABF",     # Burkina Faso
    "bank of africa ml": "BOAM",      # Mali
    "bank of africa sn": "BOAS",      # Sénégal
    "bank of africa ng": "BOAN",      # Niger — la cote n'a pas de BOA Nigeria
}


def rapprocher(noms, referentiel: pd.DataFrame) -> tuple[dict, list]:
    """{nom de la source: ticker}, et la liste de ce qui n'a pas été apparié.

    QUATRE RÈGLES, ET LA DERNIÈRE COMPTE AUTANT QUE LES TROIS AUTRES.

    1. `ALIAS_SOCIETES` d'abord : les noms d'époque et les sigles, qu'aucune
       similarité ne peut retrouver.

    2. Un nom qui EST un ticker s'apparie à lui-même. Le calendrier écrit
       « NSBC » là où le référentiel écrit « NSIA BANQUE COTE D'IVOIRE » :
       la source donne parfois le symbole dans la colonne du nom.

    3. On apparie sur le nom débarrassé de son suffixe pays, d'abord à
       l'identique, puis par préfixe — « africa global logist » est un
       préfixe de « africa global logistics ».

    4. DÈS QUE DEUX CANDIDATS CORRESPONDENT, ON REFUSE. Un dividende
       attribué à la mauvaise société ne se verrait jamais : il n'y a
       aucun contrôle en aval capable de le rattraper. Mieux vaut une
       ligne non appariée, qui se voit dans le rapport, qu'une ligne
       appariée à tort, qui ne se voit pas.
    """
    if referentiel is None or referentiel.empty:
        return {}, list(dict.fromkeys(noms))

    # DEUX INDEX, ET L'ORDRE DANS LEQUEL ON LES INTERROGE COMPTE. Retirer
    # le pays des deux côtés d'emblée effaçait ce qui distingue « BANK OF
    # AFRICA BENIN » de ses six sœurs : le nom complet doit donc être
    # essayé en premier, et le nom écourté seulement s'il n'a rien donné.
    complets, ecourtes = {}, {}
    tickers = set()
    for _, ligne in referentiel.iterrows():
        nom, ticker = str(ligne["nom"]), str(ligne["ticker"])
        complets.setdefault(_normaliser(nom), []).append(ticker)
        ecourtes.setdefault(_sans_pays(nom), []).append(ticker)
        tickers.add(ticker.upper())

    trouve, absents = {}, []
    for nom in dict.fromkeys(noms):
        entier, cible = _normaliser(nom), _sans_pays(nom)

        # Un alias déclaré prime, mais seulement s'il désigne une société
        # réellement cotée : une entrée périmée ne doit pas survivre en
        # silence à une radiation.
        alias = ALIAS_SOCIETES.get(entier)
        if alias and alias in tickers:
            trouve[nom] = alias
            continue

        if str(nom).strip().upper() in tickers:
            trouve[nom] = str(nom).strip().upper()
            continue

        candidats = complets.get(entier) or ecourtes.get(cible) or []
        if not candidats and len(cible) >= PREFIXE_MINIMUM:
            # Le préfixe ne sert qu'en dernier recours, et seulement
            # au-delà de quatre caractères : « CIE » préfixe la moitié
            # d'un annuaire.
            candidats = sorted({
                t for index in (complets, ecourtes)
                for reference, tickers_ in index.items()
                if reference.startswith(cible) for t in tickers_
            })
        if len(candidats) == 1:
            trouve[nom] = candidats[0]
        else:
            absents.append(nom)
    return trouve, absents


def _date(valeur: object) -> str:
    """Vers l'ISO. Chaîne vide si illisible — jamais une date inventée.

    LES DEUX SOURCES N'ÉCRIVENT PAS LES DATES PAREIL, et l'oubli d'une
    forme rend une source entière muette. sikafinance publie
    « 27/07/2026 » ; brvm.org publie « 4 septembre 2026 ». Faute de lire
    la seconde, `lire_dividendes` vidait la table de toutes ses lignes,
    puis la rejetait — en accusant les colonnes, qui étaient pourtant
    reconnues. Le message d'échec désignait donc le mauvais coupable, et
    le calendrier officiel — le seul à porter la date de détachement ET
    l'exercice comptable — passait pour illisible depuis le début.
    """
    texte = str(valeur).strip()
    for forme in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y", "%d/%m/%y"):
        try:
            lu = pd.to_datetime(texte, format=forme)
        except (ValueError, TypeError):
            continue
        # `pd.to_datetime("")` NE LÈVE PAS : il rend NaT, dont `.isoformat()`
        # rend la CHAÎNE « NaT ». Elle passait le filtre des dates vides de
        # `lire_dividendes` et serait devenue une clé primaire
        # (ticker, « NaT ») dans l'archive. Le calendrier de brvm.org laisse
        # la date de détachement vide sur près d'une ligne sur deux — la
        # sonde du 31/07/2026 en montre trois sur ses premières lignes.
        if pd.isna(lu):
            return ""
        return lu.date().isoformat()

    # « 4 septembre 2026 », « Lundi, 27 juillet, 2026 ». Le mois est
    # comparé sans accent ni casse, comme partout ailleurs dans le projet.
    trouve = re.search(
        r"(\d{1,2})\s*,?\s+(" + "|".join(MOIS) + r")\s*,?\s+(\d{4})",
        _normaliser(texte),
    )
    if trouve:
        jour, mois, annee = trouve.groups()
        try:
            return date(int(annee), MOIS[mois], int(jour)).isoformat()
        except ValueError:
            return ""
    return ""


# --- Accès réseau ---------------------------------------------------------
#
# Non vérifiée d'ici : les trois hôtes sont refusés au CONNECT depuis
# l'environnement de développement. Réduite au minimum pour cette raison.

def _telecharger(source: str, date: str | None = None) -> str:
    conf = charger().get("ingestion", {})
    reglage = SOURCES[source]
    entetes = {"User-Agent": conf.get("user_agent", "brvm/0.1")}
    delai = int(conf.get("delai_secondes", 30))

    if reglage["methode"] == "POST":
        reponse = requests.post(
            reglage["url"], data={"date": date, "submit": "Valider"},
            headers=entetes, timeout=delai)
    else:
        reponse = requests.get(reglage["url"], headers=entetes, timeout=delai)

    if reponse.status_code in (403, 429):
        raise SourceIllisible(
            f"{reponse.status_code} sur {source} — le service refuse "
            f"l'appel. L'agent « {entetes['User-Agent']} », le rythme, ou "
            "un filtrage réseau en amont."
        )
    reponse.raise_for_status()
    return reponse.text


def sonder(date: str | None = None) -> dict[str, dict]:
    """Interroge les trois sources et décrit ce qu'elles rendent.

    N'écrit rien et ne lève pas : une source injoignable est un fait à
    rapporter, pas une panne à propager. C'est le journal de cette
    fonction qui dira quels sélecteurs corriger — les hypothèses de ce
    module n'ont jamais rencontré les vraies pages.
    """
    rapport = {}
    for source, reglage in SOURCES.items():
        entree = {"url": reglage["url"], "nature": reglage["nature"]}
        try:
            html = _telecharger(source, date)
        except Exception as erreur:  # noqa: BLE001
            rapport[source] = {**entree,
                               "echec": f"{type(erreur).__name__} — {erreur}"}
            continue

        trouves = tableaux(html)
        entree["octets"] = len(html)
        entree["tableaux"] = len(trouves)
        entree["entetes"] = [list(t.columns)[:12] for t in trouves]
        entree["dimensions"] = [t.shape for t in trouves]
        # Toutes les lignes d'exemple, et pas seulement celles des deux
        # premiers tableaux : c'est le troisième qui portait les
        # dividendes sur brvm.org, et il est resté invisible au premier
        # passage de la sonde.
        entree["premieres_lignes"] = [t.head(2).to_dict("records")
                                      for t in trouves]
        # La correspondance trouvée par tableau, pour que le journal dise
        # quel alias manque au lieu de rendre un refus opaque.
        entree["correspondances"] = [
            _correspondance(list(t.columns), ALIAS_DIVIDENDES)
            for t in trouves
        ]
        try:
            if reglage["nature"] == "calendrier":
                lu = lire_dividendes(html)
                entree["lu"] = f"{len(lu)} dividendes"
                entree["extrait"] = lu.head(5).to_dict("records")
                try:
                    histo = lire_historique(html)
                    entree["historique"] = f"{len(histo)} mesures"
                    entree["extrait_historique"] = histo.head(4).to_dict("records")
                except SourceIllisible:
                    entree["historique"] = "aucun tableau pluriannuel"
            else:
                lu = lire_fondamentaux(html, date or "?")
                entree["lu"] = f"{len(lu)} mesures"
                entree["extrait"] = lu.head(5).to_dict("records")
        except SourceIllisible as erreur:
            entree["lu"] = f"illisible — {erreur}"
        rapport[source] = entree
    return rapport


# --- Sonde des exercices anciens ------------------------------------------
#
# LE PROBLÈME. `lire_historique` rend quatre exercices (2022-2025) parce que
# c'est ce que la page de sikafinance affiche. Quatre exercices donnent trois
# transitions annuelles : de quoi établir que le dividende persiste
# (Spearman +0,83), pas de quoi tester si le RENDEMENT du dividende prédit
# les cours — cela demanderait des périodes disjointes en nombre, et trois
# n'en font pas un échantillon.
#
# CE QUI SUIT N'EST QU'UNE LISTE D'HYPOTHÈSES. Aucune n'a été vérifiée : les
# trois hôtes sont refusés au CONNECT depuis l'environnement de
# développement. C'est le journal de l'action GitHub qui dira laquelle
# existe, et les sélecteurs se corrigeront sur ce qu'elle aura montré — pas
# l'inverse.

PISTES_HISTORIQUE = [
    {
        # OÙ S'ARRÊTE VRAIMENT LE CALENDRIER ? La collecte du 01/08/2026
        # a parcouru 44 pages puis s'est arrêtée sur une empreinte déjà
        # vue, et le plus ancien détachement lu date du 24/04/2016. Deux
        # lectures possibles : le calendrier commence en 2016, ou le site
        # resert sa dernière page au-delà d'un rang. Les pages 40 à 52
        # tranchent — si les empreintes se répètent à partir d'un rang
        # fixe, c'est la seconde.
        "nom": "brvm.org — la fin de la pagination",
        "url": "https://www.brvm.org/fr/esv/paiement-de-dividendes?page={n}",
        "parametres": [{"n": n} for n in range(40, 53)],
    },
    {
        # LA FICHE SOCIÉTÉ DE SIKAFINANCE. Le tableau large du site donne
        # quatre exercices pour toutes les valeurs ; une fiche par valeur
        # en donne peut-être davantage pour une seule. Trois orthographes
        # d'URL, aucune vérifiée — la page d'historique se sert en
        # « /marches/historiques/SDSC.ci », la cotation peut-être ailleurs.
        "nom": "sikafinance — fiche société",
        # ÉTABLI PAR LA SONDE DU 01/08/2026 : « /marches/societe/TICKER »
        # existe et rend un tableau 7 × 6 dont les colonnes sont des
        # années. Reste à savoir ce que portent ses LIGNES — le tableau
        # est transposé, et l'en-tête seul n'en dit rien.
        "url": "https://www.sikafinance.com/marches/societe/{t}.ci",
        "parametres": [{"t": t} for t in ("SDSC", "SNTS", "BOAC")],
    },
]


def _empreinte(html: str) -> str:
    """Empreinte du CONTENU des tableaux, pas de la page.

    DEUX FAÇONS DE SE TROMPER, RENCONTRÉES TOUTES LES DEUX AU PREMIER
    PASSAGE. Comparer les octets de la page fait passer pour différentes
    deux réponses qui ne diffèrent que par un horodatage ou un encart. Et
    se fier à ce qu'un lecteur a réussi à extraire rend aveugle dès que ce
    lecteur échoue : les six pages du calendrier de brvm.org ont été
    déclarées identiques alors que leurs tailles différaient toutes, parce
    que `lire_dividendes` échouait sur chacune et que la clé de comparaison
    valait « rien » des deux côtés.

    L'empreinte porte donc sur les cellules des tableaux, seule chose qui
    dise si la page apporte des données nouvelles.
    """
    cellules = []
    for table in tableaux(html):
        cellules.append("|".join(str(c) for c in table.columns))
        for ligne in table.itertuples(index=False, name=None):
            cellules.append("|".join(str(c) for c in ligne))
    return hashlib.sha256("\n".join(cellules).encode()).hexdigest()[:16]


def _annees_vues(html: str) -> list[str]:
    """Les exercices que porte réellement la page, lus dans les en-têtes.

    C'est la seule mesure qui compte pour trancher une piste : une page qui
    répond 200 avec les mêmes quatre années que la page par défaut n'a rien
    apporté, quel que soit son poids en octets.
    """
    annees = set()
    for table in tableaux(html):
        for colonne in table.columns:
            norme = _normaliser(colonne)
            chiffres = "".join(c for c in norme if c.isdigit())
            if len(chiffres) == 4 and (norme.startswith("div")
                                       or norme.startswith("rend")):
                annees.add(chiffres)
    return sorted(annees)


def sonder_historique() -> list[dict]:
    """Essaie les pistes vers les exercices anciens. N'écrit rien, ne lève pas.

    Rend une ligne par tentative : ce qu'on a demandé, ce qui est revenu, et
    surtout les exercices que la page porte. Une piste ne vaut que si elle
    montre des années que la page par défaut n'a pas.
    """
    conf = charger().get("ingestion", {})
    entetes = {"User-Agent": conf.get("user_agent", "brvm/0.1")}
    delai = int(conf.get("delai_secondes", 30))
    pause = float(conf.get("delai_entre_requetes_s", 1.5))

    rapport = []
    for piste in PISTES_HISTORIQUE:
        for parametres in piste["parametres"]:
            url = piste["url"].format(**parametres)
            entree = {"piste": piste["nom"], "url": url}
            try:
                reponse = requests.get(url, headers=entetes, timeout=delai)
                entree["code"] = reponse.status_code
                entree["octets"] = len(reponse.text)
                if reponse.ok:
                    trouves = tableaux(reponse.text)
                    entree["tableaux"] = len(trouves)
                    entree["dimensions"] = [t.shape for t in trouves]
                    entree["entetes"] = [list(t.columns)[:14] for t in trouves]
                    # LES INTITULÉS DE LIGNE, PAS SEULEMENT DE COLONNE. La
                    # fiche société de sikafinance est transposée : ses
                    # colonnes sont des années, ses LIGNES sont les
                    # indicateurs. N'imprimer que l'en-tête d'un tableau
                    # ainsi tourné revient à ne rien voir de son contenu.
                    entree["premiere_colonne"] = [
                        [str(v)[:28] for v in t.iloc[:, 0].tolist()[:10]]
                        for t in trouves]
                    entree["exercices"] = _annees_vues(reponse.text)
                    entree["empreinte"] = _empreinte(reponse.text)
                    # Le calendrier ne porte pas de colonnes « Div. AAAA » :
                    # pour lui, l'apport se mesure aux dates lues.
                    try:
                        lu = lire_dividendes(reponse.text)
                        entree["dividendes_lus"] = len(lu)
                        if not lu.empty and "date_detachement" in lu.columns:
                            dates = sorted(d for d in lu["date_detachement"] if d)
                            entree["dates"] = (
                                f"{dates[0]} → {dates[-1]}" if dates else "aucune"
                            )
                            entree["extrait"] = lu.head(3).to_dict("records")
                    except SourceIllisible as erreur:
                        entree["dividendes_lus"] = f"illisible — {erreur}"
            except Exception as erreur:  # noqa: BLE001
                entree["echec"] = f"{type(erreur).__name__} — {erreur}"
            rapport.append(entree)
            time.sleep(pause)
    return rapport


PAGES_MAX = 120

# La pagination du calendrier officiel. Établie par la sonde du 31/07/2026 :
# trente pages, trente empreintes différentes, dix lignes chacune, et la
# page 29 était encore sur l'exercice 2018 — le fond n'était pas atteint.
MOTIF_PAGE = "https://www.brvm.org/fr/esv/paiement-de-dividendes?page={n}"


def pages_calendrier(pages_max: int = PAGES_MAX):
    """Les pages du calendrier officiel, jusqu'au fond. Rend (n, html).

    L'ARRÊT NE SE DÉCIDE PAS SUR UN NOMBRE DE PAGES. brvm.org ne rend pas
    404 sur un paramètre hors bornes — il a déjà été vu servir la cote
    entière pour un identifiant de secteur inconnu. Compter les pages
    reviendrait donc soit à s'arrêter trop tôt, soit à collecter dix fois
    la même dernière page.

    On s'arrête sur une empreinte déjà rencontrée : c'est le seul signal
    qui distingue « il y a une suite » de « le site me resert ce que j'ai
    déjà ». `pages_max` n'est qu'une sécurité contre une pagination
    infinie, pas la condition d'arrêt attendue.
    """
    conf = charger().get("ingestion", {})
    entetes = {"User-Agent": conf.get("user_agent", "brvm/0.1")}
    delai = int(conf.get("delai_secondes", 30))
    pause = float(conf.get("delai_entre_requetes_s", 1.5))

    vues: set[str] = set()
    for n in range(pages_max):
        reponse = requests.get(MOTIF_PAGE.format(n=n), headers=entetes,
                               timeout=delai)
        if not reponse.ok:
            return
        empreinte = _empreinte(reponse.text)
        if empreinte in vues:
            return
        vues.add(empreinte)
        yield n, reponse.text
        time.sleep(pause)


def collecter(referentiel: pd.DataFrame, sources=("sikafinance", "brvm.org"),
              pages_max: int = PAGES_MAX):
    """Calendriers et historique, appariés aux tickers. Rend (div, fonda, rapport).

    Les deux calendriers sont réunis : brvm.org est la source primaire et
    porte l'exercice comptable, sikafinance porte le rendement. Une même
    (société, date de détachement) vue des deux côtés ne compte qu'une fois.

    brvm.org est parcouru page à page. Sa première page ne porte que les
    détachements à venir — dix lignes, l'exercice en cours ; c'est la
    pagination qui donne l'historique, et sans elle le calendrier officiel
    n'apporte rien qu'on n'ait déjà.
    """
    calendriers, mesures, rapport = [], [], {}
    for source in sources:
        if source == "brvm.org":
            lots, pages = [], 0
            try:
                for _, html in pages_calendrier(pages_max):
                    pages += 1
                    try:
                        lots.append(lire_dividendes(html))
                    except SourceIllisible:
                        # Une page sans tableau lisible n'arrête pas le
                        # parcours : la mise en page varie d'une page à
                        # l'autre — la 28 porte une colonne « Date
                        # ex-coupon » que les autres n'ont pas.
                        continue
            except Exception as erreur:  # noqa: BLE001
                rapport[source] = (f"interrompu après {pages} pages — "
                                   f"{type(erreur).__name__} : {erreur}")
            if lots:
                calendriers.append(pd.concat(lots, ignore_index=True))
                rapport.setdefault(
                    source,
                    f"{pages} pages, {len(calendriers[-1])} détachements")
            else:
                rapport.setdefault(source, f"{pages} pages, aucun détachement")
            continue

        try:
            html = _telecharger(source)
        except Exception as erreur:  # noqa: BLE001
            rapport[source] = f"injoignable — {type(erreur).__name__} : {erreur}"
            continue

        detail = []
        try:
            calendriers.append(lire_dividendes(html))
            detail.append(f"{len(calendriers[-1])} détachements")
        except SourceIllisible as erreur:
            detail.append(f"calendrier illisible ({erreur})")
        try:
            mesures.append(lire_historique(html))
            detail.append(f"{len(mesures[-1])} mesures pluriannuelles")
        except SourceIllisible:
            detail.append("pas de tableau pluriannuel")
        rapport[source] = " ; ".join(detail)

    tout = pd.concat(calendriers, ignore_index=True) if calendriers \
        else pd.DataFrame(columns=["nom", "date_detachement", "montant"])
    histo = pd.concat(mesures, ignore_index=True) if mesures \
        else pd.DataFrame(columns=["nom", "date", "indicateur", "valeur"])

    noms = list(tout.get("nom", [])) + list(histo.get("nom", []))
    correspondance, absents = rapprocher(noms, referentiel)
    rapport["non_apparies"] = absents

    for table in (tout, histo):
        if not table.empty and "nom" in table.columns:
            table["ticker"] = table["nom"].map(correspondance)

    div = pd.DataFrame(columns=["ticker", "date_detachement", "montant",
                                "exercice"])
    if not tout.empty:
        garde = tout[tout["ticker"].notna()].copy()
        if "exercice" not in garde.columns:
            garde["exercice"] = pd.NA
        div = (garde[["ticker", "date_detachement", "montant", "exercice"]]
               .drop_duplicates(subset=["ticker", "date_detachement"],
                                keep="first"))

    fonda = pd.DataFrame(columns=["ticker", "date", "indicateur", "valeur"])
    if not histo.empty:
        garde = histo[histo["ticker"].notna()]
        fonda = (garde[["ticker", "date", "indicateur", "valeur"]]
                 .drop_duplicates(subset=["ticker", "date", "indicateur"],
                                  keep="first"))
    return div, fonda, rapport


def fondamentaux(date: str) -> pd.DataFrame:
    """Les fondamentaux d'une séance, prêts pour la table `fondamentaux`."""
    return lire_fondamentaux(_telecharger("abourse", date), date)


# --- Sonde des avis officiels ---------------------------------------------
#
# LE CALENDRIER PORTE UNE COLONNE « Avis » DONT LE TEXTE EST « Télécharger ».
# Le lecteur n'extrait que du texte : l'adresse cachée derrière est donc
# jetée depuis le début. Si elle mène à l'avis publié par la Bourse, ce
# serait la première fois que ce projet confronte une donnée à un DOCUMENT
# PRIMAIRE et non à une seconde source secondaire — de quoi trancher les
# 43 désaccords qui valent douze points de rendement total.
#
# RIEN N'EST ACQUIS. Le témoin de test est une capture synthétique sans
# aucun lien. Que « Télécharger » soit une ancre, que sa cible réponde, et
# que ce soit un PDF, sont trois hypothèses distinctes ; la sonde les
# tranche dans cet ordre et dit laquelle échoue.

MOTIF_CALENDRIER = "https://www.brvm.org/fr/esv/paiement-de-dividendes?page={n}"


def _liens_avis(html: str) -> list[dict]:
    """Les lignes du calendrier portant une ancre, avec son adresse.

    Le texte entier de la ligne est rendu avec le lien : une ancre n'a pas
    d'intitulé de colonne, et l'appariement doit être vérifié par un
    humain plutôt que supposé par un sélecteur.
    """
    soupe = BeautifulSoup(html, "html.parser")
    trouves = []
    for table in soupe.find_all("table"):
        for ligne in table.find_all("tr"):
            ancres = [a for a in ligne.find_all("a") if a.get("href")]
            if not ancres:
                continue
            cellules = [c.get_text(" ", strip=True)
                        for c in ligne.find_all(["td", "th"])]
            # Une ligne de calendrier porte au moins l'émetteur, deux dates
            # et un montant : quatre cellules non vides.
            if sum(1 for c in cellules if c) < 4:
                continue
            trouves.append({"ligne": " | ".join(cellules)[:110],
                            "liens": [a.get("href") for a in ancres]})
    return trouves


def sonder_avis(pages: int = 2) -> dict:
    """Les avis officiels sont-ils atteignables ? N'écrit rien, ne lève pas."""
    conf = charger().get("ingestion", {})
    entetes = {"User-Agent": conf.get("user_agent", "brvm/0.1")}
    delai = int(conf.get("delai_secondes", 30))
    pause = float(conf.get("delai_entre_requetes_s", 1.5))

    rapport: dict = {"pages": [], "avis": []}
    adresses: list[str] = []
    for n in range(pages):
        url = MOTIF_CALENDRIER.format(n=n)
        entree = {"url": url}
        try:
            reponse = requests.get(url, headers=entetes, timeout=delai)
            entree["code"] = reponse.status_code
            if reponse.ok:
                lignes = _liens_avis(reponse.text)
                entree["lignes_avec_lien"] = len(lignes)
                entree["exemples"] = lignes[:3]
                for lien in lignes:
                    adresses.extend(lien["liens"])
        except Exception as erreur:  # noqa: BLE001
            entree["echec"] = f"{type(erreur).__name__} - {erreur}"
        rapport["pages"].append(entree)
        time.sleep(pause)

    # Deux cibles suffisent : si la premiere est un PDF, la seconde dit si
    # c'est la regle ou l'exception.
    for adresse in list(dict.fromkeys(adresses))[:2]:
        complet = (adresse if adresse.startswith("http")
                   else "https://www.brvm.org" + adresse)
        entree = {"url": complet}
        try:
            reponse = requests.get(complet, headers=entetes, timeout=delai)
            entree["code"] = reponse.status_code
            entree["type"] = reponse.headers.get("Content-Type", "?")
            entree["octets"] = len(reponse.content)
            entree["est_pdf"] = reponse.content[:5] == b"%PDF-"
        except Exception as erreur:  # noqa: BLE001
            entree["echec"] = f"{type(erreur).__name__} - {erreur}"
        rapport["avis"].append(entree)
        time.sleep(pause)
    return rapport


# LECTURE DES AVIS — DÉPENDANCE OPTIONNELLE, COMME SCIKIT-LEARN. `pypdf`
# ne sert qu'ici, à confronter un montant à son document officiel. Son
# absence coûte cette vérification et rien d'autre : ni l'ingestion, ni
# l'analyse, ni l'app n'en dépendent.
# `except Exception` ET NON `except ImportError`, ET CE N'EST PAS DE LA
# PARANOÏA. `pypdf` charge `cryptography`, dont l'extension Rust peut
# PANIQUER à l'import quand l'environnement est bancal — c'est arrivé dans
# le conteneur de développement, et une panique n'est pas une ImportError.
# Un garde-fou trop étroit aurait laissé une dépendance facultative
# emporter tout le paquet, exactement ce que l'import optionnel de
# scikit-learn avait été écrit pour empêcher.
try:
    from pypdf import PdfReader

    LECTURE_PDF_DISPONIBLE = True
except BaseException as _erreur:  # noqa: BLE001 — voir ci-dessus
    # ATTRAPER `BaseException` EST NORMALEMENT UNE FAUTE. Ici c'est la
    # seule option correcte : la panique de pyo3 en dérive directement, et
    # un `except Exception` ne la voit pas — vérifié dans le conteneur de
    # développement, où le paquet entier refusait de s'importer à cause
    # d'une dépendance FACULTATIVE. C'est précisément ce que l'import
    # optionnel de scikit-learn avait été écrit pour empêcher.
    #
    # Les deux interruptions qui ne doivent jamais être avalées sont
    # relancées : un Ctrl-C pendant un import reste un Ctrl-C.
    if isinstance(_erreur, (KeyboardInterrupt, SystemExit)):
        raise
    PdfReader = None
    LECTURE_PDF_DISPONIBLE = False


def texte_avis(contenu: bytes, pages: int = 2) -> str:
    """Le texte d'un avis, ou une chaîne vide s'il n'y en a pas.

    UNE CHAÎNE VIDE N'EST PAS UN ÉCHEC MUET, C'EST UN FAIT : les avis
    anciens peuvent être des scans sans couche texte. L'appelant doit
    pouvoir distinguer « rien à lire » de « pas lu », d'où le retour vide
    plutôt qu'une exception.
    """
    if not LECTURE_PDF_DISPONIBLE or contenu[:5] != b"%PDF-":
        return ""
    import io
    try:
        lecteur = PdfReader(io.BytesIO(contenu))
        return "\n".join((page.extract_text() or "")
                          for page in lecteur.pages[:pages])
    except Exception:  # noqa: BLE001 - un PDF malforme est un fait
        return ""


def sonder_texte_avis(combien: int = 2, pages_calendrier: int = 1) -> list[dict]:
    """Vide le texte des premiers avis rencontrés. N'écrit rien.

    ÉTAPE OBLIGÉE AVANT D'ÉCRIRE UN EXTRACTEUR. La formulation d'un avis
    de la Bourse est inconnue : « Montant du dividende net », « dividende
    unitaire », un tableau ? Écrire le motif avant d'avoir vu le document
    reviendrait à deviner, et c'est exactement ce que ce projet s'interdit
    depuis son premier sélecteur.
    """
    conf = charger().get("ingestion", {})
    entetes = {"User-Agent": conf.get("user_agent", "brvm/0.1")}
    delai = int(conf.get("delai_secondes", 30))
    pause = float(conf.get("delai_entre_requetes_s", 1.5))

    adresses = []
    for n in range(pages_calendrier):
        try:
            reponse = requests.get(MOTIF_CALENDRIER.format(n=n),
                                   headers=entetes, timeout=delai)
            if reponse.ok:
                for entree in _liens_avis(reponse.text):
                    for lien in entree["liens"]:
                        adresses.append((entree["ligne"], lien))
        except Exception:  # noqa: BLE001
            pass
        time.sleep(pause)

    rapport = []
    for ligne, adresse in adresses[:combien]:
        complet = (adresse if adresse.startswith("http")
                   else "https://www.brvm.org" + adresse)
        entree = {"ligne": ligne, "url": complet,
                  "lecture_disponible": LECTURE_PDF_DISPONIBLE}
        try:
            reponse = requests.get(complet, headers=entetes, timeout=delai)
            entree["octets"] = len(reponse.content)
            texte = texte_avis(reponse.content)
            entree["caracteres"] = len(texte)
            entree["texte"] = texte[:1600]
        except Exception as erreur:  # noqa: BLE001
            entree["echec"] = f"{type(erreur).__name__} - {erreur}"
        rapport.append(entree)
        time.sleep(pause)
    return rapport

