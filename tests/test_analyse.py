"""Traits et scoring, sur des séries fabriquées.

Pourquoi pas sur des données réelles : la base ne contient qu'une séance,
celle du 27/07/2026. Aucun momentum n'existe encore, et il faudra des
années avant qu'un backtest signifie quelque chose.

Ces tests ne disent donc pas que la stratégie gagne — ils ne peuvent pas.
Ils disent que le calcul fait ce qu'il annonce, sur des séries dont la
bonne réponse se pose à la main. C'est la seule chose vérifiable
aujourd'hui, et c'est celle qui casse en silence si on ne la fige pas.

    python tests/test_analyse.py
    pytest tests/test_analyse.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
os.environ.setdefault(
    "BRVM_BASE", str(Path(tempfile.gettempdir()) / "brvm_tests.db")
)

import pandas as pd  # noqa: E402

from brvm import features, scoring  # noqa: E402

REGLAGES = {
    "analyse": {
        "volume_median_min_fcfa": 1_000_000,
        "fenetre_momentum": 250, "saut_momentum": 20,
        "fenetre_volatilite": 60, "fenetre_liquidite": 60,
        "moyenne_courte": 20, "moyenne_longue": 100,
        "min_par_secteur": 5,
    },
    "ponderations": {"momentum": 0.5, "tendance": 0.3, "volatilite": -0.2},
}


def _cours(series: dict[str, list[float]], volume_fcfa: float = 5_000_000):
    """Table `cours` fabriquée à partir d'une trajectoire par ticker."""
    lignes = []
    for ticker, prix in series.items():
        for rang, valeur in enumerate(prix):
            lignes.append({
                "date": f"2026-{1 + rang // 28:02d}-{1 + rang % 28:02d}",
                "ticker": ticker,
                "cloture": valeur,
                "volume_titres": 100.0,
                "volume_fcfa": volume_fcfa,
            })
    # La date fabriquée ci-dessus n'est pas un calendrier réel, mais elle
    # est croissante et unique, ce qui suffit : les fenêtres se comptent en
    # séances, pas en jours.
    return pd.DataFrame(lignes).sort_values(["date", "ticker"])


def test_momentum_saute_le_dernier_mois():
    """Le piège que le saut existe pour éviter.

    Une valeur qui monte toute l'année puis s'effondre sur les trois
    dernières semaines doit garder un momentum POSITIF : le retournement de
    court terme n'est pas censé entrer dans la mesure. Sans le saut, cette
    valeur serait notée comme une valeur en baisse, et le classement
    achèterait systématiquement les hausses les plus fraîches — les plus
    fragiles.
    """
    hausse = [100.0 * (1.004 ** i) for i in range(251)]   # ~×2,7 sur l'année
    effondrement = hausse[:231] + [hausse[230] * (0.97 ** i) for i in range(1, 21)]

    prix = features.serie(_cours({"AAAA": effondrement}))
    mom = features.momentum(prix, fenetre=250, saut=20)["AAAA"]

    attendu = effondrement[-21] / effondrement[0] - 1
    assert abs(mom - attendu) < 1e-9
    assert mom > 1.0, "le krach des 20 dernières séances a contaminé le momentum"


def test_historique_insuffisant_ne_produit_pas_de_score():
    """Trois semaines de cotation ne donnent pas un momentum à un an.

    L'échec doit être un NaN qui exclut la valeur, pas un nombre calculé
    « sur ce qu'on a » — celui-ci se classerait comme un vrai momentum.
    """
    court = _cours({"AAAA": [100.0 + i for i in range(15)]})
    traits = features.calculer(court, REGLAGES)

    assert traits["momentum"].isna().all()
    assert traits["tendance"].isna().all()
    assert scoring.noter(traits, None, REGLAGES).empty


def test_liquidite_mediane_et_manquants_a_zero():
    """Une transaction de bloc isolée ne rend pas une valeur liquide."""
    dormante = _cours({"AAAA": [100.0] * 60}, volume_fcfa=0.0)
    # Une seule séance très active au milieu d'un désert.
    dormante.loc[dormante.index[30], "volume_fcfa"] = 900_000_000.0

    liq = features.liquidite(dormante, fenetre=60)["AAAA"]
    assert liq == 0.0, f"médiane {liq} : la moyenne aurait été trompeuse"


