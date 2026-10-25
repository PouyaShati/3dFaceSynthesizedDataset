"""Commission and currency-conversion cost gate."""

from __future__ import annotations

from desk.config import DeskConfig


def needs_conversion(symbol_currency: str, account_currency: str) -> bool:
    return symbol_currency.upper() != account_currency.upper()


def conversion_cost(notional: float, config: DeskConfig, convert: bool) -> float:
    """Round-trip conversion cost in account currency.

    A conversion is charged on the way into the trade currency and on the way
    back. Matching cash already held means the cost is zero for this trade.
    """
    if not convert:
        return 0.0
    spread = notional * (config.fx_spread_bps / 10_000.0)
    per_side = config.usd_conversion_fee + spread
    return 2 * per_side


def round_trip_commission(config: DeskConfig) -> float:
    return 2 * config.commission_per_trade


def round_trip_cost(shares: int, entry: float, config: DeskConfig, convert: bool) -> float:
    return round_trip_commission(config) + conversion_cost(shares * entry, config, convert)


def cost_eats_target(shares: int, entry: float, config: DeskConfig, convert: bool) -> bool:
    """True when round-trip costs consume the configured fraction of a 2 percent gain."""
    target_dollars = shares * entry * 0.02
    if target_dollars <= 0:
        return True
    return round_trip_cost(shares, entry, config, convert) + 1e-9 >= (
        config.cost_skip_fraction_of_target * target_dollars
    )
