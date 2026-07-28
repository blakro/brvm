"""Rapatriement de l'historique depuis sikafinance.com.

POURQUOI UNE DEUXIÈME SOURCE
----------------------------
brvm.org publie la cote du jour, pas son passé. L'archive ne pouvait donc
grandir qu'au rythme d'une séance par jour ouvré : le premier classement
tombait vers juillet 2027, le premier backtest vers octobre. sikafinance
publie l'historique séance par séance, ce qui ramène cette attente à la
durée d'un rapatriement.

    https://www.sikafinance.com/marches/historiques/SDSC.ci

CE QUE CETTE SOURCE DONNE, ET CE QU'ON EN GARDE
-----------------------------------------------
Le tableau porte huit colonnes : Date, Clôture, Plus bas, Plus haut,
Ouverture, Volume Titres, Volume FCFA, Variation %. On n'en écrit que
quatre en base, et ce tri n'est pas de la prudence de principe — il vient
d'un contrôle sur dix séances consécutives d'AFRICA GLOBAL LOGISTICS
(SDSC), mars 2026 :

  - LA CLÔTURE EST FIABLE. Sur les neuf transitions vérifiables, la
    variation recalculée depuis la colonne Clôture retombe au centième
    près sur la variation annoncée. Deux colonnes indépendantes qui
    concordent neuf fois de suite ne concordent pas par hasard.

  - PLUS BAS, PLUS HAUT ET OUVERTURE NE LE SONT PAS. Sur huit des dix
    séances, « plus bas » dépasse la clôture — ce qui est impossible par
    définition. L'anomalie ne frappe que les séances de baisse ; les
    séances de hausse sont cohérentes. Aucune règle simple ne relie ces
    colonnes à la clôture de la veille, et une hypothèse inventée depuis
    dix lignes serait invérifiable une fois la base remplie. Elles sont
    donc lues, contrôlées, et NON écrites. Le schéma `cours` a les
    colonnes prêtes le jour où la règle sera comprise.

  - LES SÉANCES SE RÉPÈTENT. Les 19 et 20 mars portent le même volume au
    titre près (11 729 titres, 20 643 040 FCFA) avec des variations
    différentes. Un volume rigoureusement identique deux séances de suite
    n'est pas une coïncidence de marché : c'est la même transaction
    publiée deux fois, sur un marché où une valeur peut ne pas coter. Les
    ingérer telles quelles doublerait le volume et fabriquerait une séance
    qui n'a pas eu lieu. `seances_repetees` les signale.

LA CONTRAINTE DES TROIS MOIS
----------------------------
Le sélecteur de période refuse plus d'un trimestre. Six ans d'historique
pour 47 valeurs font donc un bon millier de requêtes : `fenetres` découpe,
et l'appelant tempère. C'est un travail de rapatriement ponctuel, pas une
ingestion quotidienne — il a sa place dans une action déclenchée à la
main, pas dans le cron.
"""

from __future__ import annotations

import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

from .brvm_org import (SourceIllisible, _en_dataframe, _nombre, _normaliser)
from ..config import charger

URL = "https://www.sikafinance.com/marches/historiques/{symbole}"

# Le symbole du site suffixe le ticker BRVM du pays de cotation. Toutes les
# valeurs observées jusqu'ici sont en « .ci » — y compris, à vérifier au
# premier rapatriement, celles dont l'émetteur est sénégalais ou béninois.
# La correspondance est explicite plutôt que devinée : une exception se
# corrige ici en une ligne, sans toucher au reste.
SUFFIXE_DEFAUT = ".ci"
SUFFIXES: dict[str, str] = {}

# Reconnaissance par l'intitulé, jamais par la position : une colonne
# insérée en tête décalerait tout un rapatriement sans rien déclencher.
ALIAS = {
    "date": ("date",),
    "cloture": ("cloture", "clot"),
    "bas": ("plus bas",),
    "haut": ("plus haut",),
    "ouverture": ("ouverture",),
    "volume_titres": ("volume titres", "titres"),
    "volume_fcfa": ("volume fcfa", "fcfa"),
    "variation": ("variation",),
}

# Ce qui part en base. Le reste est lu pour être contrôlé, puis abandonné.
RETENUES = ["date", "ticker", "cloture", "volume_titres", "volume_fcfa"]

