"""Print the fee scenarios and save the equity-curve chart.

The 3% result is rendered first. The 63-day lookback is only a check that
cheaper fees still rank above more expensive ones. It is not a second strategy.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from src.backtest import BacktestResult, run_backtest
from src.strategy import DEFAULT_LOOKBACK, Signal
from src.universe import Universe


ROUND_TRIP_FEES = (0.03, 0.005, 0.0005)
ROBUSTNESS_LOOKBACK = 63

DISCLAIMER = (
    "Educational simulation only. Not a recommendation to buy or sell. "
    "A backtest is not a future result. This program does not connect to a "
    "broker; any order is one you place yourself."
)


def fee_rank(results: list[BacktestResult]) -> tuple[float, ...]:
    """Higher CAGR first. Near-ties break toward the cheaper fee."""

    def sort_key(result: BacktestResult) -> tuple[float, float]:
        cagr = result.cagr
        rounded = round(cagr, 6) if pd.notna(cagr) else float("-inf")
        return (-rounded, result.fee)

    return tuple(result.fee for result in sorted(results, key=sort_key))


def format_result(result: BacktestResult, fee_drag: float) -> str:
    start = result.equity.index[0].date()
    end = result.equity.index[-1].date()
    lines = [
        (
            f"{result.fee:.2%} round-trip fee | {result.lookback}-day lookback | "
            f"{start} to {end}"
        ),
        f"  CAGR: {result.cagr:.2%}",
        f"  Max drawdown: {result.max_drawdown:.2%}",
        f"  Trades per year: {result.trades_per_year:.2f}",
        f"  Average hold: {result.avg_hold_days:.1f} trading days",
        f"  Fee drag vs 0% fee (CAGR): {fee_drag:.2%}",
        f"  Switches: {result.switches} over {result.years:.1f} years",
        f"  Holding at the last close: {result.end_holding}",
    ]
    if result.fee >= 0.03 and (pd.isna(result.cagr) or result.cagr <= 0):
        lines.append(
            "  At this fee the simulated CAGR is not positive. "
            "Keep it on paper."
        )
    return "\n".join(lines)


def _run_fee_set(
    prices: pd.DataFrame,
    universe: Universe,
    lookback: int,
) -> tuple[BacktestResult, list[BacktestResult]]:
    baseline = run_backtest(prices, universe, lookback, fee=0.0)
    results = [
        run_backtest(prices, universe, lookback, fee=fee) for fee in ROUND_TRIP_FEES
    ]
    return baseline, results


def plot_fee_comparison(results: list[BacktestResult], path: Path, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 5.5))
    for result in results:
        ax.plot(
            result.equity.index,
            result.equity.to_numpy(),
            label=f"{result.fee:.2%} round trip",
        )
    ax.set_yscale("log")
    ax.set_title(title)
    ax.set_ylabel("Growth of 1 (log scale)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _rank_line(lookback: int, results: list[BacktestResult]) -> str:
    order = " > ".join(f"{fee:.2%}" for fee in fee_rank(results))
    return f"Fee ranking by CAGR, {lookback}-day: {order}"


def build_report(prices: pd.DataFrame, universe: Universe, chart_path: Path) -> str:
    baseline, primary = _run_fee_set(prices, universe, DEFAULT_LOOKBACK)
    check_base, check = _run_fee_set(prices, universe, ROBUSTNESS_LOOKBACK)
    blocks = [
        format_result(result, baseline.cagr - result.cagr) for result in primary
    ]
    check_blocks = [
        format_result(result, check_base.cagr - result.cagr) for result in check
    ]
    primary_rank = fee_rank(primary)
    check_rank = fee_rank(check)
    stable = "yes" if primary_rank == check_rank else "no"
    plot_fee_comparison(
        primary,
        chart_path,
        title=f"{universe.name} dual momentum, {DEFAULT_LOOKBACK}-day lookback",
    )
    cash_note = (
        f"Cash fund: {universe.cash}. Days before it lists earn zero."
        if universe.cash
        else "Cash is uninvested and earns zero. It is not charged a fund switch."
    )
    lines = [
        *blocks,
        "",
        f"Preset: {universe.name}. {universe.note}",
        cash_note,
        "Fill: next session's close after the month-end signal. "
        "The signal does not use the fill session.",
        "",
        f"Robustness check only ({ROBUSTNESS_LOOKBACK}-day lookback, not the live rule):",
        *check_blocks,
        "",
        _rank_line(DEFAULT_LOOKBACK, primary),
        _rank_line(ROBUSTNESS_LOOKBACK, check),
        f"Fee ranking stable across lookbacks: {stable}",
        f"Chart: {chart_path}",
        DISCLAIMER,
    ]
    return "\n".join(lines) + "\n"


def format_signal(signal: Signal, universe: Universe, lookback: int) -> str:
    def score_lines(scores: pd.Series) -> list[str]:
        lines = []
        for ticker in universe.equities:
            lines.append(
                f"  {ticker} ({universe.role_of(ticker)}): {float(scores[ticker]):+.2%}"
            )
        return lines

    lines = [
        f"Preset: {universe.name}",
        universe.note,
        f"Latest bar: {signal.as_of.date()}",
        (
            f"Decision date: {signal.decision_date.date()} "
            f"(month-end, {lookback}-day lookback)"
        ),
        "Scores on the decision date (these choose the holding):",
        *score_lines(signal.decision_scores),
        f"Target: {signal.target} at 100%",
    ]
    if signal.decision_is_latest_bar:
        lines.extend(
            [
                "This bar is the month-end decision. The fill is the next session's close.",
                f"Until that close, the previous target still applies: {signal.previous_target}.",
            ]
        )
    else:
        lines.extend(
            [
                "A session after this decision is already in the data, so this is the current holding.",
                "Scores through the latest bar are not an order. The next order is the next month-end.",
                "Scores through the latest bar (informational):",
                *score_lines(signal.latest_scores),
            ]
        )
    if lookback != DEFAULT_LOOKBACK:
        lines.append(
            f"The live rule uses {DEFAULT_LOOKBACK} trading days. "
            "This lookback is informational only."
        )
    lines.extend(
        [
            "Place any order yourself at your broker. This script does not send orders.",
            DISCLAIMER,
        ]
    )
    return "\n".join(lines) + "\n"
