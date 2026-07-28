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

import pandas as pd
import requests
from bs4 import BeautifulSoup

from ..config import charger
from .brvm_org import SourceIllisible, _en_dataframe, _nombre, _normaliser

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
ALIAS_DIVIDENDES = {
    "ticker": ("symbole", "ticker", "code"),
    "nom": ("societe", "valeur", "emetteur", "libelle"),
    "date_detachement": ("detachement", "ex date", "ex dividende", "date ex"),
    "date_paiement": ("paiement", "mise en paiement", "date de paiement"),
    "montant": ("dividende net", "net par action", "montant", "dividende"),
    "exercice": ("exercice", "annee"),
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


def _date(valeur: object) -> str:
    """Vers l'ISO. Chaîne vide si illisible — jamais une date inventée."""
    texte = str(valeur).strip()
    for forme in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y", "%d/%m/%y"):
        try:
            return pd.to_datetime(texte, format=forme).date().isoformat()
        except (ValueError, TypeError):
            continue
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
        entree["entetes"] = [list(t.columns)[:12] for t in trouves[:4]]
        entree["dimensions"] = [t.shape for t in trouves[:4]]
        entree["premieres_lignes"] = [
            t.head(2).to_dict("records") for t in trouves[:2]
        ]
        try:
            if reglage["nature"] == "calendrier":
                lu = lire_dividendes(html)
                entree["lu"] = f"{len(lu)} dividendes"
                entree["extrait"] = lu.head(5).to_dict("records")
            else:
                lu = lire_fondamentaux(html, date or "?")
                entree["lu"] = f"{len(lu)} mesures"
                entree["extrait"] = lu.head(5).to_dict("records")
        except SourceIllisible as erreur:
            entree["lu"] = f"illisible — {erreur}"
        rapport[source] = entree
    return rapport


def dividendes(source: str = "sikafinance") -> pd.DataFrame:
    """Le calendrier d'une source, prêt pour la table `dividendes`."""
    lu = lire_dividendes(_telecharger(source))
    colonnes = [c for c in ("ticker", "date_detachement", "montant", "exercice")
                if c in lu.columns]
    return lu[colonnes]


def fondamentaux(date: str) -> pd.DataFrame:
    """Les fondamentaux d'une séance, prêts pour la table `fondamentaux`."""
    return lire_fondamentaux(_telecharger("abourse", date), date)
