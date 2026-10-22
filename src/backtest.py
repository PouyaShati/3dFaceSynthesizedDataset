"""Next-session fill for the month-end signal, with a round-trip fee.

The signal is the month-end close. The fill is the next session's close, so
that session's move is still earned by the previous holding. The fee is
charged at the fill. A round trip is a sale plus a purchase: switching from
one traded fund to another costs the full fee, and moving between a real
cash fund (SGOV) and an equity ETF does too. Uninvested cash that is not a
fund costs half the round trip to enter or leave.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.data import prepare_prices
from src.strategy import holding_ticker, month_end_decisions
from src.universe import CASH_COLUMN, Universe


def round_trip_cost(
    old: pd.Series,
    new: pd.Series,
    fee: float,
    traded_columns: list[str],
) -> float:
    """Charge `fee` (buy plus sell) times the share of the book that is replaced.

    Each unit bought or sold costs ``fee / 2``. A full switch buys 1 and sells
    1, so it costs exactly ``fee``.
    """
    if fee < 0:
        raise ValueError("fee must be non-negative")
    delta = (new - old).reindex(traded_columns).fillna(0.0)
    traded_notional = float(delta.abs().sum())
    return (fee / 2.0) * traded_notional


def _traded_columns(universe: Universe) -> list[str]:
    columns = list(universe.equities)
    if universe.cash:
        columns.append(CASH_COLUMN)
    return columns


def _execution_map(
    decisions: pd.DataFrame,
    index: pd.DatetimeIndex,
) -> dict[pd.Timestamp, pd.Series]:
    """Map each next session to the month-end weights filled that day."""
    executions: dict[pd.Timestamp, pd.Series] = {}
    for decision_day, weights in decisions.iterrows():
        decision_day = pd.Timestamp(decision_day)
        position = int(index.searchsorted(decision_day, side="right"))
        if position >= len(index):
            continue
        fill_day = pd.Timestamp(index[position])
        if fill_day <= decision_day:
            raise RuntimeError("Fill must be strictly after the decision close")
        executions[fill_day] = weights
    return executions


@dataclass(frozen=True)
class BacktestResult:
    fee: float
    lookback: int
    equity: pd.Series
    holdings: pd.Series
    end_holding: str
    cagr: float
    max_drawdown: float
    switches: int
    trades_per_year: float
    avg_hold_days: float
    years: float


def _cagr(final_nav: float, years: float) -> float:
    if years <= 0 or final_nav <= 0:
        return float("nan")
    return float(final_nav ** (1.0 / years) - 1.0)


def _max_drawdown(equity: pd.Series) -> float:
    # The curve starts at 1 before the first session's return.
    peak = equity.cummax().clip(lower=1.0)
    return float((equity / peak - 1.0).min())


def _average_hold(holdings: pd.Series) -> float:
    if holdings.empty:
        return float("nan")
    segments = (holdings != holdings.shift()).cumsum()
    return float(holdings.groupby(segments).size().mean())


def run_backtest(
    prices: pd.DataFrame,
    universe: Universe,
    lookback: int,
    fee: float,
) -> BacktestResult:
    if lookback < 1:
        raise ValueError("lookback must be at least 1")
    if fee < 0:
        raise ValueError("fee must be non-negative")

    panel = prepare_prices(prices, universe)
    decisions = month_end_decisions(panel, lookback, universe.equities)
    if decisions.empty:
        raise ValueError(f"No month-end with a {lookback}-day history")

    index = pd.DatetimeIndex(panel.index)
    returns = panel.pct_change()
    executions = _execution_map(decisions, index)
    if not executions:
        raise ValueError("Month-end signals have no following session to fill")

    cash_label = universe.cash or "CASH"
    traded = _traded_columns(universe)
    columns = list(universe.equities) + [CASH_COLUMN]
    held = pd.Series(0.0, index=columns, dtype=float)
    held[CASH_COLUMN] = 1.0

    first_fill = min(executions)
    nav = 1.0
    nav_points: list[float] = []
    held_during_day: list[str] = []
    switches = 0
    end_holding = cash_label

    for day in index[index >= first_fill]:
        day = pd.Timestamp(day)
        start_name = holding_ticker(held, cash_label)
        day_return = returns.loc[day].reindex(columns).fillna(0.0)
        gross = float((held * day_return).sum())
        fee_cost = 0.0
        fill = executions.get(day)
        if fill is not None:
            new = fill.reindex(columns).fillna(0.0).astype(float)
            if abs(float(new.sum()) - 1.0) > 1e-9:
                raise RuntimeError(f"Weights on {day.date()} sum to {float(new.sum())}")
            fee_cost = round_trip_cost(held, new, fee, traded)
            new_name = holding_ticker(new, cash_label)
            if new_name != start_name:
                switches += 1
            held = new
            end_holding = new_name
        else:
            end_holding = start_name
        nav *= 1.0 + gross - fee_cost
        nav_points.append(nav)
        held_during_day.append(start_name)

    dates = index[index >= first_fill]
    equity = pd.Series(nav_points, index=dates, name="equity")
    holdings = pd.Series(held_during_day, index=dates, name="holding")
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1 / 365.25)
    return BacktestResult(
        fee=fee,
        lookback=lookback,
        equity=equity,
        holdings=holdings,
        end_holding=end_holding,
        cagr=_cagr(float(equity.iloc[-1]), years),
        max_drawdown=_max_drawdown(equity),
        switches=switches,
        trades_per_year=switches / years,
        avg_hold_days=_average_hold(holdings),
        years=years,
    )
