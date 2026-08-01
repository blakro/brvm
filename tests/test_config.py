"""La configuration : des défauts utilisables, une fusion clé à clé.

Le parti pris à protéger : un fichier de configuration est FACULTATIF, et
déclarer un seul réglage ne doit pas faire perdre les autres. Une fusion
section par section — au lieu de clé à clé — écraserait silencieusement
dix-neuf réglages sur vingt, et le projet tournerait avec des fenêtres par
défaut sans que rien ne le dise.
"""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from brvm import config  # noqa: E402


def test_sans_fichier_tout_a_un_defaut(monkeypatch, tmp_path):
    """Un projet qui refuse de démarrer sans config.toml oblige à recopier
    un exemple avant de pouvoir lancer le diagnostic — or c'est le
    diagnostic qu'on veut lancer en premier quand rien ne va."""
    monkeypatch.setenv("BRVM_CONFIG", str(tmp_path / "absent.toml"))
    reglages = config.charger()
    assert reglages["analyse"]["fenetre_momentum"] == 250
    assert reglages["backtest"]["positions"] == 10
    assert reglages["ponderations"]["volatilite"] < 0


def test_un_reglage_declare_ne_fait_pas_perdre_les_autres(monkeypatch, tmp_path):
    fichier = tmp_path / "config.toml"
    fichier.write_text("[analyse]\nfenetre_momentum = 120\n")
    monkeypatch.setenv("BRVM_CONFIG", str(fichier))
    analyse = config.charger()["analyse"]
    assert analyse["fenetre_momentum"] == 120
    assert analyse["saut_momentum"] == 20, "les autres réglages ont sauté"
    assert "volume_median_min_fcfa" in analyse


def test_une_section_absente_du_fichier_garde_ses_defauts(monkeypatch, tmp_path):
    fichier = tmp_path / "config.toml"
    fichier.write_text("[analyse]\nfenetre_momentum = 120\n")
    monkeypatch.setenv("BRVM_CONFIG", str(fichier))
    assert config.charger()["backtest"]["pas_rebalancement"] == 60


def test_charger_ne_rend_jamais_la_meme_instance(monkeypatch, tmp_path):
    """Les défauts sont copiés en profondeur : un appelant qui modifie ce
    qu'il reçoit ne doit pas contaminer l'appel suivant."""
    monkeypatch.setenv("BRVM_CONFIG", str(tmp_path / "absent.toml"))
    premier = config.charger()
    premier["analyse"]["fenetre_momentum"] = 1
    assert config.charger()["analyse"]["fenetre_momentum"] == 250


def test_le_chemin_de_base_prime_par_l_environnement(monkeypatch, tmp_path):
    """`BRVM_BASE` existe pour les tests et les exécutions jetables : sans
    elle, une suite de tests qui ingère écrirait dans la base du projet."""
    monkeypatch.setenv("BRVM_BASE", str(tmp_path / "jetable.db"))
    assert config.chemin_base() == tmp_path / "jetable.db"


def test_un_chemin_relatif_est_resolu_depuis_la_racine(monkeypatch):
    """Le cron ne s'exécute pas forcément depuis la racine, et une base
    créée au hasard des répertoires est une base perdue."""
    monkeypatch.setenv("BRVM_BASE", "data/essai.db")
    chemin = config.chemin_base()
    assert chemin.is_absolute()
    assert chemin == config.RACINE / "data" / "essai.db"


def test_l_exemple_livre_ne_declare_rien_d_inconnu():
    """`config.exemple.toml` sert de documentation : une section ou une
    clé qui n'existe plus y resterait sans que rien ne le signale."""
    import tomllib
    exemple = tomllib.loads((config.RACINE / "config.exemple.toml").read_text())
    for section, valeurs in exemple.items():
        assert section in config.DEFAUTS, f"section inconnue : {section}"
        if not isinstance(valeurs, dict):
            continue
        for cle in valeurs:
            assert cle in config.DEFAUTS[section], \
                f"réglage inconnu : {section}.{cle}"
