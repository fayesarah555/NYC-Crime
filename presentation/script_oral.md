# Script oral : Criminalité dans les parcs de New York

Module Open Data, IPSSI · Sujet 2 · 23 diapositives · 3 intervenants.
Durée : **30 minutes pile**, démonstration live comprise.

`make deck` régénère `presentation/nyc_crime_deck.pptx` et recopie le speech
de chaque section `## Slide N` ci-dessous dans les notes de l'orateur de la
diapositive correspondante. Les diapositives ne portent ni timing ni prénom :
ces indications ne vivent que dans ce fichier et dans les notes.

Fil conducteur : **« Le chiffre qui mentait »**. La source brute annonce
+3,93 % de crimes en 2025 ; à périmètre constant, c'est −1,06 %. Chaque partie
du projet (données, architecture, interface) sert à protéger la vérité du
chiffre, et la conclusion referme la boucle.

Règle d'écriture : des phrases courtes, des mots simples. Un terme technique
n'est gardé que s'il est nécessaire, et il est alors expliqué en une phrase.

## Minutage

| # | Section | Slides | Intervenant | Début → fin | Durée |
|---|---|---|---|---|---|
| A | Ouverture | 1 | Soufiane | 00:00 → 00:45 | 0:45 |
| B | Accroche : le chiffre qui mentait | 2 | Sarah | 00:45 → 02:00 | 1:15 |
| C | Problématique & vue d'ensemble | 3 | Youcef | 02:00 → 03:15 | 1:15 |
| D | Data : collecte → modèles → résultats | 4–11 | Sarah | 03:15 → 12:30 | 9:15 |
| E | Architecture, base, données servies, mise en ligne, qualité | 12–17 | Youcef | 12:30 → 19:30 | 7:00 |
| F | Interface et graphiques | 18–19 | Soufiane | 19:30 → 21:30 | 2:00 |
| G | Démo live | 20 | Soufiane (Youcef au clavier si besoin) | 21:30 → 27:30 | 6:00 |
| H | Limites & suite | 21 | Sarah | 27:30 → 28:45 | 1:15 |
| I | Conclusion : retour au chiffre | 22 | Youcef | 28:45 → 29:30 | 0:45 |
| J | Questions | 23 | Soufiane | 29:30 → 30:00 | 0:30 |
| | **Total** | 23 | Sarah 11:45 · Youcef 9:00 · Soufiane 9:15 | | **30:00** |

**En cas de retard :** raccourcir la slide 11 (profils de parcs) de 30 s, la
slide 13 (base de données) de 30 s, puis couper la séquence « Méthode » de la
démo (45 s). Ne jamais couper les slides 7 et 10 : elles portent les réserves.

## Slide 1 · Criminalité dans les parcs de New York

**Régie :** Soufiane · 00:00 – 00:45 · Le site est déjà ouvert dans un second
onglet (nyc-crimes.vercel.app, et localhost:5173 en secours).

> Bonjour à toutes et à tous. Nous allons vous montrer comment nous sommes partis de quarante-six fichiers Excel publiés par la police de New York pour arriver à un site public, que tout le monde peut consulter et que l'on peut reconstruire à l'identique. Le site est en ligne, vous pouvez le suivre en même temps que nous. Nous sommes trois : Sarah s'est occupée des données, Youcef de l'organisation du projet et de la mise en ligne, et moi du site et de la démonstration. Mais d'abord, Sarah va vous montrer un chiffre.

## Slide 2 · Le chiffre qui mentait

**Régie :** Sarah · 00:45 – 02:00 · Trois clics : le chiffre seul, puis barré,
puis l'explication.

> Si on prend les chiffres de la police tels quels et qu'on compare 2025 à 2024, on trouve une hausse de 3,93 % des crimes dans les parcs. C'est le genre de chiffre qu'on lit dans un journal.
> [clic] Mais ce chiffre est faux. Si on compare les mêmes parcs d'une année à l'autre, les crimes baissent de 1,06 %.
> [clic] Pourquoi cette différence ? Parce que Central Park n'apparaît dans les fichiers de la police qu'à partir de 2025. Ses 52 crimes ne sont pas une hausse : ils n'étaient simplement pas comptés avant. C'est tout le sujet de notre projet : une donnée publique n'est pas forcément une donnée juste. Tout ce que nous allons vous présenter sert à éviter ce genre d'erreur. Youcef, tu nous montres le chemin complet ?

