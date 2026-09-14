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
            "meilleur_arbitrage": float("nan"), "positions": positions,
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
    return {**vide, "lignes": _finir(rendu, classement), "ic": ic,
            "dispersion": disp, "ecart_minimal": seuil,
            "arbitrages": arbitrages, "meilleur_arbitrage": meilleur}


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
    lignes = [
        f"Frais retenus : {cout:.2%} par sens, soit {2 * cout:.2%} "
        "l'aller-retour.",
        f"IC employé : {ic:+.4f}"
        + (" (borne basse de l'intervalle à 95 %, estimation prudente)"
           if resultat["prudence"] else " (estimation ponctuelle)")
        + f" ; dispersion transversale {disp:.1%}.",
        "",
    ]
    if not np.isfinite(seuil) or seuil == float("inf"):
        lignes += [
            "AUCUN ARBITRAGE NE PEUT SE PAYER, quel que soit le classement.",
            "L'IC prudent est nul ou négatif : la preuve ne permet pas "
            "d'affirmer",
            "que le classement ordonne mieux que le hasard, et un coût "
            "certain ne",
            "s'engage pas contre un gain qui n'est pas établi.",
            "",
        ]
    else:
        lignes += [
            f"Écart de score minimal pour qu'un arbitrage se paie : "
            f"{seuil:.2f}.",
            f"Meilleur écart réellement disponible : "
            f"{resultat['meilleur_arbitrage']:+.2f}.",
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
                "MAIS LE CLASSEMENT NE JUSTIFIE PAS DE SE CONCENTRER. L'IC "
                "prudent étant nul",
                "ou négatif, rien n'établit que ces lignes-là valent mieux "
                "qu'un panier large",
                "du même univers — et un panier large coûte les mêmes frais "
                "en étant moins",
                "exposé à une valeur qui déçoit. Ce qui suit est l'ordre du "
                "classement, pas",
                "un avantage démontré.",
                "",
            ]
    elif resultat["arbitrages"] == 0:
        lignes += [
            "CONSEIL : NE RIEN FAIRE.",
            "",
            "Ce n'est pas une absence de réponse. Le classement distingue "
            "bien des",
            "valeurs, mais l'écart qu'il mesure entre elles est plus petit "
            "que ce que",
            "coûte le fait d'y réagir. Sur cette place, où l'aller-retour se "
            "compte en",
            "pourcents et non en points de base, l'inaction est la décision "
            "la plus",
            "souvent correcte.",
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
    lignes += ["", "À retenir avant de passer un ordre :"]
    lignes += [f"  - {a}" for a in resultat["avertissements"]]
    return "\n".join(lignes)