TOLERANCE_VARIATION = 0.02  # points de pourcentage


def symbole(ticker: str) -> str:
    """Ticker BRVM → identifiant sikafinance."""
    return f"{ticker}{SUFFIXES.get(ticker, SUFFIXE_DEFAUT)}"


def fenetres(debut: str | date, fin: str | date,
             mois: int = 3) -> list[tuple[str, str]]:
    """Découpe une période en tranches que le site accepte.

    Les bornes sont incluses et les tranches jointives : une tranche qui
    reprendrait à la date de fin de la précédente ferait ingérer deux fois
    la même séance, et une tranche qui sauterait un jour créerait un trou
    invisible au milieu de l'historique.
    """
    d = _en_date(debut)
    f = _en_date(fin)
    if d > f:
        raise ValueError(f"période à l'envers : {d} → {f}")

    tranches: list[tuple[str, str]] = []
    courant = d
    while courant <= f:
        mois_total = courant.month - 1 + mois
        an = courant.year + mois_total // 12
        mois_fin = mois_total % 12 + 1
        # Le jour d'avant, le même quantième : trois mois pleins, sans
        # recouvrement avec la tranche suivante.
        suivant = date(an, mois_fin, min(courant.day, _jours(an, mois_fin)))
        borne = min(_veille(suivant), f)
        tranches.append((courant.isoformat(), borne.isoformat()))
        courant = _lendemain(borne)
    return tranches


def _jours(an: int, mois: int) -> int:
    if mois == 12:
        return 31
    return (date(an, mois + 1, 1) - date(an, mois, 1)).days


def _veille(jour: date) -> date:
    return date.fromordinal(jour.toordinal() - 1)


def _lendemain(jour: date) -> date:
    return date.fromordinal(jour.toordinal() + 1)


def _en_date(valeur: str | date) -> date:
    if isinstance(valeur, date):
        return valeur
    return datetime.strptime(str(valeur)[:10], "%Y-%m-%d").date()


def _date_fr(valeur: object) -> str:
    """« 31/03/2026 » → « 2026-03-31 ». Chaîne vide si illisible.

    Le format ISO est celui de toute la base : mélanger les deux ferait
    trier « 31/03 » après « 01/04 », et le désordre ne se verrait qu'au
    moment de calculer un momentum.
    """
    texte = str(valeur).strip()
    for forme in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texte, forme).date().isoformat()
        except ValueError:
            continue
    return ""


def _correspondance(entete: list[str]) -> dict[str, str]:
    """{nom interne: intitulé d'origine}, une colonne attribuée une fois."""
    normalises = {colonne: _normaliser(colonne) for colonne in entete}
    trouve: dict[str, str] = {}
    pris: set[str] = set()
    for interne, motifs in ALIAS.items():
        for motif in motifs:
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


def lire_tableau(html: str, ticker: str) -> pd.DataFrame:
    """Le tableau d'historique d'une page, en colonnes internes.

    Renvoie toutes les colonnes reconnues, y compris celles qu'on n'écrira
    pas : `coherence` a besoin de la variation annoncée pour vérifier la
    clôture, et le tri se fait après le contrôle, pas avant.
    """
    soupe = BeautifulSoup(html, "html.parser")
    for balise in soupe.find_all("table"):
        tableau = _en_dataframe(balise)
        if tableau is None or tableau.empty:
            continue
        corr = _correspondance(list(tableau.columns))
        if "date" not in corr or "cloture" not in corr:
            continue

        lu = pd.DataFrame({interne: tableau[origine]
                           for interne, origine in corr.items()})
        lu["date"] = lu["date"].map(_date_fr)
        for colonne in lu.columns:
            if colonne != "date":
                lu[colonne] = lu[colonne].map(_nombre)
        lu = lu[lu["date"] != ""]
        if lu.empty:
            continue
        lu.insert(1, "ticker", ticker)
        # Du plus ancien au plus récent : le site publie l'inverse, et
        # tout le reste du projet suppose l'ordre chronologique.
        return lu.sort_values("date").reset_index(drop=True)

    raise SourceIllisible(
        f"aucun tableau d'historique reconnaissable pour {ticker} : "
        "une colonne « Date » et une colonne « Clôture » sont attendues"
    )