## Slide 3 · Trois questions, une chaîne de bout en bout

**Régie :** Youcef · 02:00 – 03:15

> Le sujet nous posait trois questions. Mesurer : combien de crimes, à quel moment de l'année, où et de quel type. Localiser : quels parcs sont les plus touchés, en tenant compte de leur taille. Prévoir : est-ce qu'un vrai modèle de prévision fait mieux qu'une règle très simple ? Pour y répondre, on a mis en place une chaîne en six étapes. On télécharge les fichiers sur le site de la ville, on les range dans une base de données, on les analyse, on prépare des fichiers pour le site, et le site les affiche. Une règle nous a guidés du début à la fin : aucun chiffre n'est recopié à la main. Le site, la documentation et même ce diaporama lisent les mêmes fichiers produits automatiquement. Sarah, on commence par les données.

## Slide 4 · Ingestion : collecter sans jamais faire confiance

**Régie :** Sarah · 03:15 – 04:30

> Nous utilisons deux sources publiques. La première : les statistiques de la police sur les parcs, avec un fichier Excel par trimestre et, pour chaque parc, les sept crimes les plus graves. La seconde : la liste officielle des parcs de la ville, qui donne leur surface et leur position. Notre programme de téléchargement vérifie tout. Il trouve lui-même les liens sur la page de la police. Il contrôle que chaque fichier est bien un vrai fichier Excel, et pas une page d'erreur. Et il calcule une empreinte de chaque fichier, une sorte de signature, pour savoir s'il a changé. Si on relance le programme, il ne retélécharge que ce qui a changé. Aujourd'hui, nous avons 46 fichiers valides. Les deux derniers trimestres de 2026 ne sont pas encore publiés : le programme le signale, sans s'arrêter.

## Slide 5 · Nettoyage : 46 classeurs hétérogènes, un format long unique

**Régie :** Sarah · 04:30 – 05:45

> Ensuite, il faut lire ces fichiers, et c'est là que le vrai travail commence. Ils ont été produits sur douze ans, et leur présentation change : les titres des colonnes ne sont pas toujours à la même ligne, et le vol de voiture n'a pas toujours le même nom. Notre programme s'adapte à ces variations et met tout au même format. Il fait aussi un contrôle simple : le total donné par la police doit être égal à la somme des sept types de crimes. Sur 53 000 lignes, une seule ne respecte pas cette règle : Flushing Meadows, fin 2025, avec un total de 17 alors que la somme fait 18. Nous ne la corrigeons pas en cachette : nous la retirons et nous la notons dans un fichier à part. Au final, on obtient une grande table de 371 616 lignes : une ligne par parc, par trimestre et par type de crime. 98 % de ces lignes valent zéro, et on les garde, parce qu'un parc sans crime, c'est aussi une information.

## Slide 6 · Géolocalisation & feature engineering

**Régie :** Sarah · 05:45 – 06:45

> Pour placer les parcs sur une carte, il faut relier nos deux sources. Le problème, c'est qu'elles n'écrivent pas les noms de la même façon. On essaie donc dans l'ordre : le nom officiel exact, puis un second nom officiel, puis un nom très proche, et toujours dans le même quartier. Pour placer le point sur la carte, on choisit un point qui est forcément à l'intérieur du parc, et pas simplement son centre, qui peut tomber à côté pour un parc de forme irrégulière. Résultat : 87 % des parcs sont placés sur la carte, et ils représentent 90 % des crimes. Nous avons vérifié à la main les rapprochements incertains : deux sont faux, et nous l'avons noté. Enfin, on prépare les indicateurs : le nombre de crimes pour 100 acres de parc, et pour chaque parc, la part de chaque type de crime, sa taille et son nombre total de crimes.

## Slide 7 · Quatre pièges de la source, traités explicitement

**Régie :** Sarah · 06:45 – 07:45 · Slide protégée : ne pas la couper.

