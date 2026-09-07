#!/usr/bin/env python3
"""Write static GitHub Pages demo JSON from a mock paper-run snapshot.

PAPER ledger only. Regenerates docs/pages/state.json, demo-state.json, and
rotating snapshots so the Pages site can be rebuilt without a live process.

  python scripts/export_pages_demo.py
  python scripts/export_pages_demo.py --out docs/pages --cycles 2
"""

from __future__ import annotations

import argparse
from pathlib import Path

from hotflow.monitoring.pages_demo import DEFAULT_PAGES_DIR, write_pages_demo


def main() -> int:
    parser = argparse.ArgumentParser(description="Export static paper dashboard JSON for GitHub Pages")
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_PAGES_DIR,
        help="Destination folder (default: docs/pages)",
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=2,
        help="Mock paper evaluate cycles (default 2; plus flatten frame unless --no-flatten)",
    )
    parser.add_argument(
        "--no-flatten",
        action="store_true",
        help="Leave paper positions open on the last snapshot",
    )
    parser.add_argument(
        "--sqlite",
        type=Path,
        default=None,
        help="Optional temp SQLite path (default: in-memory / unused store)",
    )
    args = parser.parse_args()
    written = write_pages_demo(
        args.out,
        cycles=args.cycles,
        flatten=not args.no_flatten,
        sqlite_path=args.sqlite,
    )
    print(f"pages demo wrote {len(written)} files under {args.out}")
    for rel in written:
        print(f"  {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
