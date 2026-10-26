"""Offline prices for the interactive desk. One fitted pullback in each market."""

from __future__ import annotations

from datetime import date, timedelta

from desk.data import StaticMarket
from desk.models import Bar, SymbolSpec
from desk.universe import GLOBAL_MARKETS


def _weekdays(count: int, start: date = date(2025, 1, 6)) -> list[date]:
    days: list[date] = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def fitted_pullback_bars(level: float = 120.0) -> list[Bar]:
    """Uptrend, about a 1 percent stop, and a daily range inside the 0.8-4 percent band.

    The dip lands on the 20-day average. The next close bounces just enough that the
    stop beyond that low is near 1 percent. Each bar has a small wick so the
    average true range is large enough for a 2 percent target and still inside
    the 1.5 percent stop band.
    """
    count = 100
    step = level * 0.0015
    closes = [level + step * index for index in range(count)]
    dip = 98
    closes[dip] = sum(closes[dip - 19 : dip]) / 19
    closes[99] = closes[dip] * 1.006
    wick = 0.004
    days = _weekdays(count)
    bars: list[Bar] = []
    for index, close in enumerate(closes):
        opened = closes[index - 1] if index else close
        bars.append(
            Bar(
                day=days[index],
                open=opened,
                high=close * (1 + wick),
                low=close * (1 - wick),
                close=close,
                volume=800_000,
            )
        )
    return bars


# One liquid name from each sleeve. Levels are typical quote units for that market.
DEMO_NAMES: tuple[tuple[str, str, str, float], ...] = (
    ("RY.TO", "Royal Bank", "Toronto large cap", 140.0),
    ("AAPL", "Apple", "US large cap", 190.0),
    ("SHEL.L", "Shell", "London large cap", 7500.0),
    ("SAP.DE", "SAP", "Europe large cap", 180.0),
    ("NESN.SW", "Nestle", "Switzerland large cap", 90.0),
    ("7203.T", "Toyota", "Tokyo large cap", 2800.0),
    ("BHP.AX", "BHP", "Australia large cap", 42.0),
    ("0700.HK", "Tencent", "Hong Kong large cap", 380.0),
)


def demo_specs() -> list[SymbolSpec]:
    by_source = {market.source: market for market in GLOBAL_MARKETS}
    specs: list[SymbolSpec] = []
    for symbol, name, source, _level in DEMO_NAMES:
        market = by_source[source]
        specs.append(SymbolSpec(symbol, market.currency, name, source, market.price_scale))
    return specs


def demo_market() -> StaticMarket:
    series = {symbol: fitted_pullback_bars(level) for symbol, _name, _source, level in DEMO_NAMES}
    last = next(iter(series.values()))[-1].day
    earnings = last + timedelta(days=40)
    return StaticMarket(
        series,
        earnings={symbol: earnings for symbol in series},
        known={symbol: True for symbol in series},
    )


def demo_session() -> date:
    return fitted_pullback_bars()[-1].day
