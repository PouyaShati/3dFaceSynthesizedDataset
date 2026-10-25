from datetime import date, timedelta

from desk.data import StaticMarket
from desk.journal import Journal
from desk.models import SymbolSpec
from desk.plan import run_daily, run_harvest, run_weekly
from tests.support import pullback_bars, sample_config


FAR_EARNINGS = date(2026, 12, 15)


def _market(symbol: str = "EXAMPLE.TO"):
    bars = pullback_bars()
    return StaticMarket({symbol: bars}, earnings={symbol: FAR_EARNINGS}, known={symbol: True}), bars


def test_daily_plan_orders_the_qualifying_pullback_and_locks_the_session(tmp_path):
    market, bars = _market()
    session = bars[-1].day
    config = sample_config(
        tmp_path,
        watchlist=(SymbolSpec("EXAMPLE.TO", "CAD", "example"),),
        equity=100_000,
        deployable_cash=100_000,
    )
    journal = Journal(config.db_path)
    first = run_daily(config, market, journal, session)
    text = first.path.read_text(encoding="utf-8")
    assert first.created is True
    assert "EXAMPLE.TO buy" in text
    assert "No currency conversion" in text
    assert "Add nothing to a loser" in text
    second = run_daily(config, market, journal, session)
    assert second.created is False
    assert second.path.read_text(encoding="utf-8") == text


def test_unknown_earnings_and_earnings_week_stay_off_the_list(tmp_path):
    bars = pullback_bars()
    session = bars[-1].day
    unknown = StaticMarket({"UNK.TO": bars}, known={"UNK.TO": False})
    config = sample_config(
        tmp_path,
        watchlist=(SymbolSpec("UNK.TO", "CAD"),),
        equity=100_000,
        deployable_cash=100_000,
    )
    journal = Journal(config.db_path)
    text = run_daily(config, unknown, journal, session).path.read_text(encoding="utf-8")
    assert "UNK.TO buy" not in text
    assert "earnings_unknown" in text

    near = session + timedelta(days=1)
    while near.weekday() >= 5:
        near += timedelta(days=1)
    known = StaticMarket({"NEAR.TO": bars}, earnings={"NEAR.TO": near}, known={"NEAR.TO": True})
    config = sample_config(
        tmp_path / "near",
        watchlist=(SymbolSpec("NEAR.TO", "CAD"),),
        equity=100_000,
        deployable_cash=100_000,
    )
    journal = Journal(config.db_path)
    text = run_daily(config, known, journal, session).path.read_text(encoding="utf-8")
    assert "NEAR.TO buy" not in text
    assert "earnings_week" in text


def test_weekend_scan_is_refused(tmp_path):
    market, _bars = _market()
    config = sample_config(tmp_path, watchlist=(SymbolSpec("EXAMPLE.TO", "CAD"),))
    journal = Journal(config.db_path)
    saturday = date(2026, 10, 24)
    assert saturday.weekday() == 5
    try:
        run_daily(config, market, journal, saturday)
    except Exception as exc:
        assert "closed" in str(exc).lower()
    else:
        raise AssertionError("weekend scan should fail")


def test_gap_through_the_stop_cancels_the_prior_order(tmp_path):
    bars = pullback_bars()
    session = bars[-1].day
    prior = bars[-2].day
    market = StaticMarket(
        {"EXAMPLE.TO": bars},
        earnings={"EXAMPLE.TO": FAR_EARNINGS},
        known={"EXAMPLE.TO": True},
    )
    config = sample_config(
        tmp_path,
        watchlist=(SymbolSpec("EXAMPLE.TO", "CAD"),),
        equity=100_000,
        deployable_cash=100_000,
    )
    journal = Journal(config.db_path)
    journal.record_run("daily", prior.isoformat(), str(tmp_path / "old.md"))
    journal.save_signal(
        prior.isoformat(),
        symbol="EXAMPLE.TO",
        status="proposed",
        setup="pullback",
        entry=bars[-2].close,
        stop=bars[-1].open + 1,
        target=bars[-2].close * 1.03,
        shares=10,
        thesis="old",
        exit_plan="scale",
    )
    text = run_daily(config, market, journal, session).path.read_text(encoding="utf-8")
    assert "Cancelled" in text or "cancelled" in text
    assert "Do not chase" in text