def coherence(table: pd.DataFrame) -> list[str]:
    """Compare la variation annoncée à celle que donne la clôture.

    C'est le contrôle qui autorise à faire confiance à la colonne Clôture,
    et le seul dont on dispose : deux colonnes produites indépendamment
    par la source qui concordent sur des dizaines de séances ne concordent
    pas par accident. Un écart signale un décalage de colonnes — donc un
    rapatriement à jeter, pas à corriger.
    """
    if "variation" not in table.columns or len(table) < 2:
        return []
    calcul = table["cloture"] / table["cloture"].shift(1) - 1
    ecart = (calcul * 100 - table["variation"]).abs()
    fautives = table.loc[ecart > TOLERANCE_VARIATION]
    return [
        f"{ligne.date} : variation annoncée {ligne.variation:+.2f} %, "
        f"clôture {ligne.cloture:.0f} → {calcul.loc[ligne.Index] * 100:+.2f} %"
        for ligne in fautives.itertuples()
        if pd.notna(calcul.loc[ligne.Index])
    ]


def seances_repetees(table: pd.DataFrame) -> list[str]:
    """Séances au volume rigoureusement identique à la précédente.

    Observé les 19 et 20 mars 2026 sur SDSC : 11 729 titres et 20 643 040
    FCFA deux jours de suite. Sur un marché où une valeur peut ne pas
    coter de la journée, c'est la même transaction republiée — pas deux
    échanges du même montant au franc près.
    """
    if not {"volume_titres", "volume_fcfa"}.issubset(table.columns):
        return []
    memes = (
        (table["volume_titres"] == table["volume_titres"].shift(1))
        & (table["volume_fcfa"] == table["volume_fcfa"].shift(1))
        & table["volume_fcfa"].notna()
        & (table["volume_fcfa"] > 0)
    )
    return [
        f"{ligne.date} : même volume que la veille "
        f"({ligne.volume_titres:.0f} titres, {ligne.volume_fcfa:.0f} FCFA)"
        for ligne in table.loc[memes].itertuples()
    ]


def retenir(table: pd.DataFrame) -> pd.DataFrame:
    """Ne garde que ce que le contrôle autorise à écrire."""
    return table[[c for c in RETENUES if c in table.columns]].copy()


# --- Accès réseau ---------------------------------------------------------
#
# Cette couche est la seule partie du module qui n'a pas pu être vérifiée
# contre le site : l'accès sortant y est refusé depuis l'environnement de
# développement. Elle est donc réduite au minimum et isolée — tout ce qui
# précède se teste sur une page enregistrée, et se testera de la même
# façon le jour où la mise en page changera.

def _page(symbole_site: str, debut: str, fin: str,
          session: requests.Session | None = None) -> str:
    conf = charger().get("ingestion", {})
    appelant = session or requests
    reponse = appelant.get(
        URL.format(symbole=symbole_site),
        params={"debut": debut, "fin": fin, "per": "Journaliere"},
        headers={"User-Agent": conf.get("agent", "brvm/0.1")},
        timeout=int(conf.get("delai_secondes", 30)),
    )
    reponse.raise_for_status()
    return reponse.text


def historique(
    ticker: str,
    debut: str | date,
    fin: str | date,
    source: str | Path | None = None,
    session: requests.Session | None = None,
    pause: float = 1.5,
) -> pd.DataFrame:
    """L'historique d'une valeur, fenêtre par fenêtre.

    `source` court-circuite le réseau avec une page enregistrée : c'est le
    chemin par lequel le module est testé, et celui qu'emprunte un
    rapatriement fait à la main depuis des captures.
    """
    if source is not None:
        html = Path(source).read_text(encoding="utf-8", errors="replace")
        return lire_tableau(html, ticker)

    morceaux = []
    for i, (d, f) in enumerate(fenetres(debut, fin)):
        if i:
            # Un millier de requêtes sur un site qui n'a rien demandé :
            # la pause n'est pas une précaution technique, c'est la
            # condition pour que la source reste disponible.
            time.sleep(pause)
        morceaux.append(lire_tableau(_page(symbole(ticker), d, f, session),
                                     ticker))
    if not morceaux:
        return pd.DataFrame(columns=RETENUES)
    tout = pd.concat(morceaux, ignore_index=True)
    return (tout.drop_duplicates(subset=["date", "ticker"], keep="last")
            .sort_values("date").reset_index(drop=True))
