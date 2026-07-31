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


def rapprocher(noms, referentiel: pd.DataFrame) -> tuple[dict, list]:
    """{nom de la source: ticker}, et la liste de ce qui n'a pas été apparié.

    DEUX RÈGLES, ET LA SECONDE COMPTE AUTANT QUE LA PREMIÈRE.

    1. On apparie sur le nom débarrassé de son suffixe pays, d'abord à
       l'identique, puis par préfixe — « africa global logist » est un
       préfixe de « africa global logistics ».

    2. DÈS QUE DEUX CANDIDATS CORRESPONDENT, ON REFUSE. Un dividende
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
    for _, ligne in referentiel.iterrows():
        nom, ticker = str(ligne["nom"]), str(ligne["ticker"])
        complets.setdefault(_normaliser(nom), []).append(ticker)
        ecourtes.setdefault(_sans_pays(nom), []).append(ticker)

    trouve, absents = {}, []
    for nom in dict.fromkeys(noms):
        entier, cible = _normaliser(nom), _sans_pays(nom)
        candidats = complets.get(entier) or ecourtes.get(cible) or []
        if not candidats and len(cible) >= PREFIXE_MINIMUM:
            # Le préfixe ne sert qu'en dernier recours, et seulement
            # au-delà de quatre caractères : « CIE » préfixe la moitié
            # d'un annuaire.
            candidats = sorted({
                t for index in (complets, ecourtes)
                for reference, tickers in index.items()
                if reference.startswith(cible) for t in tickers
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
            return pd.to_datetime(texte, format=forme).date().isoformat()
        except (ValueError, TypeError):
            continue

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
        "nom": "brvm.org — calendrier paginé",
        # La piste la plus prometteuse ET la plus utile : le calendrier
        # officiel porte « Date ex-dividende » et « Montant du dividende
        # net ». S'il remonte, on obtient de vraies dates de détachement,
        # strictement mieux que l'exercice seul de sikafinance — le
        # backtest total-return répartit aujourd'hui le dividende sur
        # l'exercice faute de savoir quand il tombe.
        # ÉTABLI PAR LA SONDE DU 31/07/2026 : la pagination fonctionne. Les
        # six pages essayées ont rendu six contenus différents, dix lignes
        # chacune, avec « Exercice comptable », « Date ex-dividende » et
        # « Montant du dividende net ». Reste à savoir jusqu'où elle
        # remonte — d'où la plage élargie.
        "url": "https://www.brvm.org/fr/esv/paiement-de-dividendes?page={n}",
        "parametres": [{"n": n} for n in range(0, 30)],
    },
    {
        # TÉMOIN NÉGATIF, GARDÉ EXPRÈS. La sonde du 31/07/2026 a montré que
        # sikafinance ignore le paramètre : six orthographes, six réponses
        # de 49 155 octets au dernier octet près, toujours 2022-2025. Cette
        # piste ne sert plus à chercher — elle sert à vérifier que le
        # verdict sait encore dire « identique ». Un contrôle qui ne répond
        # jamais « rien de neuf » ne prouve rien quand il dit le contraire.
        "nom": "sikafinance — paramètre d'exercice (témoin négatif)",
        "url": "https://www.sikafinance.com/marches/dividendes?annee={a}",
        "parametres": [{"a": a} for a in (2015, 2018)],
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


def collecter(referentiel: pd.DataFrame, sources=("sikafinance", "brvm.org")):
    """Calendriers et historique, appariés aux tickers. Rend (div, fonda, rapport).

    Les deux calendriers sont réunis : brvm.org est la source primaire et
    porte l'exercice comptable, sikafinance porte le rendement. Une même
    (société, date de détachement) vue des deux côtés ne compte qu'une fois.
    """
    calendriers, mesures, rapport = [], [], {}
    for source in sources:
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
