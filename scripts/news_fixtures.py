#!/usr/bin/env python3
"""PAPER news fixtures. No LIVE, no invented headlines."""

from __future__ import annotations

import sys

from hotflow.cli import app


def main() -> None:
    raise SystemExit(app(args=["news-fixtures", *sys.argv[1:]]))


if __name__ == "__main__":
    main()
