#!/usr/bin/env python3
"""Backtest monthly dual momentum at 3%, 0.5%, and 0.05% round-trip fees."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data import load_prices
from src.report import build_report
from src.universe import PRESETS, get_preset


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset", default="us_listed", choices=sorted(PRESETS))
    parser.add_argument("--refresh", action="store_true", help="Ignore the price cache")
    parser.add_argument("--start", default="2004-01-01")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "data" / "cache")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "output" / "fee_comparison.png",
    )
    args = parser.parse_args(argv)
    universe = get_preset(args.preset)
    try:
        prices = load_prices(
            universe,
            cache_dir=args.cache_dir,
            refresh=args.refresh,
            start=args.start,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"Could not load prices: {exc}", file=sys.stderr)
        return 1
    text = build_report(prices, universe, args.output)
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
