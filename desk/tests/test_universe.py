from datetime import date
from pathlib import Path

from desk.data import StaticMarket
from desk.journal import Journal
from desk.models import SymbolSpec
from desk.plan import run_daily, run_universe
from desk.universe import (
    classify,
    is_common_listing,
    load_symbol_file,
    search_market,
)
from tests.support import bars_from_ohlc, pullback_bars, sample_config

PACKAGED = Path(__file__).resolve().parents[1] / "universes"
FAR = date(2026, 12, 15)


def _rising(count: int = 80, start: float = 100.0, step: float = 0.2, span: float = 0.016, volume: float = 500_000):
    closes = [start + step * index for index in range(count)]
    rows = []
    volumes = []
    for index, close in enumerate(closes):
        opened = closes[index - 1] if index else close
        rows.append((opened, close * (1 + span / 2), close * (1 - span / 2), close))
        volumes.append(volume)
    return bars_from_ohlc(rows, volumes=volumes)


def _files(root: Path, cad: list[str], usd: list[str] | None = None) -> tuple[Path, Path]:
    folder = root / "universes"
    folder.mkdir(parents=True, exist_ok=True)
    cad_path = folder / "cad.txt"
    usd_path = folder / "usd.txt"
    cad_path.write_text("\n".join(cad) + "\n", encoding="utf-8")
    usd_path.write_text("\n".join(usd or []) + "\n", encoding="utf-8")
    return cad_path, usd_path


def test_shipped_universes_match_the_account_split():
    cad = load_symbol_file(PACKAGED / "tsx60.txt", "CAD")
    usd = load_symbol_file(PACKAGED / "us_large.txt", "USD")
    assert len(cad) == 60
    assert len({spec.symbol for spec in cad}) == 60
    assert all(spec.symbol.endswith(".TO") for spec in cad)
    assert {spec.symbol for spec in cad} >= {"RY.TO", "SHOP.TO", "CTC-A.TO", "BIP-UN.TO", "TECK-B.TO"}
    assert len(usd) >= 20
    assert all(not spec.symbol.endswith(".TO") for spec in usd)
    assert is_common_listing("CTC-A.TO") is True
    assert is_common_listing("ABC-WT.TO") is False
    assert is_common_listing("XYZ-PR.TO") is False


def test_structure_keeps_a_liquid_trend_and_rejects_the_untradable(tmp_path):
    config = sample_config(tmp_path, search_enabled=True)
    trend = classify(SymbolSpec("RY.TO", "CAD", "Royal"), _rising(), config)
    assert trend.stage == "in_trend"

    cheap = classify(SymbolSpec("CHEAP.TO", "CAD"), _rising(start=4, step=0.01, volume=5_000_000), config)
    assert cheap.stage == "price"

    thin = classify(SymbolSpec("THIN.TO", "CAD"), _rising(volume=10), config)
    assert thin.stage == "illiquid"

    quiet = classify(SymbolSpec("QUIET.TO", "CAD"), _rising(span=0.002), config)
    assert quiet.stage == "atr_low"

    wild = classify(SymbolSpec("WILD.TO", "CAD"), _rising(span=0.10), config)
    assert wild.stage == "atr_high"

    falling = _rising()
    # Reverse the closes by rebuilding a decline with the same range and volume.
    declined = _rising(start=200, step=-0.3)
    assert classify(SymbolSpec("DOWN.TO", "CAD"), declined, config).stage == "no_trend"
    del falling


def test_usd_names_stay_out_until_usd_cash_is_held(tmp_path):
    cad_path, usd_path = _files(tmp_path, ["RY.TO Royal"], ["AAPL Apple"])
    bars = {"RY.TO": _rising(), "AAPL": _rising(start=180)}
    market = StaticMarket(bars)
    session = bars["RY.TO"][-1].day
    cash = sample_config(
        tmp_path,
        search_enabled=True,
        cad_universe=cad_path,
        usd_universe=usd_path,
        usd_cash=0,
    )
    found = search_market(cash, market, session)
    assert [row.symbol for row in found.rows] == ["RY.TO"]

    held = sample_config(
        tmp_path / "usd",
        search_enabled=True,
        cad_universe=cad_path,
        usd_universe=usd_path,
        usd_cash=5_000,
    )
    found = search_market(held, market, session)
    assert {row.symbol for row in found.rows} == {"RY.TO", "AAPL"}


def test_a_warrant_in_the_file_is_excluded_without_a_setup(tmp_path):
    cad_path, usd_path = _files(tmp_path, ["ABC-WT.TO Warrant"])
    config = sample_config(
        tmp_path,
        search_enabled=True,
        cad_universe=cad_path,
        usd_universe=usd_path,
    )
    found = search_market(config, StaticMarket({}), date(2026, 10, 23))
    assert found.rows[0].stage == "excluded"
    assert found.tradable == []


def test_daily_search_orders_only_a_name_that_clears_the_universe(tmp_path):
    bars = pullback_bars()
    session = bars[-1].day
    cad_path, usd_path = _files(tmp_path, ["EXAMPLE.TO Example", "QUIET.TO Quiet"])
    quiet = _rising(span=0.002)
    market = StaticMarket(
        {"EXAMPLE.TO": bars, "QUIET.TO": quiet},
        earnings={"EXAMPLE.TO": FAR, "QUIET.TO": FAR},
        known={"EXAMPLE.TO": True, "QUIET.TO": True},
    )
    config = sample_config(
        tmp_path,
        search_enabled=True,
        cad_universe=cad_path,
        usd_universe=usd_path,
        min_price=1,
        min_atr_pct=0.0001,
        max_atr_pct=0.5,
        min_avg_dollar_volume=1,
        equity=100_000,
        deployable_cash=100_000,
        watchlist=(SymbolSpec("PIN.TO", "CAD", "Pinned"),),
    )
    # The pin has no bars, so it is searched and then dropped. It is not an order.
    market = StaticMarket(
        {"EXAMPLE.TO": bars, "QUIET.TO": quiet},
        earnings={"EXAMPLE.TO": FAR, "QUIET.TO": FAR, "PIN.TO": FAR},
        known={"EXAMPLE.TO": True, "QUIET.TO": True, "PIN.TO": True},
    )
    journal = Journal(config.db_path)
    written = run_daily(config, market, journal, session)
    plan = written.path.read_text(encoding="utf-8")
    universe = (config.out_dir / f"universe-{session.isoformat()}.md").read_text(encoding="utf-8")
    assert "EXAMPLE.TO buy" in plan
    assert "Search:" in plan
    assert "QUIET.TO buy" not in plan
    assert "PIN.TO buy" not in plan
    assert "EXAMPLE.TO" in universe
    assert "In trend" in universe
    assert run_universe(config, market, journal, session).created is False
