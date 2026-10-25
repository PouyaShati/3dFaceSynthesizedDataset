from desk.cli import main
from tests.support import sample_config


def _write_config(tmp_path, **overrides):
    config = sample_config(tmp_path, **overrides)
    text = f"""
timezone: America/Toronto
short_term:
  account_type: {config.account_type}
  currency: {config.currency}
  equity: {config.equity}
  deployable_cash: {config.deployable_cash}
  max_positions: {config.max_positions}
  risk_fraction: 0.005
commission_per_trade: 0
usd_conversion_fee: 2
fx_spread_bps: 0
fx_rates:
  CAD: 1
  USD: 1.35
exit_plan: scale
journal_min_trades: 30
enable_breakout: false
active_setup: pullback
min_harvest_loss: 50
paths:
  db: {config.db_path}
  out: {config.out_dir}
  lots: {config.lots_path}
watchlist:
  - symbol: EXAMPLE.TO
    currency: CAD
    name: example
"""
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_weekend_daily_does_not_scan(tmp_path, capsys):
    path = _write_config(tmp_path)
    code = main(["--config", str(path), "run", "daily", "--date", "2026-10-24"])
    assert code == 2
    assert "closed" in capsys.readouterr().err.lower()


def test_show_today_does_not_create_a_plan(tmp_path, capsys):
    path = _write_config(tmp_path)
    code = main(["--config", str(path), "show", "today", "--date", "2026-10-23"])
    assert code == 1
    assert "does not scan" in capsys.readouterr().err.lower()


def test_journal_refuses_an_oversized_position(tmp_path, capsys):
    path = _write_config(tmp_path, equity=20_000, deployable_cash=20_000)
    code = main(
        [
            "--config",
            str(path),
            "journal",
            "add",
            "--symbol",
            "EXAMPLE.TO",
            "--entry",
            "50",
            "--stop",
            "49.5",
            "--date",
            "2026-10-23",
            "--shares",
            "10000",
            "--thesis",
            "too big",
        ]
    )
    assert code == 1
    assert "0.5 percent" in capsys.readouterr().err
