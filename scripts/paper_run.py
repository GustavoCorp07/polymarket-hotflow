#!/usr/bin/env python3
"""Convenience wrapper: python scripts/paper_run.py [--mock]."""

from __future__ import annotations

import sys

from hotflow.cli import app

if __name__ == "__main__":
    raise SystemExit(app(args=["paper-run", *sys.argv[1:]]))