> Cette slide est la plus importante de ma partie. Les données publiques ont des trous, et il faut les montrer plutôt que les cacher. Premier piège : certains parcs apparaissent en cours de route, comme Central Park. Donc chaque comparaison d'une année sur l'autre est faite avec et sans lui. Deuxième piège : le premier trimestre 2020 manque dans les données. Si on le comptait comme zéro, on inventerait une chute des crimes pendant le Covid. On le remplace par une estimation, uniquement pour la prévision, et on le dit. Troisième piège : le total incohérent que je viens de vous montrer. Quatrième : un parc sur huit n'a pas de position, et le site indique combien de parcs manquent sur la carte au lieu de les faire disparaître sans prévenir.

## Slide 8 · Mesurer : une tendance, un rythme saisonnier

**Régie :** Sarah · 07:45 – 08:45

> Premier objectif : mesurer. Sur toute la période, on compte 12 526 crimes graves déclarés dans les parcs. Le point le plus haut, c'est l'été 2018, avec 545 crimes en trois mois. Depuis 2022, le niveau est plus bas et plus stable. Et la marche que vous voyez en 2025, c'est Central Park, rien d'autre. Mais ce qui frappe le plus, c'est la saison : il y a quatre fois plus de crimes en été qu'en hiver, 441 en moyenne au troisième trimestre contre 111 au premier. C'est vrai tous les ans. Donc on ne compare jamais l'été et l'automne, et tout modèle de prévision doit tenir compte des saisons.

## Slide 9 · Localiser : le volume ment, la surface rectifie

**Régie :** Sarah · 08:45 – 10:00

> Deuxième objectif : localiser. En nombre de crimes, le parc le plus touché est Flushing Meadows, avec 881 crimes, devant Washington Square et Coney Island. Mais un grand parc a forcément plus de crimes qu'un petit. Il faut donc tenir compte de la surface. Et là, l'écart est énorme : à Manhattan, on compte 147 crimes pour 100 acres de parc, contre 2 à Staten Island. C'est 70 fois plus. Attention : cela mesure le nombre de crimes par surface, pas le danger pour un promeneur, car nous ne savons pas combien de personnes fréquentent chaque parc. Enfin, le type de crime change selon le quartier. Un test statistique, le test du chi-deux, confirme que ce lien existe, mais il reste faible. À Manhattan, ce sont surtout des vols sans violence ; dans le Bronx, surtout des vols avec violence.

## Slide 10 · Prévoir : battre la règle naïve, honnêtement

**Régie :** Sarah · 10:00 – 11:30 · Slide protégée : ne pas la couper.

> Troisième objectif : prévoir. Un modèle de prévision n'a d'intérêt que s'il fait mieux qu'une règle très simple. Notre règle simple, c'est : « ce trimestre ressemblera au même trimestre de l'an dernier ». Nous avons comparé cette règle à deux vrais modèles de prévision, dont un modèle appelé SARIMAX, fait pour les données qui suivent les saisons. On les a testés sur les huit derniers trimestres, en leur cachant ces données pendant l'apprentissage. Le SARIMAX gagne : il se trompe en moyenne de 20 crimes par trimestre, contre 23 pour la règle simple. C'est 12 % d'erreur en moins. L'autre modèle fait moins bien que la règle simple : un modèle compliqué ne gagne pas toujours. Pour l'été 2026, on prévoit 378 crimes, probablement entre 258 et 498. Deux précautions : on a choisi le meilleur modèle sur ces mêmes huit trimestres, donc son avantage est un peu flatteur ; et la prévision est un peu gonflée par l'arrivée de Central Park.

## Slide 11 · Typologie : quatre profils de parcs

**Régie :** Sarah · 11:30 – 12:30 · Raccourcissable de 30 s.

> Dernière question : est-ce qu'il existe des familles de parcs ? Nous avons utilisé une méthode qui regroupe automatiquement les parcs qui se ressemblent. Elle a trouvé quatre groupes parmi les 337 parcs qui ont au moins cinq crimes. Les groupes ne sont pas parfaitement séparés : ce sont des tendances, pas des cases fermées. Le résultat le plus fort : 81 grands parcs concentrent plus des deux tiers de tous les crimes. À côté, on trouve deux familles de petits parcs de quartier, l'une avec surtout des vols sans violence, l'autre avec surtout des vols avec violence. Et un petit groupe de quinze parcs où les violences graves pèsent beaucoup plus. Ces groupes servent à mieux cibler la prévention, pas à juger des quartiers. Voilà pour les données. Youcef va maintenant vous expliquer comment tout cela est organisé.

