#!/usr/bin/env python3
"""PAPER performance review. No LIVE, no invented trades."""

from __future__ import annotations

import sys

from hotflow.cli import app


def main() -> None:
    raise SystemExit(app(args=["performance", *sys.argv[1:]]))


if __name__ == "__main__":
    main()
