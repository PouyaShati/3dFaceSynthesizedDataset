"""Position size is 0.5 percent of equity divided by the stop distance."""

from __future__ import annotations

import math


def position_shares(
    equity: float,
    risk_fraction: float,
    entry: float,
    stop: float,
    deployable_cash: float,
    price_scale: float = 1.0,
    fx_rate: float = 1.0,
) -> int | None:
    """Whole shares that risk at most `risk_fraction` of equity.

    `price_scale` converts a quote such as London pence into major currency
    units. `fx_rate` converts that major unit into account currency.
    Returns None when one share would risk more than the budget or when cash
    cannot fund a single share. If cash cannot fund the full size, the share
    count is reduced and the dollar risk is smaller than the budget.
    """
    risk_per_share = (entry - stop) * price_scale * fx_rate
    price_account = entry * price_scale * fx_rate
    if risk_per_share <= 0 or price_account <= 0 or equity <= 0:
        return None
    budget = equity * risk_fraction
    if risk_per_share > budget + 1e-9:
        return None
    shares = int(math.floor(budget / risk_per_share))
    if shares < 1:
        return None
    if shares * price_account > deployable_cash + 1e-9:
        shares = int(math.floor(deployable_cash / price_account))
    if shares < 1:
        return None
    return shares


def stop_in_favor(current_stop: float, proposed_stop: float) -> float | None:
    """Move a long stop only upward. Returns the new stop, or None to leave it."""
    if proposed_stop > current_stop + 1e-12:
        return proposed_stop
    return None
