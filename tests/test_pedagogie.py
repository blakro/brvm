"""Les phrases affichées se testent comme les chiffres.

Une phrase fausse trompe aussi sûrement qu'un chiffre faux, et elle passe
plus facilement inaperçue : personne ne relit « 3ᵉ sur 47 » avec méfiance.
Les montants, surtout, doivent garder leur ordre de grandeur : se tromper
d'un facteur mille sur un volume est l'erreur la plus facile à commettre et
la plus difficile à voir.

    python tests/test_pedagogie.py
    pytest tests/test_pedagogie.py
"""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from brvm import pedagogie  # noqa: E402


def test_les_montants_gardent_leur_ordre_de_grandeur():
    assert pedagogie.montant(12_345_678) == "12,3 M FCFA"
    assert pedagogie.montant(2_400_000_000) == "2,4 Md FCFA"
    assert pedagogie.montant(14_229) == "14 229 FCFA"
    assert pedagogie.montant(0) == "0 FCFA"
    assert pedagogie.montant(None) == "—"
    assert pedagogie.montant(float("nan")) == "—"
    assert pedagogie.montant(-5_000_000) == "-5,0 M FCFA"
    # Jamais de séparateur anglais : l'app affiche « 14 229 » ailleurs.
    assert "," not in pedagogie.montant(14_229)


def test_les_pourcentages_se_lisent_en_francais():
    """Une virgule décimale et une espace avant le signe : deux conventions
    dans la même phrase se remarquent, et distraient de ce qu'elle dit."""
    assert pedagogie.pourcentage(0.0213) == "+2,1\u202f%"
    assert pedagogie.pourcentage(-0.0821) == "-8,2\u202f%"
    assert pedagogie.pourcentage(0.30, signe=False) == "30,0\u202f%"
    assert pedagogie.pourcentage(None) == "—"
    assert "." not in pedagogie.pourcentage(0.5761)
    # Espace fine insécable : « 6,3 » et « % » ne doivent pas
    # se retrouver sur deux lignes.
    assert "\u202f" in pedagogie.pourcentage(0.063)


def test_les_dates_se_lisent_en_francais():
    """L'ISO est le bon format pour un fichier, pas pour une phrase."""
    assert pedagogie.jour("2026-07-27") == "27 juillet 2026"
    assert pedagogie.jour(None) == "—"
    # Une date illisible ressort telle quelle plutôt que de faire tomber
    # la page : c'est l'archive qu'il faudra corriger, pas l'affichage.
    assert pedagogie.jour("pas une date") == "pas une date"


def test_l_ordinal_se_lit_en_francais():
    assert pedagogie.ordinal(1) == "1ᵉʳ"
    assert pedagogie.ordinal(3) == "3ᵉ"
    assert pedagogie.ordinal(47) == "47ᵉ"


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
