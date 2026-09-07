#!/usr/bin/env python3
"""PAPER soak wrapper: short mock, --long labeled closes, or --mixed allocator audit. No LIVE."""

from __future__ import annotations

import sys

from hotflow.cli import app

if __name__ == "__main__":
    raise SystemExit(app(args=["paper-soak", *sys.argv[1:]]))