def test_frozen_journal_manages_positions_and_emits_no_new_order(tmp_path):
    market, bars = _market()
    session = bars[-1].day
    config = sample_config(
        tmp_path,
        watchlist=(SymbolSpec("EXAMPLE.TO", "CAD"), SymbolSpec("HELD.TO", "CAD")),
        equity=100_000,
        deployable_cash=100_000,
    )
    journal = Journal(config.db_path)
    for index in range(30):
        trade_id = journal.add_trade(
            symbol=f"OLD{index}",
            account="non_registered",
            setup="pullback",
            mode="paper",
            thesis="flat",
            entry_date=date(2026, 1, 5),
            entry_price=10.0,
            stop=9.0,
            target=11.0,
            shares=1,
            exit_plan="fixed3",
            commissions=1.0,
            fx_cost=0.0,
            currency="CAD",
        )
        journal.close_trade(trade_id, exit_date=date(2026, 1, 6), exit_price=10.0, fx_rate=1.0)
    held_bars = pullback_bars()
    # A position still open, with the latest bar through the stop, must be managed.
    journal.add_trade(
        symbol="HELD.TO",
        account="non_registered",
        setup="pullback",
        mode="paper",
        thesis="open loser",
        entry_date=held_bars[-5].day,
        entry_price=held_bars[-5].close,
        stop=held_bars[-1].high + 10,
        target=held_bars[-5].close * 1.03,
        shares=2,
        exit_plan="scale",
        commissions=0.0,
        fx_cost=0.0,
        currency="CAD",
    )
    market = StaticMarket(
        {"EXAMPLE.TO": bars, "HELD.TO": held_bars},
        earnings={"EXAMPLE.TO": FAR_EARNINGS, "HELD.TO": FAR_EARNINGS},
        known={"EXAMPLE.TO": True, "HELD.TO": True},
    )
    text = run_daily(config, market, journal, session).path.read_text(encoding="utf-8")
    assert "No new order" in text
    assert "frozen" in text.lower() or "freeze" in text
    assert "HELD.TO" in text
    assert "Exit the position" in text


def test_add_to_loser_is_named_on_the_plan(tmp_path):
    market, bars = _market()
    session = bars[-1].day
    config = sample_config(
        tmp_path,
        watchlist=(SymbolSpec("EXAMPLE.TO", "CAD"),),
        equity=100_000,
        deployable_cash=100_000,
    )
    journal = Journal(config.db_path)
    journal.add_trade(
        symbol="EXAMPLE.TO",
        account="non_registered",
        setup="pullback",
        mode="paper",
        thesis="underwater",
        entry_date=bars[-10].day,
        entry_price=bars[-1].close + 5,
        stop=bars[-1].close - 1,
        target=bars[-1].close + 8,
        shares=10,
        exit_plan="scale",
        commissions=0.0,
        fx_cost=0.0,
        currency="CAD",
    )
    text = run_daily(config, market, journal, session).path.read_text(encoding="utf-8")
    assert "add_to_loser" in text
    assert "EXAMPLE.TO buy" not in text


def test_weekly_scorecard_and_harvest_file(tmp_path):
    market, bars = _market()
    session = bars[-1].day
    lots = tmp_path / "lots.csv"
    lots.write_text(
        "symbol,account,acquired,shares,acb,currency\n"
        "EXAMPLE.TO,non_registered,2024-01-15,100,200.00,CAD\n"
        "EXAMPLE.TO,tfsa,2024-01-15,10,200.00,CAD\n",
        encoding="utf-8",
    )
    config = sample_config(
        tmp_path,
        watchlist=(SymbolSpec("EXAMPLE.TO", "CAD"),),
        lots_path=lots,
        equity=100_000,
        deployable_cash=100_000,
    )
    journal = Journal(config.db_path)
    weekly = run_weekly(config, journal, session)
    assert "Gate: collecting" in weekly.path.read_text(encoding="utf-8")
    assert run_weekly(config, journal, session).created is False
    harvest = run_harvest(config, market, journal, date(2026, 11, 15))
    report = harvest.path.read_text(encoding="utf-8")
    assert "non_registered" in report
    assert "not deductible" in report
    assert "candidate" in report
