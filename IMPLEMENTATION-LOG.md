# Journal d'implémentation

## LOT-01 — Socle et contrat

- **État :** terminé ; contrôles verts.
- **Tâches :** TASK-001, TASK-002 et TASK-003 (REQ-01, REQ-02, REQ-09,
  REQ-10).
- **Changements :** packaging Python 3.11+, dépendances Typer/Pydantic,
  configuration TOML typée, modèles de preuve/manifeste, enregistrement des
  commandes CLI, script PowerShell, pipeline GitLab, tests de configuration et
  documentation du socle.
- **Validation :** environnement isolé Python 3.14.8 ; `ruff check src tests`
  réussi, `mypy src` réussi en mode strict, `pytest` réussi (4 tests) et
  `retro-doc-lab --help` ainsi que `analyze --help` exécutés sans erreur.
- **Écart :** les commandes d'analyse et `validate` sont enregistrées, mais
  retournent explicitement le code 3 jusqu'aux lots qui implémentent leurs
  fonctionnalités. Le script `run` vise la fixture FastAPI du LOT-07.
- **Décision :** poursuivre avec LOT-02 après validation verte.

## LOT-02 — Scanner sûr et caractérisation

- **État :** terminé ; contrôles verts.
- **Tâches :** TASK-004, TASK-005 et TASK-006 (REQ-02, REQ-03, REQ-04,
  REQ-09).
- **Changements :** scanner trié et borné, exclusions par défaut et règles
  `.gitignore` racine/nestées, absence de suivi des liens symboliques,
  empreinte et inventaire par fichier, schéma Pydantic de caractérisation,
  extraction des manifestes usuels, langages, frameworks, entrées candidates,
  infrastructure, données, noms de variables d'environnement, tests et
  documentation. `characterize` génère un nouveau run dans un dossier de
  sortie extérieur à la source ainsi que `characterization.json/.md`,
  manifestes et rapport d'étape.
- **Validation :** `ruff check src tests` réussi ; `mypy src` strict réussi ;
  `pytest` : 9 réussis, 1 ignoré (Windows n'autorise pas la création de lien
  symbolique dans l'environnement courant). La CLI `characterize --help` et
  son chemin d'écriture explicite sont couverts.
- **Limites/écarts :** analyse de manifestes en best-effort ; révision Git,
  fichiers modifiés et couverture documentaire non collectés ; motifs
  textuels pour variables d'environnement et points d'entrée ; fichiers
  symboliques, binaires ou exclus documentés sans inspection. Les autres
  commandes restent en attente de leurs lots.
- **Décision :** garder le statut d'exécution partiel quand des fichiers
  admissibles sont non inspectés ou des limites du scanner sont rencontrées.

## LOT-03 — Analyse Python et audit d'architecture

- **État :** terminé pour le noyau statique et validation verte.
- **Tâches :** TASK-007, TASK-008 et TASK-009 (REQ-05, REQ-06, REQ-09).
- **Changements :** consolidation de l'analyseur Python AST, extraction de
  modules/imports/fonctions/appels, détection de cycles et de signaux de secret,
  construction de findings étayés, génération des livrables d'audit dans
  `architecture-audit/` et rapport de synthèse dans le dossier de run.
- **Validation :** `ruff check src tests` réussi ; `mypy --strict src` réussi ;
  `pytest -q` réussi (9 tests, 1 ignoré sur Windows pour la création de lien
  symbolique). Toutes les opérations restantes restent hors périmètre source et
  sans exécution des dépendances du dépôt analysé.
- **Écarts et hypothèses :** le graphe est statique et best-effort ; les appels
  dynamiques, les décorateurs opaques et les injections sont explicitement
  marqués comme non vérifiés, avec preuves limitées aux fichiers inspectés.
- **Décision :** passer au LOT-04 pour la sélection de parcours et la génération
  des diagrammes Mermaid, en gardant le mode `--no-llm` comme chemin de
  fonctionnement principal.
