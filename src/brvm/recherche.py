"""Recherche systématique : quel prédicteur, sur quel segment, à quel horizon.

CE QUE CE MODULE FAIT
---------------------
Il balaie une grille — prédicteurs × segments × horizons — et mesure pour
chaque case la capacité du prédicteur à ordonner les rendements futurs.
Les segments sont le marché entier, chaque secteur, et chaque valeur prise
seule pour ce qui relève de la série temporelle.

LE PIÈGE QU'IL EXISTE POUR ÉVITER
---------------------------------
Une grille de huit prédicteurs, huit segments et trois horizons fait près
de deux cents tests. À 5 % de seuil, **une dizaine ressortiront
significatifs alors que rien n'existe** — c'est la définition même du
seuil. Publier la meilleure case d'un tel balayage revient à publier le
meilleur tirage d'une loterie et à l'appeler une découverte.

Deux protections, toutes deux indispensables :

1. L'ERREUR-TYPE HONNÊTE. Les étiquettes se recouvrent sur l'horizon :
   avec 60 séances, l'observation du lundi et celle du mardi partagent
   59/60 de leur avenir. L'incertitude se calcule donc sur le nombre de
   périodes disjointes, comme dans `prediction.mesurer_ic`.

2. LA CORRECTION DE BENJAMINI-HOCHBERG. Elle contrôle la part attendue de
   fausses découvertes parmi les cases retenues. Sans elle, la question
   « quel est le meilleur modèle ? » a toujours une réponse, y compris
   quand la bonne réponse est « aucun ».

CE QU'IL NE PEUT PAS FAIRE
--------------------------
Les modèles recommandés par secteur dans la littérature de ce marché —
retour à la moyenne du rendement du dividende pour les télécoms et les
services publics, ARIMAX sur commodités décalées pour l'agro-alimentaire,
panel de fondamentaux pour les financières — demandent des données que ce
projet n'a pas : dividendes, cours des matières premières, comptes des
émetteurs. Ce balayage épuise ce que les prix, les volumes et l'OHLC
permettent de dire. Le reste attend d'autres sources, et ce module dira
alors la même chose de ces données-là.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import dividende, features
from .config import charger

# Horizons en séances : un, trois et six mois. En deçà, les frais de
# 2,5 à 3,5 % l'aller-retour condamnent tout signal avant qu'il ne serve ;
# au-delà, l'historique ne fournit plus assez de périodes disjointes.
HORIZONS = (20, 60, 120)

# Un secteur de trois valeurs ne permet pas de mesurer un classement : un
# rang de Spearman sur trois points ne prend que quelques valeurs, et son
# écart-type entre dates dit plus sur l'arithmétique que sur le marché.
MEMBRES_MINIMUM = 4

SEUIL_FDR = 0.10


def _prix(cours: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Les matrices brutes dont tous les prédicteurs dérivent."""
    cloture = features.serie(cours, "cloture")
    matrices = {"cloture": cloture}
    for colonne in ("haut", "bas", "volume_fcfa"):
        matrices[colonne] = features.serie(cours, colonne).reindex(
            index=cloture.index, columns=cloture.columns)
    return matrices


# --- Les prédicteurs ------------------------------------------------------
#
# Chacun rend une matrice dates × tickers, alignée sur les cours. Aucun ne
# regarde au-delà de sa date : ce sont des fenêtres glissantes fermées à
# gauche, et `balayer` compare ensuite à un rendement strictement futur.

def _momentum(m, fenetre, saut):
    p = m["cloture"]
    debut, fin = p.shift(fenetre), p.shift(saut)
    return (fin / debut - 1).where(debut > 0)


def _tendance(m, courte=20, longue=100):
    p = m["cloture"]
    c, l = p.rolling(courte).mean(), p.rolling(longue).mean()
    return (c / l - 1).where(l > 0)


def _volatilite(m, fenetre=60):
    return np.log(m["cloture"]).diff().rolling(fenetre).std() * np.sqrt(250)


def _liquidite(m, fenetre=60):
    return m["volume_fcfa"].fillna(0).rolling(fenetre, min_periods=1).median()