## Slide 12 · Architecture : une chaîne de lots, des artefacts comme contrats

**Régie :** Youcef · 12:30 – 13:45

> Merci Sarah. L'organisation du projet repose sur une idée simple : chaque étape est un petit programme séparé, et les étapes se passent le travail uniquement par des fichiers. Le téléchargement produit les fichiers Excel. La lecture produit la base de données. L'analyse produit des tableaux, des graphiques et des fichiers de résultats. Le site, l'outil d'analyse et même ce diaporama lisent uniquement ces fichiers de résultats. C'est ce qui garantit qu'aucun chiffre n'est recopié à la main : si un résultat change, il change partout en même temps. Une seule commande, make all, relance toute la chaîne. Et dans notre dépôt de code, on ne garde pas les cent mégaoctets de données brutes, puisqu'on peut les retélécharger, mais seulement les petits fichiers dont le site a besoin.

## Slide 13 · Base de données : un entrepôt SQLite en format long

**Régie :** Youcef · 13:45 – 14:45 · Raccourcissable de 30 s.

> Pour la base de données, nous avons choisi SQLite. On pourrait se demander pourquoi pas une base plus connue, comme PostgreSQL. La raison est simple : nos données changent quatre fois par an, on ne fait que les lire, et elles tiennent dans une soixantaine de mégaoctets. Installer et maintenir un serveur de base de données n'aurait servi à rien. SQLite, c'est un simple fichier : facile à copier, qu'on peut interroger en SQL, et qu'on reconstruit entièrement à chaque fois, donc il est toujours identique. Il contient deux tables : les crimes, et la liste des parcs. On a aussi ajouté un index, c'est-à-dire un sommaire, pour retrouver rapidement les crimes par trimestre, par parc et par type.

## Slide 14 · Pas de serveur d'API : un contrat de données statique et vérifié

**Régie :** Youcef · 14:45 – 16:00

> Habituellement, un site demande ses données à un serveur à chaque visite. Nous avons fait autrement. Comme nos résultats sont calculés à l'avance, on n'a pas besoin de les recalculer à chaque visite. On prépare donc six petits fichiers, environ 250 kilo-octets en tout, et le site les lit directement. Avant de créer ces fichiers, le programme fait plusieurs vérifications. Le total de chaque parc doit être égal à la somme de ses crimes. Le total de la ville doit être égal à celui de l'analyse. Et l'ensemble ne doit pas dépasser deux mégaoctets. Si une vérification échoue, tout s'arrête et le site n'est pas mis à jour. Résultat : pas de serveur à payer, pas d'attente, et beaucoup moins de risques côté sécurité.

## Slide 15 · Déploiement : du push Git à la production

**Régie :** Youcef · 16:00 – 17:15

> Pour la mise en ligne, nous utilisons Vercel, un service d'hébergement. Il est relié à notre dépôt de code : dès qu'on envoie une modification sur la branche principale, Vercel reconstruit le site automatiquement. Il installe exactement les mêmes versions des outils que chez nous, puis il vérifie le code. S'il trouve une erreur, le site n'est pas mis à jour. Ensuite, le site est publié et servi rapidement partout. Point important : la partie données ne tourne pas chez Vercel. On la lance chez nous, et on n'envoie que les petits fichiers prêts à l'emploi. On a donc deux rythmes : les données changent une fois par trimestre, le site peut changer à chaque modification.

## Slide 16 · Qualité : 62 tests et des étapes qui refusent les données fausses

**Régie :** Youcef · 17:15 – 18:15 · Avant de dire « les tests du site
passent », vérifier `npm test` sur une machine en Node 24+ (Vitest 5 ne démarre
pas sous Node 22.12).

> Pour la qualité, nous avons écrit 62 tests automatiques. Ce sont de petits programmes qui vérifient que chaque étape fait bien ce qu'elle doit faire : le téléchargement, la lecture des fichiers, le placement sur la carte, les statistiques, les prévisions et la préparation des données du site. Le site a aussi ses propres tests. Mais surtout, à chaque étape, une donnée incohérente arrête tout : un faux fichier, un fichier modifié, un total qui ne tombe pas juste, ou une erreur dans le code du site. Et la preuve que tout est reproductible est simple : nous avons tout reconstruit depuis zéro sur un nouvel ordinateur, les 62 tests passent, et on obtient exactement les mêmes résultats, au chiffre près.

