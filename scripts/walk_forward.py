#!/usr/bin/env python3
"""PAPER walk-forward on existing closes. No LIVE, no invented trades."""

from __future__ import annotations

import sys

from hotflow.cli import app


def main() -> None:
    raise SystemExit(app(args=["walk-forward", *sys.argv[1:]]))


if __name__ == "__main__":
    main()
