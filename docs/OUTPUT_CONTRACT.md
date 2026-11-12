# Output contract v1
Each execution writes a NEW output/<run-id>/ directory; never reuse an older run.
Required files: state-of-art.md, coverage.json, run.json, diagrams/architecture.mmd,
diagrams/workflow.mmd. Generate additional workflow diagrams when justified.

run.json fields:
- schema_version: 1
- status: completed | failed | partial
- source_root: canonical absolute path
- source_revision: commit hash or null (dirty working tree must be recorded)
- started_at, finished_at: ISO 8601 timestamps with timezone
- inspected_files: list of relative source paths
- errors: list of strings
- limitations: list of strings

coverage.json fields:
- schema_version: 1
- items: list of {id, status, evidence, documentation}
- status: covered | partial | missing | stale | unknown
- evidence: list of {path, start_line, end_line, sha256}
- documentation: list of relative generated or existing document paths
- excluded_files, uninspected_files: lists of relative source paths

state-of-art.md must explain scope, revision, architecture, workflows, interfaces,
data, deployment, security observations, documentation gaps and uncertainty.
Coverage measures only the declared inspected scope, never universal completeness.
A missing existing documentation baseline must be reported, not treated as coverage.
Record Mermaid parser version and validation outcome in limitations or an added field.

The local phased pipeline may additionally emit `characterization.json`,
`static-audit.json`, `sequence-index.json`, `sequences.md`, and `audit_report.md`.
`audit_report.md` is produced only when the `reporter` phase is selected.
Phase selection and completed prerequisites are recorded in `run.json`.
