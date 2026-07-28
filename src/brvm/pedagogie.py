"""Mise en mots : ce que l'app doit dire à qui ne connaît pas le vocabulaire.

POURQUOI CE MODULE EXISTE
-------------------------
Le reste du projet parle la langue d'un quant — momentum, IC de Spearman,
biais du survivant, rotation. Ce vocabulaire est juste, et il ne doit pas
être appauvri : c'est lui qui empêche de confondre un classement avec un
conseil. Mais il est illisible pour un épargnant, et un tableau de bord que
personne ne peut lire ne protège personne.

D'où ce module, qui ne calcule rien de nouveau. Il traduit :

- `GLOSSAIRE` donne UNE phrase par terme, sans jargon dans la définition —
  une définition qui appelle un deuxième glossaire n'en est pas une ;
- `attente` transforme un refus en compteur. « Aucune valeur classée » se
  lit comme une panne ; « 1 séance sur 251, premier classement vers
  juillet 2027 » se lit comme une attente, ce que c'est réellement ;
- `ordinal` et `montant` remplacent les nombres nus. « 3ᵉ sur 47 » se
  comprend sans rien savoir, « score 0,62 » ne veut rien dire.

Le module est ici et non dans `streamlit_app.py` pour être testé : une
phrase fausse trompe aussi sûrement qu'un chiffre faux, et elle passe plus
facilement inaperçue.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

# La BRVM cote du lundi au vendredi : cinq séances pour sept jours. Le
# rapport sert à estimer une date d'arrivée à partir d'un nombre de séances
# manquantes — approximation assumée, les jours fériés la rallongent un peu.
SEANCES_PAR_SEMAINE = 5
JOURS_PAR_SEMAINE = 7

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]

# Une phrase, pas de terme technique à l'intérieur, pas de formule. Les
# nuances qui manquent sont dans les docstrings des modules de calcul ; ici
# le but est qu'un lecteur qui voit le mot pour la première fois puisse
# continuer sa lecture.
GLOSSAIRE: dict[str, str] = {
    "momentum":
        "La hausse ou la baisse accumulée par une valeur sur l'année "
        "écoulée, sans compter le dernier mois — un pari sur le fait qu'une "
        "valeur qui monte depuis longtemps continue un peu.",
    "tendance":
        "L'écart entre le cours moyen des dernières semaines et celui des "
        "derniers mois : positif quand la valeur accélère, négatif quand "
        "elle s'essouffle.",
    "volatilite":
        "L'ampleur habituelle des écarts de cours d'une séance à l'autre. "
        "Élevée, elle signale une valeur qui bouge fort dans les deux sens.",
    "liquidite":
        "Le montant qui s'échange en moyenne chaque séance. Une valeur peu "
        "liquide s'achète difficilement, et se revend encore moins bien.",
    "score":
        "La note qui sert à ordonner les valeurs entre elles. Elle n'a pas "
        "d'unité et ne se compare pas d'un jour à l'autre : seul le rang "
        "compte.",
    "rang":
        "La place d'une valeur dans le classement du jour, de la mieux "
        "notée à la moins bien notée.",
    "fixing":
        "La BRVM ne cote pas en continu : les ordres sont regroupés et un "
        "seul cours est fixé par séance, à l'issue de la confrontation.",
    "limite":
        "Un cours ne peut ni monter ni baisser de plus de 7,5 % en une "
        "séance. Au-delà, la cotation est suspendue et reprend le lendemain.",
    "dividende":
        "La part du bénéfice qu'une société verse à ses actionnaires, "
        "généralement une fois par an.",
    "rendement":
        "Le dividende rapporté au cours : ce que verse la société chaque "
        "année pour 100 F investis aujourd'hui.",
    "backtest":
        "Rejouer une stratégie sur le passé pour voir ce qu'elle aurait "
        "donné. Un bon résultat passé ne promet rien : il dit seulement que "
        "la règle n'était pas absurde.",
    "reference":
        "Le résultat qu'on aurait obtenu en achetant toutes les valeurs "
        "éligibles à parts égales. C'est elle qu'une stratégie doit battre, "
        "pas zéro.",
    "perte_max":
        "La plus forte baisse subie depuis un sommet. Le chiffre qui décide "
        "si une stratégie est tenable : celle qu'on abandonne au creux ne "
        "rapporte pas ce que le passé annonçait.",
    "rotation":
        "La part du portefeuille remplacée à chaque révision. Elle coûte "
        "cher : chaque ligne vendue puis rachetée paie deux fois les frais.",
    "frais":
        "Sur la BRVM, un aller-retour coûte environ 2,5 à 3,5 % entre "
        "courtage, commissions et taxes. Un écart de performance inférieur à "
        "cela ne se récupère pas.",
    "ic":
        "Une mesure de la qualité d'un classement : à quel point l'ordre "
        "prévu ressemble à l'ordre réellement constaté ensuite. Entre 0,02 "
        "et 0,05, c'est déjà exploitable ; au-delà de 0,30, c'est suspect.",
    "survivant":
        "Le passé simulé ne contient que les sociétés encore cotées "
        "aujourd'hui. Celles qui ont disparu, souvent après avoir mal fini, "
        "en sont absentes — ce qui embellit tous les résultats.",
    "sgi":
        "Société de Gestion et d'Intermédiation : le seul intermédiaire par "
        "lequel un particulier peut passer un ordre sur la BRVM.",
}


# Le libellé affiché quand il diffère de la clé — accents, sigles, et les
# quelques entrées dont le nom court serait ambigu tout seul.
LIBELLES: dict[str, str] = {
    "volatilite": "volatilité",
    "liquidite": "liquidité",
    "score": "score composite",
    "limite": "limite de ±7,5 %",
    "rendement": "rendement du dividende",
    "reference": "référence équipondérée",
    "perte_max": "perte maximale",
    "frais": "frais de transaction",
    "ic": "IC",
    "survivant": "biais du survivant",
    "sgi": "SGI",
}


def glossaire(*cles: str) -> str:
    """Rend en markdown les définitions demandées, dans l'ordre demandé.

    Lève `KeyError` sur un terme inconnu plutôt que de l'ignorer : un
    glossaire qui saute silencieusement une entrée laisse le lecteur devant
    le mot qu'il ne comprenait justement pas.
    """
    manquants = [c for c in cles if c not in GLOSSAIRE]
    if manquants:
        raise KeyError(f"termes absents du glossaire : {', '.join(manquants)}")
    return "\n".join(
        f"**{LIBELLES.get(c, c.replace('_', ' '))}** — {GLOSSAIRE[c]}\n"
        for c in cles
    )


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


def _mois_estime(derniere: str | date | None, manquantes: int) -> str | None:
    """« vers juillet 2027 », à partir d'un nombre de séances manquantes."""
    if derniere is None or manquantes <= 0:
        return None
    if isinstance(derniere, str):
        try:
            depart = datetime.strptime(derniere[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    else:
        depart = derniere
    jours = round(manquantes * JOURS_PAR_SEMAINE / SEANCES_PAR_SEMAINE)
    cible = depart + timedelta(days=jours)
    return f"{MOIS[cible.month - 1]} {cible.year}"


def attente(
    disponible: int,
    requis: int,
    derniere: str | date | None = None,
    unite: str = "séance",
) -> dict:
    """Un refus, exprimé comme une attente : où l'on en est, et jusqu'à quand.

    `disponible` et `requis` se comptent dans la même unité — séances pour
    le classement et le backtest, observations pour la prédiction. La date
    n'est estimée que pour les séances : une observation n'arrive pas à
    rythme fixe, et annoncer une date fausse serait pire que de se taire.
    """
    manquantes = max(0, requis - disponible)
    part = 0.0 if requis <= 0 else min(1.0, disponible / requis)
    phrase = (
        f"{disponible} {unite}{'s' if disponible > 1 else ''} sur les "
        f"{requis} nécessaires."
    )
    mois = _mois_estime(derniere, manquantes) if unite == "séance" else None
    if manquantes and mois:
        phrase += (f" Il en manque {manquantes} — une par jour ouvré, "
                   f"soit un premier résultat vers {mois}.")
    elif manquantes:
        phrase += f" Il en manque {manquantes}."
    return {
        "part": part,
        "disponible": disponible,
        "requis": requis,
        "manquantes": manquantes,
        "mois_estime": mois,
        "phrase": phrase,
    }
