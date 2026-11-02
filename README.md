# retro_doc_lab
A source-grounded retrospective documentation agent scaffold. Implementation pending.
Python 3.10+, no third-party dependencies for setup/diagnostics.

1. Configure config/agent.json source_root as an absolute external repository path.
2. Run: python scripts/diagnose_retro_doc_lab.py --root .
3. Implement the agent in a later Project Twin conversation using the handoff.
4. After a future run: python scripts/diagnose_retro_doc_lab.py --root . --phase postflight --run-id RUN_ID

Exit codes: 0 checks passed; 1 validation failures; 2 bad configuration/arguments;
3 preflight structurally ready but agent implementation pending.
Diagnostics check artifact structure and basic content, not factual correctness or
Mermaid syntax. Use a Mermaid parser during agent implementation.
Outputs and source inputs are ignored by Git. Never place secrets in configuration.
