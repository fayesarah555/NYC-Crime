# Script oral : Criminalité dans les parcs de New York

Module Open Data, IPSSI · Sujet 2 · 18 diapositives.
Durée cible : **17 min 30 s (1050 secondes)**, dans la fourchette imposée de
15 à 20 minutes. Les temps sont cumulables : `make deck` régénère le diaporama,
ce script se lit à côté.

| # | Diapositive | Durée |
| --- | --- | --- |
| 1 | Titre | 0:30 |
| 2 | Problématique | 1:00 |
| 3 | Données et sources | 1:15 |
| 4 | Architecture | 1:00 |
| 5 | Pipeline qualité | 1:15 |
| 6 | Tendances | 1:15 |
| 7 | Saisonnalité | 1:00 |
| 8 | Arrondissement × type | 1:00 |
| 9 | Parcs critiques | 1:00 |
| 10 | Taux par acre | 0:45 |
| 11 | Concentration | 0:45 |
| 12 | Prévision et backtest | 1:30 |
| 13 | Prévisions par arrondissement | 0:30 |
| 14 | Typologie des parcs | 1:00 |
| 15 | Application | 1:15 |
| 16 | Limites | 0:45 |
| 17 | Conclusion | 0:45 |
| 18 | Questions | 1:00 |
| | **Total** | **17:30 (1050 s)** |

## 1. Titre (0:30)

Bonjour. Nous présentons le sujet 2 du module Open Data : la criminalité dans
les parcs de New York. Le jeu de données couvre 2014Q4 à 2026Q2, soit
12 526 crimes majeurs déclarés par le NYPD, parc par parc et trimestre par
trimestre. Nous verrons ce que ces chiffres disent, et surtout ce qu'ils ne
disent pas.

**Transition :** commençons par la question qui structure tout le projet.

## 2. Problématique (1:00)

Les parcs new-yorkais concentrent-ils les crimes majeurs sur quelques sites
prévisibles, ou sont-ils un risque diffus ? Nous répondons en trois temps :
mesurer le volume et la structure, localiser les parcs critiques, puis prévoir
et vérifier qu'un modèle bat vraiment une règle naïve. Chaque réponse sort du
même pipeline, sans enquête terrain.

**Transition :** pour cela, il faut d'abord savoir d'où viennent les données.

## 3. Données et sources (1:15)

Deux sources ouvertes. Côté NYPD, un classeur Excel par trimestre publie les
sept crimes majeurs de chaque parc : 46 classeurs, de 2014Q4 à 2026Q2. Côté
ville de New York, le référentiel Parks Properties fournit la surface en acres
et les coordonnées. Au total : 12 526 crimes, 1 155 parcs dont 792 touchés au
moins une fois, et 1 009 parcs géolocalisés. Trois trous assumés : 2020Q1 est
absent de la source, 2026Q3 et 2026Q4 ne sont pas encore publiés (404), et
Central Park n'entre dans les classeurs qu'en 2025Q1.

**Transition :** ces données arrivent brutes ; voici comment elles deviennent
un entrepôt fiable.

## 4. Architecture (1:00)

Cinq étapes, toutes scriptées. Le téléchargement vérifie chaque classeur par
sha256 dans un manifeste : un rerun ne retélécharge que ce qui a changé.
Le parseur construit un entrepôt SQLite et un CSV long, une ligne par parc,
trimestre et type de délit. L'analyse produit tables et figures, les modèles
produisent prévisions, backtest et clusters ; les deux interfaces lisent
uniquement ces artefacts : le tableau de bord web Astryx via `export/export_web.py`
(JSON statique), Streamlit via l'entrepôt et les CSV. Une commande, `make all`,
rejoue toute la chaîne.

**Transition :** cette chaîne est aussi un filtre qualité.

## 5. Pipeline qualité (1:15)

Quatre pièges, traités explicitement. Premier : la couverture bouge. Central
Park n'apparaît qu'en 2025Q1, donc la hausse 2025 est de +3,93 % avec lui, mais
de −1,06 % hors Central Park, soit 1 031 crimes contre 1 042. Deuxième : 2020Q1
manque et il est interpolé pour le modèle, jamais traité comme un zéro.
Troisième : dans le classeur 2025Q4, Flushing Meadows affiche un TOTAL de 17
contre 18 pour la somme ; la ligne est exclue et journalisée. Quatrième : la
géolocalisation couvre 87,4 % des parcs, 90,5 % pondéré par volume, avec deux
rapprochements flous assumés. Aucun de ces choix n'est silencieux.

**Transition :** avec un entrepôt propre, regardons la trajectoire.

## 6. Tendances (1:15)

La série citywide culmine en 2018Q3 avec 545 crimes sur le trimestre ; depuis
2022 le niveau est plus bas et plus stable. Le total de la période est de
12 526 crimes. La marche visible en 2025Q1 n'est pas une hausse réelle : c'est
l'ajout de Central Park à la source. À périmètre constant, 2025 recule de
1,06 %. C'est le genre de conclusion qu'un graphique seul ne donne pas.

**Transition :** la série ne bouge pas seulement par année, elle bouge aussi
dans l'année.

## 7. Saisonnalité (1:00)

L'été pèse quatre fois plus que l'hiver : 441 crimes par trimestre en moyenne
au troisième trimestre, contre 111 au premier. Ce facteur quatre est stable sur
toute la période. Conséquence méthodologique : on ne compare jamais deux
trimestres consécutifs, et le modèle doit être saisonnier.

**Transition :** cette saisonnalité se combine à une géographie des délits.

## 8. Arrondissement × type (1:00)

