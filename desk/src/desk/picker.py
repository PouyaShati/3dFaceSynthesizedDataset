"""Watchlist funnel. The watchlist is the universe. Rules do the picking."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from desk.calendar import in_earnings_blackout
from desk.config import DeskConfig
from desk.costs import cost_eats_target, needs_conversion, round_trip_cost
from desk.data import MarketData
from desk.models import OpenTrade, SetupRejection, SetupSignal, SymbolSpec
from desk.risk import position_shares
from desk.setups.breakout import evaluate_breakout
from desk.setups.pullback import evaluate_pullback


@dataclass(frozen=True)
class Skip:
    symbol: str
    reason: str
    detail: str


@dataclass(frozen=True)
class Order:
    signal: SetupSignal
    shares: int
    currency: str
    convert: bool
    estimated_cost: float
    dollar_risk: float
    source: str = ""
    name: str = ""


def _rank_key(order_signal: SetupSignal, currency: str, account_currency: str) -> tuple:
    conversion_penalty = 0 if currency.upper() == account_currency.upper() else 1
    # Round so two stops that are the same to a thousandth of a percent
    # fall through to the slope instead of to floating-point noise.
    distance_from_one_percent = round(abs(order_signal.stop_pct - 0.01), 6)
    return (
        conversion_penalty,
        distance_from_one_percent,
        -order_signal.sma_slope,
        order_signal.symbol,
    )


def screen(
    config: DeskConfig,
    market: MarketData,
    asof: date,
    open_trades: list[OpenTrade],
    *,
    allow_breakout: bool,
    symbols: Sequence[SymbolSpec] | None = None,
) -> tuple[list[SetupSignal], list[Skip]]:
    """Apply trend, setup, and earnings rules. Sizing happens after ranking.

    `symbols` is the group that already passed the universe search. When it is
    omitted, the hand-written watchlist is used.
    """
    chosen = config.watchlist if symbols is None else symbols
    open_by_symbol = {trade.symbol: trade for trade in open_trades}
    signals: list[SetupSignal] = []
    skips: list[Skip] = []

    for spec in chosen:
        trade = open_by_symbol.get(spec.symbol)
        if trade is not None:
            bars = market.bars(spec.symbol, asof)
            last_close = bars[-1].close if bars else trade.entry_price
            if last_close < trade.entry_price:
                skips.append(
                    Skip(
                        spec.symbol,
                        "add_to_loser",
                        "The open position is below its entry. Add nothing to a loser.",
                    )
                )
            else:
                skips.append(
                    Skip(
                        spec.symbol,
                        "already_open",
                        "The symbol already has an open position.",
                    )
                )
            continue

        try:
            bars = market.bars(spec.symbol, asof)
        except Exception as exc:
            skips.append(Skip(spec.symbol, "data_error", str(exc)))
            continue
        if not bars:
            skips.append(Skip(spec.symbol, "no_bars", "No daily bars on or before the session."))
            continue

        outcome = evaluate_pullback(bars, config, spec.symbol)
        if not isinstance(outcome, SetupSignal):
            if allow_breakout:
                breakout = evaluate_breakout(bars, config, spec.symbol, gate_open=True)
                if isinstance(breakout, SetupSignal):
                    outcome = breakout
                else:
                    skips.append(
                        Skip(spec.symbol, outcome.reason, f"Pullback setup rejected: {outcome.reason}.")
                    )
                    if isinstance(breakout, SetupRejection):
                        skips.append(
                            Skip(
                                spec.symbol,
                                breakout.reason,
                                f"Breakout setup rejected: {breakout.reason}.",
                            )
                        )
                    continue
            else:
                skips.append(Skip(spec.symbol, outcome.reason, f"Pullback setup rejected: {outcome.reason}."))
                continue

        status = market.earnings_status(spec.symbol, asof)
        if status != "known":
            skips.append(
                Skip(
                    spec.symbol,
                    "earnings_unknown",
                    "Earnings date is unknown. The symbol stays off the action list.",
                )
            )
            continue
        earnings = market.earnings_date(spec.symbol, asof)
        if earnings is None:
            skips.append(
                Skip(
                    spec.symbol,
                    "earnings_unknown",
                    "Earnings date is unknown. The symbol stays off the action list.",
                )
            )
            continue
        if in_earnings_blackout(asof, earnings, config.earnings_blackout_days):
            skips.append(
                Skip(
                    spec.symbol,
                    "earnings_week",
                    f"Earnings on {earnings.isoformat()} fall inside the {config.earnings_blackout_days}-session blackout.",
                )
            )
            continue
        signals.append(outcome)
    return signals, skips


def _as_spec(symbol: str, listed: dict[str, SymbolSpec | str], fallback: str) -> SymbolSpec:
    value = listed.get(symbol, fallback)
    if isinstance(value, SymbolSpec):
        return value
    return SymbolSpec(symbol, str(value))


def select_orders(
    config: DeskConfig,
    signals: list[SetupSignal],
    currencies: dict[str, SymbolSpec | str],
    open_trades: list[OpenTrade],
) -> tuple[list[Order], list[Skip]]:
    """Rank qualifying names and size at most the free slots."""
    slots = config.max_positions - len(open_trades)
    reserved = 0.0
    for trade in open_trades:
        spec = _as_spec(trade.symbol, currencies, trade.currency or config.currency)
        rate = config.fx_rates.get(spec.currency.upper(), 1.0)
        reserved += trade.shares * trade.entry_price * spec.price_scale * rate
    cash = config.deployable_cash - reserved
    ranked = sorted(
        signals,
        key=lambda signal: _rank_key(
            signal,
            _as_spec(signal.symbol, currencies, config.currency).currency,
            config.currency,
        ),
    )
    orders: list[Order] = []
    skips: list[Skip] = []
    if slots <= 0:
        for signal in ranked:
            skips.append(
                Skip(
                    signal.symbol,
                    "max_positions",
                    f"Open positions are already at the cap of {config.max_positions}.",
                )
            )
        return orders, skips

    for signal in ranked:
        if len(orders) >= slots:
            skips.append(
                Skip(
                    signal.symbol,
                    "max_positions",
                    f"The plan already filled the remaining {slots} slot(s).",
                )
            )
            continue
        spec = _as_spec(signal.symbol, currencies, config.currency)
        currency = spec.currency
        rate = config.fx_rates.get(currency.upper(), 1.0)
        convert = needs_conversion(currency, config.currency, config.cash_balances)
        shares = position_shares(
            config.equity,
            config.risk_fraction,
            signal.entry,
            signal.stop,
            max(cash, 0.0),
            spec.price_scale,
            rate,
        )
        risk_account = (signal.entry - signal.stop) * spec.price_scale * rate
        if shares is None:
            reason = "risk_too_large" if risk_account > config.equity * config.risk_fraction else "no_cash"
            detail = (
                "One share would risk more than 0.5 percent of equity."
                if reason == "risk_too_large"
                else "Deployable cash cannot fund a share at this stop."
            )
            skips.append(Skip(signal.symbol, reason, detail))
            continue
        if cost_eats_target(shares, signal.entry, config, convert, spec.price_scale, rate):
            skips.append(
                Skip(
                    signal.symbol,
                    "cost",
                    "Round-trip commission plus conversion would consume too much of a 2 percent gain.",
                )
            )
            continue
        cost = round_trip_cost(shares, signal.entry, config, convert, spec.price_scale, rate)
        orders.append(
            Order(
                signal=signal,
                shares=shares,
                currency=currency,
                convert=convert,
                estimated_cost=cost,
                dollar_risk=shares * risk_account,
                source=spec.source,
                name=spec.name,
            )
        )
        cash -= shares * signal.entry * spec.price_scale * rate
    return orders, skips
