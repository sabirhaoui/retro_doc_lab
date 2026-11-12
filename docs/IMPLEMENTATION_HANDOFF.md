# Next conversation: Project Twin implementation
The local static runner and read-only execution dashboard are implemented.
There is no LLM integration. Semantic architecture tracing, existing-document
comparison and historical finding reconciliation remain future work. Inventory
coverage stays unknown until that review is implemented and verified.
Supply the Project Twin source location, existing docs and exclusions in that conversation.
Confirm actual components from code before tailoring skills (do not assume a stack).
Implement: inventory -> architecture/workflows -> Markdown/diagrams -> coverage -> validation.
Support resumable bounded reads, source fingerprints, prompt-injection resistance,
secret filtering, deterministic artifact paths and structured failures.
Implement a CLI with --config and --run-id; return nonzero for failure or incomplete work.
Add tests using a small synthetic source fixture and known stale/missing docs.
Verify read-only source behavior, excluded paths, oversized files, symbolic links,
contradictory evidence, invalid Mermaid, interrupted execution and partial reports.
Use OS permissions or a sandbox to enforce read-only and no-network requirements;
configuration values alone are not enforcement.
Use diagnose_retro_doc_lab.py before and after execution; it never launches the agent.
