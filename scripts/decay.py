#!/usr/bin/env python3
"""PAPER alpha-decay report. Suggestion-only; never auto-disables."""

from __future__ import annotations

import sys

from hotflow.cli import app


def main() -> None:
    raise SystemExit(app(args=["decay", *sys.argv[1:]]))


if __name__ == "__main__":
    main()