def test_le_filtre_de_liquidite_agit_avant_la_notation():
    """Une valeur illiquide ne doit pas non plus servir à noter les autres.

    Écartée après coup, elle occuperait un rang et décalerait le centile de
    toutes les autres. Le test le vérifie en comparant les scores obtenus
    avec et sans elle dans la table de départ.
    """
    trajectoires = {
        f"T{i:03d}": [100.0 * (1 + 0.002 * i) ** j for j in range(251)]
        for i in range(6)
    }
    liquides = _cours(trajectoires, volume_fcfa=5_000_000)
    illiquide = _cours({"ZZZZ": [100.0] * 251}, volume_fcfa=1_000.0)

    avec = scoring.noter(
        features.calculer(pd.concat([liquides, illiquide]), REGLAGES),
        None, REGLAGES,
    )
    sans = scoring.noter(features.calculer(liquides, REGLAGES), None, REGLAGES)

    assert "ZZZZ" not in set(avec["ticker"])
    obtenus = avec.set_index("ticker")["score"].round(6)
    attendus = sans.set_index("ticker")["score"].round(6)
    assert obtenus.to_dict() == attendus.to_dict(), (
        "la valeur illiquide a influencé les rangs avant d'être écartée"
    )


def test_le_classement_suit_le_momentum():
    """Toutes choses égales par ailleurs, plus de momentum vaut mieux."""
    trajectoires = {
        f"T{i:03d}": [100.0 * (1 + 0.001 * i) ** j for j in range(251)]
        for i in range(1, 7)
    }
    classement = scoring.noter(
        features.calculer(_cours(trajectoires), REGLAGES), None, REGLAGES
    )
    assert list(classement["ticker"]) == [f"T{i:03d}" for i in range(6, 0, -1)]


def test_neutralisation_sectorielle():
    """Un secteur porté ne doit pas confisquer tout le haut du classement.

    Seize bancaires sur quarante-sept : sans neutralisation, une année
    faste du secteur suffirait à remplir le portefeuille de banques, et ce
    qui se présente comme une sélection de valeurs serait un pari
    sectoriel déguisé.
    """
    fort = {f"F{i:03d}": [100.0 * (1 + 0.003 + 0.0001 * i) ** j
                          for j in range(251)] for i in range(6)}
    faible = {f"W{i:03d}": [100.0 * (1 + 0.0001 * i) ** j
                            for j in range(251)] for i in range(6)}
    cours = _cours({**fort, **faible})

    referentiel = pd.DataFrame(
        [{"ticker": t, "nom": t, "secteur": "Fort"} for t in fort]
        + [{"ticker": t, "nom": t, "secteur": "Faible"} for t in faible]
    )
    traits = features.calculer(cours, REGLAGES)

    sans = scoring.noter(traits, None, REGLAGES)
    assert set(sans.head(6)["ticker"]) == set(fort), (
        "sans secteur, le secteur porté rafle bien les six premières places"
    )

    avec = scoring.noter(traits, referentiel, REGLAGES)
    tete = set(avec.head(6)["ticker"])
    assert tete & set(faible), "la neutralisation n'a rien changé"
    assert tete & set(fort)


def test_un_secteur_trop_petit_est_note_face_au_marche():
    """Comparer entre elles les deux seules sociétés de services publics
    n'a aucun sens : en deçà de `min_par_secteur`, pas de neutralisation."""
    trajectoires = {
        f"T{i:03d}": [100.0 * (1 + 0.001 * i) ** j for j in range(251)]
        for i in range(1, 8)
    }
    cours = _cours(trajectoires)
    referentiel = pd.DataFrame([
        {"ticker": t, "nom": t, "secteur": "Minuscule" if t in ("T001", "T002")
         else "Grand"}
        for t in trajectoires
    ])
    traits = features.calculer(cours, REGLAGES)

    avec = scoring.noter(traits, referentiel, REGLAGES).set_index("ticker")
    sans = scoring.noter(traits, None, REGLAGES).set_index("ticker")

    # Les deux du secteur minuscule gardent le score du marché.
    for ticker in ("T001", "T002"):
        assert abs(avec.loc[ticker, "score"] - sans.loc[ticker, "score"]) < 1e-9


def test_sortie_lisible_quand_rien_n_est_classable():
    """Le message doit dire quoi faire, pas seulement que c'est vide."""
    message = scoring.expliquer(scoring.noter(pd.DataFrame(), None, REGLAGES))
    assert "historique trop court" in message and "brvm etat" in message


if __name__ == "__main__":
    echecs = 0
    for nom, fonction in sorted(globals().items()):
        if not nom.startswith("test_"):
            continue
        try:
            fonction()
            print(f"  ok    {nom}")
        except AssertionError as erreur:
            echecs += 1
            print(f"  ÉCHEC {nom}\n        {erreur}")
    print(f"\n{'tout passe' if not echecs else f'{echecs} échec(s)'}")
    sys.exit(1 if echecs else 0)
