#!/usr/bin/env python3
"""Convenience wrapper: python scripts/dashboard.py [--mock]."""

from __future__ import annotations

import sys

from hotflow.cli import app

if __name__ == "__main__":
    raise SystemExit(app(args=["dashboard", *sys.argv[1:]]))
