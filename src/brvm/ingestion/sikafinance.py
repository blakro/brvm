"""Rapatriement de l'historique depuis sikafinance.

POURQUOI UNE DEUXIÈME SOURCE
----------------------------
brvm.org publie la cote du jour, pas son passé. L'archive ne pouvait donc
grandir qu'au rythme d'une séance par jour ouvré : le premier classement
tombait vers juillet 2027, le premier backtest vers octobre. sikafinance
publie l'historique séance par séance.

PAS DU HTML — UNE API JSON
--------------------------
La page `/marches/historiques/SDSC.ci` n'est qu'une vitrine ; le tableau
est rempli par un appel que le navigateur fait derrière :

    POST https://www.sikafinance.com/api/general/GetHistos
    {"ticker": "SDSC.ci", "datedeb": "2026-01-01",
     "datefin": "2026-03-31", "xperiod": "0"}
    → {"lst": [{"Date": "31/03/2026", "Open": …, "High": …,
                "Low": …, "Close": …, "Volume": …}, …]}

Ce protocole vient du paquet R `BRVM` de Koffi Fredy Sessie (MIT,
github.com/Koffi-Fredysessie/BRVM), qui l'exerce contre le site depuis
2023. Aucune ligne de son code n'est reprise : ce qui est repris, c'est
l'adresse, la forme du corps et le pas de 89 jours — des faits sur le
site, que personne ne possède. Le mérite de les avoir établis lui revient.

Lire l'API plutôt que la page vaut mieux sur trois plans : le JSON ne se
décale pas quand la mise en page change, il évite d'analyser un document
entier pour dix lignes, et il rend des nombres au lieu de « 20 643 040 ».

CE QUE LA SONDE A TRANCHÉ, ET QUI NE POUVAIT L'ÊTRE AUTREMENT
--------------------------------------------------------------
L'accès sortant vers sikafinance est refusé depuis l'environnement de
développement. Deux questions sont donc restées ouvertes jusqu'au premier
appel réel, exécuté par `brvm sonder` sur un runner GitHub le 28/07/2026.
Elles ont toutes deux démenti ce que la page laissait croire — d'où
l'insistance à ne rien écrire avant de les avoir posées.

1. `Volume` COMPTE DES TITRES, PAS DES FRANCS. Le tableau HTML porte deux
   colonnes, l'API n'en rend qu'une, et son ordre de grandeur suggérait
   les francs. Le témoin — SDSC au 19/03/2026, 11 729 titres et
   20 643 040 FCFA, connus par ailleurs — a rendu 11 729. Parier aurait
   rangé des nombres de titres dans une colonne de francs : un facteur
   1 700 d'erreur, invisible jusqu'au jour où le filtre de liquidité
   laisse tout passer.

2. L'API EST COHÉRENTE LÀ OÙ LA PAGE NE L'EST PAS. Dans le HTML,
   « plus bas » dépasse la clôture huit fois sur dix, ce qui est
   impossible. Sur les 64 séances rendues par l'API pour le premier
   trimestre 2026, `bas <= clôture <= haut` tient partout. C'est donc le
   rendu du site qui déforme, pas la donnée — et `ouverture`, `haut` et
   `bas` entrent en base, où le schéma les attendait. Le projet y gagne un
   vrai OHLC, donc une volatilité mesurée sur l'amplitude réelle des
   séances plutôt que sur les seules clôtures.

TROISIÈME PIÈGE, CONFIRMÉ DES DEUX CÔTÉS
----------------------------------------
Des séances portent le même volume que la veille, au titre près. La
capture en montrait une (19 et 20 mars) ; la sonde en a trouvé deux sur le
seul premier trimestre 2026. Sur un marché où une valeur peut ne pas coter
de la journée, c'est la même transaction republiée. `seances_repetees` les
signale : les ingérer doublerait le volume et fabriquerait une séance.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

from ..config import charger
from .brvm_org import SourceIllisible, _en_dataframe, _nombre, _normaliser

API = "https://www.sikafinance.com/api/general/GetHistos"
ACCUEIL = "https://www.sikafinance.com/"
PAGE = "https://www.sikafinance.com/marches/historiques/{symbole}"

# `xperiod` : 0 journalier, 7 hebdomadaire, 30 mensuel, 91 trimestriel,
# 365 annuel. Le projet ne travaille qu'en séances.
PERIODE_JOURNALIERE = "0"

# Le site refuse plus d'un trimestre par appel. 89 jours est le pas retenu
# par le paquet R, éprouvé contre l'API — préféré à « trois mois
# calendaires », qui peut faire 92 jours d'août à octobre.
PAS_JOURS = 89

# Le suffixe pays fait partie de l'identifiant : SDSC.ci, et pas SDSC. Il
# ne se devine pas — la BRVM cote des émetteurs de huit pays — il se lit
# dans le menu déroulant de l'accueil (`select#dpShares`), où chaque
# option porte `value="SDSC.ci"`. `symboles()` va le chercher.
SUFFIXE_DEFAUT = ".ci"

# Ce qui part en base. `ouverture`, `haut` et `bas` y figurent depuis que
# la sonde a montré l'API cohérente — voir l'en-tête, point 2.
RETENUES = ["date", "ticker", "ouverture", "haut", "bas", "cloture",
            "volume_titres", "volume_fcfa"]

# Ce que compte le champ `Volume` de l'API. Établi par le témoin, pas
# supposé : la sonde du 28/07/2026 a rendu 11 729 pour la séance dont on
# savait qu'elle valait 11 729 titres et 20 643 040 FCFA.
VOLUME_API = "volume_titres"

# Le témoin qui répond au point 1. Valeurs relevées sur une capture de la
# page SDSC, séance du 19/03/2026. `sonder` compare ce que rend l'API à
# ces deux nombres : l'un d'eux tombera juste.
TEMOIN = {
    "ticker": "SDSC",
    "date": "2026-03-19",
    "cloture": 1700.0,
    "volume_titres": 11_729.0,
    "volume_fcfa": 20_643_040.0,
}

ALIAS = {
    "date": ("date",),
    "cloture": ("close", "cloture", "clot"),
    "ouverture": ("open", "ouverture"),
    "haut": ("high", "plus haut"),
    "bas": ("low", "plus bas"),
    # L'ORDRE COMPTE, ET C'EST LE SEUL ENDROIT OÙ IL COMPTE. `_correspondance`
    # attribue chaque colonne d'origine une seule fois, en parcourant ce
    # dictionnaire dans l'ordre : le générique « volume » placé avant les
    # deux spécifiques avalait « Volume Titres » du tableau HTML, qui se
    # retrouvait alors sans volume en titres.
    "volume_titres": ("volume titres", "titres"),
    "volume_fcfa": ("volume fcfa", "fcfa"),
    "volume": ("volume",),
    "variation": ("variation",),
}

TOLERANCE_VARIATION = 0.02  # points de pourcentage


# --- Identifiants ---------------------------------------------------------

def symbole(ticker: str, suffixes: dict[str, str] | None = None) -> str:
    """Ticker BRVM → identifiant sikafinance, suffixe pays compris."""
    return f"{ticker}{(suffixes or {}).get(ticker, SUFFIXE_DEFAUT)}"


def lire_symboles(html: str) -> dict[str, str]:
    """{ticker: suffixe} depuis le menu « Choisir une valeur » de l'accueil.

    Les indices (BRVM10, BRVMC…) et les séries maison (SIKA…) sont écartés :
    ce ne sont pas des sociétés, et les demander à l'API d'historique des
    actions ne rendrait rien d'exploitable.
    """
    soupe = BeautifulSoup(html, "html.parser")
    menu = soupe.select_one("#dpShares")
    if menu is None:
        raise SourceIllisible(
            "menu « select#dpShares » introuvable sur l'accueil : "
            "les suffixes pays ne peuvent pas être lus"
        )
    trouves: dict[str, str] = {}
    for option in menu.select("option"):
        valeur = (option.get("value") or "").strip()
        if "." not in valeur:  # indices et entrée vide
            continue
        ticker, _, pays = valeur.partition(".")
        if ticker.startswith(("BRVM", "SIKA")):
            continue
        trouves[ticker] = f".{pays}"
    if not trouves:
        raise SourceIllisible("menu trouvé mais aucune action dedans")
    return trouves


# --- Découpage ------------------------------------------------------------

def fenetres(debut: str | date, fin: str | date,
             jours: int = PAS_JOURS) -> list[tuple[str, str]]:
    """Découpe une période en tranches que l'API accepte.

    Bornes incluses, tranches jointives et disjointes : un recouvrement
    ferait ingérer deux fois la même séance, un trou créerait un vide au
    milieu de l'historique qui ne se verrait qu'au premier momentum tombant
    dedans.
    """
    d, f = _en_date(debut), _en_date(fin)
    if d > f:
        raise ValueError(f"période à l'envers : {d} → {f}")

    tranches: list[tuple[str, str]] = []
    courant = d
    while courant <= f:
        borne = min(courant + timedelta(days=jours - 1), f)
        tranches.append((courant.isoformat(), borne.isoformat()))
        courant = borne + timedelta(days=1)
    return tranches


def _en_date(valeur: str | date) -> date:
    if isinstance(valeur, date):
        return valeur
    return datetime.strptime(str(valeur)[:10], "%Y-%m-%d").date()


def _date_fr(valeur: object) -> str:
    """« 31/03/2026 » → « 2026-03-31 ». Chaîne vide si illisible.

    Tout le reste de la base est en ISO. Mélanger les deux ferait trier
    « 31/03 » après « 01/04 », et le désordre ne se verrait qu'au moment de
    calculer un momentum — c'est-à-dire trop tard.
    """
    texte = str(valeur).strip()
    for forme in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(texte, forme).date().isoformat()
        except ValueError:
            continue
    return ""


def _correspondance(champs) -> dict[str, str]:
    """{nom interne: nom d'origine}, une origine attribuée une seule fois."""
    normalises = {c: _normaliser(c) for c in champs}
    trouve: dict[str, str] = {}
    pris: set[str] = set()
    for interne, motifs in ALIAS.items():
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


# --- Lecture --------------------------------------------------------------

def lire_json(charge: dict | list, ticker: str) -> pd.DataFrame:
    """La réponse de l'API en colonnes internes, du plus ancien au plus récent.

    Les champs sont reconnus par leur nom, jamais par leur position : une
    clé ajoutée en tête décalerait un rapatriement entier sans que rien ne
    le signale.
    """
    lignes = charge.get("lst") if isinstance(charge, dict) else charge
    if not lignes:
        return pd.DataFrame(columns=["date", "ticker"])

    brut = pd.DataFrame(lignes)
    corr = _correspondance(list(brut.columns))
    if "date" not in corr or "cloture" not in corr:
        raise SourceIllisible(
            f"réponse inattendue pour {ticker} : champs "
            f"{sorted(brut.columns)} — « Date » et « Close » sont attendus"
        )

    lu = pd.DataFrame({interne: brut[origine] for interne, origine in corr.items()})
    lu["date"] = lu["date"].map(_date_fr)
    for colonne in lu.columns:
        if colonne != "date":
            lu[colonne] = lu[colonne].map(_nombre)
    lu = lu[lu["date"] != ""]
    if lu.empty:
        return pd.DataFrame(columns=["date", "ticker"])

    lu.insert(1, "ticker", ticker)
    return lu.sort_values("date").reset_index(drop=True)


def lire_tableau(html: str, ticker: str) -> pd.DataFrame:
    """Le tableau HTML de la page, au cas où l'API disparaîtrait.

    Conservé comme second chemin : une API non documentée peut fermer du
    jour au lendemain, et la page publique lui survivra probablement.
    """
    soupe = BeautifulSoup(html, "html.parser")
    for balise in soupe.find_all("table"):
        tableau = _en_dataframe(balise)
        if tableau is None or tableau.empty:
            continue
        corr = _correspondance(list(tableau.columns))
        if "date" not in corr or "cloture" not in corr:
            continue
        lu = pd.DataFrame({i: tableau[o] for i, o in corr.items()})
        lu["date"] = lu["date"].map(_date_fr)
        for colonne in lu.columns:
            if colonne != "date":
                lu[colonne] = lu[colonne].map(_nombre)
        lu = lu[lu["date"] != ""]
        if lu.empty:
            continue
        lu.insert(1, "ticker", ticker)
        return lu.sort_values("date").reset_index(drop=True)

    raise SourceIllisible(
        f"aucun tableau d'historique reconnaissable pour {ticker} : "
        "une colonne « Date » et une colonne « Clôture » sont attendues"
    )


# --- Contrôles ------------------------------------------------------------

def coherence(table: pd.DataFrame) -> list[str]:
    """Compare la variation annoncée à celle que donne la clôture.

    Le seul contrôle dont on dispose, et il suffit : deux colonnes
    produites indépendamment par la source qui retombent l'une sur l'autre
    des dizaines de fois ne le font pas par accident. Un écart signale un
    décalage de colonnes — un lot à jeter, pas à rattraper.

    Ne s'applique qu'au HTML : l'API ne rend pas la variation.
    """
    if "variation" not in table.columns or len(table) < 2:
        return []
    calcul = table["cloture"] / table["cloture"].shift(1) - 1
    ecart = (calcul * 100 - table["variation"]).abs()
    return [
        f"{ligne.date} : variation annoncée {ligne.variation:+.2f} %, "
        f"clôture {ligne.cloture:.0f} → {calcul.loc[ligne.Index] * 100:+.2f} %"
        for ligne in table.loc[ecart > TOLERANCE_VARIATION].itertuples()
        if pd.notna(calcul.loc[ligne.Index])
    ]


def ohlc_incoherent(table: pd.DataFrame) -> list[str]:
    """Séances où « plus bas » ≤ clôture ≤ « plus haut » est violé.

    C'est ce contrôle qui décidera du sort d'`Open`, `High` et `Low` : le
    HTML les rend faux huit fois sur dix, et il faut savoir si l'API fait
    de même avant d'écrire quoi que ce soit en base.
    """
    if not {"bas", "haut", "cloture"}.issubset(table.columns):
        return []
    faux = table[
        (table["bas"] > table["cloture"]) | (table["cloture"] > table["haut"])
    ]
    return [
        f"{ligne.date} : bas {ligne.bas:.0f} / clôture {ligne.cloture:.0f} "
        f"/ haut {ligne.haut:.0f}"
        for ligne in faux.itertuples()
    ]


def seances_repetees(table: pd.DataFrame) -> list[str]:
    """Séances au volume rigoureusement identique à la veille.

    Observé les 19 et 20 mars 2026 sur SDSC : 11 729 titres et 20 643 040
    FCFA deux jours de suite. Deux échanges égaux au franc près n'existent
    pas — c'est la même transaction republiée. Les volumes nuls, eux, se
    répètent normalement sur ce marché et ne sont pas signalés.
    """
    colonnes = [c for c in ("volume_titres", "volume_fcfa", "volume")
                if c in table.columns]
    if not colonnes:
        return []
    memes = pd.Series(True, index=table.index)
    for colonne in colonnes:
        memes &= (table[colonne] == table[colonne].shift(1)) & (table[colonne] > 0)
    return [
        f"{ligne.date} : même volume que la veille "
        f"({getattr(ligne, colonnes[0]):.0f})"
        for ligne in table.loc[memes.fillna(False)].itertuples()
    ]


def retenir(table: pd.DataFrame,
            volume: str | None = VOLUME_API) -> pd.DataFrame:
    """Ne garde que ce que les contrôles autorisent à écrire.

    `volume` dit dans quelle colonne verser le `Volume` de l'API. La
    réponse — des titres — vient du témoin et non d'une supposition ; le
    paramètre reste pour qu'elle se corrige sans toucher au code le jour
    où le service changerait d'avis. Passer `None` écarte le volume plutôt
    que de le ranger au hasard : une archive sans volume se complète, une
    archive au volume faux se découvre le jour où le filtre de liquidité
    laisse passer n'importe quoi.
    """
    lu = table.copy()
    if "volume" in lu.columns:
        if volume in ("volume_titres", "volume_fcfa"):
            lu[volume] = lu["volume"]
        lu = lu.drop(columns=["volume"])
    return lu[[c for c in RETENUES if c in lu.columns]].copy()


def temoin(table: pd.DataFrame) -> str:
    """Ce que mesure la colonne `Volume`, tranché par une valeur connue.

    L'API rend un seul volume, la page en affiche deux. Plutôt que de
    parier, on compare à une séance dont les deux nombres sont connus.
    """
    ligne = table[table["date"] == TEMOIN["date"]]
    if ligne.empty or "volume" not in table.columns:
        return (f"témoin indisponible : séance du {TEMOIN['date']} absente "
                "de la réponse, ou colonne « Volume » manquante")
    valeur = float(ligne["volume"].iloc[0])
    for nom in ("volume_titres", "volume_fcfa"):
        if abs(valeur - TEMOIN[nom]) < 1:
            return f"« Volume » = {nom} ({valeur:,.0f})".replace(",", " ")
    return (f"« Volume » = {valeur:,.0f}, ne correspond ni aux "
            f"{TEMOIN['volume_titres']:,.0f} titres ni aux "
            f"{TEMOIN['volume_fcfa']:,.0f} FCFA connus".replace(",", " "))


# --- Accès réseau ---------------------------------------------------------
#
# Seule partie du module non vérifiable depuis l'environnement de
# développement, l'accès sortant y étant refusé. Elle est donc réduite au
# strict nécessaire : tout ce qui précède se teste sur réponse enregistrée.

def _session(session: requests.Session | None = None) -> requests.Session:
    """Session partagée, avec un agent qui dit qui appelle.

    La clé de configuration est `user_agent`, la même que pour brvm.org —
    j'ai d'abord lu `agent`, qui n'existe pas : la valeur de repli
    s'appliquait donc toujours, et le réglage du projet ne servait à rien.

    L'agent reste identifiable plutôt que déguisé en navigateur. Si
    sikafinance refuse ce choix, `sonder` le dira et le réglage se change
    dans la configuration — mais c'est une décision à prendre en connaissance
    de cause, pas un défaut à contourner par défaut.
    """
    s = session or requests.Session()
    conf = charger().get("ingestion", {})
    s.headers.update({
        "User-Agent": conf.get("user_agent", "brvm/0.1"),
        "Accept": "*/*",
        "Origin": "https://www.sikafinance.com",
    })
    return s


def _appeler(symbole_site: str, debut: str, fin: str,
             session: requests.Session | None = None) -> dict:
    s = _session(session)
    conf = charger().get("ingestion", {})
    reponse = s.post(
        API,
        json={"ticker": symbole_site, "datedeb": debut, "datefin": fin,
              "xperiod": PERIODE_JOURNALIERE},
        # Le Referer désigne la page dont l'appel est censé venir. Sans lui
        # l'API peut répondre vide sans le dire.
        headers={"Referer": PAGE.format(symbole=symbole_site)},
        timeout=int(conf.get("delai_secondes", 30)),
    )
    if reponse.status_code in (403, 429):
        raise SourceIllisible(
            f"{reponse.status_code} sur l'API pour {symbole_site} — le "
            f"service refuse l'appel. Causes probables, dans l'ordre : "
            f"l'agent « {s.headers.get('User-Agent')} » (réglable par "
            "[ingestion] user_agent), un rythme trop soutenu (--pause), "
            "ou un filtrage réseau en amont."
        )
    reponse.raise_for_status()
    return reponse.json()


def symboles(session: requests.Session | None = None) -> dict[str, str]:
    """Les suffixes pays, lus sur l'accueil plutôt que devinés."""
    s = _session(session)
    reponse = s.get(ACCUEIL, timeout=30)
    reponse.raise_for_status()
    return lire_symboles(reponse.text)


def historique(
    ticker: str,
    debut: str | date,
    fin: str | date,
    source: str | Path | None = None,
    session: requests.Session | None = None,
    suffixes: dict[str, str] | None = None,
    pause: float = 0.5,
) -> pd.DataFrame:
    """L'historique d'une valeur, fenêtre par fenêtre.

    `source` court-circuite le réseau avec une réponse enregistrée — JSON
    ou page HTML selon l'extension. C'est le chemin par lequel le module
    est testé, et celui qu'emprunte un rapatriement fait depuis des
    captures.
    """
    if source is not None:
        chemin = Path(source)
        texte = chemin.read_text(encoding="utf-8", errors="replace")
        if chemin.suffix.lower() == ".json":
            import json
            return lire_json(json.loads(texte), ticker)
        return lire_tableau(texte, ticker)

    identifiant = symbole(ticker, suffixes)
    morceaux = []
    for i, (d, f) in enumerate(fenetres(debut, fin)):
        if i:
            # Un millier d'appels à un service qui n'a rien demandé : la
            # pause n'est pas une précaution technique, c'est la condition
            # pour que la source reste disponible.
            time.sleep(pause)
        morceaux.append(lire_json(_appeler(identifiant, d, f, session), ticker))

    morceaux = [m for m in morceaux if not m.empty]
    if not morceaux:
        return pd.DataFrame(columns=RETENUES)
    tout = pd.concat(morceaux, ignore_index=True)
    return (tout.drop_duplicates(subset=["date", "ticker"], keep="last")
            .sort_values("date").reset_index(drop=True))
