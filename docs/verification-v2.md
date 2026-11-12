# Verification de la cartographie v2 — 12 novembre 2026

Environnement effectivement utilise : Windows PowerShell, interpreteur Python
du runtime local Codex. L'alias WindowsApps `python.exe` etait inutilisable;
aucun paquet n'a ete telecharge. Aucun script, test, hook ou module de Project
Twin n'a ete execute. Les modifications preexistantes du lab ont ete conservees.

## Commandes executees

Depuis `C:\workspace\retro_doc_lab` :

```powershell
$py = 'C:\Users\sabirhaoui\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH = "$PWD\src"
$env:PYTHONDONTWRITEBYTECODE = '1'
& $py -B -m unittest discover -s tests -p test_scan.py -v
& $py -B -m retro_doc_lab scan --repo C:\workspace\twins_project --profile profiles/project-twin.toml --out output/project-twin-v2
& $py -B -m retro_doc_lab scan --repo C:\workspace\twins_project --profile profiles/project-twin.toml --out output/project-twin-v2-repeat
& $py -B scripts/verify_scan_v2.py output/project-twin-v2 output/project-twin-v2-repeat --result output/verification-v2.json
```

Les sorties doivent etre neuves : choisir d'autres noms pour rejouer ces commandes.
Les runs `twin-map-v2-01` a `twin-map-v2-04` sont des passages intermediaires;
la livraison finale est `output/project-twin-v2`.

## Resultats observes

- Six tests synthetiques reussis : reproductibilite, immutabilite de la fixture,
  rapprochement et preuves, exclusions/secrets, aucun code cible execute,
  depot inconnu, Python invalide, refus de sortie interne/existante,
  maintien des candidats ambigus, attribution des methodes TypeScript.
- Le test du bootstrap appelle deux fois `bootstrap(parent)` : creation au
  premier passage, zero fichier cree au second, empreintes inchangees et README
  personnalise preserve. Le script doit etre distribue avec les fichiers du lab.
- Project Twin : 1 271 fichiers admissibles inspectes; 50 rapprochements HTTP
  uniques inferes, 129 non resolus. Cinq rapprochements disposent aussi d'un
  candidat d'appel depuis un composant Angular. Cinq liens publication/tache
  Celery inferes. Il ne s'agit pas de traces d'execution.
- Les 15 fichiers de chaque scan final sont identiques octet par octet.
- Les bornes et empreintes des citations sont verifiees. Le scanner compare
  aussi l'inventaire admissible avant/apres interpretation : aucune derive.
- Le sous-ensemble de constructions Mermaid generees passe le controle local
  de grammaire dans `scripts/verify_scan_v2.py`. **Le parseur officiel Mermaid
  n'est pas disponible** : `validation.json` conserve `unvalidated`.

## Parcours representatifs et preuves

Les chemins ci-dessous sont relatifs au depot Project Twin. Toutes les preuves
et empreintes se trouvent dans `architecture.json`.

**Synchrone : creation d'un workspace**, identifiant
`flow_2bf03fce4d274c3b3632`, represente dans `diagrams/workflow.mmd` :

- appel du composant : `frontend/src/app/studio/pages/workspace/workspace.component.ts:265-265`;
- service HTTP : `frontend/src/app/studio/services/studio-api.service.ts:46-46`;
- construction de l'URL : meme fichier, lignes `35-36`, import ligne `4`,
  et `frontend/src/environments/environment.ts:4-4`;
- route FastAPI : `backend/app/modules/studio_v2/router.py:64-64`, prefixe `54-54`;
- application et montage : `backend/app/main.py:39-43` et `131-131`.

Le lien ecran/service est une heuristique par type injecte et nom de methode.
Le rapprochement HTTP tient compte de la methode et du prefixe. L'activation de
l'environnement Angular et les appels indirects jusqu'a la persistance restent
non etablis dans cette sequence. Aucun retour HTTP reussi n'est invente.

**Asynchrone : publication et tache d'experimentation**, identifiant
`async_flow_dba52b6837f729155863`, dans `diagrams/async.mmd` :
publication `backend/app/modules/experimentation/application/celery_dispatch.py:21-21`,
declaration de tache `backend/app/modules/experimentation/tasks.py:46-48`.
L'import et le symbole permettent un rapprochement infere. Le parcours complet
ecran → API → file → worker, le broker effectif, les retries et les reprises
ne sont pas reconstruits par ce diagramme.

**Technologies** : Celery est observe dans `backend/app/celery_app.py:9-9`.
PostgreSQL est etaye notamment par le dialecte importe dans
`backend/app/models/orm/outlook.py:7-7`. Ce sont des declarations dans les sources,
pas une verification du deploiement. Caddy n'est pas confirme dans la portee
admissible : il n'est donc pas ajoute a la cartographie.

## Limites et verifications restantes

Les configurations Compose contenant des motifs de secrets ont ete exclues en
entier; elles n'ont pas ete contournees pour obtenir une cartographie plus complete.
Les fichiers exclus ne sont pas ouverts pour calculer leur empreinte : seule
l'integrite du perimetre admissible est controlee. La lecture seule n'est pas une
attestation d'absence de modification par un autre processus.

L'analyse TypeScript reste heuristique; les appels indirects, configurations
conditionnelles, reecritures Caddy et etats metier exigent une analyse plus riche.
Les etats UI observes et les transitions candidates sont distingues; une origine
inconnue n'est pas remplacee par un etat initial suppose. Le diagramme detaille
est limite a 250 relations; le JSON conserve le graphe complet extrait.
La documentation preexistante n'est pas comparee semantiquement.

Linux, installation editable et rendu par parseur officiel Mermaid restent a
verifier. Aucun telechargement ni appel de modele distant n'a ete effectue.
