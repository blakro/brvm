"""Mise en forme : ce que l'app écrit, en français lisible.

Ce module ne calcule rien. Il transforme des nombres en mots qu'un
lecteur non spécialiste lit d'un trait :

- `montant` garde l'ordre de grandeur visible — « 12,3 M FCFA » plutôt
  que « 12345678 » ;
- `pourcentage` écrit « +2,1 % », virgule décimale et espace insécable ;
- `jour` écrit « 27 juillet 2026 » plutôt que l'ISO ;
- `ordinal` écrit « 1ᵉʳ », « 3ᵉ ».

Il est ici et non dans `streamlit_app.py` pour être testé : une phrase
fausse trompe aussi sûrement qu'un chiffre faux, et passe plus facilement
inaperçue.
"""

from __future__ import annotations

from datetime import date, datetime

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]


def ordinal(rang: int) -> str:
    """1 → « 1ᵉʳ », 3 → « 3ᵉ »."""
    return "1ᵉʳ" if rang == 1 else f"{rang}ᵉ"


def montant(valeur: float | None, unite: str = "FCFA") -> str:
    """Un montant lisible d'un coup d'œil, en séparateurs français.

    « 12,3 M FCFA » plutôt que « 12345678 » : sur des volumes qui vont de
    quelques milliers à quelques milliards, compter les chiffres à l'œil est
    la façon la plus courante de se tromper d'un facteur mille.
    """
    if valeur is None or valeur != valeur:  # NaN
        return "—"
    valeur = float(valeur)
    signe = "-" if valeur < 0 else ""
    reste = abs(valeur)
    if reste >= 1e9:
        return f"{signe}{reste / 1e9:.1f} Md {unite}".replace(".", ",")
    if reste >= 1e6:
        return f"{signe}{reste / 1e6:.1f} M {unite}".replace(".", ",")
    return f"{signe}{reste:,.0f} {unite}".replace(",", " ")


def pourcentage(valeur: float | None, signe: bool = True) -> str:
    """0,0213 → « +2,1 % ». Virgule décimale, comme le reste de la phrase.

    Le format Python donne « +2.1% » : un point décimal et une espace
    manquante, au milieu d'un texte français où les montants s'écrivent
    « 1,0 M FCFA ». Deux conventions dans la même phrase se remarquent.
    """
    if valeur is None or valeur != valeur:  # NaN
        return "—"
    brut = f"{valeur:+.1%}" if signe else f"{valeur:.1%}"
    # Espace fine insécable avant le signe : c'est l'usage français, et
    # surtout cela empêche « 6,3 » et « % » de se retrouver sur deux lignes.
    return brut.replace(".", ",").replace("%", " %")


def jour(valeur: str | date | None) -> str:
    """« 2026-07-27 » → « 27 juillet 2026 ».

    L'ISO est le bon format pour un fichier et le mauvais pour une phrase :
    il se lit chiffre par chiffre, alors que le reste de la phrase se lit
    d'un trait.
    """
    if valeur is None:
        return "—"
    if isinstance(valeur, str):
        try:
            valeur = datetime.strptime(valeur[:10], "%Y-%m-%d").date()
        except ValueError:
            return str(valeur)
    return f"{valeur.day} {MOIS[valeur.month - 1]} {valeur.year}"
