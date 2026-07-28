"""Simulation historique du classement produit par `scoring`.

CE QUE CE MODULE NE PEUT PAS VOUS DIRE
--------------------------------------
Trois biais lui survivent, et aucun n'est corrigeable avec les données dont
le projet dispose. Ils sont rappelés dans `AVERTISSEMENTS`, qui accompagne
chaque résultat — pour qu'un chiffre flatteur ne circule jamais sans eux.

1. BIAIS DU SURVIVANT. Le référentiel liste les sociétés cotées
   aujourd'hui. Une société radiée entre-temps a disparu de l'univers, y
   compris des périodes où elle cotait encore — et elle a généralement été
   radiée après avoir mal fini. Le passé simulé est donc celui des
   survivants, et il est plus beau que le vrai.

2. PAS DE DIVIDENDES. La table `cours` porte des cours nus. Sur la BRVM,
   où les rendements dépassent souvent 5 %, les ignorer sous-estime la
   performance de toutes les stratégies — et pénalise doublement les
   valeurs de rendement, celles-là mêmes que le momentum délaisse.

3. FRAIS ESTIMÉS. Commissions et impact sont des paramètres, pas des
   relevés de courtage. Ils sont pris par défaut du côté prudent.

CE QU'IL PROTÈGE, EN REVANCHE
-----------------------------
Le regard en avant, qui est l'erreur qui transforme une stratégie médiocre
en courbe magnifique. Deux garde-fous :

- la décision d'une date `t` ne voit que les cours jusqu'à `t` inclus, le
  classement étant recalculé sur une tranche coupée à `t` ;
- l'exécution est retardée d'une séance : on décide sur la clôture de `t`,
  on achète à celle de `t+1`. Décider et exécuter au même cours revient à
  passer un ordre à un prix déjà connu.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import dividende, features, scoring
from .config import charger

AVERTISSEMENTS = (
    "univers restreint aux sociétés cotées aujourd'hui (biais du survivant)",
    "dividendes non pris en compte",
    "frais et impact estimés, non relevés",
)

# Le même jeu, quand le dividende EST pris en compte. Le deuxième
# avertissement change de nature plutôt que de disparaître : la
# correction est partielle et approximée, et le taire serait pire que
# l'ancien aveu d'ignorance.
AVERTISSEMENTS_AVEC_DIVIDENDES = (
    "univers restreint aux sociétés cotées aujourd'hui (biais du survivant)",
    "dividende réparti sur l'exercice faute de date de détachement, et "
    "connu sur une partie seulement de la période",
    "frais et impact estimés, non relevés",
)

COLONNES = ["date_decision", "date_entree", "date_sortie", "positions",
            "rendement", "dividende", "rotation", "cout", "valeur",
            "valeur_reference"]


def _perte_max(valeurs: pd.Series) -> float:
    """Plus forte baisse depuis un sommet, en proportion.

    Le chiffre qui décide si une stratégie est tenable : un rendement
    annuel de 15 % assorti d'une perte maximale de 60 % ne se garde pas
    jusqu'au bout, et une stratégie qu'on abandonne au creux ne rapporte
    pas ce que le backtest annonce.
    """
    if valeurs.empty:
        return float("nan")
    sommets = valeurs.cummax()
    return float((valeurs / sommets - 1).min())


def _annualiser(valeur_finale: float, seances: int) -> float:
    if seances <= 0 or valeur_finale <= 0:
        return float("nan")
    return float(valeur_finale ** (features.SEANCES_PAR_AN / seances) - 1)


def backtester(
    cours: pd.DataFrame,
    referentiel: pd.DataFrame | None = None,
    reglages: dict | None = None,
    fondamentaux: pd.DataFrame | None = None,
) -> dict:
    """Rejoue le classement dans le temps. Renvoie mesures et journal.

    Le journal (`etapes`) porte une ligne par rééquilibrage, avec les dates
    de décision, d'entrée et de sortie : c'est lui qu'on relit quand un
    résultat paraît trop beau.
    """
    conf = reglages or charger()
    bt = conf.get("backtest", {})
    positions = int(bt.get("positions", 10))
    pas = int(bt.get("pas_rebalancement", 20))
    delai = int(bt.get("delai_execution", 1))
    cout_unitaire = (
        float(bt.get("frais_pourcent", 1.0)) + float(bt.get("impact_pourcent", 0.5))
    ) / 100.0

    prix = features.serie(cours)
    dates = list(prix.index)
    # Le dividende vaut 7 à 10 % l'an sur ce marché quand le cours en rend
    # 2,8 : l'ignorer ne biaise pas le résultat à la marge, il en change
    # l'ordre de grandeur. `accroissement` le répartit sur les séances de
    # son exercice — voir `dividende` pour ce que cette convention
    # approxime et ce qu'elle ne peut pas rendre.
    accru = dividende.accroissement(cours, fondamentaux) \
        if fondamentaux is not None and not fondamentaux.empty else None
    couverture = dividende.couverture(cours, fondamentaux) \
        if accru is not None else None
    avertissements = (AVERTISSEMENTS_AVEC_DIVIDENDES if accru is not None
                      else AVERTISSEMENTS)
    besoin = int(conf.get("analyse", {}).get("fenetre_momentum", 250)) + 1

    vide = {
        "etapes": pd.DataFrame(columns=COLONNES),
        "seances": len(dates),
        "seances_requises": besoin + delai + pas,
        "avertissements": avertissements,
        "couverture_dividende": couverture,
    }
    if len(dates) < besoin + delai + pas:
        return vide

    # Une seule passe glissante, comme dans prediction : le backtest
    # recalculait sinon tous les traits à chaque rééquilibrage.
    matrices = features.traits_glissants(cours, conf)

    etapes: list[dict] = []
    detenu: set[str] = set()
    valeur = 1.0
    valeur_prix = 1.0
    valeur_reference = 1.0

    for i in range(besoin - 1, len(dates) - delai - 1, pas):
        entree = i + delai
        sortie = min(i + delai + pas, len(dates) - 1)
        if sortie <= entree:
            break

        # Décision : les traits de la date `i` ne sont fabriqués que de
        # cours antérieurs ou égaux, par construction des fenêtres
        # glissantes. Rien de ce qui suit ne peut influencer le choix.
        traits = pd.DataFrame(
            {nom: matrices[nom].loc[dates[i]]
             for nom in ["cloture", *features.TRAITS]}
        )
        traits.index.name = "ticker"
        classement = scoring.noter(traits, referentiel, conf)
        if classement.empty:
            continue

        choisis = list(classement.head(positions)["ticker"])
        eligibles = list(classement["ticker"])

        depart = prix.iloc[entree]
        arrivee = prix.iloc[sortie]
        rendements = (arrivee / depart - 1).replace([np.inf, -np.inf], np.nan)

        gain_prix = float(rendements.reindex(choisis).dropna().mean())
        if np.isnan(gain_prix):
            continue

        # Le dividende accru pendant la détention, de l'entrée à la sortie.
        gain_dividende = 0.0
        appoint_reference = 0.0
        if accru is not None:
            tranche = accru.iloc[entree:sortie]
            gain_dividende = float(tranche[choisis].sum().mean())
            appoint_reference = float(
                tranche[[t for t in eligibles if t in tranche.columns]]
                .sum().mean())
        gain = gain_prix + gain_dividende

        gain_reference = float(rendements.reindex(eligibles).dropna().mean())
        if not np.isnan(gain_reference):
            gain_reference += appoint_reference

        # Chaque ligne remplacée est vendue puis rachetée : deux passages
        # de frais sur la fraction renouvelée.
        nouveaux = set(choisis)
        rotation = (
            len(nouveaux - detenu) / len(nouveaux) if nouveaux else 0.0
        )
        cout = rotation * cout_unitaire * 2
        detenu = nouveaux

        valeur *= 1 + gain - cout
        valeur_prix *= 1 + gain_prix - cout
        valeur_reference *= 1 + (
            gain_reference if not np.isnan(gain_reference) else 0.0
        )

        etapes.append({
            "date_decision": dates[i],
            "date_entree": dates[entree],
            "date_sortie": dates[sortie],
            "positions": ", ".join(choisis),
            "rendement": gain_prix,
            "dividende": gain_dividende,
            "rotation": rotation,
            "cout": cout,
            "valeur": valeur,
            "valeur_reference": valeur_reference,
        })

    journal = pd.DataFrame(etapes, columns=COLONNES)
    if journal.empty:
        return vide

    seances = len(dates) - (besoin - 1)
    return {
        "etapes": journal,
        "seances": len(dates),
        "rebalancements": len(journal),
        "rendement_total": valeur - 1,
        "rendement_annualise": _annualiser(valeur, seances),
        "rendement_prix": valeur_prix - 1,
        "rendement_prix_annualise": _annualiser(valeur_prix, seances),
        "apport_dividende": valeur - valeur_prix,
        "reference_total": valeur_reference - 1,
        "reference_annualisee": _annualiser(valeur_reference, seances),
        "perte_max": _perte_max(journal["valeur"]),
        "perte_max_reference": _perte_max(journal["valeur_reference"]),
        "rotation_moyenne": float(journal["rotation"].mean()),
        "cout_cumule": float(journal["cout"].sum()),
        "avertissements": avertissements,
        "couverture_dividende": couverture,
    }


def expliquer(resultat: dict) -> str:
    """Rendu texte, avertissements compris — ils ne sont pas optionnels."""
    if resultat["etapes"].empty:
        return (
            f"Backtest impossible : {resultat['seances']} séances en base, "
            f"{resultat['seances_requises']} nécessaires. Le momentum se "
            "mesure sur un an ; il faut au moins cela avant la première "
            "décision, plus une période à mesurer ensuite."
        )

    pct = lambda x: "—" if pd.isna(x) else f"{x:+.1%}"  # noqa: E731
    lignes = [
        f"{resultat['rebalancements']} rééquilibrages sur "
        f"{resultat['seances']} séances",
        "",
    ]
    couverture = resultat.get("couverture_dividende")
    if couverture:
        lignes += [
            f"Dividende compté sur {couverture['part']:.0%} des séances "
            f"(exercices {', '.join(couverture['exercices'])}) ; il apporte "
            f"{pct(resultat.get('apport_dividende'))} au total.",
            f"Sans lui, la stratégie rendrait "
            f"{pct(resultat.get('rendement_prix_annualise'))} l'an au lieu de "
            f"{pct(resultat['rendement_annualise'])}.",
            "",
        ]
    lignes += [
        f"{'':<22}{'stratégie':>12}{'référence':>12}",
        f"{'rendement total':<22}{pct(resultat['rendement_total']):>12}"
        f"{pct(resultat['reference_total']):>12}",
        f"{'annualisé':<22}{pct(resultat['rendement_annualise']):>12}"
        f"{pct(resultat['reference_annualisee']):>12}",
        f"{'perte maximale':<22}{pct(resultat['perte_max']):>12}"
        f"{pct(resultat['perte_max_reference']):>12}",
        "",
        f"rotation moyenne       {resultat['rotation_moyenne']:.0%}",
        f"coût cumulé            {resultat['cout_cumule']:.1%}",
        "",
        "La référence est l'univers éligible équipondéré : c'est elle qu'il",
        "faut battre, pas zéro.",
        "",
        "À retenir avant de citer ces chiffres :",
    ]
    lignes += [f"  - {a}" for a in resultat["avertissements"]]
    return "\n".join(lignes)
