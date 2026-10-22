"""Shifting prices after a decision date must not change that date's weights."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.report import format_signal
from src.strategy import current_signal, month_end_decisions, weights_as_of
from src.universe import CASH_COLUMN, US_LISTED


EQUITIES = ("QQQ", "VGK", "EWC")


def sample_prices(days: int = 500) -> pd.DataFrame:
    index = pd.bdate_range("2015-01-01", periods=days)
    frame = pd.DataFrame(index=index)
    for offset, ticker in enumerate(EQUITIES):
        frame[ticker] = [100.0 * ((1.0004 + offset * 0.00015) ** i) for i in range(days)]
    frame["SGOV"] = [100.0 * (1.0001 ** i) for i in range(days)]
    return frame


class NoLookaheadTests(unittest.TestCase):
    def test_unfinished_month_is_not_a_decision(self) -> None:
        index = pd.bdate_range("2024-01-02", "2024-02-15")
        prices = pd.DataFrame({ticker: 100.0 for ticker in EQUITIES}, index=index)
        decisions = month_end_decisions(prices, lookback=5, equities=EQUITIES)
        self.assertIn(pd.Timestamp("2024-01-31"), decisions.index)
        self.assertNotIn(pd.Timestamp("2024-02-15"), decisions.index)

        closed = prices.loc[: pd.Timestamp("2024-01-31")]
        closed_decisions = month_end_decisions(closed, lookback=5, equities=EQUITIES)
        self.assertIn(pd.Timestamp("2024-01-31"), closed_decisions.index)

    def test_future_prices_do_not_change_todays_weight(self) -> None:
        prices = sample_prices()
        as_of = prices.index[300]
        before = weights_as_of(prices, as_of, lookback=126, equities=EQUITIES)

        shocked = prices.copy()
        future = shocked.index > as_of
        shocked.loc[future, list(EQUITIES)] = shocked.loc[future, list(EQUITIES)] * 7.0 + 50.0
        after = weights_as_of(shocked, as_of, lookback=126, equities=EQUITIES)

        pd.testing.assert_series_equal(before, after)

    def test_next_bar_does_not_change_month_end_decision(self) -> None:
        prices = sample_prices()
        original = month_end_decisions(prices, 126, EQUITIES)
        decision = original.index[4]
        shocked = prices.copy()
        later = shocked.index > decision
        shocked.loc[later, list(EQUITIES)] *= 4.0
        revised = month_end_decisions(shocked, 126, EQUITIES)

        pd.testing.assert_series_equal(original.loc[decision], revised.loc[decision])
        earlier = original.index[original.index <= decision]
        pd.testing.assert_frame_equal(original.loc[earlier], revised.loc[earlier])

    def test_weights_use_only_prices_through_the_decision(self) -> None:
        prices = sample_prices()
        decisions = month_end_decisions(prices, 63, EQUITIES)
        decision = decisions.index[3]
        sliced = weights_as_of(prices.loc[:decision], decision, 63, EQUITIES)
        pd.testing.assert_series_equal(
            decisions.loc[decision], sliced, check_names=False
        )

    def test_highest_positive_score_is_held(self) -> None:
        prices = sample_prices(200)
        as_of = prices.index[-1]
        base = prices.index[-1 - 126]
        prices.loc[as_of, "QQQ"] = prices.loc[base, "QQQ"] * 1.05
        prices.loc[as_of, "VGK"] = prices.loc[base, "VGK"] * 1.40
        prices.loc[as_of, "EWC"] = prices.loc[base, "EWC"] * 0.80
        weights = weights_as_of(prices, as_of, 126, EQUITIES)
        self.assertEqual(weights["VGK"], 1.0)
        self.assertEqual(weights["QQQ"], 0.0)
        self.assertEqual(weights[CASH_COLUMN], 0.0)

    def test_all_non_positive_scores_hold_cash(self) -> None:
        prices = sample_prices(200)
        as_of = prices.index[-1]
        base = prices.index[-1 - 126]
        for ticker, factor in ("QQQ", 0.90), ("VGK", 1.00), ("EWC", 0.70):
            prices.loc[as_of, ticker] = prices.loc[base, ticker] * factor
        weights = weights_as_of(prices, as_of, 126, EQUITIES)
        self.assertEqual(weights[CASH_COLUMN], 1.0)
        self.assertEqual(float(weights[list(EQUITIES)].sum()), 0.0)

    def test_signal_target_ignores_prices_after_the_decision(self) -> None:
        prices = sample_prices()
        signal = current_signal(prices, US_LISTED, lookback=126)
        shocked = prices.copy()
        shocked.loc[shocked.index > signal.decision_date, list(EQUITIES)] *= 5.0
        revised = current_signal(shocked, US_LISTED, lookback=126)
        self.assertEqual(signal.target, revised.target)
        pd.testing.assert_series_equal(signal.decision_scores, revised.decision_scores)
        text = format_signal(signal, US_LISTED, 126)
        self.assertIn("does not send orders", text)
        self.assertIn(signal.target, text)

    def test_tie_keeps_the_earlier_ticker(self) -> None:
        prices = sample_prices(200)
        as_of = prices.index[-1]
        base = prices.index[-1 - 126]
        for ticker in EQUITIES:
            prices.loc[as_of, ticker] = prices.loc[base, ticker] * 1.10
        weights = weights_as_of(prices, as_of, 126, EQUITIES)
        self.assertEqual(weights["QQQ"], 1.0)
        self.assertEqual(weights["VGK"], 0.0)


if __name__ == "__main__":
    unittest.main()
