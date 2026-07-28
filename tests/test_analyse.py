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


def test_les_traits_glissants_redonnent_les_traits_ponctuels():
    """L'optimisation ne doit pas déplacer un seul chiffre.

    Les traits sont désormais calculés en une passe glissante sur toute la
    matrice au lieu d'être refaits date par date — 0,05 s au lieu de 9,75 s
    sur 400 séances. Une accélération de ce facteur n'a aucune valeur si
    elle change les nombres, et l'écart serait indétectable à l'œil : ce
    test compare les deux chemins sur un échantillon de dates.

    Les fonctions ponctuelles `momentum`, `tendance`, `volatilite` et
    `liquidite` sont conservées pour cela — elles sont la définition de
    référence contre laquelle la version rapide est mesurée.
    """
    import numpy as np

    from brvm import features

    rng = np.random.default_rng(4)
    n = 160
    trajectoires = {
        f"T{i:02d}": 100 * np.exp(np.cumsum(rng.normal(0, 0.015, n)))
        for i in range(6)
    }
    cours = _cours(trajectoires, volume_fcfa=3_000_000)
    reglages = {"analyse": {"fenetre_momentum": 60, "saut_momentum": 5,
                            "fenetre_volatilite": 20, "fenetre_liquidite": 20,
                            "moyenne_courte": 5, "moyenne_longue": 20}}

    f = features._fenetres(reglages)
    matrices = features.traits_glissants(cours, reglages)
    dates = sorted(cours["date"].unique())

    compares = 0
    for date in dates[::17]:
        tranche = cours[cours["date"] <= date]
        prix = features.serie(tranche)
        ponctuels = {
            "momentum": features.momentum(prix, f["fenetre_momentum"],
                                          f["saut_momentum"]),
            "tendance": features.tendance(prix, f["moyenne_courte"],
                                          f["moyenne_longue"]),
            "volatilite": features.volatilite(prix, f["fenetre_volatilite"]),
            "liquidite": features.liquidite(tranche, f["fenetre_liquidite"]),
        }
        for nom, attendu in ponctuels.items():
            obtenu = matrices[nom].loc[date]
            attendu = attendu.reindex(obtenu.index)
            # Les manquants doivent manquer aux mêmes endroits : un trait
            # calculé « sur ce qu'on a » là où l'ancien refusait serait une
            # régression silencieuse.
            assert (attendu.isna() == obtenu.isna()).all(), (
                f"{date} {nom} : motifs de valeurs manquantes différents"
            )
            deux = attendu.notna() & obtenu.notna()
            if deux.any():
                ecart = float((attendu[deux] - obtenu[deux]).abs().max())
                assert ecart < 1e-9, f"{date} {nom} : écart {ecart:.2e}"
        compares += 1

    assert compares >= 5


def test_une_societe_radiee_ne_disparait_pas_du_referentiel():
    """Le biais du survivant, arrêté à la source.

    Le référentiel était réécrit depuis l'instantané du jour : une société
    radiée perdait sa ligne, son nom et son secteur — y compris pour les
    années où elle cotait. Le passé simulé devenait celui des seuls
    survivants. Cette information ne se reconstitue jamais après coup,
    d'où la règle : on fusionne, on n'efface pas.
    """
    from brvm import db

    hier = pd.DataFrame([
        {"ticker": "AAAA", "nom": "Alpha", "secteur": "Industriels"},
        {"ticker": "BBBB", "nom": "Beta", "secteur": "Energie"},
    ])
    fusion, _ = db.fusionner_referentiel(pd.DataFrame(), hier, "2026-01-05")
    assert set(fusion["ticker"]) == {"AAAA", "BBBB"}
    assert (fusion["premiere_vue"] == "2026-01-05").all()

    # BBBB quitte la cote ; AAAA reste ; CCCC entre.
    aujourdhui = pd.DataFrame([
        {"ticker": "AAAA", "nom": "Alpha", "secteur": "Industriels"},
        {"ticker": "CCCC", "nom": "Gamma", "secteur": "Energie"},
    ])
    fusion, changements = db.fusionner_referentiel(fusion, aujourdhui,
                                                   "2026-06-30")
    par_ticker = fusion.set_index("ticker")

    assert "BBBB" in par_ticker.index, "la société radiée a été effacée"
    assert par_ticker.at["BBBB", "derniere_vue"] == "2026-01-05"
    assert par_ticker.at["BBBB", "nom"] == "Beta"
    assert par_ticker.at["AAAA", "premiere_vue"] == "2026-01-05"
    assert par_ticker.at["AAAA", "derniere_vue"] == "2026-06-30"
    assert par_ticker.at["CCCC", "premiere_vue"] == "2026-06-30"

    assert any("BBBB" in c and "absente" in c for c in changements)
    assert any("CCCC" in c and "entrée" in c for c in changements)


