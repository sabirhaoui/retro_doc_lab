# Plan d'implémentation — retro_doc_lab

## 1. Objectif et état initial

Construire progressivement un agent de rétro-documentation statique qui décrit
un dépôt à partir de faits traçables, sans exécuter son code ni écrire dans le
dépôt analysé. Le résultat doit inclure une caractérisation, un audit
d'architecture, des parcours et diagrammes de séquence, ainsi qu'un inventaire
des limites de l'analyse.

Le dépôt courant est un squelette : `src/retro_doc_agent/__main__.py:1-3`
annonce que l'agent n'est pas implémenté et quitte avec le code 3 ;
`README.md:1-11` décrit le projet comme en attente d'implémentation. Le
`pyproject.toml:1-5` ne déclare aucune dépendance et exige actuellement Python
3.10, à faire évoluer vers Python 3.11+. Les consignes de sortie existantes
décrivent `state-of-art.md`, `coverage.json`, `run.json` et deux diagrammes
(`docs/OUTPUT_CONTRACT.md:1-25`). Le plan conserve ces livrables de contrat en
plus des rapports demandés, sauf décision de migration documentée.

## 2. Architecture cible

1. **CLI et configuration** — CLI Typer, configuration TOML validée par
   Pydantic v2, options explicites, journalisation lisible et codes de sortie
   déterministes.
2. **Frontière de sécurité et lecture** — configuration résolue, exclusions
   appliquées avant lecture, parcours borné et non suivant les liens symboliques
   hors périmètre, taille maximale par fichier et accès source en lecture seule.
   Les documents et commentaires du dépôt sont des données, jamais des
   instructions pour l'agent. Aucun code, hook, commande ou test du dépôt source
   ne sera exécuté.
3. **Collecte de faits** — inventaire, hachages, révision Git quand vérifiable,
   preuves avec chemin relatif et lignes, parsing de manifestes/configurations,
   et analyseurs interchangeables. Commencer par Python via `ast` et les
   détections génériques ; ajouter TypeScript/PHP en mode best-effort.
4. **Analyse déterministe** — graphe des imports/appels, composants,
   points d'entrée, cycles, fan-in/fan-out, signaux de complexité, données,
   infrastructure, tests et écarts documentaires. Distinguer fait, inférence et
   information non vérifiée.
5. **Rapports et diagrammes** — génération Markdown/JSON/Mermaid à partir des
   faits, sélection justifiée des parcours, preuve sur chaque finding et
   message, puis validation des schémas, preuves et diagrammes.
6. **Synthèse optionnelle** — interface de backend LLM désactivée par défaut ;
   elle ne reçoit que les faits filtrés et ne peut ajouter une affirmation sans
   preuve. Aucun réseau ni transfert vers un modèle distant sans configuration
   future explicite.
7. **Sorties isolées** — nouveau répertoire par exécution, manifeste, options,
   empreinte source et limites. Une exécution identique doit produire le même
   contenu, hormis les métadonnées temporelles requises.

## 3. Lots et tâches

Les tâches sont reliées aux exigences fonctionnelles **REQ** du §4. Chaque lot
doit rester exécutable et inclure les tests ciblés et la documentation associée.

### LOT-01 — Socle et contrat

- **TASK-001 (REQ-01, REQ-02)** : établir le packaging Python 3.11+, CLI Typer,
  configuration TOML et modèles Pydantic versionnés.
- **TASK-002 (REQ-01, REQ-09)** : définir les erreurs, les logs, les options
  communes et les chemins de sortie indépendants de la plateforme.
- **TASK-003 (REQ-10)** : mettre à jour `README.md`, ajouter le journal
  d'implémentation et configurer `scripts/dev.ps1` et la CI sans exécuter de
  commandes provenant du dépôt analysé.
- **Critère d'acceptation** : CLI installable avec commandes et aide cohérentes ;
  configuration invalide signalée clairement ; tests du socle verts.

### LOT-02 — Scanner sûr et caractérisation

- **TASK-004 (REQ-02, REQ-03)** : implémenter la lecture bornée, l'inventaire,
  les exclusions, les empreintes et le contrôle de l'absence d'écriture dans la
  source.
