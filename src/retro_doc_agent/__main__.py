#!/usr/bin/env python3
"""Create a local-only, bounded source inventory for a documentation run."""

import argparse
import sys
from pathlib import Path

from .inventory import InventoryError, load_config, run_inventory


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "config" / "agent.json",
    )
    parser.add_argument(
        "--run-id",
        help="Optional new output directory name; defaults to a timestamp-based id",
    )
    args = parser.parse_args(argv)

    try:
        config, repo_root = load_config(args.config)
        run_dir = run_inventory(config, repo_root, args.run_id)
    except (InventoryError, OSError, ValueError) as exc:
        print(f"Inventory failed: {exc}", file=sys.stderr)
        return 1

    print(f"Inventory written to {run_dir}")
    print("Documentation generation is not implemented; this run is partial.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