def test_un_reclassement_sectoriel_est_signale():
    """Reclasser une valeur sans le dire réécrit rétroactivement la
    composition des secteurs — donc la neutralisation sectorielle de tout
    l'historique, sans qu'aucun chiffre ne bouge visiblement."""
    from brvm import db

    connu, _ = db.fusionner_referentiel(
        pd.DataFrame(),
        pd.DataFrame([{"ticker": "AAAA", "nom": "Alpha",
                       "secteur": "Industriels"}]),
        "2026-01-05",
    )
    _, changements = db.fusionner_referentiel(
        connu,
        pd.DataFrame([{"ticker": "AAAA", "nom": "Alpha",
                       "secteur": "Energie"}]),
        "2026-06-30",
    )
    assert any("reclassement" in c and "Industriels" in c and "Energie" in c
               for c in changements), changements


def test_les_dates_manquantes_viennent_des_cours():
    """Migration d'un référentiel non daté : la première et la dernière
    séance où un ticker apparaît sont une donnée réelle, meilleure que la
    date du jour où l'on a commencé à dater."""
    from brvm import db

    cours = _cours({"AAAA": [100.0] * 5, "BBBB": [50.0] * 5})
    ref = pd.DataFrame([{"ticker": "AAAA", "nom": "Alpha", "secteur": "X"}])
    date = db.dater_depuis_les_cours(ref, cours).set_index("ticker")

    bornes = cours[cours["ticker"] == "AAAA"]["date"]
    assert date.at["AAAA", "premiere_vue"] == bornes.min()
    assert date.at["AAAA", "derniere_vue"] == bornes.max()


def test_l_archive_se_lit_sans_base():
    """Le chemin de la web app : lire le CSV sans créer de SQLite.

    Sur un hébergeur gratuit le conteneur est éphémère et son disque ne
    survit pas ; y ouvrir une base donnerait une app affichant des données
    que personne ne pourrait retrouver ailleurs.
    """
    from brvm import db

    colonnes = db._colonnes_declarees("cours")
    assert colonnes == ["date", "ticker", "ouverture", "haut", "bas",
                        "cloture", "volume_titres", "volume_fcfa"]
    # premiere_vue / derniere_vue datent l'appartenance à la cote : sans
    # elles, une société radiée disparaîtrait du passé qu'elle a vécu.
    assert db._colonnes_declarees("referentiel") == [
        "ticker", "nom", "secteur", "premiere_vue", "derniere_vue"]

    with tempfile.TemporaryDirectory() as dossier:
        config = Path(dossier) / "c.toml"
        archive = Path(dossier) / "cours.csv"
        config.write_text(
            f'[base]\narchive_cours = "{archive.as_posix()}"\n', encoding="utf-8"
        )
        ancien = os.environ.get("BRVM_CONFIG")
        os.environ["BRVM_CONFIG"] = str(config)
        try:
            # Archive absente : tableau vide aux bonnes colonnes, pas d'erreur.
            vide = db.charger_archive("cours")
            assert vide.empty and list(vide.columns) == colonnes

            pd.DataFrame([{"date": "2026-07-27", "ticker": "SNTS",
                           "cloture": 31010.0}]).to_csv(archive, index=False)
            lu = db.charger_archive("cours")
            assert len(lu) == 1 and lu.iloc[0]["ticker"] == "SNTS"
            # Date et ticker doivent rester du texte : lus en nombres,
            # « 2026-07-27 » deviendrait une date locale et un ticker
            # numérique perdrait ses zéros de tête.
            assert pd.api.types.is_string_dtype(lu["date"])
            assert pd.api.types.is_string_dtype(lu["ticker"])
        finally:
            if ancien is None:
                del os.environ["BRVM_CONFIG"]
            else:
                os.environ["BRVM_CONFIG"] = ancien


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