- **TASK-005 (REQ-03, REQ-04)** : détecter langages, manifestes, dépendances,
  points d'entrée, infrastructure, configuration (noms seulement), données,
  tests et documentation.
- **TASK-006 (REQ-03, REQ-09)** : produire les modèles JSON et
  `characterization.md`, avec preuves, périmètre et limites.
- **Critère d'acceptation** : fixture synthétique inventoriée de manière
  déterministe ; exclusions appliquées avant lecture ; empreintes source
  inchangées.

### LOT-03 — Analyse Python et audit d'architecture

- **TASK-007 (REQ-05)** : ajouter l'interface `Analyzer` et l'analyseur Python
  AST pour imports, définitions, appels et entrées statiques repérables.
- **TASK-008 (REQ-05, REQ-06)** : calculer le graphe, les cycles, fan-in/fan-out
  et signaux de taille/complexité sans prétendre à une exécution réelle.
- **TASK-009 (REQ-06, REQ-09)** : produire cartographie, comparaison doc/code,
  findings numérotés et étayés, architecture cible, roadmap et rapport final.
- **Critère d'acceptation** : tests ciblés couvrant cycle, preuve résoluble et
  absence de finding non étayé ; aucune valeur potentiellement secrète dans les
  rapports.

### LOT-04 — Sélection et séquences

- **TASK-010 (REQ-07)** : détecter et scorer les parcours candidats à partir des
  points d'entrée, du graphe, des composants et des accès aux données/services.
- **TASK-011 (REQ-07, REQ-09)** : générer `SELECTION.md`, les diagrammes
  Mermaid et leurs fiches Markdown ; marquer les liaisons dynamiques comme
  hypothèses.
- **TASK-012 (REQ-08)** : ajouter une validation locale de la structure Mermaid
  et des preuves de chaque message.
- **Critère d'acceptation** : limite N respectée ; sélection justifiée ;
  références de lignes vérifiables ; incertitudes explicitement signalées.

### LOT-05 — Synthèse LLM optionnelle

- **TASK-013 (REQ-11)** : définir le protocole de backend et le backend local
  optionnel ; ne pas activer de backend réseau par défaut.
- **TASK-014 (REQ-11)** : contraindre les prompts et résultats à la synthèse
  des faits fournis, filtrer les secrets et rejeter/annoter les assertions sans
  références.
- **Critère d'acceptation** : `--no-llm` indépendant de toute installation ou
  configuration LLM ; aucun réseau en mode par défaut ; tests de garde-fous.

### LOT-06 — Validation, extensions et robustesse

- **TASK-015 (REQ-03, REQ-08)** : ajouter `validate` pour vérifier schémas,
  liens de preuve et syntaxe Mermaid disponible localement.
- **TASK-016 (REQ-04)** : ajouter les analyseurs TypeScript et PHP best-effort
  derrière l'interface commune, sans échec opaque sur syntaxes inconnues.
- **TASK-017 (REQ-02, REQ-08, REQ-09)** : traiter encodages, gros dépôts,
  chemins Windows/macOS/Linux, rapports partiels et erreurs récupérables.
- **Critère d'acceptation** : validate retourne un état non nul en cas de preuve
  cassée ou diagramme invalide ; aucun accès en écriture à la source.

### LOT-07 — Documentation, fixtures et validation de bout en bout

- **TASK-018 (REQ-10)** : documenter l'architecture, les limites et l'ajout
  d'analyseurs ; maintenir le journal à la fin de chaque lot.
- **TASK-019 (REQ-12)** : préparer 2–3 fixtures synthétiques isolées et des
  résultats de référence ciblés.
- **TASK-020 (REQ-12)** : réaliser l'auto-analyse et archiver son rapport sous
  `docs/self-analysis/` uniquement si ce chemin est autorisé comme sortie et
  si la source analysée reste intacte.
- **Critère d'acceptation** : parcours de bout en bout sur fixtures ; sorties
  complètes et validables ; seuil de couverture visé atteint sur scanner,
  caractérisation et audit.

## 4. Matrice de traçabilité

