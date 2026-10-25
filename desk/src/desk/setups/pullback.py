"""Setup A: pullback toward a rising 20-day average that has stopped falling."""

from __future__ import annotations

from desk.config import DeskConfig
from desk.indicators import sma_series, trend_state
from desk.models import Bar, SetupRejection, SetupSignal


def evaluate_pullback(
    bars: list[Bar],
    config: DeskConfig,
    symbol: str,
) -> SetupSignal | SetupRejection:
    closes = [bar.close for bar in bars]
    ok, reason, slope = trend_state(closes, config.sma_slow, config.sma_rise_lookback)
    if not ok:
        return SetupRejection(symbol, "pullback", reason)

    if len(bars) < 2:
        return SetupRejection(symbol, "pullback", "insufficient_history")

    index = len(bars) - 1
    today = bars[index]
    previous = bars[index - 1]
    if today.close <= previous.close:
        return SetupRejection(symbol, "pullback", "still_falling")
    if today.low < previous.low:
        return SetupRejection(symbol, "pullback", "new_low")

    fast = sma_series(closes, config.sma_fast)
    slow = sma_series(closes, config.sma_slow)
    window_start = index - config.pullback_lookback
    if window_start < 0:
        return SetupRejection(symbol, "pullback", "insufficient_history")

    touch_indexes: list[int] = []
    for cursor in range(window_start, index):
        level = fast[cursor]
        trend = slow[cursor]
        if level is None or trend is None:
            continue
        low = bars[cursor].low
        ceiling = level * (1 + config.touch_tolerance_pct)
        floor = level * (1 - config.touch_max_pierce_pct)
        if floor <= low <= ceiling and bars[cursor].close > trend:
            touch_indexes.append(cursor)
    if not touch_indexes:
        return SetupRejection(symbol, "pullback", "no_pullback_touch")

    first_touch = touch_indexes[0]
    came_from_above = False
    for cursor in range(max(0, first_touch - 5), first_touch):
        level = fast[cursor]
        if level is not None and closes[cursor] > level:
            came_from_above = True
            break
    if not came_from_above:
        return SetupRejection(symbol, "pullback", "not_from_above")

    for cursor in range(first_touch, index + 1):
        trend = slow[cursor]
        if trend is None or closes[cursor] <= trend:
            return SetupRejection(symbol, "pullback", "lost_trend_during_pullback")

    prior_low = min(bar.low for bar in bars[first_touch:index])
    if today.low < prior_low:
        return SetupRejection(symbol, "pullback", "new_pullback_low")

    pullback_low = min(prior_low, today.low)
    stop = pullback_low * (1 - config.stop_buffer_pct)
    entry = today.close
    if stop >= entry:
        return SetupRejection(symbol, "pullback", "stop_not_below_entry")

    stop_pct = (entry - stop) / entry
    if stop_pct < config.min_stop_pct - 1e-12 or stop_pct > config.max_stop_pct + 1e-12:
        return SetupRejection(symbol, "pullback", "stop_distance")

    risk = entry - stop
    return _signal(symbol, config, entry, stop, risk, stop_pct, slope)


def _signal(
    symbol: str,
    config: DeskConfig,
    entry: float,
    stop: float,
    risk: float,
    stop_pct: float,
    slope: float,
) -> SetupSignal | SetupRejection:
    if config.exit_plan == "fixed3":
        target = entry * 1.03
        if target + 1e-9 < entry + 2 * risk:
            return SetupRejection(symbol, "pullback", "target_below_2r")
        partial = None
        thesis = (
            f"{symbol} daily trend long. Close is above a rising 50-day average "
            "and a pullback to the 20-day average has stopped falling. "
            f"Stop {stop:.4f} is just beyond the pullback low. "
            "Exit the position at 3 percent, which is at least twice the risk."
        )
    else:
        target = entry + 3 * risk
        partial = entry * 1.02
        thesis = (
            f"{symbol} daily trend long. Close is above a rising 50-day average "
            "and a pullback to the 20-day average has stopped falling. "
            f"Stop {stop:.4f} is just beyond the pullback low. "
            "Sell half near 2 percent and trail the rest under recent daily lows."
        )
    return SetupSignal(
        symbol=symbol,
        setup="pullback",
        entry=entry,
        stop=stop,
        target=target,
        partial_price=partial,
        exit_plan=config.exit_plan,
        stop_pct=stop_pct,
        risk_per_share=risk,
        thesis=thesis,
        sma_slope=slope,
    )
