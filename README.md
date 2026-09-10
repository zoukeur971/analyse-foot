# Analyse Foot

Site d'analyse football et de detection de value bets, mis a jour tout seul chaque matin.

Le modele (Poisson bivarie, correction Dixon-Coles, forces d'attaque et de defense,
avantage du terrain, melange avec la cote du marche) vit dans `engine/`. Il remplace
le classeur Excel : celui-ci n'est plus qu'une copie de sortie, dans `classeur/`.

## Ce que fait la mise a jour automatique

Chaque passage, dans l'ordre :

1. releve les scores des rencontres jouees depuis la derniere fois ;
2. les archive dans `data/results.json` avec la prediction exactement telle qu'elle
   avait ete annoncee, jamais recalculee apres coup ;
3. recalcule les forces de chaque equipe a partir de tous les matchs de la saison,
   en s'appuyant sur la saison precedente pour les championnats absents de la base
   fournie (Eredivisie, Primeira Liga, Championship, Bresil, Libertadores) ;
4. recalcule la calibration (verdict correct, log-loss, tranches de probabilite) et
   reajuste le correctif de niveau de buts et l'avantage du terrain, amortis tant que
   l'echantillon est faible et plafonnes a 3 % de variation par passage ;
5. recupere les rencontres des 7 prochains jours et leurs cotes 1N2 ;
6. ecrit `docs/data.json`, que le site lit au chargement, et regenere `classeur/`.

## Installation, une seule fois

### 1. Les deux cles d'API (gratuites)

| Service | Adresse | Ce qu'il apporte | Plan gratuit |
|---|---|---|---|
| football-data.org | <https://www.football-data.org/client/register> | calendriers et resultats des 13 competitions | 10 appels par minute |
| the-odds-api.com | <https://the-odds-api.com/#get-access> | cotes 1N2, Betclic France incluse | 500 credits par mois |

La mise a jour consomme au plus un credit de cotes par competition et par passage,
soit environ 390 par mois en tournant tous les jours, et moins en pratique puisque
seules les competitions qui ont des rencontres dans la fenetre sont interrogees. Le nombre de credits restants
est affiche dans le journal de chaque execution.

### 2. Le depot

Cree un depot **public** sur GitHub (les GitHub Pages ne sont gratuites que sur un
depot public ; en depot prive il faut un compte Pro), puis depose ces fichiers a la
racine. Aucune cle n'est ecrite dans le code : elles vivent dans les secrets.

### 3. Les secrets

Onglet **Settings > Secrets and variables > Actions > New repository secret** :

- `FOOTBALL_DATA_TOKEN` : la cle football-data.org
- `ODDS_API_KEY` : la cle the-odds-api.com

### 4. La publication du site

Onglet **Settings > Pages** : source **Deploy from a branch**, branche `main`,
dossier `/docs`. Le site apparait sur `https://<ton-pseudo>.github.io/<depot>/`.

### 5. Le premier passage

Onglet **Actions > Actualiser > Run workflow**. Le meme bouton sert a forcer une
actualisation a tout moment, depuis un ordinateur comme depuis un telephone.
Ensuite, le job tourne seul chaque matin a 5h30 UTC (7h30 a Paris en ete).

## Regler le modele

Tout est dans `data/params.json`, modifiable directement sur GitHub :

| Cle | Role |
|---|---|
| `avantage_terrain` | multiplie les buts attendus a domicile, divise ceux a l'exterieur |
| `rho` | correction Dixon-Coles, rehausse les scores serres |
| `poids_forme` | part maximale de la saison en cours dans la force d'une equipe |
| `poids_h2h` | part des confrontations directes dans la probabilite finale |
| `poids_marche` | part de la cote du marche dans le verdict affiche |
| `correctif_buts` | multiplie les deux buts attendus de chaque rencontre |
| `edge_min`, `cote_max`, `divergence_max` | filtres de detection des value bets |
| `proba_min_selection`, `edge_min_selection`, `cote_min_selection` | seuils de l'onglet Selections |
| `kelly`, `bankroll` | calcul des mises |
| `auto_calibration` | si `true`, ajuste seul le correctif de buts et l'avantage du terrain |
| `auto_poids_marche` | si `true`, deplace le poids du marche vers son optimum, au-dela de 150 matchs |

`historique` garde la trace de chaque ajustement automatique.

## Fichiers

```
engine/model.py       Poisson, Dixon-Coles, marches derives, selections
engine/calibrate.py   journal des predictions, log-loss, calibration, reglages suggeres
engine/sources.py     football-data.org et the-odds-api
engine/names.py       correspondance des noms d'equipes entre API et base
engine/build.py       la chaine complete
tools/classeur.py     copie Excel de la sortie
tools/amorcer.py      genere un data.json de depart sans appeler les API
data/                 base des equipes, journal des resultats, H2H, parametres, etat
docs/                 le site (index.html + data.json)
```

## Les competitions couvertes

Ligue 1, Premier League, Liga, Serie A, Bundesliga, Eredivisie, Primeira Liga,
Championship, Campeonato Brasileiro, Copa Libertadores, Ligue des Champions,
Championnat d'Europe, Coupe du Monde.

Les cinq grands championnats arrivent avec la base 2025-26 deja saisie. Les autres
se construisent tout seuls au premier passage a partir de la saison precedente
recuperee sur l'API, puis se calibrent au fil des journees jouees.

## Limites a garder en tete

Sur les cotes relevees, la probabilite moyenne du favori du marche tourne autour de
52 %. C'est le taux de bonnes issues maximal atteignable en 1N2 : viser 70 % n'a de
sens qu'en double chance ou sur les marches de buts. Sous 100 matchs enregistres,
aucun ecart de calibration n'est interpretable, la variance domine tout.

Les cotes de doubles chances affichees sont deduites des cotes 1N2 et sont optimistes
de deux a quatre points. Releve la vraie cote chez ton bookmaker avant de miser.
