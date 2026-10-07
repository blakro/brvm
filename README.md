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
| 🔎 **Une action** | La fiche d'une société : son prix, son évolution, ce que seraient devenus 100 000 FCFA, ses dividendes. |
| 💰 **Dividendes** | Les sociétés qui reversent le plus à leurs actionnaires, et un calculateur : « combien rapporterait mon épargne ? » |
| 🎓 **Comprendre** | La BRVM en quelques cartes : trois règles à connaître et un petit lexique. |

## Les trois choses à retenir

1. **Personne ne sait prédire les prix.** Des centaines de méthodes ont été
   testées sur onze ans d'historique : aucune ne choisit les actions mieux
   que le hasard une fois les frais payés.
2. **Ce qui rapporte régulièrement, ce sont les dividendes** : 7 à 10 % par
   an en moyenne ces dernières années, alors que les prix font le yo-yo.
3. **Acheter puis revendre coûte cher** (2,5 à 3,5 % de frais). Changer
   souvent d'actions coûte plus que ce que ça rapporte.

## Le petit lexique

| Mot | Ce que ça veut dire |
|---|---|
| **Action** | Un petit morceau d'une entreprise. |
| **Séance** | Une journée de bourse (environ 250 par an). |
| **Dividende** | La part du bénéfice que la société reverse chaque année à ses actionnaires. |
| **Rendement** | Le dividende divisé par le prix. 8 % = 8 000 FCFA par an pour 100 000 investis. |
| **SGI** | L'intermédiaire agréé par qui il faut passer pour acheter ou vendre. |

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
