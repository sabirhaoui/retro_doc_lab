"""Local lab entry point; does not import inspected repository code."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
from retro_doc_agent.pipeline import main

if __name__ == '__main__':
    raise SystemExit(main())