## Slide 17 · Sécurité & performance

**Régie :** Youcef · 18:15 – 19:30

> Le fait de ne pas avoir de serveur nous aide aussi pour la sécurité et la rapidité. Pour la sécurité : il n'y a pas de serveur à attaquer, pas de base de données exposée sur internet, et aucun mot de passe dans notre code. Le site ne contacte qu'un seul service extérieur : celui qui fournit le fond de carte. Et les noms des parcs, qui viennent d'une source extérieure, sont affichés comme du simple texte, ce qui empêche d'y cacher du code malveillant. Pour la rapidité : quand vous changez un filtre, tout est recalculé directement dans votre navigateur, sans rien demander à un serveur. Et le code du site est découpé en plusieurs morceaux, que le navigateur garde en mémoire séparément. Le morceau le plus lourd reste la bibliothèque de composants visuels, plus de 260 kilo-octets compressés : la prochaine amélioration sera de ne charger certains onglets qu'au moment où on les ouvre. Soufiane, à toi de nous montrer ce que voit l'utilisateur.

## Slide 18 · Interface : rendre la nuance visible

**Régie :** Soufiane · 19:30 – 20:30

> Merci Youcef. Le site est construit avec React, un outil très utilisé pour créer des sites interactifs, et avec une bibliothèque de composants visuels qui s'appelle Astryx. Pour la carte, on utilise Leaflet, et pour les graphiques, Recharts. Notre objectif : montrer les nuances, pas seulement les chiffres. Le site a trois onglets : explorer, prévoir et vérifier. Les quatre chiffres clés en haut se mettent à jour à chaque filtre. Et les précautions, comme l'effet Central Park ou les parcs absents de la carte, sont affichées juste à côté des chiffres concernés, pas cachées dans une page que personne ne lit. On a aussi soigné les détails : la recherche fonctionne même si on oublie un accent ou une majuscule, et tout le site est en français, y compris pour les personnes qui utilisent un lecteur d'écran.

## Slide 19 · Visualisation : chaque encodage est un choix

**Régie :** Soufiane · 20:30 – 21:30

> Dans un graphique, chaque choix compte. Sur la carte, chaque parc est un cercle, et la taille du cercle dépend du nombre de crimes. Mais attention : notre œil compare des surfaces, pas des largeurs. Si on doublait la largeur du cercle quand les crimes doublent, un parc avec quatre fois plus de crimes paraîtrait seize fois plus gros. On a donc réglé la taille pour que la surface du cercle suive le nombre de crimes. Et on a fixé une taille maximale, pour que les très grands parcs ne cachent pas leurs voisins. La couleur montre soit le type de crime le plus fréquent, soit la famille du parc trouvée par Sarah. Les couleurs ont été choisies pour rester lisibles par les personnes daltoniennes. Et une prévision est toujours affichée avec sa marge d'erreur. Maintenant, passons au site.

## Slide 20 · Démonstration

**Régie :** Soufiane au micro, Youcef au clavier si besoin · 21:30 – 27:30 ·
Préparation : nyc-crimes.vercel.app ouvert, zoom navigateur à 125 %, filtres
réinitialisés. Secours, dans l'ordre : (1) `npm run dev` en local sur
localhost:5173 ; (2) vidéo de démo pré-enregistrée de 6 min ; (3) captures
d'écran.

