"""Monthly dual momentum.

Score each equity ETF on its total return over the lookback window. Hold the
single ETF with the highest score if that score is above zero. Otherwise hold
cash. Scores on a date use prices through that date only.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.universe import CASH_COLUMN, Universe


DEFAULT_LOOKBACK = 126


def _as_timestamp(value: object) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert(None)
    return stamp.normalize()


def _equity_history(prices: pd.DataFrame, equities: tuple[str, ...] | list[str]) -> pd.DataFrame:
    missing = [ticker for ticker in equities if ticker not in prices.columns]
    if missing:
        raise ValueError(f"Price history is missing {missing}")
    history = prices.loc[:, list(equities)].copy()
    history.index = pd.DatetimeIndex([_as_timestamp(day) for day in history.index])
    history = history.sort_index()
    history = history[~history.index.duplicated(keep="last")]
    return history.dropna(how="any")


def _last_weekday_of_month(day: pd.Timestamp) -> pd.Timestamp:
    last = pd.Timestamp(day + pd.offsets.MonthEnd(0)).normalize()
    while last.weekday() >= 5:
        last -= pd.Timedelta(days=1)
    return last


def month_end_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Last session of each finished month.

    A month is finished when a later month is already in the series, or when
    the last session is on the month's last weekday. The newest bar of an
    unfinished month is not a decision. Exchange holidays on that last weekday
    show up once the next month has a session.
    """
    if len(index) == 0:
        return pd.DatetimeIndex([])
    stamps = pd.DatetimeIndex(index).sort_values().unique()
    grouped = pd.Series(stamps, index=stamps).groupby(stamps.to_period("M")).max()
    confirmed: list[pd.Timestamp] = []
    periods = list(grouped.index)
    for position, period in enumerate(periods):
        day = pd.Timestamp(grouped.loc[period]).normalize()
        month_has_ended = position < len(periods) - 1 or day >= _last_weekday_of_month(day)
        if month_has_ended:
            confirmed.append(day)
    return pd.DatetimeIndex(confirmed)


def lookback_scores(history: pd.DataFrame, lookback: int) -> pd.Series:
    """Total return from the close `lookback` sessions ago to the last row.

    `history` must already be sliced through the decision date.
    """
    if lookback < 1:
        raise ValueError("lookback must be at least 1")
    if len(history) <= lookback:
        raise ValueError(
            f"Need more than {lookback} sessions to score, have {len(history)}"
        )
    latest = history.iloc[-1]
    base = history.iloc[-1 - lookback]
    if (base <= 0).any() or (latest <= 0).any():
        raise ValueError("Prices in the lookback window must be positive")
    scores = latest / base - 1.0
    scores.name = history.index[-1]
    return scores


def weights_from_scores(scores: pd.Series, equities: list[str]) -> pd.Series:
    """100% in the best positive score, else 100% cash. Ties keep preset order."""
    ordered = scores.reindex(equities)
    if ordered.isna().any():
        raise ValueError("Cannot rank a missing score")
    weights = pd.Series(0.0, index=equities + [CASH_COLUMN], dtype=float)
    eligible = ordered[ordered > 0.0]
    if eligible.empty:
        weights[CASH_COLUMN] = 1.0
        return weights
    weights[str(eligible.idxmax())] = 1.0
    return weights


def weights_as_of(
    prices: pd.DataFrame,
    as_of: object,
    lookback: int,
    equities: tuple[str, ...] | list[str],
) -> pd.Series:
    """Target weights on `as_of`, using no later prices."""
    history = _equity_history(prices, equities)
    day = _as_timestamp(as_of)
    history = history.loc[:day]
    if history.empty or history.index[-1] != day:
        raise ValueError(f"No complete equity prices on {day.date()}")
    return weights_from_scores(lookback_scores(history, lookback), list(equities))


def month_end_decisions(
    prices: pd.DataFrame,
    lookback: int,
    equities: tuple[str, ...] | list[str],
) -> pd.DataFrame:
    """One weight row per month-end that has a full lookback."""
    history = _equity_history(prices, equities)
    rows: list[pd.Series] = []
    dates: list[pd.Timestamp] = []
    for day in month_end_dates(history.index):
        window = history.loc[:day]
        if len(window) <= lookback:
            continue
        rows.append(weights_from_scores(lookback_scores(window, lookback), list(equities)))
        dates.append(pd.Timestamp(day))
    columns = list(equities) + [CASH_COLUMN]
    frame = pd.DataFrame(rows, index=pd.DatetimeIndex(dates), columns=columns)
    frame.index.name = "decision"
    return frame


def holding_ticker(weights: pd.Series, cash_label: str) -> str:
    name = str(weights.idxmax())
    if float(weights[name]) <= 0.0:
        raise ValueError("Weight row has no holding")
    if name == CASH_COLUMN:
        return cash_label
    return name


@dataclass(frozen=True)
class Signal:
    as_of: pd.Timestamp
    decision_date: pd.Timestamp
    decision_scores: pd.Series
    latest_scores: pd.Series
    weights: pd.Series
    target: str
    previous_target: str
    decision_is_latest_bar: bool


def current_signal(prices: pd.DataFrame, universe: Universe, lookback: int = DEFAULT_LOOKBACK) -> Signal:
    history = _equity_history(prices, universe.equities)
    if history.empty:
        raise ValueError("No equity prices")
    decisions = month_end_decisions(history, lookback, universe.equities)
    if decisions.empty:
        raise ValueError(
            f"Not enough history for a {lookback}-day score. "
            f"Have {len(history)} complete sessions."
        )
    as_of = pd.Timestamp(history.index[-1])
    decision_date = pd.Timestamp(decisions.index[-1])
    cash_label = universe.cash or "CASH"
    weights = decisions.iloc[-1]
    if len(decisions) >= 2:
        previous = holding_ticker(decisions.iloc[-2], cash_label)
    else:
        previous = cash_label
    return Signal(
        as_of=as_of,
        decision_date=decision_date,
        decision_scores=lookback_scores(history.loc[:decision_date], lookback),
        latest_scores=lookback_scores(history, lookback),
        weights=weights,
        target=holding_ticker(weights, cash_label),
        previous_target=previous,
        decision_is_latest_bar=as_of == decision_date,
    )
