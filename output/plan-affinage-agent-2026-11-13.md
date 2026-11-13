# Spécification d’implémentation — affinage de `retro_doc_agent`

## Garde de provenance

Le chemin déclaré par l’utilisateur est `C:\workspace\twins_project`; sa révision est inconnue. La référence manuelle désigne une autre racine. Jusqu’à résolution, les changements ci-dessous doivent être développés et testés avec des fixtures synthétiques du laboratoire, sans lire le code cible ni recopier les findings manuels.

L’agent dispose de deux parcours à préserver : le pipeline historique (`pipeline.py`, `static_audit.py`, `sequences.py`, `reporter.py`) qui produit notamment `characterization.json`, `static-audit.json` et `sequence-index.json`; et le scan statique (`scan.py`, `inventory.py`, `analyzers/*`, `resolution.py`, `renderers/markdown.py`) qui produit notamment `architecture.json`, `inventory.json`, `coverage.json` et Mermaid. Les sorties et schémas ne doivent pas être assimilés sans contrôle de version.

Chaque tâche ci-dessous indique les fichiers concernés, les dépendances, les critères d’acceptation et les tests suggérés. Les tests sont des propositions pour un futur agent autorisé; aucun test n’a été lancé dans cette reprise.

## T0 — Provenance explicite et non fusion des sorties

- **Fichiers concernés** : `src/retro_doc_agent/pipeline.py` (création de `run.json`), `src/retro_doc_agent/scan.py` (manifestes v2), `src/retro_doc_agent/models/report.py` et `src/retro_doc_agent/reporter.py`.
- **Dépendances** : aucune; prérequis à toute comparaison de code avec un baseline.
- **Travail** : faire apparaître dans tous les manifests la racine source déclarée, la révision exacte lorsqu’elle est fournie, et le cas `unknown` sans la remplacer par une valeur implicite. Garder source, hash de périmètre, révision et état de complétude distincts. Refuser les comparaisons de code entre racines différentes ou entre versions inconnues, sauf mode explicitement « artefacts seulement ».
- **Acceptation** : les deux formats de sortie exposent des champs provenance cohérents; l’absence de révision reste `null`/`unknown`; aucune comparaison de documentation au code n’est qualifiée de fraîche sans racine et version identiques.
- **Tests suggérés** : manifestes sans révision; racines différentes; même racine mais révisions différentes; comparaison artefacts seulement. Ajouter aux tests de pipeline existants sans accéder à un dépôt réel.

## T1 — Exclusions sûres et comptage du périmètre

- **Fichiers concernés** : `src/retro_doc_agent/pipeline.py:16, 66-104`, `src/retro_doc_agent/inventory.py:9-88`, `src/retro_doc_agent/scanner/filesystem.py:69-220`, `src/retro_doc_agent/config.py`.
- **Dépendances** : aucune. Cette tâche précède l’analyse des fichiers inclus.
- **Travail** : unifier les exclusions utilisées par chaque scanner et les appliquer avant l’ouverture des fichiers. Ajouter au minimum caches (`.angular/cache`, `.pytest_cache`, `.ruff_cache`, `.mypy_cache`, `__pycache__`), builds (`dist`, `build`, `out`, `target`, `.next`), environnements (`.venv`, `venv`, `.tox`, `.nox`, `node_modules`) et artefacts générés de tests (`coverage`, `htmlcov`, `test-results`, `playwright-report`, `.coverage*`, dossiers temporaires `.test-*`, bytecode et bundles compilés). Ne pas exclure en bloc les sources de tests maintenues. Conserver les protections nommées pour secrets; ne jamais recopier de valeur sensible.
- **Acceptation** : les fixtures placées dans chaque catégorie apparaissent exclues avant toute lecture; les sources de tests demeurent incluses; chaque sortie compte explicitement les fichiers admis, les entrées exclues et les éléments non inspectés avec causes. Les catégories de compte sont documentées et sans double compte silencieux.
- **Tests suggérés** : étendre `tests/test_scanner.py` et `tests/test_pipeline.py` avec un lecteur instrumenté qui échoue si un fichier exclu est ouvert; tester les exclusions imbriquées, les motifs configurés, les fichiers trop grands et les comptes.

## T2 — Cohérence atomique des séquences

