from datetime import date, timedelta

from desk.harvest import Lot, evaluate_harvest
from tests.support import sample_config


def _lot(**overrides: object) -> Lot:
    values: dict[str, object] = {
        "symbol": "EXAMPLE.TO",
        "account": "non_registered",
        "acquired": date(2024, 1, 15),
        "shares": 100,
        "acb": 40.0,
        "currency": "CAD",
    }
    values.update(overrides)
    return Lot(**values)  # type: ignore[arg-type]


def test_tfsa_lot_is_excluded_and_a_cash_loss_is_a_candidate(tmp_path):
    config = sample_config(tmp_path, min_harvest_loss=50)
    asof = date(2026, 11, 15)
    rows = evaluate_harvest(
        [_lot(), _lot(account="tfsa", acb=80)],
        {"EXAMPLE.TO": 30.0},
        set(),
        [],
        asof,
        config,
    )
    by_account = {row.account: row for row in rows}
    assert by_account["tfsa"].status == "excluded"
    assert "not deductible" in by_account["tfsa"].reason
    assert by_account["non_registered"].status == "candidate"
    assert by_account["non_registered"].loss == 1000
    assert by_account["non_registered"].earliest_rebuy == asof + timedelta(days=30)
    assert by_account["non_registered"].replacement == ""


def test_recent_tfsa_buy_blocks_the_cash_loss(tmp_path):
    config = sample_config(tmp_path)
    asof = date(2026, 11, 15)
    rows = evaluate_harvest(
        [
            _lot(),
            _lot(account="tfsa", acquired=asof - timedelta(days=10), acb=20, shares=10),
        ],
        {"EXAMPLE.TO": 30.0},
        set(),
        [],
        asof,
        config,
    )
    cash = next(row for row in rows if row.account == "non_registered")
    assert cash.status == "blocked"
    assert "30 days" in cash.reason


def test_open_short_term_trade_and_a_small_loss_are_excluded(tmp_path):
    config = sample_config(tmp_path, min_harvest_loss=50)
    asof = date(2026, 11, 15)
    rows = evaluate_harvest(
        [
            _lot(symbol="OPEN.TO", acb=40),
            _lot(symbol="TINY.TO", acb=10.2, shares=10),
        ],
        {"OPEN.TO": 30.0, "TINY.TO": 10.0},
        {"OPEN.TO"},
        [],
        asof,
        config,
    )
    by_symbol = {row.symbol: row for row in rows}
    assert by_symbol["OPEN.TO"].status == "excluded"
    assert "short-term" in by_symbol["OPEN.TO"].reason
    assert by_symbol["TINY.TO"].status == "excluded"
    assert by_symbol["TINY.TO"].loss == pytest_loss(10.2, 10.0, 10)


def test_a_journal_buy_inside_the_window_blocks(tmp_path):
    config = sample_config(tmp_path)
    asof = date(2026, 11, 15)
    rows = evaluate_harvest(
        [_lot()],
        {"EXAMPLE.TO": 30.0},
        set(),
        [("EXAMPLE.TO", asof - timedelta(days=5), "tfsa")],
        asof,
        config,
    )
    assert rows[0].status == "blocked"


def pytest_loss(acb: float, price: float, shares: float) -> float:
    return (acb - price) * shares
