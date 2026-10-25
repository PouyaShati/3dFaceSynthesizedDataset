"""Daily moving averages used by the trend filter."""

from __future__ import annotations


def sma_series(values: list[float], window: int) -> list[float | None]:
    if window <= 0:
        raise ValueError("window must be positive")
    out: list[float | None] = [None] * len(values)
    total = 0.0
    for index, value in enumerate(values):
        total += value
        if index >= window:
            total -= values[index - window]
        if index >= window - 1:
            out[index] = total / window
    return out


def trend_state(
    closes: list[float],
    slow: int,
    rise_lookback: int,
) -> tuple[bool, str, float]:
    """Return whether the close is above a rising slow average, plus the slope.

    Slope is slow-average today minus slow-average `rise_lookback` sessions ago.
    A non-positive slope is not a rising average.
    """
    series = sma_series(closes, slow)
    index = len(closes) - 1
    prior = index - rise_lookback
    if index < 0 or prior < 0 or series[index] is None or series[prior] is None:
        return False, "insufficient_history", 0.0
    today = series[index]
    earlier = series[prior]
    assert today is not None and earlier is not None
    slope = today - earlier
    if closes[index] <= today:
        return False, "below_sma50", slope
    if slope <= 0:
        return False, "sma50_not_rising", slope
    return True, "trend", slope