> [21:30 – 22:15 · onglet Exploration] Voici le site en ligne. En haut, quatre chiffres clés : les 12 526 crimes de toute la période, le nombre de parcs touchés, le type de crime le plus fréquent et l'évolution récente. Tout est déjà chargé : le site n'attend aucune réponse d'un serveur.
> [22:15 – 23:30 · sélectionner MANHATTAN dans « Arrondissements »] Je choisis Manhattan. Regardez : les chiffres, la carte, la courbe et le classement changent tout de suite.
> [ajouter GRAND LARCENY dans « Types de délit »] J'ajoute le vol sans violence, le crime le plus fréquent à Manhattan, comme l'a montré Sarah. Sur la carte, Washington Square ressort tout de suite. [survoler le cercle pour afficher l'infobulle]
> [23:30 – 24:15 · réinitialiser les filtres, curseur « Période » sur 2024Q1 → 2026Q2] Revenons au chiffre du début. Je limite la période à 2024–2026. La marche au début de 2025 est bien là : c'est l'arrivée de Central Park dans les données.
> [taper « central » dans « Rechercher un parc »] Et si je cherche Central Park, il n'a aucun crime avant 2025. La preuve est visible directement sur le site.
> [24:15 – 24:45 · vider la recherche, activer « Colorer par cluster »] Avec ce bouton, la carte montre les quatre familles de parcs. Les grands parcs se distinguent clairement des petits parcs de quartier.
> [24:45 – 26:15 · cliquer sur « Prévisions »] Deuxième onglet : les prévisions. On y voit le modèle choisi et ses erreurs lors du test. La courbe montre le passé, puis la prévision pour les quatre prochains trimestres, avec une zone colorée qui représente la marge d'erreur.
> [montrer le tableau « Prévisions citywide »] Le tableau prévoit 378 crimes pour l'été 2026. Vous remarquerez aussi une valeur basse négative début 2027. Évidemment, on ne peut pas avoir moins de zéro crime : c'est une limite de la méthode de calcul de la marge. Nous préférons la montrer plutôt que la cacher, et la corriger fait partie de nos prochaines étapes. Juste en dessous, la précaution sur le choix du modèle est écrite en clair.
> [26:15 – 27:00 · cliquer sur « Méthode »] Dernier onglet : la méthode. On y trouve les sources, la période couverte, le trimestre 2020 manquant, l'erreur de total de Flushing Meadows, la part des parcs placés sur la carte et les conditions d'utilisation des données. Tous les pièges présentés par Sarah sont expliqués ici, pour le grand public.
> [27:00 – 27:30 · revenir sur Exploration, filtres réinitialisés] Un site, trois onglets, et aucune donnée inventée. Sarah, quelles sont les limites de tout ça ?

## Slide 21 · Limites & feuille de route

**Régie :** Sarah · 27:30 – 28:45

> Soyons honnêtes sur ce que ces données ne disent pas. Comme nous ne savons pas combien de personnes vont dans chaque parc, le nombre de crimes par surface ne dit pas si un promeneur est en danger. Ce sont aussi des plaintes, pas des faits prouvés, et les gens ne portent pas plainte de la même façon dans tous les quartiers. Côté prévision, le choix du modèle est un peu flatteur, et la marge d'erreur peut descendre sous zéro, ce qui n'a pas de sens pour un nombre de crimes : une méthode adaptée aux comptages corrigerait ce point. Deux zones n'ont pas assez de données pour une prévision à part. Enfin, les tests ne se lancent pas encore automatiquement à chaque modification du code, et les versions des outils Python ne sont pas encore figées. Pour chaque limite, la prochaine étape est indiquée dans ce tableau. Youcef, on conclut ?

## Slide 22 · Trois réponses, une méthode

**Régie :** Youcef · 28:45 – 29:30

> Trois questions, trois réponses. Les crimes sont concentrés : la plupart des parcs n'ont aucun crime grave sur un trimestre. Ils dépendent du lieu : 70 fois plus de crimes par surface à Manhattan qu'à Staten Island. Et ils sont prévisibles à court terme, avec 12 % d'erreur en moins qu'une règle simple. Mais si vous ne retenez qu'une chose, c'est ce chiffre : plus 3,93 % dans les données brutes, mais moins 1,06 % en réalité. C'est toute la différence entre publier une donnée et publier une donnée juste. Et c'est pour cette différence que nous avons construit tout ce projet.

## Slide 23 · Questions

**Régie :** Soufiane · 29:30 – 30:00 · Les trois intervenants se placent face
au jury.

> Merci de votre attention. Le site reste en ligne, et tout le code est disponible sur GitHub. Une seule commande permet de tout refaire, du téléchargement jusqu'au site. Nous sommes prêts pour vos questions : Sarah pour les données, Youcef pour l'organisation et la mise en ligne, et moi pour le site.
