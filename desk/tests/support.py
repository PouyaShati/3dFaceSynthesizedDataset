"""Shared config and price fixtures. No network."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from desk.config import DeskConfig
from desk.models import Bar, OpenTrade, SetupSignal


def trading_dates(count: int, start: date = date(2025, 1, 6)) -> list[date]:
    days: list[date] = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def bars_from_ohlc(
    rows: list[tuple[float, float, float, float]],
    *,
    volume: float = 1_000_000,
    start: date = date(2025, 1, 6),
    volumes: list[float] | None = None,
) -> list[Bar]:
    days = trading_dates(len(rows), start)
    bars: list[Bar] = []
    for index, (opened, high, low, close) in enumerate(rows):
        bars.append(
            Bar(
                day=days[index],
                open=opened,
                high=high,
                low=low,
                close=close,
                volume=volume if volumes is None else volumes[index],
            )
        )
    return bars


def linear_closes(count: int, start: float = 100.0, step: float = 0.3) -> list[float]:
    return [start + step * index for index in range(count)]


def pullback_rows() -> list[tuple[float, float, float, float]]:
    """Uptrend with the last full session touching the 20-day average, then a bounce.

    The bounce is about 0.9 percent above that low so the buffered stop is about 1 percent away.
    """
    closes = linear_closes(100)
    dip_index = 98
    prior_sum = sum(closes[dip_index - 19 : dip_index])
    closes[dip_index] = prior_sum / 19
    closes[99] = closes[dip_index] * 1.009
    rows: list[tuple[float, float, float, float]] = []
    for index, close in enumerate(closes):
        opened = closes[index - 1] if index else close
        rows.append((opened, close + 0.2, close, close))
    return rows


def pullback_bars() -> list[Bar]:
    return bars_from_ohlc(pullback_rows())


def falling_average_bars() -> list[Bar]:
    """Price finishes just above a declining 50-day average."""
    closes = [150 - 0.4 * index for index in range(80)]
    closes[-1] = closes[-2]
    rows = []
    for index, close in enumerate(closes):
        opened = closes[index - 1] if index else close
        rows.append((opened, close + 0.2, close - 0.05, close))
    # Lift the last close a little once the average is known to the caller if needed.
    return bars_from_ohlc(rows)


def breakout_bars() -> list[Bar]:
    """Rising trend, seven tight sessions, then a close above that range on high volume."""
    closes = linear_closes(90, start=80.0, step=0.2)
    # Park the base just under a round level near the trend, about 1 percent above the base low.
    base = closes[81]
    for index in range(82, 89):
        closes[index] = base
    closes[89] = base * 1.008
    rows = []
    volumes: list[float] = []
    for index, close in enumerate(closes):
        if 82 <= index <= 88:
            low = base * 0.997
            high = base * 1.001
            opened = base
        elif index == 89:
            low = base * 1.001
            high = close + 0.1
            opened = base * 1.002
        else:
            low = close - 0.1
            high = close + 0.15
            opened = close - 0.05
        rows.append((opened, high, low, close))
        volumes.append(3_000_000 if index == 89 else 1_000_000)
    return bars_from_ohlc(rows, volumes=volumes)


def sample_config(root: Path, **overrides: object) -> DeskConfig:
    root.mkdir(parents=True, exist_ok=True)
    out = root / "out"
    db = root / "desk.sqlite"
    lots = root / "lots.csv"
    if not lots.exists():
        lots.write_text(
            "symbol,account,acquired,shares,acb,currency\n",
            encoding="utf-8",
        )
    values: dict[str, object] = {
        "timezone": "America/Toronto",
        "account_type": "non_registered",
        "currency": "CAD",
        "equity": 20_000.0,
        "deployable_cash": 20_000.0,
        "max_positions": 5,
        "risk_fraction": 0.005,
        "commission_per_trade": 0.0,
        "usd_conversion_fee": 2.0,
        "fx_spread_bps": 0.0,
        "cost_skip_fraction_of_target": 0.30,
        "fx_rates": {"CAD": 1.0, "USD": 1.35},
        "min_stop_pct": 0.0075,
        "max_stop_pct": 0.015,
        "stop_buffer_pct": 0.001,
        "exit_plan": "scale",
        "sma_fast": 20,
        "sma_slow": 50,
        "sma_rise_lookback": 10,
        "pullback_lookback": 8,
        "touch_tolerance_pct": 0.005,
        "touch_max_pierce_pct": 0.02,
        "earnings_blackout_days": 5,
        "journal_min_trades": 30,
        "active_setup": "pullback",
        "enable_breakout": False,
        "breakout_range_days": 7,
        "breakout_max_width_pct": 0.03,
        "breakout_volume_multiple": 1.5,
        "min_harvest_loss": 50.0,
        "watchlist": (),
        "search_enabled": False,
        "cad_universe": root / "universes" / "tsx60.txt",
        "usd_universe": root / "universes" / "us_large.txt",
        "usd_cash": 0.0,
        "min_price": 10.0,
        "min_avg_dollar_volume": 5_000_000.0,
        "max_participation": 0.01,
        "atr_window": 14,
        "min_atr_pct": 0.008,
        "max_atr_pct": 0.04,
        "dollar_volume_window": 20,
        "db_path": db,
        "out_dir": out,
        "lots_path": lots,
        "source_path": root / "config.yaml",
    }
    values.update(overrides)
    return DeskConfig(**values)  # type: ignore[arg-type]


def make_trade(**overrides: object) -> OpenTrade:
    values: dict[str, object] = {
        "id": 1,
        "symbol": "EXAMPLE.TO",
        "account": "non_registered",
        "setup": "pullback",
        "mode": "paper",
        "thesis": "test",
        "entry_date": date(2026, 10, 1),
        "entry_price": 100.0,
        "stop": 99.0,
        "initial_stop": 99.0,
        "target": 103.0,
        "shares": 100,
        "exit_plan": "scale",
        "status": "open",
        "half_sold": False,
        "half_price": None,
        "currency": "CAD",
        "commissions": 0.0,
        "fx_cost": 0.0,
    }
    values.update(overrides)
    return OpenTrade(**values)  # type: ignore[arg-type]


def make_signal(**overrides: object) -> SetupSignal:
    values: dict[str, object] = {
        "symbol": "EXAMPLE.TO",
        "setup": "pullback",
        "entry": 50.0,
        "stop": 49.5,
        "target": 51.5,
        "partial_price": 51.0,
        "exit_plan": "scale",
        "stop_pct": 0.01,
        "risk_per_share": 0.5,
        "thesis": "test",
        "sma_slope": 1.0,
    }
    values.update(overrides)
    return SetupSignal(**values)  # type: ignore[arg-type]
