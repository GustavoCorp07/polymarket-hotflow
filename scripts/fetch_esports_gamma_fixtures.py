#!/usr/bin/env python3
"""PAPER helper: pull public Gamma esports-tag market text into tests/fixtures/esports."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from hotflow.discovery.esports_gamma import DEFAULT_FIXTURE_DIR, collect_esports_fixtures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_FIXTURE_DIR)
    parser.add_argument("--data-out", type=Path, default=None)
    parser.add_argument("--open-only", action="store_true")
    args = parser.parse_args()
    payload = asyncio.run(
        collect_esports_fixtures(
            directory=args.out,
            data_directory=args.data_out,
            include_closed=not args.open_only,
        )
    )
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