- **Fichiers concernés** : `src/retro_doc_agent/sequences.py:24-125`, `src/retro_doc_agent/static_audit.py:140-156`, `src/retro_doc_agent/pipeline.py:107-156`, `src/retro_doc_agent/reporter.py`.
- **Dépendances** : aucune pour la correction et les tests sur fixtures.
- **Travail** : former une seule donnée de séquence canonique par identifiant : méthode, route résolue ou `null`, handler, preuves de route/appels et contenu Mermaid. Produire le JSON, le diagramme lié, le Mermaid incorporé dans `sequences.md` et tout extrait de rapport depuis cette même donnée. Ne pas réutiliser de variable de diagramme provenant d’une autre itération. Préserver les marqueurs `observé`, `inféré` et `non résolu`; route dynamique ou non résolue doit rester explicitement inconnue.
- **Acceptation** : pour chaque ID, les valeurs méthode/route/handler/preuves sont identiques dans les rendus; le diagramme embarqué est identique au fichier lié; aucune référence ne pointe vers un autre ID. Pour `request-001`, le fixture avec index `POST` + `app.api.auth_router.setup_account`, diagramme lié auth/POST et bloc Markdown discordant workspace/PUT échoue avant correction et passe après. Le test vérifie la cohérence interne, pas la route réelle du projet.
- **Tests suggérés** : ajouter des fixtures multi-routes à `tests/test_pipeline.py` ou un fichier de test dédié à `sequences.py`; couvrir zéro route, plusieurs routes avec méthodes différentes, route nulle, troncature et ordre stable.

## T3 — Couverture Angular traçable

- **Fichiers concernés** : `src/retro_doc_agent/analyzers/web_infra.py:1-122`, `src/retro_doc_agent/scan.py:13-126`, `src/retro_doc_agent/model.py`, `src/retro_doc_agent/renderers/markdown.py:18-22`.
- **Dépendances** : T1 pour garantir que seuls les fichiers source ciblés sont ouverts.
- **Travail** : étendre le modèle statique existant pour inventer les routes (`path`, `children`), navigation lazy (`loadChildren`, `loadComponent`), guards (`canActivate`, `canMatch`), composants, services HTTP, interceptors, environnements, et configuration proxy Angular. Associer chaque fait à une preuve de chemin et de lignes. Les expressions non littérales restent non résolues; ne pas évaluer TypeScript ni déduire une activation runtime.
- **Acceptation** : `coverage.json`/`architecture.json` distinguent catégorie, preuve et statut; l’index inclut les routes lazy/guards et signale explicitement les références dynamiques; composants/services/interceptors sont séparés; environnements et proxy sont rapportés comme candidats jusqu’à preuve de configuration utilisée.
- **Tests suggérés** : fixtures TypeScript pour route déclarative, enfant lazy, guard, composant, service `HttpClient`, interceptor fonctionnel et classe, `environment` importé, proxy déclaré/non littéral; vérifier les lignes citées et les cas non résolus. Étendre les tests autour de `scan.py` sans parser ni exécuter les fixtures.

## T4 — Corrélation Angular ↔ FastAPI à confiance explicite

- **Fichiers concernés** : `src/retro_doc_agent/analyzers/web_infra.py`, `src/retro_doc_agent/analyzers/python_api.py:90-147`, `src/retro_doc_agent/resolution.py:1-125`, `src/retro_doc_agent/model.py`.
- **Dépendances** : T1 et T3; réutiliser les méthodes, préfixes `include_router` et appels HTTP statiques existants.
- **Travail** : construire les liens par étapes prouvées : route écran → composant → service → appel HTTP/URL reconstruite → rewrite/proxy établi → route FastAPI finale → paramètres `Depends`/auth → appels service → stockage/externe. Reporter pour chaque relation `certain`, `probable` ou `non_resolu`, preuves et raison. Ne promouvoir une paire à `certain` que si elle est unique et déterminée par des éléments statiques explicites; une compatibilité de motif seule reste `probable`. Laisser les montages conditionnels, URLs runtime et imports dynamiques non résolus. Publier les appels frontend sans endpoint candidat **et** les endpoints backend sans appel candidat.
- **Acceptation** : aucun appariement n’est créé sans preuve pour chaque arête; méthode, préfixes, paramètres de chemin et rewrites sont pris en compte; `Depends` est relié seulement quand l’argument/la relation est traçable; les deux listes de non-appariements sont présentes même si vides; la confiance est toujours l’une des trois valeurs prescrites.
- **Tests suggérés** : fixtures minimales synthétiques avec route FastAPI directe, préfixes d’application/routeur, méthode incompatible, paramètre de chemin, base URL littérale, rewrite proxy explicite, service Angular, URL dynamique et endpoint orphelin. Tester les trois confiances et les deux directions non appariées.

## T5 — Parcours transversaux sélectionnés depuis le graphe prouvé

- **Fichiers concernés** : `src/retro_doc_agent/sequences.py`, `src/retro_doc_agent/resolution.py`, `src/retro_doc_agent/renderers/markdown.py:62-111`, `src/retro_doc_agent/model.py`.
- **Dépendances** : T2 et T4.
- **Travail** : sélectionner un petit nombre de parcours à partir de chemins prouvés du graphe, avec borne explicite. Représenter UI, API, service, stockage/externe seulement si la relation existe. Chaque étape porte son statut `observé` ou `inféré`; toute possibilité non étayée est notée `[HYPOTHÈSE]` et visuellement distincte, jamais présentée comme une étape observée. Ne pas présumer que les parcours manuels auth/Studio existent dans la version à analyser.
- **Acceptation** : chaque nœud et arête renvoie à une preuve; les séquences coupées, ambiguës ou dynamiques signalent où et pourquoi; aucun parcours n’est généré si le graphe n’établit pas de chemin transversal.
- **Tests suggérés** : fixtures d’un parcours complet prouvé, d’un parcours interrompu par une URL dynamique, de deux candidats backend, d’un lien asynchrone incertain et d’un graphe sans chemin UI→API.

