"""Que faire, concrètement : acheter, conserver, vendre.

CE QUI MANQUAIT, ET POURQUOI C'EST CE MODULE
--------------------------------------------
Le reste du projet produit un CLASSEMENT et des mesures de sa qualité. Aucun
n'a jamais dit quoi faire. Or un classement ne répond pas à la question que
se pose quelqu'un qui détient déjà des titres : « dois-je vendre la SGBC
pour acheter la SICOR ? » La réponse dépend de trois choses que le
classement ignore — ce que vous détenez, ce que l'arbitrage rapporterait, et
ce qu'il coûterait chez VOTRE intermédiaire.

Ce module fait cette arithmétique. Il ne découvre rien : il applique aux
mesures des autres modules la seule règle qui vaille avant de passer un
ordre.

    un arbitrage ne se fait que si son gain attendu dépasse son coût.

LE GAIN ATTENDU, ET IL EST CALCULABLE
-------------------------------------
Relation de Grinold : le rendement attendu d'une valeur, en excès du marché,
vaut

    alpha = IC × dispersion × z

où l'IC est la qualité mesurée du classement, la dispersion l'écart-type
transversal des rendements à l'horizon, et z le score normalisé de la valeur
— sa position dans le classement, exprimée en écarts-types.

Remplacer une ligne par une autre rapporte donc IC × dispersion × (z_entrant
− z_sortant), et coûte deux passages de frais. Les deux grandeurs sont dans
la même unité et se comparent directement. Aucun paramètre libre : l'IC
vient de la validation, la dispersion de l'échantillon, les frais de votre
devis.

L'ESTIMATION PRUDENTE EST LE DÉFAUT, ET C'EST UN CHOIX
------------------------------------------------------
L'IC mesuré sur cette archive vaut +0,045 avec un intervalle à 95 % qui
contient zéro. Sizer un arbitrage sur +0,045 revient à parier que
l'estimation ponctuelle est juste ; la borne basse de l'intervalle, elle,
est ce qu'on peut défendre. `prudence=True` l'emploie, et le résultat est
qu'aucun arbitrage ne passe — ce qui est l'information, pas une panne.

Un conseiller qui recommande d'agir quand la preuve ne le permet pas ne rend
pas service ; il facture une rotation.

CE QUE CE MODULE NE FAIT PAS
----------------------------
Il ne dit pas quoi acheter avec de l'argent frais versus rester liquide : la
question demande un rendement attendu du marché, que ce projet ne prétend
pas prévoir. Il compare des valeurs entre elles, à somme investie donnée.

Il ne connaît ni votre fiscalité, ni votre horizon, ni votre tolérance au
risque, ni la part que ces titres représentent dans votre patrimoine. Ce
qu'il rend est une arithmétique, pas une recommandation personnalisée — et
un conseil d'investissement suppose tout ce qu'il ignore.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .config import charger

ACTIONS = ("acheter", "conserver", "vendre", "vendre et remplacer")

COLONNES = ["ticker", "nom", "detenu", "rang", "action", "paire",
            "gain_attendu", "cout", "net", "motif"]

AVERTISSEMENTS = (
    "arithmétique de l'arbitrage, pas un conseil d'investissement",
    "l'IC mesuré n'est pas significativement différent de zéro",
    "ni fiscalité, ni horizon, ni tolérance au risque ne sont connus",
    "univers restreint aux sociétés cotées aujourd'hui (biais du survivant)",
)


def _quantile_normal(p: float) -> float:
    """Φ⁻¹(p), sans imposer scipy.

    Approximation rationnelle de Moro, exacte à 3e-9 sur la plage utile. Le
    projet garde scipy optionnelle — voir `recherche._valeur_p` pour le même
    choix — et un quantile normal ne justifie pas de la rendre obligatoire.
    """
    if not 0.0 < p < 1.0:
        return float("nan")
    try:  # pragma: no cover — dépend de l'environnement
        from scipy import stats
        return float(stats.norm.ppf(p))
    except ImportError:  # pragma: no cover
        pass
    a = (2.50662823884, -18.61500062529, 41.39119773534, -25.44106049637)
    b = (-8.47351093090, 23.08336743743, -21.06224101826, 3.13082909833)
    c = (0.3374754822726147, 0.9761690190917186, 0.1607979714918209,
         0.0276438810333863, 0.0038405729373609, 0.0003951896511919,
         0.0000321767881768, 0.0000002888167364, 0.0000003960315187)
    y = p - 0.5
    if abs(y) < 0.42:
        r = y * y
        return float(y * (((a[3] * r + a[2]) * r + a[1]) * r + a[0])
                     / ((((b[3] * r + b[2]) * r + b[1]) * r + b[0]) * r + 1.0))
    r = p if y < 0 else 1.0 - p
    r = math.log(-math.log(r))
    x = c[0]
    for i in range(1, 9):
        x += c[i] * r ** i
    return float(-x if y < 0 else x)


def scores_normalises(rangs: pd.Series, effectif: int | None = None) -> pd.Series:
    """Rang (1 = meilleur) → score en écarts-types.

    LE RANG N'EST PAS UNE UNITÉ. Passer de la 3e à la 1re place ne vaut pas
    la même chose que passer de la 20e à la 18e : les extrêmes du classement
    sont beaucoup plus écartés que son milieu. Le score normalisé remet tout
    le monde sur une échelle où les différences s'additionnent — celle où le
    gain attendu se calcule.
    """
    n = int(effectif or len(rangs))
    if n < 2:
        return pd.Series(0.0, index=rangs.index)
    return rangs.astype(float).map(
        lambda r: _quantile_normal(1.0 - (float(r) - 0.5) / n))


def dispersion(echantillon: pd.DataFrame,
               colonne: str = "rendement_futur") -> float:
    """Écart-type transversal des rendements à l'horizon, moyenné sur les séances.

    C'est le facteur d'échelle du gain attendu : un classement parfait ne
    rapporte rien sur un marché où toutes les valeurs font le même
    rendement. Mesuré dans la séance et non sur l'ensemble des dates
    confondues, sans quoi on mesurerait surtout les écarts entre années.
    """
    if echantillon.empty or colonne not in echantillon.columns:
        return float("nan")
    par_seance = echantillon.groupby("date")[colonne].std()
    return float(par_seance.mean())


def ic_retenu(mesure: dict | None, prudence: bool = True) -> float:
    """L'IC à employer : la borne basse de l'intervalle, ou l'estimation nue.

    POURQUOI LA BORNE BASSE PAR DÉFAUT. Un arbitrage se décide contre un
    coût certain. Employer l'estimation ponctuelle d'un IC dont l'intervalle
    à 95 % contient zéro revient à payer une dépense sûre contre un gain
    dont on n'a pas établi l'existence. La borne basse est ce qu'on peut
    défendre devant le relevé de courtage.

    Quand l'intervalle contient zéro, la borne basse est négative et aucun
    arbitrage ne passe. C'est le résultat, pas une défaillance : sur cette
    archive, la preuve ne permet pas de recommander de tourner.
    """
    if not mesure:
        return 0.0
    ic = float(mesure.get("ic", float("nan")))
    if not np.isfinite(ic):
        return 0.0
    if not prudence:
        return ic
    erreur = float(mesure.get("erreur_type", float("nan")))
    if not np.isfinite(erreur):
        return 0.0
    # Deux erreurs-types, comme partout ailleurs dans le projet.
    return ic - 2 * erreur


def gain_haut(avantage: dict | None, prudence: bool = True) -> float:
    """Ce que le HAUT DE LISTE a rapporté, en rendement, borne basse.

    POURQUOI CE CHIFFRE À CÔTÉ DE L'IC. L'IC passe par la relation de
    Grinold — `ecart_minimal` — pour devenir un gain en pourcent : trois
    quantités estimées, une hypothèse de linéarité, et un lecteur qui doit
    croire la chaîne. L'avantage du haut de liste, lui, EST déjà un
    rendement : c'est ce qu'ont rapporté les `positions` premières valeurs
    contre l'univers, mesuré hors échantillon, et il se compare aux frais
    d'un aller-retour sans aucun intermédiaire théorique.

    Les deux sont conservés parce qu'ils ne disent pas la même chose. L'IC
    note l'ordre de toute la cote et sert à départager DEUX lignes ; celui-ci
    ne regarde que le haut et dit si le suivre paie. Sur cette archive, ils
    ont divergé en signe — voir `apprentissage.avantage_par_date`.

    Même prudence qu'ailleurs : deux erreurs-types retirées par défaut.
    """
    if not avantage:
        return 0.0
    valeur = float(avantage.get("avantage", float("nan")))
    if not np.isfinite(valeur):
        return 0.0
    if not prudence:
        return valeur
    erreur = float(avantage.get("erreur_type", float("nan")))
    if not np.isfinite(erreur):
        return 0.0
    return valeur - 2 * erreur


def concentration_secteur(
    classement: pd.DataFrame,
    referentiel: pd.DataFrame | None,
    positions: int = 10,
) -> dict:
    """Dans quels secteurs tombent les `positions` premières, et à quel point.

    POURQUOI L'AFFICHER. Un classement ne choisit pas de parier sur un
    secteur, mais il le fait quand même. Mesuré sur l'archive avant la
    comparaison à secteur égal, les dix premières lignes du classement de
    production étaient à 43,9 % des Services Financiers contre 34,5 % dans
    l'univers coté — neuf points et demi de pari que personne n'avait
    décidé, ramenés à cinq depuis. Un
    porteur qui suit dix recommandations dont quatre sont des banques n'est
    pas diversifié, et rien dans l'écran ne le lui disait.

    `part` est la part du haut de liste par secteur, `ecart` l'écart à
    l'univers coté du jour. `herfindahl` résume : c'est la somme des carrés
    des parts, 1 si tout le portefeuille est dans un seul secteur, environ
    1/7 s'il est réparti sur les sept. L'univers lui-même vaut 0,202, ce qui
    est le repère à côté duquel le lire.
    """
    vide = {"part": {}, "ecart": {}, "herfindahl": float("nan"),
            "herfindahl_univers": float("nan"), "premier": None,
            "part_premier": float("nan"), "positions": int(positions)}
    if (classement is None or classement.empty or referentiel is None
            or "secteur" not in getattr(referentiel, "columns", [])
            or "ticker" not in classement.columns):
        return vide
    table = referentiel.dropna(subset=["ticker", "secteur"])
    if table.empty:
        return vide
    secteurs = table.set_index("ticker")["secteur"]
    ordre = (classement.sort_values("rang") if "rang" in classement.columns
             else classement)
    haut = ordre.head(int(positions))["ticker"].map(secteurs).dropna()
    univers = ordre["ticker"].map(secteurs).dropna()
    if haut.empty or univers.empty:
        return vide
    # Réindexés sur les MÊMES secteurs, zéro quand absent : sans quoi les
    # écarts ne sommeraient pas à zéro et un secteur jamais retenu
    # paraîtrait surpondéré.
    tous = sorted(set(univers) | set(haut))
    p_haut = haut.value_counts(normalize=True).reindex(tous, fill_value=0.0)
    p_uni = univers.value_counts(normalize=True).reindex(tous, fill_value=0.0)
    ecart = (p_haut - p_uni).sort_values(ascending=False)
    premier = str(p_haut.idxmax())
    return {"part": {str(k): float(v) for k, v in p_haut.items()},
            "ecart": {str(k): float(v) for k, v in ecart.items()},
            "herfindahl": float((p_haut ** 2).sum()),
            "herfindahl_univers": float((p_uni ** 2).sum()),
            "premier": premier, "part_premier": float(p_haut.max()),
            "positions": int(positions)}


def ecart_minimal(ic: float, dispersion_: float, cout: float) -> float:
    """Écart de score qu'un arbitrage doit franchir pour se payer.

    2·coût = IC × dispersion × Δz, donc Δz = 2·coût / (IC × dispersion).

    Ce nombre est le plus utile du module : il dit, une fois pour toutes et
    pour VOS frais, de combien une candidate doit dépasser ce que vous
    détenez avant que l'ordre ait un sens. Sur 37 valeurs, l'échelle des
    scores va d'environ -2 à +2 : un Δz requis de 3 signifie qu'aucune paire
    du classement ne le franchit, et qu'il ne faut rien faire.
    """
    if not np.isfinite(ic) or ic <= 0 or not np.isfinite(dispersion_) \
            or dispersion_ <= 0:
        return float("inf")
    return float(2.0 * cout / (ic * dispersion_))


def conseiller(
    classement: pd.DataFrame,
    detenu: list[str] | None = None,
    mesure: dict | None = None,
    dispersion_: float | None = None,
    reglages: dict | None = None,
    prudence: bool = True,
    avantage: dict | None = None,
) -> dict:
    """Une action par ligne : acheter, conserver, vendre, ou ne rien faire.

    `classement` vient de `scoring.noter` ou de `prediction.predire` — il
    suffit qu'il porte `ticker` et `rang`. `detenu` est ce que vous avez en
    portefeuille. `mesure` est la mesure d'IC de la validation, dont on tire
    l'estimation prudente du gain.

    LES ARBITRAGES SONT APPARIÉS DU MEILLEUR AU PIRE. On confronte la
    meilleure candidate non détenue à la plus mauvaise ligne détenue : c'est
    l'arbitrage qui a le plus de chances de franchir le coût. S'il ne le
    franchit pas, aucun autre ne le franchira, et la boucle s'arrête — ce
    n'est pas une heuristique, c'est que l'écart de score ne peut que
    diminuer ensuite.
    """
    conf = reglages or charger()
    bt = conf.get("backtest", {})
    positions = int(bt.get("positions", 10))
    cout = (float(bt.get("frais_pourcent", 1.0))
            + float(bt.get("impact_pourcent", 0.5))) / 100.0

    vide = {"lignes": pd.DataFrame(columns=COLONNES), "ic": 0.0,
            "dispersion": float("nan"), "cout": cout,
            "ecart_minimal": float("inf"), "arbitrages": 0,
            # CONSTITUER N'EST PAS ARBITRER, et les confondre faisait dire au
            # rendu « aucun arbitrage ne peut se payer » puis « 10 arbitrages
            # couvrent leurs frais » dans le même souffle. Un achat initial ne
            # remplace rien : il n'a pas d'aller-retour à amortir, et son
            # nombre se compte à part.
            "constitution": 0,
            "meilleur_arbitrage": float("nan"),
            # LE MÊME ÉCART, MAIS EN POURCENTAGE, et c'est ce qui rend la
            # section lisible. « Écart de score requis : 3,06 » ne veut rien
            # dire pour qui n'a pas lu Grinold ; « le meilleur échange promet
            # 3,08 % et coûte 3,00 % » se compare à vue d'œil, et c'est
            # exactement la même arithmétique.
            "gain_meilleur": float("nan"),
            # CE QUE LE HAUT DE LISTE A RAPPORTÉ, mesuré et non déduit. Voir
            # `gain_haut` : c'est le seul chiffre du module qui se compare
            # aux frais sans passer par Grinold.
            "gain_haut": gain_haut(avantage, prudence),
            # Le constat NU à côté de sa borne : `expliquer` a besoin des
            # deux, et les confondre ferait écrire qu'un gain constaté est
            # négatif alors que c'est son plancher qui l'est.
            "avantage_mesure": float((avantage or {}).get(
                "avantage", float("nan"))),
            "haut_mesure": bool(avantage),
            "positions": positions,
            "prudence": prudence, "avertissements": AVERTISSEMENTS}
    if classement is None or classement.empty or "ticker" not in classement:
        return vide

    table = classement.copy()
    if "rang" not in table.columns:
        table["rang"] = range(1, len(table) + 1)
    table = table.sort_values("rang").reset_index(drop=True)
    table["z"] = scores_normalises(table["rang"])

    ic = ic_retenu(mesure, prudence)
    disp = dispersion_ if dispersion_ is not None else float("nan")
    seuil = ecart_minimal(ic, disp, cout)
    haut = gain_haut(avantage, prudence)

    tenus = [t for t in (detenu or []) if t in set(table["ticker"])]
    hors_univers = [t for t in (detenu or []) if t not in set(table["ticker"])]
    z = dict(zip(table["ticker"], table["z"]))
    rang = dict(zip(table["ticker"], table["rang"]))

    lignes: dict[str, dict] = {}

    def poser(ticker, action, gain, frais, motif, paire=None):
        """LE GAIN ET LE COÛT SONT CEUX DE L'OPÉRATION, PAS DE LA LIGNE.

        Un arbitrage a deux jambes et un seul sens. Porter la moitié du coût
        sur chacune donnait des « net -0,65 % » sur des lignes que le module
        venait de recommander — l'arithmétique était juste, la présentation
        mentait. Les deux jambes portent donc désormais le gain de la PAIRE
        et l'aller-retour complet : un seul chiffre à lire, celui de la
        décision qu'on prend.
        """
        lignes[ticker] = {
            "ticker": ticker, "detenu": ticker in (detenu or []),
            "rang": rang.get(ticker), "action": action, "paire": paire,
            "gain_attendu": gain, "cout": frais,
            "net": (gain - frais) if np.isfinite(gain) else float("nan"),
            "motif": motif,
        }

    # 1. UNE LIGNE QUI A QUITTÉ L'UNIVERS SE VEND SANS ARBITRAGE. Elle n'est
    #    plus classée : trop illiquide, ou plus cotée. Le motif n'est pas un
    #    gain attendu, c'est l'impossibilité d'en sortir plus tard.
    for ticker in hors_univers:
        poser(ticker, "vendre", float("nan"), cout,
              "sortie de l'univers classable : illiquide ou non cotée")

    # 2. PORTEFEUILLE VIDE : il faut bien commencer quelque part, et le coût
    #    d'entrée est payé une fois, pas deux.
    if not tenus:
        for ligne in table.head(positions).itertuples():
            # Un seul passage de frais : on entre, on ne sort de rien.
            poser(ligne.ticker, "acheter", ic * disp * ligne.z, cout,
                  f"{positions} premières du classement, portefeuille à "
                  "constituer")
        rendu = pd.DataFrame(lignes.values())
        return {**vide, "lignes": _finir(rendu, classement), "ic": ic,
                "dispersion": disp, "ecart_minimal": seuil,
                "constitution": sum(1 for l in lignes.values()
                                    if l["action"] == "acheter")}

    # 3. LES ARBITRAGES, du plus prometteur au moins. On s'arrête au premier
    #    qui ne se paie pas : les suivants ont un écart de score plus petit.
    candidates = [t for t in table["ticker"] if t not in set(tenus)]
    sortantes = sorted(tenus, key=lambda t: -rang[t])   # la pire d'abord
    arbitrages = 0
    meilleur = float("nan")
    for sortante in sortantes:
        if not candidates:
            break
        entrante = candidates[0]
        ecart = z[entrante] - z[sortante]
        if not np.isfinite(meilleur) or ecart > meilleur:
            meilleur = ecart
        gain = ic * disp * ecart
        if not (np.isfinite(gain) and gain > 2 * cout):
            break
        poser(sortante, "vendre et remplacer", gain, 2 * cout,
              f"écart de score {ecart:+.2f}, il en faut {seuil:.2f}",
              paire=entrante)
        poser(entrante, "acheter", gain, 2 * cout,
              f"écart de score {ecart:+.2f}, il en faut {seuil:.2f}",
              paire=sortante)
        candidates.pop(0)
        arbitrages += 1

    # 4. TOUT LE RESTE SE CONSERVE, et c'est le cas le plus fréquent.
    for ticker in tenus:
        if ticker in lignes:
            continue
        motif = "aucun arbitrage ne couvre ses frais"
        if np.isfinite(seuil) and np.isfinite(meilleur):
            motif += (f" (meilleur écart disponible {meilleur:+.2f}, "
                      f"il en faudrait {seuil:.2f})")
        poser(ticker, "conserver", ic * disp * z[ticker], 0.0, motif)

    rendu = pd.DataFrame(lignes.values())
    gain_meilleur = (ic * disp * meilleur
                     if np.isfinite(meilleur) and np.isfinite(ic)
                     and np.isfinite(disp) else float("nan"))
    return {**vide, "lignes": _finir(rendu, classement), "ic": ic,
            "dispersion": disp, "ecart_minimal": seuil,
            "arbitrages": arbitrages, "meilleur_arbitrage": meilleur,
            "gain_meilleur": gain_meilleur, "gain_haut": haut,
            "avantage_mesure": float((avantage or {}).get(
                "avantage", float("nan"))),
            "haut_mesure": bool(avantage)}


def _finir(rendu: pd.DataFrame, classement: pd.DataFrame) -> pd.DataFrame:
    """Colonnes dans l'ordre, nom de société joint quand il existe."""
    if rendu.empty:
        return pd.DataFrame(columns=COLONNES)
    if "nom" in classement.columns:
        noms = dict(zip(classement["ticker"], classement["nom"]))
        rendu["nom"] = rendu["ticker"].map(noms)
    else:
        rendu["nom"] = pd.NA
    ordre = {a: i for i, a in enumerate(
        ("vendre", "vendre et remplacer", "acheter", "conserver"))}
    rendu = rendu.sort_values(
        ["action", "rang"], key=lambda c: c.map(ordre) if c.name == "action" else c)
    return rendu[COLONNES].reset_index(drop=True)


