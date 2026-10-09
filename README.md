# 📈 brvm

**La Bourse Régionale des Valeurs Mobilières (BRVM), expliquée simplement.**

La BRVM est la bourse commune à huit pays d'Afrique de l'Ouest
🇧🇯 🇧🇫 🇨🇮 🇬🇼 🇲🇱 🇳🇪 🇸🇳 🇹🇬. Ce projet récupère chaque soir les prix des
actions qui y sont cotées, les garde en mémoire depuis 2015, et les
affiche dans une application colorée, faite pour les débutants.

### ➜ [Ouvrir l'application](https://brvm227.streamlit.app)

Rien à installer, tout se passe dans le navigateur.

> ⚠️ **Ce n'est pas un conseil en investissement.** L'application montre ce
> qui s'est passé, pas ce qui va se passer.

---

## Ce que vous y trouverez

| Onglet | À quoi il sert |
|---|---|
| 🏠 **Aujourd'hui** | La « météo » du marché : combien d'actions montent, combien baissent, les plus fortes hausses et baisses, les secteurs. |
| 🔎 **Une action** | Tout savoir avant d'acheter ou de vendre : prix et évolution, une **fiche en six points** (facile à revendre ? prix agité ? pire chute ? dividendes ? frais ?), un **simulateur d'achat** (frais compris, prix pour ne rien perdre) et la prévision du modèle pour le mois et le trimestre qui viennent. |
| 🔮 **Prédictions** | La « boule de cristal honnête » : la météo du mois ou du trimestre qui vient pour chaque action, combien de fois le modèle a eu raison par le passé, et pourquoi les frais mangent son avance. |
| 💰 **Dividendes** | Les sociétés qui reversent le plus, les derniers versements, et un calculateur : « combien rapporterait mon épargne ? » |
| 🎓 **Comprendre** | Acheter sa première action en 6 étapes, trois règles à connaître, un glossaire de 24 mots avec recherche, et la signification des couleurs et symboles. |

Chaque onglet se termine par une **🗺️ Légende** qui explique ses couleurs,
ses icônes et ses chiffres.

## Comment lire la prédiction

Le modèle ne devine pas le prix de demain. Il estime les chances qu'une
action fasse **mieux que la moitié du marché** pendant **le mois qui vient**
(20 séances) ou **le trimestre qui vient** (60 séances). Il est entraîné à
part pour chaque échéance : les deux avis restent proches, mais peuvent
différer.

- **Une pièce de monnaie ferait 50 %.** Le modèle donne entre 44 % et 54 %
  environ : un léger penchant, jamais une certitude.
- **Il a fait mieux qu'une pièce 9 années sur 10**, aux deux échéances,
  quand on l'a testé sur des années qu'il n'avait jamais vues — avec
  environ 52 bonnes réponses sur 100.
- **Mais les frais l'emportent.** Un achat suivi d'une revente coûte
  environ 3 %, bien plus que l'avance de ses favorites :

  | | Le mois qui vient | Le trimestre qui vient |
  |---|---|---|
  | Avance de ses 10 favorites | +0,6 % par mois | +0,9 % par trimestre, **pas démontrée** |
  | Suivre ses favorites, sans frais | +5 % par an | +1 % par an |
  | … avec des frais réalistes | **−14 % par an** | **−6 % par an** |

Pourquoi pas la semaine prochaine ? C'est là que le modèle classe le mieux,
mais une météo de la semaine invite à acheter et vendre chaque semaine, et
c'est ce que les frais punissent le plus : **−36 % par an**.

Et si un jour le modèle ne faisait plus ses preuves à une échéance, l'app
le dirait : « 🤐 le devin se tait », sans météo, plutôt qu'un avis qu'il ne
peut pas défendre.

Conclusion : c'est un indice de plus pour départager deux actions, pas un
signal d'achat.

## Les trois choses à retenir

1. **Personne ne sait prédire les prix avec certitude.** Le meilleur modèle
   testé fait à peine mieux qu'une pièce de monnaie, pas assez pour payer
   les frais.
2. **Ce qui rapporte régulièrement, ce sont les dividendes** : en général
   7 à 10 % du prix par an ces dernières années, alors que les prix font
   le yo-yo.
3. **Acheter puis revendre coûte cher** (2,5 à 3,5 % de frais). Changer
   souvent d'actions coûte plus que ce que ça rapporte.

## Le petit lexique

| Mot | Ce que ça veut dire |
|---|---|
| **Action** | Un petit morceau d'une entreprise. |
| **Séance** | Une journée de bourse (environ 250 par an). |
| **Prix de clôture** | Le prix en fin de séance : c'est la référence. |
| **Dividende** | La part du bénéfice que la société reverse chaque année à ses actionnaires. |
| **Rendement** | Le dividende divisé par le prix. 8 % = 8 000 FCFA par an pour 100 000 investis. |
| **Détachement** | Le jour où le dividende est versé ; il faut détenir l'action avant. |
| **SGI** | L'intermédiaire agréé par qui il faut passer pour acheter ou vendre. |
| **Ordre à cours limité** | Un ordre où vous fixez votre prix maximum (achat) ou minimum (vente). |
| **Liquidité** | La facilité à revendre : certaines actions s'échangent très peu. |
| **Limite de ±7,5 %** | Un prix ne peut pas varier de plus de 7,5 % en une séance. |

Le glossaire complet (24 mots) est dans l'onglet 🎓 Comprendre.

---

## Pour les curieux et les développeurs

```bash
pip install -e ".[web]"
streamlit run streamlit_app.py     # lance l'application en local
pytest                             # lance les tests (pip install -e ".[dev]")
```

- Les données sont dans le dossier `data/` (simples fichiers CSV).
- Le code d'analyse est dans `src/brvm/`. Les analyses statistiques avancées
  (classement, prédiction, backtest) restent disponibles en ligne de
  commande : `brvm --help`.
- Tout le détail technique (sources, robots de collecte, méthodes
  statistiques, résultats chiffrés) est dans
  **[docs/technique.md](docs/technique.md)**.

Licence MIT.