def _amplitude(m, fenetre=60):
    """Écart haut-bas moyen, rapporté au cours.

    Mesurable seulement depuis que l'OHLC est en base. Elle dit autre
    chose que la volatilité des clôtures : une valeur peut clôturer au
    même cours chaque séance après y avoir beaucoup circulé.
    """
    etendue = (m["haut"] - m["bas"]) / m["cloture"].where(m["cloture"] > 0)
    return etendue.rolling(fenetre).mean()


def _ecart_moyenne(m, fenetre=250):
    """Écart au cours moyen de l'année : le retour à la moyenne, en coupe."""
    moyenne = m["cloture"].rolling(fenetre).mean()
    return (m["cloture"] / moyenne - 1).where(moyenne > 0)


PREDICTEURS = {
    "momentum 12-1": lambda m: _momentum(m, 250, 20),
    "momentum 6-1": lambda m: _momentum(m, 125, 20),
    "retournement 1 mois": lambda m: -_momentum(m, 20, 0),
    "tendance": _tendance,
    "volatilité": _volatilite,
    "liquidité": _liquidite,
    "amplitude": _amplitude,
    "écart à la moyenne": _ecart_moyenne,
}


# --- Mesure ---------------------------------------------------------------

def _rendement_futur(cloture: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Rendement des `horizon` séances SUIVANTES. Strictement futur."""
    return cloture.shift(-horizon) / cloture - 1


def _ic_transversal(valeurs: pd.DataFrame, futur: pd.DataFrame,
                    horizon: int) -> dict:
    """IC de Spearman date par date, puis moyenne et incertitude honnête.

    Calculé d'un bloc plutôt que date par date : la boucle Python coûtait
    quatre minutes de tests pour un résultat identique au flottant près.
    Le rang se prend LIGNE PAR LIGNE (`axis=1`) — c'est un classement à
    l'intérieur d'une séance, jamais à travers le temps.
    """
    # Support commun d'abord : un rang calculé avant le masquage
    # compterait des valeurs dont le rendement futur est inconnu.
    commun = valeurs.notna() & futur.notna()
    assez = commun.sum(axis=1) >= MEMBRES_MINIMUM
    if not assez.any():
        return {"ic": float("nan"), "erreur_type": float("nan"),
                "t": float("nan"), "dates": 0, "periodes": 0,
                "p": float("nan")}

    x = valeurs.where(commun)[assez].rank(axis=1)
    y = futur.where(commun)[assez].rank(axis=1)
    # Pearson sur les rangs = Spearman. `corrwith(axis=1)` rend NaN pour
    # une séance où l'un des deux est constant, ce qui est le bon refus.
    serie = x.corrwith(y, axis=1).dropna()
    vide = {"ic": float("nan"), "erreur_type": float("nan"),
            "t": float("nan"), "dates": 0, "periodes": 0, "p": float("nan")}
    if len(serie) < 2:
        return {**vide, "dates": len(serie)}

    periodes = max(1, int(np.ceil(len(serie) / max(1, horizon))))
    if periodes < 3:
        return {**vide, "ic": float(serie.mean()), "dates": len(serie),
                "periodes": periodes}

    erreur = float(serie.std(ddof=1) / np.sqrt(periodes))
    if erreur == 0:
        return {**vide, "ic": float(serie.mean()), "dates": len(serie),
                "periodes": periodes}
    t = float(serie.mean()) / erreur
    return {"ic": float(serie.mean()), "erreur_type": erreur, "t": t,
            "dates": len(serie), "periodes": periodes,
            "p": _valeur_p(t, periodes - 1)}


def _valeur_p(t: float, ddl: int) -> float:
    """Bilatérale. Loi de Student si scipy est là, normale sinon.

    L'écart entre les deux, à une trentaine de degrés de liberté, se joue
    à la troisième décimale — il ne change aucune conclusion ici. Mais
    dépendre de scipy pour cela seul serait payer cher une précision dont
    on n'a pas l'usage.
    """
    if not np.isfinite(t):
        return float("nan")
    try:
        from scipy import stats
        return float(2 * stats.t.sf(abs(t), ddl))
    except ImportError:  # pragma: no cover — dépend de l'environnement
        # Approximation normale : erf via math.
        import math
        return float(math.erfc(abs(t) / math.sqrt(2)))


def benjamini_hochberg(valeurs_p: pd.Series, seuil: float = SEUIL_FDR) -> pd.Series:
    """Seuil ajusté au nombre de tests. Rend le booléen « retenu ».

    Bonferroni diviserait le seuil par le nombre de tests et ne laisserait
    rien passer sur deux cents cases ; Benjamini-Hochberg contrôle la PART
    de fausses découvertes parmi les retenues, ce qui est la question
    qu'on se pose vraiment : « si j'en garde cinq, combien sont du bruit ? »
    """
    p = valeurs_p.dropna().sort_values()
    if p.empty:
        return pd.Series(False, index=valeurs_p.index)
    rangs = np.arange(1, len(p) + 1)
    sous_seuil = p.to_numpy() <= seuil * rangs / len(p)
    retenu = pd.Series(False, index=valeurs_p.index)
    if sous_seuil.any():
        # Toutes les p-valeurs jusqu'au plus grand rang qui passe.
        limite = int(np.max(np.where(sous_seuil)[0]))
        retenu.loc[p.index[:limite + 1]] = True
    return retenu


# --- Balayage transversal -------------------------------------------------

def segments(referentiel: pd.DataFrame | None,
             tickers: list[str]) -> dict[str, list[str]]:
    """Le marché entier, puis chaque secteur assez peuplé pour être classé."""
    trouves = {"tout le marché": list(tickers)}
    if referentiel is None or referentiel.empty:
        return trouves
    ref = referentiel[referentiel["ticker"].isin(tickers)]
    for secteur, groupe in ref.dropna(subset=["secteur"]).groupby("secteur"):
        membres = sorted(groupe["ticker"])
        if len(membres) >= MEMBRES_MINIMUM:
            trouves[secteur] = membres
    return trouves


def balayer(cours: pd.DataFrame, referentiel: pd.DataFrame | None = None,
            horizons=HORIZONS, reglages: dict | None = None) -> pd.DataFrame:
    """La grille entière, une ligne par case, correction du test multiple.

    Le tri final est par |t| décroissant, mais c'est la colonne `retenu`
    qui décide : le meilleur t d'un balayage sans découverte reste du
    bruit, et il est toujours flatteur.
    """
    conf = reglages or charger()
    matrices = _prix(cours)
    cloture = matrices["cloture"]
    if cloture.empty:
        return pd.DataFrame()

    decoupes = segments(referentiel, list(cloture.columns))
    valeurs = {nom: fonction(matrices) for nom, fonction in PREDICTEURS.items()}
    futurs = {h: _rendement_futur(cloture, h) for h in horizons}

    lignes = []
    for horizon in horizons:
        for segment, membres in decoupes.items():
            for nom, matrice in valeurs.items():
                mesure = _ic_transversal(
                    matrice[membres], futurs[horizon][membres], horizon)
                lignes.append({
                    "segment": segment, "valeurs": len(membres),
                    "prédicteur": nom, "horizon": horizon, **mesure,
                })

    table = pd.DataFrame(lignes)
    if table.empty:
        return table
    table["retenu"] = benjamini_hochberg(table["p"])
    table["|t|"] = table["t"].abs()
    return table.sort_values("|t|", ascending=False).reset_index(drop=True)


# --- Série temporelle, valeur par valeur ----------------------------------

def retour_a_la_moyenne(cours: pd.DataFrame,
                        minimum: int = 500) -> pd.DataFrame:
    """Chaque valeur est-elle attirée par un cours d'équilibre ?

    L'ajustement d'Ornstein-Uhlenbeck est repris de `dividende`, avec son
    garde-fou : une régression des moindres carrés « détecte » un retour à
    la moyenne sur quatre marches aléatoires sur cinq, et le test de
    Dickey-Fuller est ce qui ramène ce taux au niveau attendu.

    La demi-vie décide de l'exploitabilité : au-delà de quelques mois,
    l'attraction existe peut-être mais elle ne se négocie pas — les frais
    la mangent avant qu'elle n'agisse.
    """
    prix = features.serie(cours, "cloture")
    lignes = []
    for ticker in prix.columns:
        serie = np.log(prix[ticker].dropna().where(lambda s: s > 0).dropna())
        if len(serie) < minimum:
            continue
        equilibre, theta = dividende.ajuster_ou(serie)
        demi = dividende.demi_vie(theta)
        lignes.append({
            "ticker": ticker,
            "séances": len(serie),
            "équilibre": float(np.exp(equilibre)) if np.isfinite(equilibre)
                         else float("nan"),
            "demi_vie": demi,
            "exploitable": bool(np.isfinite(demi) and demi <= 120),
        })
    table = pd.DataFrame(lignes)
    if table.empty:
        return table
    table = table.sort_values("demi_vie").reset_index(drop=True)
    # LE MÊME PIÈGE QU'AU-DESSUS, UN CRAN PLUS BAS. Le test de
    # Dickey-Fuller contrôle le risque d'UNE valeur ; appliqué à
    # quarante-cinq, il en laisse passer deux ou trois par construction.
    # Trois « découvertes » sur quarante-cinq, c'est le taux d'erreur, pas
    # un résultat. Le nombre attendu voyage donc avec le tableau.
    table.attrs["testees"] = len(table)
    table.attrs["attendues_par_hasard"] = 0.05 * len(table)
    return table


def expliquer(table: pd.DataFrame, retour: pd.DataFrame | None = None) -> str:
    """Rendu texte. Le verdict d'ensemble avant le détail, jamais l'inverse."""
    if table.empty:
        return "Balayage impossible : aucun cours exploitable."

    retenues = table[table["retenu"]]
    lignes = [
        f"{len(table)} cases balayées "
        f"({table['prédicteur'].nunique()} prédicteurs × "
        f"{table['segment'].nunique()} segments × "
        f"{table['horizon'].nunique()} horizons).",
        "",
    ]
    if retenues.empty:
        lignes += [
            "AUCUNE CASE NE SURVIT À LA CORRECTION DU TEST MULTIPLE.",
            "",
            f"Le meilleur |t| du balayage vaut {table['|t|'].max():.1f}, et il",
            "est exactement ce qu'on attend du hasard sur ce nombre de tests.",
            "Le retenir serait publier le meilleur tirage d'une loterie.",
            "",
        ]
    else:
        lignes += [f"{len(retenues)} cases retenues à {SEUIL_FDR:.0%} de "
                   "fausses découvertes attendues :", ""]

    entete = (f"{'segment':<26}{'prédicteur':<21}{'h':>4}"
              f"{'IC':>8}{'±2σ':>8}{'t':>7}{'p':>8}  retenu")
    lignes += [entete, "-" * len(entete)]
    # `itertuples` renomme les colonnes accentuées en _1, _2… : on lit
    # donc par leur nom, qui est ce qui rend le code relisible.
    for _, r in table.head(12).iterrows():
        lignes.append(
            f"{r['segment'][:25]:<26}{r['prédicteur'][:20]:<21}"
            f"{r['horizon']:>4}{r['ic']:>+8.3f}{2 * r['erreur_type']:>8.3f}"
            f"{r['t']:>+7.1f}{r['p']:>8.3f}  {'oui' if r['retenu'] else ''}"
        )

    if retour is not None and not retour.empty:
        exploitables = retour[retour["exploitable"]]
        attendues = retour.attrs.get("attendues_par_hasard", 0.05 * len(retour))
        lignes += [
            "",
            f"Retour à la moyenne, valeur par valeur : "
            f"{len(exploitables)} sur {len(retour)} montrent une attraction "
            "significative et assez rapide pour être négociable.",
            f"Le hasard seul en produirait {attendues:.1f} : "
            + ("cet écart n'est pas concluant."
               if len(exploitables) <= 2 * attendues
               else "l'écart mérite un examen valeur par valeur."),
        ]
        for _, r in exploitables.head(8).iterrows():
            lignes.append(
                f"  {r['ticker']:<8} demi-vie {r['demi_vie']:>6.0f} séances, "
                f"équilibre {r['équilibre']:>10,.0f} FCFA".replace(",", " "))
    return "\n".join(lignes)

# Nombre minimal de sociétés pour qu'une saison compte. En deçà, un IC
# transversal se calcule encore mais ne mesure plus rien : sur cinq
# valeurs, une seule inversion le fait changer de signe.
SOCIETES_MINIMUM_SAISON = 8


def rendement_transversal(cours: pd.DataFrame, dividendes: pd.DataFrame,
                          jours: int = 365) -> pd.DataFrame:
    """Le rendement du dividende prédit-il le cours des douze mois suivants ?

    LA QUESTION QUI A MOTIVÉ LA COLLECTE DE ONZE EXERCICES. Aucun facteur
    de prix ne bat le hasard sur cette place ; le dividende est la seule
    piste restée ouverte, et avec quatre exercices elle n'était pas
    testable — trois transitions annuelles ne font pas un échantillon.

    DEUX PIÈGES, FERMÉS ICI PARCE QU'ILS SE SONT REFERMÉS SUR MOI.

    1. LE REGARD EN AVANT. Le dividende de l'exercice N se détache au
       milieu de l'année N+1 : il n'est pas connu en janvier. Un premier
       calcul confrontait le rendement de l'exercice N à l'année civile
       N+1 ENTIÈRE, donc à des mois déjà écoulés quand l'information
       paraît. Ici chaque rendement est daté de SON détachement et ne
       prédit que les douze mois qui le suivent.

    2. L'ÉCHELLE D'AVANT LA RÉDUCTION DU NOMINAL. Les montants publiés
       avant 2018 ne sont pas comparables aux cours archivés ; les
       rendements implicites y atteignent 383 %. Un second calcul les
       laissait entrer. `dividende.detachements` les écarte — c'est lui
       qui est appelé ici, pas le calendrier brut.

    Rend une ligne par saison : le nombre de sociétés et l'IC de Spearman.
    L'agrégation et son incertitude restent à l'appelant, qui doit compter
    les saisons comme périodes disjointes — elles le sont, contrairement
    aux dates d'un historique quotidien.
    """
    prix = features.serie(cours)
    table, _ = dividende.detachements(cours, dividendes)
    if prix.empty or (table == 0).all().all():
        return pd.DataFrame(columns=["saison", "societes", "ic"])

    # `.stack()` ne supprime PLUS les valeurs manquantes depuis pandas 3 :
    # sans le `dropna`, toutes les cellules nulles entraient et chaque
    # saison comptait les 47 sociétés de la cote au lieu des trente qui
    # détachent. Le symptôme était un IC calculé sur des rendements
    # inexistants, pas une erreur visible.
    empile = table[table > 0].stack().dropna()
    if empile.empty:
        return pd.DataFrame(columns=["saison", "societes", "ic"])
    recus = empile.rename("rendement").reset_index()
    recus.columns = ["detachement", "ticker", "rendement"]
    recus["saison"] = recus["detachement"].str[:4]

    lignes = []
    for saison, bloc in recus.groupby("saison"):
        # Une observation par société : la somme des acomptes de la
        # saison, datée du dernier détachement — c'est là qu'on saurait.
        par = bloc.groupby("ticker").agg(rdt=("rendement", "sum"),
                                         fin=("detachement", "max"))
        scores, perfs = [], []
        for ticker, ligne in par.iterrows():
            fin = pd.Timestamp(ligne["fin"]) + pd.Timedelta(days=jours)
            fenetre = prix[ticker].loc[ligne["fin"]:fin.strftime("%Y-%m-%d")]
            fenetre = fenetre.dropna()
            if len(fenetre) < 100 or fenetre.iloc[0] <= 0:
                continue
            scores.append(ligne["rdt"])
            perfs.append(fenetre.iloc[-1] / fenetre.iloc[0] - 1)
        if len(scores) < SOCIETES_MINIMUM_SAISON:
            continue
        ic = pd.Series(scores).corr(pd.Series(perfs), method="spearman")
        # Un IC indéfini n'est pas une mesure nulle : il arrive quand tous
        # les rendements — ou toutes les performances — sont identiques, et
        # la corrélation n'a alors pas de sens. Le laisser passer le ferait
        # entrer dans la moyenne de l'appelant sous forme de NaN, qui
        # contaminerait le résultat entier au lieu de retirer une saison.
        if pd.isna(ic):
            continue
        lignes.append({"saison": saison, "societes": len(scores),
                       "ic": float(ic)})
    return pd.DataFrame(lignes)
