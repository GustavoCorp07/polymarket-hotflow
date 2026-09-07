#!/usr/bin/env python3
"""PAPER-only official-shape stream recorder. Default is the synthetic fixture."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from hotflow.backtest.recorder import (
    DEFAULT_FIXTURE_DIR,
    LONGER_SYNTHETIC_NAME,
    build_synthetic_longer_stream,
    record_live_stream,
    write_stream,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Record CLOB/RTDS official-shape events")
    parser.add_argument("--live", action="store_true", help="Public collect (default off)")
    parser.add_argument("--seconds", type=float, default=20.0)
    parser.add_argument("--rtds", action="store_true")
    parser.add_argument("--symbol", default="btc/usd")
    parser.add_argument("--token-id")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.live:
        document = asyncio.run(
            record_live_stream(
                seconds=args.seconds,
                token_id=args.token_id,
                include_rtds=args.rtds,
                symbol=args.symbol,
            )
        )
        target = args.out or Path("reports") / "record-stream-live.json"
    else:
        document = build_synthetic_longer_stream()
        target = args.out or (DEFAULT_FIXTURE_DIR / LONGER_SYNTHETIC_NAME)
    write_stream(target, document)
    print(f"wrote {target} origin={document.get('origin')} events={document.get('event_count')}")


if __name__ == "__main__":
    main()
