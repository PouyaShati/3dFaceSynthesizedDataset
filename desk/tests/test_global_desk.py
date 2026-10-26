import json
import threading
from urllib.request import Request, urlopen

from desk.demo import demo_market, demo_session, demo_specs, fitted_pullback_bars
from desk.server import DeskApp, make_server
from desk.setups.pullback import evaluate_pullback
from desk.universe import atr_percent, candidate_specs, classify, global_specs
from desk.models import SetupSignal, SymbolSpec
from tests.support import sample_config


def _money(equity: float = 20_000, deployable: float = 200_000, **extra: object) -> dict:
    body = {
        "equity": equity,
        "deployable_cash": deployable,
        "max_positions": 5,
        "exit_plan": "scale",
        "commission_per_trade": 0,
        "usd_conversion_fee": 2,
        "fx_spread_bps": 0,
        "demo": True,
        "cash": {},
    }
    body.update(extra)
    return body


def test_global_scope_reads_every_sleeve(tmp_path):
    config = sample_config(tmp_path, search_enabled=True, search_scope="global", usd_cash=0)
    specs = {spec.symbol: spec for spec in candidate_specs(config)}
    assert specs["RY.TO"].source == "Toronto large cap"
    assert specs["AAPL"].currency == "USD"
    assert specs["SHEL.L"].price_scale == 0.01
    assert specs["SHEL.L"].source == "London large cap"
    assert specs["SAP.DE"].currency == "EUR"
    assert specs["NESN.SW"].currency == "CHF"
    assert specs["7203.T"].currency == "JPY"
    assert specs["7203.T"].source == "Tokyo large cap"
    assert specs["BHP.AX"].currency == "AUD"
    assert specs["0700.HK"].currency == "HKD"
    assert len(global_specs()) > 100


def test_london_pence_are_priced_in_the_account_currency(tmp_path):
    config = sample_config(tmp_path)
    cheap = classify(
        SymbolSpec("SHEL.L", "GBP", "Shell", "London large cap", 0.01),
        fitted_pullback_bars(200),
        config,
    )
    assert cheap.stage == "price"
    assert cheap.source == "London large cap"


def test_fitted_demo_names_are_pullbacks(tmp_path):
    config = sample_config(tmp_path, search_enabled=True, search_scope="global")
    market = demo_market()
    session = demo_session()
    for spec in demo_specs():
        bars = market.bars(spec.symbol, session)
        assert config.min_atr_pct <= atr_percent(bars, 14) <= config.max_atr_pct
        assert classify(spec, bars, config).stage == "in_trend"
        signal = evaluate_pullback(bars, config, spec.symbol)
        assert isinstance(signal, SetupSignal)
        assert config.min_stop_pct <= signal.stop_pct <= config.max_stop_pct


def test_scan_names_the_source_and_resize_changes_the_book(tmp_path):
    config = sample_config(
        tmp_path,
        search_enabled=True,
        search_scope="global",
        equity=20_000,
        deployable_cash=200_000,
    )
    app = DeskApp(config, None, True)
    view = app.scan(_money())
    by_symbol = {order["symbol"]: order for order in view["orders"]}
    assert by_symbol["RY.TO"]["source"] == "Toronto large cap"
    assert "Sell half near" in by_symbol["RY.TO"]["exit"]
    assert by_symbol["SHEL.L"]["source"] == "London large cap"
    assert by_symbol["SHEL.L"]["convert"] is True
    assert by_symbol["7203.T"]["source"] == "Tokyo large cap"
    assert by_symbol["0700.HK"]["source"] == "Hong Kong large cap"
    assert by_symbol["AAPL"]["source"] == "US large cap"
    assert [order["symbol"] for order in view["orders"]] == ["RY.TO", "SHEL.L", "7203.T", "0700.HK", "AAPL"]
    first = by_symbol["RY.TO"]["shares"]
    doubled = app.resize(_money(equity=40_000, deployable=400_000))
    second = next(order for order in doubled["orders"] if order["symbol"] == "RY.TO")
    assert second["shares"] in {first * 2, first * 2 + 1}

    fixed = app.resize(_money(exit_plan="fixed3"))
    royal = next(order for order in fixed["orders"] if order["symbol"] == "RY.TO")
    assert "3 percent" in royal["exit"]

    costly = app.resize(_money(fx_spread_bps=150))
    assert all(order["currency"] == "CAD" for order in costly["orders"])
    assert any(skip["symbol"] == "SHEL.L" and skip["reason"] == "cost" for skip in costly["skipped"])

    held = app.resize(_money(fx_spread_bps=150, cash={"USD": 5_000}))
    apple = next(order for order in held["orders"] if order["symbol"] == "AAPL")
    assert apple["convert"] is False
    assert apple["source"] == "US large cap"


def test_http_demo_scan_and_a_rejected_resize(tmp_path):
    config = sample_config(tmp_path, equity=20_000, deployable_cash=200_000)
    server = make_server(config, None, 0, True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        page = urlopen(base + "/").read()
        assert b"Source" in page
        defaults = json.load(urlopen(base + "/api/defaults"))
        assert defaults["demo_default"] is True
        assert "London large cap" in defaults["markets"]
        try:
            urlopen(Request(
                base + "/api/resize",
                data=json.dumps(_money()).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            ))
            raise AssertionError("resize before a search should fail")
        except Exception as exc:
            assert getattr(exc, "code", None) == 400
        view = json.load(urlopen(Request(
            base + "/api/scan",
            data=json.dumps(_money()).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )))
        assert any(order["source"] == "Hong Kong large cap" for order in view["orders"])
        resized = json.load(urlopen(Request(
            base + "/api/resize",
            data=json.dumps(_money(equity=30_000)).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )))
        assert resized["orders"]
        try:
            urlopen(Request(
                base + "/api/scan",
                data=json.dumps(_money(equity=-1)).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            ))
            raise AssertionError("negative equity should fail")
        except Exception as exc:
            assert getattr(exc, "code", None) == 400
    finally:
        server.shutdown()
        thread.join(timeout=5)
