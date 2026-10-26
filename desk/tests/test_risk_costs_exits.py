from datetime import timedelta

from desk.costs import cost_eats_target, needs_conversion, round_trip_cost
from desk.exits import propose_actions
from desk.models import Bar
from desk.picker import select_orders
from desk.risk import position_shares, stop_in_favor
from tests.support import make_signal, make_trade, sample_config


def test_share_formula_uses_half_a_percent_of_equity(tmp_path):
    # 0.5 percent of 20_000 is 100. Risk per share is 0.50, so 200 shares.
    shares = position_shares(20_000, 0.005, 50.0, 49.5, 20_000)
    assert shares == 200
    assert shares * 0.5 == 100


def test_cash_reduces_size_below_the_risk_budget(tmp_path):
    shares = position_shares(20_000, 0.005, 50.0, 49.5, 5_000)
    assert shares == 100
    assert shares * 0.5 < 100


def test_one_share_that_risks_too_much_is_skipped():
    assert position_shares(1_000, 0.005, 100.0, 90.0, 10_000) is None


def test_stop_moves_only_up():
    assert stop_in_favor(10.0, 10.5) == 10.5
    assert stop_in_favor(10.0, 10.0) is None
    assert stop_in_favor(10.0, 9.5) is None


def test_matching_currency_has_no_conversion_and_a_mismatch_can_eat_the_target(tmp_path):
    config = sample_config(tmp_path)
    assert needs_conversion("CAD", "CAD") is False
    assert needs_conversion("USD", "CAD") is True
    assert round_trip_cost(200, 50.0, config, False) == 0
    # 10 shares at 20 is a 4 dollar move at 2 percent. Two 2-unit conversion fees are 8.
    assert cost_eats_target(10, 20.0, config, True) is True
    assert cost_eats_target(200, 50.0, config, True) is False


def test_conversion_that_eats_a_two_percent_gain_is_not_ordered(tmp_path):
    config = sample_config(tmp_path, equity=1_000, deployable_cash=20_000, max_positions=5)
    signal = make_signal(
        symbol="USD",
        entry=20.0,
        stop=19.8,
        target=20.6,
        partial_price=20.4,
        stop_pct=0.01,
        risk_per_share=0.2,
    )
    orders, skips = select_orders(config, [signal], {"USD": "USD"}, [])
    assert orders == []
    assert skips[0].reason == "cost"


def test_ranking_prefers_account_currency_and_respects_the_slot_cap(tmp_path):
    config = sample_config(tmp_path, max_positions=4, deployable_cash=50_000, equity=20_000)
    cad = make_signal(symbol="CAD.TO", sma_slope=0.5)
    usd = make_signal(symbol="USD", sma_slope=5.0, stop_pct=0.01)
    closer = make_signal(symbol="CLOSER.TO", stop_pct=0.0101, sma_slope=0.1)
    orders, skips = select_orders(
        config,
        [usd, closer, cad],
        {"CAD.TO": "CAD", "USD": "USD", "CLOSER.TO": "CAD"},
        [make_trade(id=1), make_trade(id=2, symbol="OPEN1"), make_trade(id=3, symbol="OPEN2")],
    )
    assert [order.signal.symbol for order in orders] == ["CAD.TO"]
    assert {skip.symbol for skip in skips} == {"USD", "CLOSER.TO"}
    assert all(skip.reason == "max_positions" for skip in skips)


def test_stop_out_beats_a_target_on_the_same_bar():
    trade = make_trade(entry_price=100.0, stop=99.0, exit_plan="fixed3")
    bar = Bar(trade.entry_date, 100.0, 104.0, 98.5, 103.0, 1_000)
    actions = propose_actions(trade, [bar], 0.001)
    assert [action.kind for action in actions] == ["stop_out"]


def test_scale_sells_half_at_two_percent_and_does_not_trail_yet():
    trade = make_trade(entry_price=100.0, stop=99.0, half_sold=False)
    day = trade.entry_date
    bars = [
        Bar(day, 100, 101, 99.5, 100.5, 1),
        Bar(day + timedelta(days=1), 100.5, 102.2, 100.2, 102.0, 1),
    ]
    actions = propose_actions(trade, bars, 0.001)
    assert [action.kind for action in actions] == ["sell_half"]
    assert abs(actions[0].price - 102.0) < 1e-9


def test_trail_raises_only_after_the_half_sale_and_only_upward():
    trade = make_trade(entry_price=100.0, stop=99.0, half_sold=True, half_price=102.0)
    day = trade.entry_date
    bars = [
        Bar(day, 102, 103, 101.5, 102.5, 1),
        Bar(day + timedelta(days=1), 102.5, 104, 102.0, 103.5, 1),
        Bar(day + timedelta(days=2), 103.5, 105, 103.0, 104.5, 1),
    ]
    actions = propose_actions(trade, bars, 0.001)
    assert len(actions) == 1
    assert actions[0].kind == "raise_stop"
    assert actions[0].new_stop is not None
    assert actions[0].new_stop > trade.stop

    # Stop is already above the trail and still under the latest low, so it stays put.
    lowered = make_trade(entry_price=100.0, stop=102.5, half_sold=True, half_price=102.0)
    assert propose_actions(lowered, bars, 0.001) == []


def test_fixed3_exits_at_three_percent():
    trade = make_trade(entry_price=100.0, stop=99.0, exit_plan="fixed3", initial_stop=99.0)
    bar = Bar(trade.entry_date, 100.0, 103.2, 99.5, 103.0, 1)
    actions = propose_actions(trade, [bar], 0.001)
    assert actions[0].kind == "target_exit"
    assert abs(actions[0].price - 103.0) < 1e-9
