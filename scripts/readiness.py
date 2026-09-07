#!/usr/bin/env python3
"""PAPER readiness rollup. No LIVE, no invented gate results."""

from __future__ import annotations

import sys

from hotflow.cli import app

if __name__ == "__main__":
    raise SystemExit(app(args=["readiness", *sys.argv[1:]]))
