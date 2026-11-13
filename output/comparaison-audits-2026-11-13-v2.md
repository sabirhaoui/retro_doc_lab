# Comparaison des audits — mise à jour du 13 novembre 2026

## Décision de provenance

L’utilisateur désigne `C:\workspace\twins_project` comme chemin source de vérité, mais la révision est **inconnue**. La référence manuelle décrit `C:\workspace\twins_project_feat_studio` et ne donne pas non plus de commit. La provenance de `twin-next` reste inconnue. En conséquence, cette note compare les livrables disponibles; elle ne rapproche pas les dépôts et ne vérifie aucun constat manuel dans le code.

**Vérification du code cible bloquée** jusqu’à confirmation d’une révision immuable ou autorisation explicite d’examiner un snapshot courant clairement marqué comme non révisé. Aucun contenu du projet cible, notamment cache, fichiers compilés ou artefacts de test, n’a été ouvert pour cette comparaison.

## Faits établis par les artefacts

| Artefact | Faits manifestés | Limite de comparaison |
|---|---|---|
| `twin-pipeline-20261113` | Statut `partial`, `source_root = C:\workspace\twins_project`, `source_revision = null` (`run.json:3-8`). 216 fichiers admis, 94 entrées exclues, 301 non inspectées; 19 fichiers Python et 3 TypeScript (`characterization.json:3-22`). | Révision et état Git inconnus; le nombre de fichiers ne mesure pas la couverture sémantique. |
| `twin-audit-v1` | Même chemin annoncé, révision nulle, statut `partial`; mêmes compteurs visibles que la dernière sortie (`run.json:3-8`, `characterization.json:3-22`). | Le manifeste est antérieur d’environ deux minutes; les compteurs communs ne prouvent pas que les livrables sont identiques. |
| `twin-next` | Statut `partial`, révision nulle; `index.md` annonce 1 271 fichiers inspectés, 149 exclusions et 105 non inspectés. Le manifeste ne contient pas de `source_root` établi (`run.json:1287-1291`, `index.md:5`). | Racine et révision inconnues : ne pas fusionner ses résultats avec les autres sorties. |
| `project-twin-backend-exhaustive` | `backend-summary.json` annonce `C:\workspace\twins_project`, révision nulle, 681 fichiers admis, 106 exclus et 8 non inspectés (`backend-summary.json:38-68`). | Périmètre backend distinct; aucun état de code commun n’est démontré. |
| Audit manuel | Le périmètre annonce `C:\workspace\twins_project_feat_studio`; branche et commit non établis. Il rapporte environ 902 fichiers, 249 fichiers Python dans `backend/app` et 46 specs frontend (`00-scope-and-environment.md:4-7`). | Ce périmètre n’est pas assimilable à `twins_project` sans preuve de provenance. |

## Apports visibles et écarts nouveaux

- **Par rapport à `twin-next`** : la dernière génération expose un registre backend distinct (`static-audit.json`), un index de séquences et des preuves par chemin/ligne/empreinte. Elle ne représente que 19 fichiers Python et 3 TypeScript; `architecture-audit.md` indique 3 fichiers dans le domaine Angular (`characterization.json:9-20`, `architecture-audit.md:5-9`). Ces différences décrivent les sorties, pas un progrès vérifié sur une même version.
- **Par rapport à `twin-audit-v1`** : les manifests consultés conservent le même chemin, les mêmes comptes, le même statut partiel et la révision inconnue. Aucun élargissement de périmètre n’est établi par ces métadonnées (`twin-audit-v1/run.json:3-8`, `twin-audit-v1/characterization.json:3-22`; `twin-pipeline-20261113/run.json:3-8`, `characterization.json:3-22`).
- **Par rapport à la sortie backend exhaustive** : les 681 fichiers de son manifeste et les 216 fichiers de la dernière génération correspondent à des périmètres différents; aucun ratio ou score de maturité n’est calculé.
- **Frontend** : l’inventaire récent inclut une route Angular comme chemin manifesté dans `twin-next` (`run.json:746`), mais cette sortie n’a pas de racine déclarée. La dernière génération a trop peu de TypeScript admis pour documenter les routes, guards, services HTTP, interceptors, environnements et proxy évoqués par la référence manuelle.
- **Findings manuels** : la référence possède un index de findings (index `architecture-audit/findings/INDEX.md`); aucun n’est confirmé ou infirmé ici. Les descriptions de la référence ne sont pas reprises comme faits du code.

## Défauts internes des livrables générés

### Incohérence de `request-001`

