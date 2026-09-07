#!/usr/bin/env python3
"""PAPER soak wrapper: short mock soak or --long labeled closes. No LIVE."""

from __future__ import annotations

import sys

from hotflow.cli import app

if __name__ == "__main__":
    raise SystemExit(app(args=["paper-soak", *sys.argv[1:]]))
