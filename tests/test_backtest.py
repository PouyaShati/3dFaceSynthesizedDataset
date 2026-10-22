"""Fee math, next-close fill, and the order of the printed fee report."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtest import round_trip_cost, run_backtest
from src.data import extract_adjusted_close
from src.report import build_report
from src.strategy import month_end_decisions
from src.universe import CASH_COLUMN, Universe


EQUITIES = ("QQQ", "VGK", "EWC")

TRADED_CASH = Universe(
    name="test_traded_cash",
    equities=EQUITIES,
    roles=("US", "Europe", "Canada"),
    cash="SGOV",
    note="test",
)
SYNTHETIC_CASH = Universe(
    name="test_synthetic_cash",
    equities=EQUITIES,
    roles=("US", "Europe", "Canada"),
    cash=None,
    note="test",
)


def flat_prices(days: int = 420) -> pd.DataFrame:
    index = pd.bdate_range("2016-01-01", periods=days)
    frame = pd.DataFrame(100.0, index=index, columns=[*EQUITIES, "SGOV"])
    return frame


class FeeTests(unittest.TestCase):
    def test_full_switch_costs_one_round_trip(self) -> None:
        columns = [*EQUITIES, CASH_COLUMN]
        old = pd.Series(0.0, index=columns)
        new = pd.Series(0.0, index=columns)
        old["QQQ"] = 1.0
        new["VGK"] = 1.0
        cost = round_trip_cost(old, new, fee=0.03, traded_columns=columns)
        self.assertAlmostEqual(cost, 0.03)

    def test_traded_cash_entry_costs_one_round_trip(self) -> None:
        columns = [*EQUITIES, CASH_COLUMN]
        old = pd.Series(0.0, index=columns)
        new = pd.Series(0.0, index=columns)
        old[CASH_COLUMN] = 1.0
        new["QQQ"] = 1.0
        cost = round_trip_cost(old, new, fee=0.03, traded_columns=columns)
        self.assertAlmostEqual(cost, 0.03)

    def test_synthetic_cash_entry_costs_half_a_round_trip(self) -> None:
        columns = [*EQUITIES, CASH_COLUMN]
        old = pd.Series(0.0, index=columns)
        new = pd.Series(0.0, index=columns)
        old[CASH_COLUMN] = 1.0
        new["QQQ"] = 1.0
        cost = round_trip_cost(old, new, fee=0.03, traded_columns=list(EQUITIES))
        self.assertAlmostEqual(cost, 0.015)

    def test_unchanged_holding_is_free(self) -> None:
        columns = [*EQUITIES, CASH_COLUMN]
        held = pd.Series(0.0, index=columns)
        held["EWC"] = 1.0
        cost = round_trip_cost(held, held.copy(), fee=0.03, traded_columns=columns)
        self.assertEqual(cost, 0.0)


class FillTests(unittest.TestCase):
    def test_fill_is_the_next_close_and_fee_hits_that_session(self) -> None:
        prices = flat_prices()
        lookback = 126
        decisions = month_end_decisions(prices, lookback, EQUITIES)
        decision = decisions.index[0]
        location = prices.index.get_loc(decision)
        self.assertIsInstance(location, int)
        base = location - lookback
        prices.loc[prices.index[base], "QQQ"] = 100.0
        prices.loc[decision, "QQQ"] = 120.0
        prices.loc[decision, "VGK"] = 90.0
        prices.loc[decision, "EWC"] = 90.0

        fill = prices.index[location + 1]
        day_after = prices.index[location + 2]
        prices.loc[fill, "QQQ"] = 120.0 * 1.50
        prices.loc[day_after, "QQQ"] = 120.0 * 1.50 * 1.10

        result = run_backtest(prices, TRADED_CASH, lookback=lookback, fee=0.03)
        # The fill session is still owned by the previous holding (cash).
        # The new ETF earns the following session.
        self.assertEqual(result.holdings.loc[fill], "SGOV")
        self.assertEqual(result.holdings.loc[day_after], "QQQ")
        start_nav = 1.0 if result.equity.index[0] == fill else float(result.equity.shift(1).loc[fill])
        self.assertAlmostEqual(result.equity.loc[fill] / start_nav, 1.0 - 0.03)
        self.assertAlmostEqual(
            result.equity.loc[day_after] / result.equity.loc[fill],
            1.10,
        )
        self.assertGreater(fill, decision)

        synthetic = run_backtest(prices, SYNTHETIC_CASH, lookback=lookback, fee=0.03)
        synthetic_start = (
            1.0 if synthetic.equity.index[0] == fill else float(synthetic.equity.shift(1).loc[fill])
        )
        self.assertAlmostEqual(synthetic.equity.loc[fill] / synthetic_start, 1.0 - 0.015)
        self.assertEqual(synthetic.holdings.loc[fill], "CASH")

    def test_cheaper_fee_ranks_ahead_and_report_leads_with_three_percent(self) -> None:
        prices = flat_prices(500)
        # Give QQQ a steady climb so the rule holds it and pays at least one fee.
        prices["QQQ"] = [100.0 * (1.001 ** i) for i in range(len(prices))]
        with tempfile.TemporaryDirectory() as tmp:
            chart = Path(tmp) / "fee_comparison.png"
            text = build_report(prices, TRADED_CASH, chart)
            self.assertTrue(chart.exists())
        self.assertTrue(text.startswith("3.00% round-trip fee"))
        three = text.index("3.00% round-trip fee")
        half = text.index("0.50% round-trip fee")
        five_bps = text.index("0.05% round-trip fee")
        self.assertLess(three, half)
        self.assertLess(half, five_bps)
        self.assertIn("Fee ranking stable across lookbacks: yes", text)
        self.assertIn("Max drawdown:", text)
        self.assertIn("Trades per year:", text)
        self.assertIn("Average hold:", text)
        self.assertIn("Fee drag vs 0% fee (CAGR):", text)


class DownloadShapeTests(unittest.TestCase):
    def test_extracts_close_from_either_multiindex_orientation(self) -> None:
        index = pd.bdate_range("2024-01-02", periods=3)
        by_field = pd.DataFrame(
            {("Close", "QQQ"): [1.0, 2.0, 3.0], ("Close", "VGK"): [4.0, 5.0, 6.0]},
            index=index,
        )
        by_field.columns = pd.MultiIndex.from_tuples(by_field.columns)
        extracted = extract_adjusted_close(by_field, ["QQQ", "VGK"])
        self.assertEqual(list(extracted.columns), ["QQQ", "VGK"])
        self.assertEqual(float(extracted.iloc[-1]["VGK"]), 6.0)

        by_ticker = pd.DataFrame(
            {("QQQ", "Close"): [1.0, 2.0, 3.0], ("VGK", "Close"): [4.0, 5.0, 6.0]},
            index=index,
        )
        by_ticker.columns = pd.MultiIndex.from_tuples(by_ticker.columns)
        extracted = extract_adjusted_close(by_ticker, ["VGK", "QQQ"])
        self.assertEqual(list(extracted.columns), ["VGK", "QQQ"])
        self.assertEqual(float(extracted.iloc[0]["QQQ"]), 1.0)


if __name__ == "__main__":
    unittest.main()