## T6 — Contrats et configuration sans rapprochement inventé

- **Fichiers concernés** : `src/retro_doc_agent/analyzers/web_infra.py`, `src/retro_doc_agent/analyzers/python_api.py`, `src/retro_doc_agent/resolution.py`, `src/retro_doc_agent/renderers/markdown.py`.
- **Dépendances** : T3 et T4.
- **Travail** : rapprocher modèles TypeScript et schémas Pydantic par route et champs lorsque le lien est déjà établi; comparer nom, type statiquement lisible, optionalité et champs de requête/réponse sans dériver le comportement d’exécution. Relier base URL d’environnement, configuration proxy et préfixes FastAPI uniquement sur preuves. Sinon enregistrer explicitement `unknown`/`non_resolu`.
- **Acceptation** : chaque différence de contrat/configuration cite les deux côtés; les paires impossibles à déterminer sont séparées des différences établies; aucun préfixe, environnement actif ou contrat n’est choisi par défaut.
- **Tests suggérés** : cas de types et champs concordants, champ absent, types incompatibles, modèle non apparié, préfixe littéral et préfixe dynamique, proxy absent/inactif/non résolu.

## T7 — Findings et comparaison documentaire sans doublons

- **Fichiers concernés** : `src/retro_doc_agent/audit/service.py:162-193, 402-423, 519-541`, `src/retro_doc_agent/models/architecture.py` (modèle `Finding`), `src/retro_doc_agent/reporter.py`, `src/retro_doc_agent/pipeline.py:322-323`.
- **Dépendances** : T0 pour toute comparaison à une version source; T1 pour l’inventaire documentaire; T4 pour les flux.
- **Travail** : réutiliser les champs existants de finding (preuves, impact, recommandation) et ajouter une clé de déduplication stable ainsi qu’un niveau de confiance et le statut de vérification. Séparer fait statique, inférence, limite et `[HYPOTHÈSE]`. Comparer les documents au code uniquement lorsque racine et révision correspondent; sinon classer le résultat comme non comparable, sans recopier les findings manuels.
- **Acceptation** : un même problème étayé par plusieurs chemins n’apparaît qu’une fois avec toutes ses preuves; impact et recommandation sont renseignés ou marqués inconnus; aucune vulnérabilité n’est annoncée par un signal générique; les comparaisons cross-version sont bloquées et motivées.
- **Tests suggérés** : findings dupliqués avec preuves multiples, même titre mais preuves/causes distinctes, statut non vérifié, racines/révisions égales et divergentes, absence de documents.

## T8 — Statuts de validation indépendants

- **Fichiers concernés** : `src/retro_doc_agent/pipeline.py:107-156`, `src/retro_doc_agent/renderers/markdown.py:130-138`, `src/retro_doc_agent/sequences.py`, `skills/diagrams/SKILL.md:6-9`.
- **Dépendances** : T2 pour contrôler les références aux séquences; les autres contrôles restent exécutables indépendamment.
- **Travail** : remplacer le booléen ambigu seul par des statuts séparés : parsing/validation JSON et schéma, intégrité structurelle et références, parsing Mermaid (`passed|failed|unvalidated`, avec parseur/version si exécuté), revue sémantique (`passed|failed|pending`) et tests (`passed|failed|not_run`). Ne jamais inférer un succès de Mermaid depuis la validité JSON ou l’enveloppe `sequenceDiagram`.
- **Acceptation** : absence de parseur produit obligatoirement `mermaid.status = unvalidated`, jamais positif; erreurs JSON/schéma, références invalides, syntaxe Mermaid et revue sémantique n’écrasent pas les statuts des autres axes; `valid: true` n’est plus présenté comme résultat global de syntaxe ou de sémantique.
- **Tests suggérés** : JSON invalide, schéma invalide, référence/empreinte invalide, Mermaid malformé avec parseur disponible, parseur absent, revue en attente et échec d’un seul axe sans faux succès sur les autres.

## Ordre suggéré

T0 et T1 peuvent démarrer indépendamment sur fixtures. T2 peut être traité en parallèle, sans code cible. Ensuite T3, puis T4; T5 et T6 dépendent de ces relations; T7 requiert T0 dès qu’il compare la documentation au code. T8 peut commencer sur les sorties existantes, puis doit être étendu aux schémas stabilisés de T2–T7.

## Limites de cette spécification

Les références aux fichiers agent décrivent les implémentations lues, pas le comportement du projet audité. Les sorties générées citées ailleurs n’établissent ni le comportement runtime, ni la sécurité effective, ni la couverture complète. Cette spécification n’est pas un patch et n’inclut aucune exécution de test.
