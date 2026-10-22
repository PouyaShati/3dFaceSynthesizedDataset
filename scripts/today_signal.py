#!/usr/bin/env python3
"""Print the current month-end target. Does not send orders."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data import load_prices
from src.report import format_signal
from src.strategy import DEFAULT_LOOKBACK, current_signal
from src.universe import PRESETS, get_preset


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset", default="us_listed", choices=sorted(PRESETS))
    parser.add_argument("--lookback", type=int, default=DEFAULT_LOOKBACK)
    parser.add_argument("--refresh", action="store_true", help="Ignore the price cache")
    parser.add_argument("--start", default="2004-01-01")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "data" / "cache")
    args = parser.parse_args(argv)
    if args.lookback < 1:
        print("lookback must be at least 1", file=sys.stderr)
        return 1
    universe = get_preset(args.preset)
    try:
        prices = load_prices(
            universe,
            cache_dir=args.cache_dir,
            refresh=args.refresh,
            start=args.start,
        )
        signal = current_signal(prices, universe, lookback=args.lookback)
    except (RuntimeError, ValueError) as exc:
        print(f"Could not build a signal: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(format_signal(signal, universe, args.lookback))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
