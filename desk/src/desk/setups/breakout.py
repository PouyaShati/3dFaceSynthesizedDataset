"""Setup B: tight multi-day range breakout. Emits nothing until the gate is open."""

from __future__ import annotations

from desk.config import DeskConfig
from desk.indicators import sma_series, trend_state
from desk.models import Bar, SetupRejection, SetupSignal


def evaluate_breakout(
    bars: list[Bar],
    config: DeskConfig,
    symbol: str,
    *,
    gate_open: bool,
) -> SetupSignal | SetupRejection | None:
    """Return a signal, a rejection, or None when the setup is not allowed to speak.

    None means the journal gate is closed or the setup is switched off. Callers
    must not treat that as a skip to show next to a live pullback scan.
    """
    if not config.enable_breakout or not gate_open:
        return None

    needed = max(
        config.sma_slow + config.sma_rise_lookback,
        config.breakout_range_days + 21,
    )
    if len(bars) < needed:
        return SetupRejection(symbol, "breakout", "insufficient_history")

    closes = [bar.close for bar in bars]
    ok, reason, slope = trend_state(closes, config.sma_slow, config.sma_rise_lookback)
    if not ok:
        return SetupRejection(symbol, "breakout", reason)

    index = len(bars) - 1
    range_bars = bars[index - config.breakout_range_days : index]
    range_high = max(bar.high for bar in range_bars)
    range_low = min(bar.low for bar in range_bars)
    width = (range_high - range_low) / range_bars[-1].close
    if width > config.breakout_max_width_pct:
        return SetupRejection(symbol, "breakout", "range_too_wide")

    today = bars[index]
    if today.close <= range_high:
        return SetupRejection(symbol, "breakout", "no_breakout")

    volume_window = bars[index - 20 : index]
    average_volume = sum(bar.volume for bar in volume_window) / len(volume_window)
    if average_volume <= 0 or today.volume < config.breakout_volume_multiple * average_volume:
        return SetupRejection(symbol, "breakout", "volume")

    # The slow average must exist across the range so the trend held into the base.
    slow = sma_series(closes, config.sma_slow)
    if any(slow[cursor] is None or closes[cursor] <= slow[cursor] for cursor in range(index - config.breakout_range_days, index + 1)):
        return SetupRejection(symbol, "breakout", "lost_trend_during_range")

    stop = range_low * (1 - config.stop_buffer_pct)
    entry = today.close
    if stop >= entry:
        return SetupRejection(symbol, "breakout", "stop_not_below_entry")
    risk = entry - stop
    stop_pct = risk / entry
    if stop_pct < config.min_stop_pct - 1e-12 or stop_pct > config.max_stop_pct + 1e-12:
        return SetupRejection(symbol, "breakout", "stop_distance")

    if config.exit_plan == "fixed3":
        target = entry * 1.03
        partial = None
        if target + 1e-9 < entry + 2 * risk:
            return SetupRejection(symbol, "breakout", "target_below_2r")
        thesis = (
            f"{symbol} daily trend long. Close broke a tight {config.breakout_range_days}-day "
            "range on higher volume while price stayed above a rising 50-day average. "
            "Exit the position at 3 percent."
        )
    else:
        target = entry + 3 * risk
        partial = entry * 1.02
        thesis = (
            f"{symbol} daily trend long. Close broke a tight {config.breakout_range_days}-day "
            "range on higher volume while price stayed above a rising 50-day average. "
            "Sell half near 2 percent and trail the rest under recent daily lows."
        )
    return SetupSignal(
        symbol=symbol,
        setup="breakout",
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