def expliquer(resultat: dict) -> str:
    """Rendu texte. Le seuil d'arbitrage n'est jamais séparé de l'action."""
    if resultat["lignes"].empty:
        return ("Aucun conseil : le classement est vide. Il faut un an de "
                "cotation avant que la première valeur soit classable.")

    ic, disp, cout = resultat["ic"], resultat["dispersion"], resultat["cout"]
    seuil = resultat["ecart_minimal"]
    gain = resultat.get("gain_meilleur", float("nan"))

    # LA COMPARAISON D'ABORD, EN POURCENTS, ET LE VOCABULAIRE APRÈS. Deux
    # nombres dans la même unité suffisent à décider : ce qu'un changement
    # rapporterait, ce qu'il coûterait. Le reste — l'écart de score, l'IC, la
    # dispersion — explique d'où ils viennent, et se lit ensuite ou jamais.
    # LES QUATRE NOMBRES SONT ALIGNÉS PAR CONSTRUCTION. Un tableau de
    # comparaison dont les colonnes ne tombent pas ne se compare pas d'un
    # coup d'œil, et c'est tout ce qu'on lui demande.
    LARGEUR = 42

    def comparer(libelle, valeur, suffixe="", signe=True):
        forme = f"{valeur:>+8.2%}" if signe else f"{valeur:>8.2%}"
        return f"  {libelle:<{LARGEUR}}{forme}{suffixe}"

    lignes = [
        "La question est celle de n'importe quel achat : est-ce que ça vaut "
        "ce que ça coûte ?",
        "",
        comparer("changer une ligne pour une autre coûte", 2 * cout,
                 signe=False),
    ]
    if np.isfinite(gain):
        lignes.append(comparer("le meilleur changement possible rapporte", gain))
    else:
        lignes.append(f"  {'le meilleur changement possible rapporte':<{LARGEUR}}"
                      "rien de mesurable")
    # LE MESURÉ ET SON PLANCHER, JAMAIS L'UN POUR L'AUTRE. Écrire « les dix
    # premières ont rapporté -1,19 % » quand elles ont rapporté +1,39 % et
    # que -1,19 % est le bas de leur marge d'erreur serait faux dans les
    # termes : « a rapporté » désigne un constat, pas une borne. Les deux
    # lignes sont donc séparées et nommées.
    mesure_haut = resultat.get("avantage_mesure", float("nan"))
    plancher = resultat.get("gain_haut", float("nan"))
    positions = resultat.get("positions", 10)
    if resultat.get("haut_mesure") and np.isfinite(mesure_haut):
        lignes.append(comparer(
            f"les {positions} premières ont rapporté", mesure_haut,
            "   (constaté hors échantillon)"))
        if np.isfinite(plancher):
            lignes.append(comparer(
                "  dont on peut garantir au moins", plancher,
                "   (bas de sa marge d'erreur)"))
    lignes.append("")
    # DEUX SITUATIONS QU'IL NE FAUT PAS CONFONDRE, et le lecteur ne peut pas
    # les distinguer des seuls pourcents : soit le classement a un avantage
    # que les frais mangent, soit il n'a pas d'avantage du tout. La première
    # se corrige en changeant d'intermédiaire, la seconde non.
    if not np.isfinite(seuil) or seuil == float("inf"):
        lignes += [
            "ET CE N'EST PAS UNE QUESTION DE FRAIS. Les mesures de ce tableau "
            "de bord ne",
            "permettent pas d'affirmer que ce classement ordonne les valeurs "
            "mieux que le",
            "hasard. Même sans frais du tout, rien ne justifierait de vendre "
            "une ligne",
            "pour une autre. Un intermédiaire moins cher ne changerait rien "
            "ici.",
            "",
        ]

    compte = resultat["lignes"]["action"].value_counts()
    if resultat.get("constitution"):
        # Portefeuille à constituer : il n'y a pas d'arbitrage à juger, et le
        # message sur les arbitrages n'a pas lieu d'être.
        lignes += [f"CONSEIL : constituer le portefeuille, "
                   f"{resultat['constitution']} lignes.", ""]
        if not np.isfinite(seuil) or seuil == float("inf"):
            lignes += [
                "MAIS RIEN NE JUSTIFIE DE SE CONCENTRER SUR CELLES-LÀ. Les "
                "mesures de ce",
                "tableau de bord ne permettent pas d'affirmer que ces lignes "
                "valent mieux",
                "qu'un panier plus large du même marché — et un panier plus "
                "large coûte les",
                "mêmes frais en étant moins exposé à une seule valeur qui "
                "déçoit. Ce qui",
                "suit est l'ordre du classement, pas un avantage démontré.",
                "",
            ]
    elif resultat["arbitrages"] == 0:
        lignes += [
            "CONSEIL : NE RIEN FAIRE.",
            "",
            "Ce n'est pas une absence de réponse. Le classement distingue "
            "bien des",
            "valeurs entre elles, mais l'écart qu'il mesure est plus petit "
            "que ce que",
            "coûte le fait d'y réagir. Ici, changer une ligne coûte quelques "
            "POURCENTS",
            "— sur les grandes places, ce serait quelques centièmes de "
            "pourcent — et",
            "l'immobilité est donc la décision la plus souvent correcte.",
            "",
        ]
    else:
        lignes += [f"CONSEIL : {resultat['arbitrages']} arbitrage(s) "
                   "couvrent leurs frais.", ""]

    entete = (f"  {'action':<22}{'ticker':<8}{'rang':>5}{'paire':>8}"
              f"{'gain att.':>11}{'frais':>8}{'net':>9}")
    lignes += [entete, "  " + "-" * (len(entete) - 2)]
    pct = lambda v: "—" if v != v else f"{v:+.2%}"  # noqa: E731
    for ligne in resultat["lignes"].itertuples():
        rang = "—" if ligne.rang != ligne.rang else f"{int(ligne.rang)}"
        paire = "—" if not isinstance(ligne.paire, str) else ligne.paire
        lignes.append(
            f"  {ligne.action:<22}{ligne.ticker:<8}{rang:>5}{paire:>8}"
            f"{pct(ligne.gain_attendu):>11}{ligne.cout:>8.2%}"
            f"{pct(ligne.net):>9}")
    if resultat["arbitrages"]:
        lignes += ["", "Le gain et les frais portés par un arbitrage sont ceux "
                   "de la PAIRE, pas de la ligne : les deux jambes affichent "
                   "le même net, qui est celui de la décision."]
    if "vendre" in compte:
        lignes += ["", "Les lignes « vendre » sans remplacement ont quitté "
                   "l'univers classable : illiquides ou plus cotées. Leur "
                   "motif n'est pas un gain attendu, c'est le risque de ne "
                   "plus pouvoir en sortir."]
    lignes += [
        "",
        "D'où viennent ces deux nombres : le coût est celui que vous avez "
        f"saisi ({cout:.2%} par sens). Ce qu'un changement rapporte est "
        f"estimé à partir de la qualité mesurée du classement (IC "
        f"{ic:+.4f}"
        + (", hypothèse prudente : la borne basse de sa marge d'erreur"
           if resultat["prudence"] else ", estimation moyenne")
        + f") et de l'écart habituel entre les valeurs de ce marché "
        f"({disp:.1%} sur l'horizon du modèle).",
    ]
    if np.isfinite(seuil) and seuil != float("inf"):
        lignes.append(
            f"Exprimé en places de classement, il faut un écart de "
            f"{seuil:.2f} pour qu'un changement se paie ; le meilleur "
            f"disponible vaut {resultat['meilleur_arbitrage']:+.2f}.")
    lignes += ["", "À retenir avant de passer un ordre :"]
    lignes += [f"  - {a}" for a in resultat["avertissements"]]
    return "\n".join(lignes)
