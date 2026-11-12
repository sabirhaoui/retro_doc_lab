# retro_doc_lab
A source-grounded retrospective documentation agent, currently at the offline
inventory and bounded-batch planning stage. Documentation analysis is not yet
implemented. Python 3.10+, no third-party dependencies.

1. Configure `config/agent.json` `source_root` as an absolute external repository path.
2. Run the preflight: `python scripts/diagnose_retro_doc_lab.py --root .`
3. Generate an offline inventory from PowerShell:
   `$env:PYTHONPATH="src"; python -m retro_doc_agent --config config/agent.json`
4. Inspect the new `output/<run-id>/inventory.md` and `inventory.json`.

The inventory command always returns exit code 1 after writing its partial report:
the later documentation-generation stages are not implemented. It only reads
configured source extensions, skips configured exclusions and symlinks, and
does not execute source code or use a network. Batch manifests contain paths,
sizes, line counts, and SHA-256 fingerprints, not source contents. Oversized,
binary, unreadable, or changing files are explicitly marked uninspected.

Preflight exit codes: 0 checks passed; 1 validation failures; 2 bad configuration
or arguments; 3 preflight structurally ready but full agent implementation pending.
Postflight diagnostics are for complete future runs, not inventory-only reports.
Outputs and source inputs are ignored by Git. Never place secrets in configuration.