Le test du chi-deux rejette très largement l'indépendance entre arrondissement
et type de délit : χ² = 1177,2 pour 30 degrés de liberté, p inférieure à
1e-200. Mais le V de Cramér vaut 0,137 : la liaison est réelle et faible. Et
des effectifs théoriques inférieurs à 5 dans certaines cellules en font un
résultat descriptif, pas prédictif. En clair, la structure existe sans être
déterminante. Manhattan penche vers le larcin, à 56,4 % de ses crimes ; le
Bronx vers le vol qualifié, à 49,2 %.

**Transition :** voyons quels parcs portent concrètement ce risque.

## 9. Parcs critiques (1:00)

Quinze parcs concentrent le risque visible. Flushing Meadows arrive en tête
avec 881 crimes, devant Washington Square à 651 et Coney Island à 493. Ces
sites cumulent volume et plusieurs types de délits : ce sont ceux où une
patrouille ciblée a le plus d'effet marginal. Mais un grand parc est aussi un
grand espace : il faut normaliser.

**Transition :** rapportons ces volumes à la surface.

## 10. Taux par acre (0:45)

Rapporté à la surface, le classement change. Manhattan concentre 146,7 crimes
pour 100 acres, contre 2,1 à Staten Island, un rapport de 70. Attention à la
lecture : le taux mesure l'exposition du parc, pas le risque par visiteur, car
nous n'avons aucune donnée de fréquentation.

**Transition :** cette concentration se lit aussi dans le temps.

## 11. Concentration (0:45)

En moyenne, 89,83 % des parcs n'enregistrent aucun crime majeur un trimestre
donné. Et sur toute la période, 792 parcs sur 1 155 sont touchés au moins une
fois. Le risque n'est donc ni uniforme ni permanent : il se concentre sur une
poignée de sites et sur quelques trimestres.

**Transition :** cette régularité permet-elle de prévoir ?

## 12. Prévision et backtest (1:30)

Nous testons trois approches sur les huit derniers trimestres connus : la règle
`seasonal_naive`, Holt-Winters et SARIMAX. Le SARIMAX atteint une MAE de
19,98 contre 22,75 pour `seasonal_naive` (règle naïve récursive), soit 12,17 %
de mieux ; face à `baseline_mae_seasonal_rule` (règle saisonnière non
récursive, 22,50), l'avantage se réduit. Le MAPE reste à 9,62 %. La prévision
2026Q3 est de 378 crimes, intervalle de 258 à 498 ; le cycle saisonnier est
reproduit sur 2026Q3–2027Q2. Deux réserves : le modèle est choisi sur la même
fenêtre qu'il rapporte, donc son avantage est optimiste ; et la prévision est
gonflée par l'ajout de Central Park.

**Transition :** la même mécanique, arrondissement par arrondissement.

## 13. Prévisions par arrondissement (0:30)

Le modèle est décliné par arrondissement. En 2026Q3, Manhattan et Brooklyn
portent les volumes les plus élevés, le Bronx les plus faibles ; les quatre
suivent le même cycle saisonnier, et Staten Island reste hors périmètre faute
de volume. Les intervalles s'élargissent hors saison haute : la prévision vaut
par son ordre de grandeur, pas au crime près.

**Transition :** au-delà du volume, existe-t-il des profils de parcs ?

## 14. Typologie des parcs (1:00)

Une classification non supervisée retient quatre groupes sur 337 parcs, avec
une silhouette de 0,225 : honnête, mais pas nette. Deux groupes sont des parcs
de proximité, l'un à vol qualifié, l'autre à larcin ; un regroupe les grands
parcs ; le dernier les sites à violence. Cette typologie sert à cibler la
prévention, pas à étiqueter les quartiers.

**Transition :** tout cela est explorable dans l'application.

## 15. Application (1:15)

L'interface principale est un tableau de bord web en Vite, React et Astryx :
il alimente l'export JSON statique des artefacts, sans backend, et `make web-build`
le reconstruit. On y trouve une carte des parcs, des filtres par arrondissement
et par type de délit, une recherche de parc sans accents, et trois onglets :
Exploration, Prévisions et Méthode. En bas, la vue analyste Streamlit,
`make app`, lit les mêmes artefacts pour un top 10 des parcs et un export CSV.
Aucune des deux interfaces ne fait d'appel réseau.

**Transition :** malgré tout ce que ces données montrent, elles ont des limites
dures.

## 16. Limites (0:45)

Cinq limites. Pas de fréquentation : le taux par acre n'est pas un risque par
visiteur. Une couverture incomplète : Central Park depuis 2025Q1, 2020Q1 et
2026Q3–Q4 absents. Des plaintes, pas des faits établis : la propension à
déclarer varie avec le quartier. Un choix de modèle optimiste. Et un périmètre
réduit : Staten Island et le libellé Brooklyn/Queens sont hors prévision par
arrondissement.

**Transition :** que retenir en trois points ?

## 17. Conclusion (0:45)

Le risque est concentré : 792 parcs touchés sur 1 155, et 89,83 % des parcs
vides un trimestre donné. Il suit l'usage du sol : 146,7 crimes pour 100 acres
à Manhattan contre 2,1 à Staten Island. Il reste prévisible à court terme :
MAE de 19,98 contre 22,75 pour la règle naïve. La réserve : toute prévision
décrit une couverture, pas une explosion.

**Transition :** nous sommes prêts pour vos questions.

## 18. Questions (1:00)

Merci de votre attention. Le dépôt contient le README de reproduction, le
diaporama généré et ce script ; `make all` rejoue toute la chaîne et `make app`
lance l'application. Nous répondons à vos questions.

## Marge de sécurité

Le total de 17 min 30 s laisse 2 minutes 30 sous la limite des 20 minutes. En cas
de dépassement, raccourcir les diapositives 4 (architecture) et 14 (typologie)
de 30 secondes chacune, jamais les diapositives 5 et 12 qui portent les
réserves méthodologiques.
