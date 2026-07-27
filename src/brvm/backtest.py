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

from . import features, scoring
from .config import charger

AVERTISSEMENTS = (
    "univers restreint aux sociétés cotées aujourd'hui (biais du survivant)",
    "dividendes non pris en compte",
    "frais et impact estimés, non relevés",
)

COLONNES = ["date_decision", "date_entree", "date_sortie", "positions",
            "rendement", "rotation", "cout", "valeur", "valeur_reference"]


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
    besoin = int(conf.get("analyse", {}).get("fenetre_momentum", 250)) + 1

    vide = {
        "etapes": pd.DataFrame(columns=COLONNES),
        "seances": len(dates),
        "seances_requises": besoin + delai + pas,
        "avertissements": AVERTISSEMENTS,
    }
    if len(dates) < besoin + delai + pas:
        return vide

    etapes: list[dict] = []
    detenu: set[str] = set()
    valeur = 1.0
    valeur_reference = 1.0

    for i in range(besoin - 1, len(dates) - delai - 1, pas):
        entree = i + delai
        sortie = min(i + delai + pas, len(dates) - 1)
        if sortie <= entree:
            break

        # Décision : la tranche est coupée à la date `i`, donc rien de ce
        # qui suit ne peut influencer le choix.
        tranche = cours[cours["date"] <= dates[i]]
        classement = scoring.noter(
            features.calculer(tranche, conf), referentiel, conf
        )
        if classement.empty:
            continue

        choisis = list(classement.head(positions)["ticker"])
        eligibles = list(classement["ticker"])

        depart = prix.iloc[entree]
        arrivee = prix.iloc[sortie]
        rendements = (arrivee / depart - 1).replace([np.inf, -np.inf], np.nan)

        gain = float(rendements.reindex(choisis).dropna().mean())
        gain_reference = float(rendements.reindex(eligibles).dropna().mean())
        if np.isnan(gain):
            continue

        # Chaque ligne remplacée est vendue puis rachetée : deux passages
        # de frais sur la fraction renouvelée.
        nouveaux = set(choisis)
        rotation = (
            len(nouveaux - detenu) / len(nouveaux) if nouveaux else 0.0
        )
        cout = rotation * cout_unitaire * 2
        detenu = nouveaux

        valeur *= 1 + gain - cout
        valeur_reference *= 1 + (
            gain_reference if not np.isnan(gain_reference) else 0.0
        )

        etapes.append({
            "date_decision": dates[i],
            "date_entree": dates[entree],
            "date_sortie": dates[sortie],
            "positions": ", ".join(choisis),
            "rendement": gain,
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
        "reference_total": valeur_reference - 1,
        "reference_annualisee": _annualiser(valeur_reference, seances),
        "perte_max": _perte_max(journal["valeur"]),
        "perte_max_reference": _perte_max(journal["valeur_reference"]),
        "rotation_moyenne": float(journal["rotation"].mean()),
        "cout_cumule": float(journal["cout"].sum()),
        "avertissements": AVERTISSEMENTS,
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
