#!/usr/bin/env python3
"""PAPER failure-injection soak. No LIVE, no invented market data."""

from __future__ import annotations

import sys

from hotflow.cli import app

if __name__ == "__main__":
    raise SystemExit(app(args=["failure-soak", *sys.argv[1:]]))
