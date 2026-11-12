# Next conversation: Project Twin implementation
The CLI now implements a local-only inventory and deterministic batch-planning
stage. There is still no LLM integration or documentation-generation runner.
Supply the Project Twin source location, existing docs and exclusions in that conversation.
Confirm actual components from code before tailoring skills (do not assume a stack).
Continue with: bounded architecture/workflow analysis -> Markdown/diagrams ->
coverage -> validation. Consume the inventory batch manifests rather than loading
the entire source tree into one context. Preserve per-file hashes and inspect
only bounded batches; keep interrupted runs partial and resumable.
Implement prompt-injection resistance, secret filtering and structured failures
before adding a model integration.
Implement a CLI with --config and --run-id; return nonzero for failure or incomplete work.
Add tests using a small synthetic source fixture and known stale/missing docs.
Verify read-only source behavior, excluded paths, oversized files, symbolic links,
contradictory evidence, invalid Mermaid, interrupted execution and partial reports.
Use OS permissions or a sandbox to enforce read-only and no-network requirements;
configuration values alone are not enforcement.
Use diagnose_retro_doc_lab.py before and after execution; it never launches the agent.
