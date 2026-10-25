from datetime import date

from desk.journal import Journal
from tests.support import sample_config


def _close_many(journal: Journal, count: int, *, gross: float, fx: float) -> None:
    for index in range(count):
        trade_id = journal.add_trade(
            symbol=f"S{index}",
            account="non_registered",
            setup="pullback",
            mode="paper",
            thesis="gate",
            entry_date=date(2026, 1, 5),
            entry_price=100.0,
            stop=99.0,
            target=103.0,
            shares=10,
            exit_plan="scale",
            commissions=0.0,
            fx_cost=fx,
            currency="CAD",
        )
        exit_price = 100.0 + gross / 10
        journal.close_trade(
            trade_id,
            exit_date=date(2026, 1, 6),
            exit_price=exit_price,
            fx_rate=1.0,
        )


def test_gate_collects_before_thirty_trades(tmp_path):
    config = sample_config(tmp_path)
    journal = Journal(config.db_path)
    _close_many(journal, 29, gross=50.0, fx=0.0)
    gate = journal.gate(config.journal_min_trades)
    assert gate.reason == "collecting"
    assert gate.allow_new_entries is True
    assert gate.allow_breakout is False


def test_gate_passes_when_net_is_positive_and_conversion_is_not_on_every_trade(tmp_path):
    config = sample_config(tmp_path)
    journal = Journal(config.db_path)
    _close_many(journal, 29, gross=50.0, fx=2.0)
    _close_many_from(journal, 1, gross=50.0, fx=0.0, start=29)
    gate = journal.gate(30)
    assert gate.reason == "pass"
    assert gate.allow_new_entries is True
    assert gate.allow_breakout is True
    assert gate.net_after_costs > 0


def test_gate_freezes_on_a_non_positive_net(tmp_path):
    config = sample_config(tmp_path)
    journal = Journal(config.db_path)
    _close_many(journal, 30, gross=0.0, fx=0.0)
    gate = journal.gate(30)
    assert gate.reason == "freeze_costs"
    assert gate.allow_new_entries is False


def test_gate_freezes_when_conversion_is_paid_on_every_trade(tmp_path):
    config = sample_config(tmp_path)
    journal = Journal(config.db_path)
    _close_many(journal, 30, gross=50.0, fx=2.0)
    gate = journal.gate(30)
    assert gate.reason == "freeze_conversion"
    assert gate.allow_new_entries is False
    assert gate.conversion_on_every_trade is True


def test_stop_update_refuses_a_lower_stop(tmp_path):
    journal = Journal(tmp_path / "desk.sqlite")
    trade_id = journal.add_trade(
        symbol="EXAMPLE.TO",
        account="non_registered",
        setup="pullback",
        mode="paper",
        thesis="trail",
        entry_date=date(2026, 10, 1),
        entry_price=100.0,
        stop=99.0,
        target=103.0,
        shares=10,
        exit_plan="scale",
        commissions=0.0,
        fx_cost=0.0,
        currency="CAD",
    )
    assert journal.update_stop(trade_id, 99.4) is True
    assert journal.update_stop(trade_id, 99.1) is False
    assert journal.get_trade(trade_id).stop == 99.4


def _close_many_from(journal: Journal, count: int, *, gross: float, fx: float, start: int) -> None:
    for offset in range(count):
        index = start + offset
        trade_id = journal.add_trade(
            symbol=f"S{index}",
            account="non_registered",
            setup="pullback",
            mode="paper",
            thesis="gate",
            entry_date=date(2026, 1, 5),
            entry_price=100.0,
            stop=99.0,
            target=103.0,
            shares=10,
            exit_plan="scale",
            commissions=0.0,
            fx_cost=fx,
            currency="CAD",
        )
        journal.close_trade(
            trade_id,
            exit_date=date(2026, 1, 6),
            exit_price=100.0 + gross / 10,
            fx_rate=1.0,
        )
