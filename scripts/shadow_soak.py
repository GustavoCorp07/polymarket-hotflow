#!/usr/bin/env python3
"""SHADOW soak wrapper: completeness, stale probe, paper comparison. No orders."""

from __future__ import annotations

import sys

from hotflow.cli import app

if __name__ == "__main__":
    raise SystemExit(app(args=["shadow-soak", *sys.argv[1:]]))