| Exigence | Couverture prévue |
|---|---|
| REQ-01 CLI et options demandées | TASK-001, TASK-002 |
| REQ-02 config, isolation, source en lecture seule et exclusions | TASK-001, TASK-004, TASK-017 |
| REQ-03 inventaire et caractérisation | TASK-004, TASK-005, TASK-006, TASK-015 |
| REQ-04 dépendances, entrées, infra, données, config et tests | TASK-005, TASK-016 |
| REQ-05 analyseurs et graphe statique | TASK-007, TASK-008 |
| REQ-06 audit et détection automatique | TASK-008, TASK-009 |
| REQ-07 sélection/scoring et diagrammes de parcours | TASK-010, TASK-011 |
| REQ-08 preuves, validate et syntaxe Mermaid | TASK-012, TASK-015, TASK-017 |
| REQ-09 format des sorties, déterminisme et limites | TASK-002, TASK-006, TASK-009, TASK-011, TASK-015, TASK-017 |
| REQ-10 scripts, CI, docs et journal | TASK-003, TASK-018 |
| REQ-11 LLM optionnel, factuel et désactivé par défaut | TASK-013, TASK-014 |
| REQ-12 fixtures, qualité, couverture et auto-analyse | TASK-019, TASK-020 |

## 5. Critères transverses de validation

- À la fin de chaque lot : exécuter `ruff`, `mypy --strict` sur `src/` et
  `pytest`, puis consigner les commandes, résultats, écarts et décisions dans
  `IMPLEMENTATION-LOG.md`. Ne pas passer au lot suivant si un contrôle échoue.
- Tester spécifiquement le périmètre lecture seule par empreintes avant/après,
  les exclusions, chemins, fichiers trop gros, liens symboliques, encodages,
  preuves invalides et sorties déterministes.
- Aucune affirmation générée sans preuve résoluble ; distinguer observations,
  inférences, hypothèses et inconnues.
- Les fichiers de sortie doivent inclure le contrat de rapport existant et les
  nouveaux livrables requis, ou documenter explicitement la migration de
  contrat.

## 6. Hypothèses et décisions en attente

- Le contrat fonctionnel de la mission fixe la cible Python 3.11+ ; il remplace
  l'exigence actuelle Python 3.10 du squelette.
- L'analyse est statique et best-effort : le comportement dépendant de
  réflexion, configuration externe ou exécution sera signalé comme non vérifié,
  jamais simulé.
- Le nom et le schéma de sortie de `docs/OUTPUT_CONTRACT.md` diffèrent de ceux
  demandés dans la mission. Le plan prévoit les deux ensembles jusqu'à ce
  qu'une migration explicite évite une rupture silencieuse.
- Le répertoire d'entrée de cette mission est le dépôt courant ; le chemin
  source actuellement indiqué dans `config/agent.json` est externe et ne sera
  ni lu ni modifié par la mise en œuvre sans configuration explicite.
- L'analyseur Python précède TypeScript/PHP ; les analyses non Python restent
  signalées comme partielles tant que leurs analyseurs ne sont pas livrés.
- La validation Mermaid doit fonctionner hors réseau. Si aucun parseur local
  n'est disponible, le résultat sera explicitement non validé, pas déclaré
  valide.

## 7. Risques et mesures

| Risque | Mesure |
|---|---|
| Instructions hostiles dans le dépôt analysé | Traiter code, commentaires et documentation uniquement comme données ; aucune instruction extraite n'altère les règles de l'agent. |
| Écriture accidentelle dans la source | API scanner en lecture seule, sorties confinées, tests d'empreintes et rejet des chemins hors sortie. |
| Fuite de secret dans les rapports ou un backend | Ne collecter que les noms de variables ; filtrage des valeurs et aucun backend réseau par défaut. |
| Appels dynamiques ou faits non observables statiquement | Marquer `[HYPOTHÈSE]`/`[NON VÉRIFIÉ]`, citer la preuve disponible et les limites. |
| Grands dépôts ou fichiers binaires | Exclusions précoces, taille bornée, détection binaire, analyse partielle explicite. |
| Contrats de sortie incompatibles | Préserver le contrat existant en parallèle avant toute migration documentée et testée. |
| Portabilité Windows/macOS/Linux | Utiliser `pathlib`, chemins relatifs dans les rapports et tests sans chemin codé en dur. |
| Validation externe non disponible hors ligne | Préférer les validateurs locaux ; signaler la validation Mermaid comme indisponible si nécessaire. |