Le JSON associe `request-001` à `POST`, `app.api.auth_router.setup_account`, une preuve dans `backend/app/api/auth_router.py:34` et un chemin final nul (`sequence-index.json:9-19`). Dans `sequences.md`, le même bloc annonce ce handler, puis incorpore un diagramme `app.api.workspace_router` / `PUT` (`sequences.md:5-30`). Le Mermaid lié contient au contraire `app.api.auth_router` / `POST` (`diagrams/sequences/request-001.mmd:1-10`). C’est un défaut de cohérence rapport ↔ artefact lié; cela ne désigne pas le diagramme conforme au code du projet.

La cause correspondante est visible dans l’agent : `diagram_text` est écrit pour chaque fichier Mermaid (`src/retro_doc_agent/sequences.py:84-97`), puis la valeur de la dernière itération est réutilisée pour chaque bloc Markdown (`sequences.py:114-125`). La cause et le défaut de rendu sont établis sans lire ni exécuter le dépôt cible.

### Routes finales nulles et validation

L’index donne `route: null` pour `request-001` (et pour les premières entrées suivantes; `sequence-index.json:9-19, 36-45`). Le générateur historique inscrit `route: None` même lorsqu’il conserve méthode, handler et présence d’un littéral (`src/retro_doc_agent/static_audit.py:140-156`). Cela explique la valeur nulle dans ces sorties; aucune route réelle n’est déduite ici.

`validation.json` combine `valid: true`, `semantic_review: pending` et `mermaid.status: unvalidated` avec `parser: null` (`validation.json:1-9`). Ce sont des statuts différents. Le code de validation vérifie notamment des références et l’enveloppe textuelle des diagrammes, mais ne parse pas la grammaire Mermaid (`src/retro_doc_agent/pipeline.py:107-156`). Le skill diagrammes demande explicitement de marquer Mermaid non validé sans parseur (`skills/diagrams/SKILL.md:6-9`).

### Périmètre d’inventaire

Les compteurs incluent les racines `.pytest_cache` et `.test-observability-runtime` (`characterization.json:24-32`); le manifeste liste aussi un chemin sous `frontend/.angular/cache` (`run.json:78, 705`). Les contenus de ces éléments n’ont pas été lus dans cette reprise. L’exclusion de ces répertoires n’est pas présente dans l’ensemble `EXCLUDE` du pipeline historique (`src/retro_doc_agent/pipeline.py:16, 66-104`). Les fichiers Python compilés sont des `.pyc`, hors extensions admises par ce pipeline, mais aucun filtre dédié des extensions compilées n’est exposé par cet ensemble. Il faut exclure les artefacts générés avant ouverture, et non seulement les ignorer après analyse.

### Sécurité et gaps documentaires

`security-audit.md` présente explicitement des signaux à qualifier et plusieurs thèmes indéterminés; ce ne sont pas des vulnérabilités vérifiées (`security-audit.md:1-3, 5-57`). `state-of-art.md` dit que tous les gaps restent inconnus et rappelle l’absence de parseur Mermaid et de révision (`state-of-art.md:13-23`). Aucun finding de l’audit manuel n’est donc validé par la dernière sortie.

## Hypothèses et points bloqués

1. **Révision source** : inconnue pour le chemin choisi `C:\workspace\twins_project`; comparaison du code bloquée.
2. **Identité `twin-next`** : son manifeste ne permet pas de confirmer la racine; résultats conservés séparément.
3. **Référence manuelle** : racine différente et révision inconnue; parité et écarts code/documentation non démontrés.
4. **Comportement runtime, sécurité effective et couverture complète** : non établis par une analyse statique partielle. Aucun signal générique n’est transformé en vulnérabilité ou en fait d’exécution.
5. **Commandes et validations** : aucune commande, import, test, build, hook, script ni parseur n’a été exécuté sur le projet audité ou sur l’agent pendant cette reprise.

## Références principales

- Agent, génération de séquences : `src/retro_doc_agent/sequences.py:24-125`; extraction de routes : `src/retro_doc_agent/static_audit.py:140-156`.
- Agent, inventaire historique et validation : `src/retro_doc_agent/pipeline.py:16, 66-156`; inventaire de l’autre pipeline : `src/retro_doc_agent/inventory.py:9-88`.
- Agent, scanner statique Angular/FastAPI distinct : `src/retro_doc_agent/scan.py:1-126`, `src/retro_doc_agent/analyzers/web_infra.py:1-122`, `src/retro_doc_agent/analyzers/python_api.py:90-147`, `src/retro_doc_agent/resolution.py:1-125`.
- Sorties comparées : `output/twin-pipeline-20261113/run.json:3-8`, `characterization.json:3-32`, `sequence-index.json:9-19`, `sequences.md:5-30`, `diagrams/sequences/request-001.mmd:1-10`, `validation.json:1-9`, `security-audit.md:1-57`, `state-of-art.md:13-23`.
- Référence manuelle de provenance : `architecture-audit/00-scope-and-environment.md:3-7`.
