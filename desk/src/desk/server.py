"""Local interactive desk. Set the money, read the strategy, and see each trade's source."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from desk.config import DeskConfig
from desk.data import StaticMarket, YahooMarket
from desk.demo import demo_market, demo_session, demo_specs
from desk.exits import propose_actions
from desk.journal import Gate, Journal
from desk.picker import screen, select_orders
from desk.universe import GLOBAL_MARKETS, candidate_specs, search_specs
from desk.models import Bar, SymbolSpec


@dataclass
class PriceCache:
    specs: list[SymbolSpec]
    bars: dict[str, list[Bar]]
    earnings: dict[str, date | None]
    known: dict[str, bool]
    asof: date


def _number(body: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(body.get(key, default))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number.") from exc


def apply_money(config: DeskConfig, body: dict[str, Any]) -> DeskConfig:
    """Apply the figures from the interactive form. Risk stays at 0.5 percent."""
    equity = _number(body, "equity", config.equity)
    deployable = _number(body, "deployable_cash", config.deployable_cash)
    try:
        max_positions = int(body.get("max_positions", config.max_positions))
    except (TypeError, ValueError) as exc:
        raise ValueError("max_positions must be 4, 5, or 6.") from exc
    exit_plan = str(body.get("exit_plan", config.exit_plan))
    if equity <= 0:
        raise ValueError("Equity must be positive.")
    if deployable < 0:
        raise ValueError("Deployable cash cannot be negative.")
    if max_positions not in {4, 5, 6}:
        raise ValueError("Open positions must be 4, 5, or 6.")
    if exit_plan not in {"scale", "fixed3"}:
        raise ValueError("Exit plan must be scale or fixed3.")
    cash = {str(key).upper(): float(value) for key, value in (body.get("cash") or {}).items()}
    rates = dict(config.fx_rates)
    for key, value in (body.get("fx_rates") or {}).items():
        rates[str(key).upper()] = float(value)
    return replace(
        config,
        equity=equity,
        deployable_cash=deployable,
        max_positions=max_positions,
        exit_plan=exit_plan,
        cash_balances=cash,
        fx_rates=rates,
        commission_per_trade=_number(body, "commission_per_trade", config.commission_per_trade),
        usd_conversion_fee=_number(body, "usd_conversion_fee", config.usd_conversion_fee),
        fx_spread_bps=_number(body, "fx_spread_bps", config.fx_spread_bps),
        search_enabled=True,
    )


def _exit_text(exit_plan: str, entry: float, target: float, partial: float | None) -> str:
    if exit_plan == "fixed3":
        return (
            f"Sell the whole position at {target:.4f}, 3 percent above {entry:.4f}, "
            "which is at least twice the risk. If the daily low hits the stop first, exit there. "
            "Do not add. Move the stop only up."
        )
    assert partial is not None
    return (
        f"Sell half near {partial:.4f}, 2 percent above {entry:.4f}. "
        "Trail the rest under the most recent three daily lows, and move that stop only up. "
        "A daily low through the stop exits the position. Do not add to it."
    )


def _strategy(config: DeskConfig, specs: list[SymbolSpec]) -> dict[str, Any]:
    sources = []
    for market in GLOBAL_MARKETS:
        if any(spec.source == market.source for spec in specs) or config.search_scope == "global":
            sources.append(
                {
                    "source": market.source,
                    "currency": market.currency,
                    "price_scale": market.price_scale,
                }
            )
    if not sources:
        sources = [
            {"source": spec.source or "Watchlist", "currency": spec.currency, "price_scale": spec.price_scale}
            for spec in specs
        ]
    exit_rule = (
        "Sell half near 2 percent and trail the rest under recent daily lows."
        if config.exit_plan == "scale"
        else "Sell the whole position at 3 percent, and only when that is at least twice the risk."
    )
    return {
        "direction": "Long only. The close must be above a rising 50-day average.",
        "entry": "Pullback toward the 20-day average that has stopped falling. Earnings week is skipped.",
        "risk": "If the stop is hit, the loss is 0.5 percent of the equity typed above. That fraction does not change.",
        "stop": "The stop sits just beyond the pullback low and must be about 0.75 to 1.5 percent from the entry.",
        "target": "The payoff is 2 to 3 times that risk, which is about a 2 to 3 percent price move.",
        "exit": exit_rule,
        "book": f"At most {config.max_positions} open positions. The rest stays in cash or the long-term ETFs.",
        "markets": sources,
        "equity": config.equity,
        "deployable_cash": config.deployable_cash,
        "exit_plan": config.exit_plan,
        "max_positions": config.max_positions,
    }


def build_view(
    config: DeskConfig,
    market: StaticMarket,
    asof: date,
    specs: list[SymbolSpec],
    journal: Journal | None = None,
) -> dict[str, Any]:
    found = search_specs(config, market, asof, specs)
    gate = (
        journal.gate(config.journal_min_trades)
        if journal is not None
        else Gate(0, 0.0, False, True, False, "collecting")
    )
    orders_out: list[dict[str, Any]] = []
    skips = []
    if gate.allow_new_entries:
        signals, setup_skips = screen(
            config,
            market,
            asof,
            [] if journal is None else journal.open_trades(),
            allow_breakout=gate.allow_breakout and config.enable_breakout,
            symbols=found.tradable,
        )
        orders, size_skips = select_orders(
            config,
            signals,
            {spec.symbol: spec for spec in found.tradable},
            [] if journal is None else journal.open_trades(),
        )
        skips = list(setup_skips) + list(size_skips)
        for order in orders:
            signal = order.signal
            orders_out.append(
                {
                    "symbol": signal.symbol,
                    "name": order.name,
                    "source": order.source,
                    "currency": order.currency,
                    "entry": signal.entry,
                    "stop": signal.stop,
                    "stop_pct": signal.stop_pct,
                    "target": signal.target,
                    "partial": signal.partial_price,
                    "shares": order.shares,
                    "dollar_risk": order.dollar_risk,
                    "risk_pct_of_equity": order.dollar_risk / config.equity,
                    "convert": order.convert,
                    "estimated_cost": order.estimated_cost,
                    "exit": _exit_text(signal.exit_plan, signal.entry, signal.target, signal.partial_price),
                    "thesis": signal.thesis,
                }
            )
    else:
        skips = []
    waiting = [
        {
            "symbol": row.symbol,
            "name": row.name,
            "source": row.source,
            "currency": row.currency,
            "detail": row.detail,
        }
        for row in found.rows
        if row.stage == "in_trend" and row.symbol not in {item["symbol"] for item in orders_out}
    ]
    exits = []
    if journal is not None:
        for trade in journal.open_trades():
            bars = market.bars(trade.symbol, asof)
            for action in propose_actions(trade, bars, config.stop_buffer_pct):
                exits.append({"symbol": trade.symbol, "kind": action.kind, "detail": action.detail})
    counts: dict[str, int] = {}
    for row in found.rows:
        counts[row.stage] = counts.get(row.stage, 0) + 1
    return {
        "asof": asof.isoformat(),
        "summary": found.summary,
        "strategy": _strategy(config, specs),
        "gate": gate.reason,
        "orders": orders_out,
        "waiting": waiting,
        "skipped": [{"symbol": skip.symbol, "reason": skip.reason, "detail": skip.detail} for skip in skips],
        "stages": [
            {"symbol": row.symbol, "source": row.source, "currency": row.currency, "stage": row.stage, "detail": row.detail}
            for row in found.rows
        ],
        "stage_counts": counts,
        "open_exits": exits,
    }


def _known_earnings(specs: list[SymbolSpec], asof: date, live: YahooMarket | None) -> tuple[dict[str, date | None], dict[str, bool]]:
    earnings: dict[str, date | None] = {}
    known: dict[str, bool] = {}
    if live is None:
        far = asof + timedelta(days=40)
        for spec in specs:
            earnings[spec.symbol] = far
            known[spec.symbol] = True
        return earnings, known
    for spec in specs:
        status = live.earnings_status(spec.symbol, asof)
        known[spec.symbol] = status == "known"
        earnings[spec.symbol] = live.earnings_date(spec.symbol, asof) if known[spec.symbol] else None
    return earnings, known


def load_prices(config: DeskConfig, demo: bool, asof: date) -> PriceCache:
    if demo:
        specs = demo_specs()
        market = demo_market()
        asof = demo_session()
        bars = {spec.symbol: market.bars(spec.symbol, asof) for spec in specs}
        earnings, known = _known_earnings(specs, asof, None)
        return PriceCache(specs, bars, earnings, known, asof)
    specs = candidate_specs(replace(config, search_enabled=True, search_scope="global"))
    live = YahooMarket()
    bars = {}
    for spec in specs:
        try:
            bars[spec.symbol] = live.bars(spec.symbol, asof)
        except Exception:
            bars[spec.symbol] = []
    earnings, known = _known_earnings(specs, asof, live)
    return PriceCache(specs, bars, earnings, known, asof)


def view_from_cache(config: DeskConfig, cache: PriceCache, journal: Journal | None) -> dict[str, Any]:
    market = StaticMarket(cache.bars, earnings=cache.earnings, known=cache.known)
    return build_view(config, market, cache.asof, cache.specs, journal)


class DeskApp:
    def __init__(self, config: DeskConfig, journal: Journal | None, demo_default: bool) -> None:
        self.config = config
        self.journal = journal
        self.demo_default = demo_default
        self.cache: PriceCache | None = None

    def defaults(self) -> dict[str, Any]:
        currencies = ["CAD", "USD", "EUR", "GBP", "JPY", "AUD", "HKD", "CHF"]
        cash = {code: self.config.cash_balances.get(code, 0.0) for code in currencies}
        if self.config.currency not in cash:
            cash[self.config.currency] = self.config.deployable_cash
        return {
            "demo_default": self.demo_default,
            "equity": self.config.equity,
            "deployable_cash": self.config.deployable_cash,
            "max_positions": self.config.max_positions,
            "exit_plan": self.config.exit_plan,
            "commission_per_trade": self.config.commission_per_trade,
            "usd_conversion_fee": self.config.usd_conversion_fee,
            "fx_spread_bps": self.config.fx_spread_bps,
            "cash": cash,
            "fx_rates": {code: self.config.fx_rates.get(code, 1.0) for code in currencies},
            "markets": [market.source for market in GLOBAL_MARKETS],
            "currency": self.config.currency,
        }

    def scan(self, body: dict[str, Any]) -> dict[str, Any]:
        config = apply_money(self.config, body)
        demo = bool(body.get("demo", self.demo_default))
        asof = date.fromisoformat(body["date"]) if body.get("date") else date.today()
        self.cache = load_prices(config, demo, asof)
        self.config = config
        return view_from_cache(config, self.cache, self.journal)

    def resize(self, body: dict[str, Any]) -> dict[str, Any]:
        if self.cache is None:
            raise ValueError("Run a search before changing the money.")
        config = apply_money(self.config, body)
        self.config = config
        return view_from_cache(config, self.cache, self.journal)


def make_server(
    config: DeskConfig,
    journal: Journal | None,
    port: int,
    demo_default: bool,
) -> ThreadingHTTPServer:
    app = DeskApp(config, journal, demo_default)
    page = _PAGE_PATH.read_text(encoding="utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:
            return

        def _send(self, status: int, payload: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw.decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError("Expected a JSON object.")
            return body

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path in {"/", "/index.html"}:
                self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
                return
            if path == "/api/defaults":
                self._send(200, json.dumps(app.defaults()).encode("utf-8"), "application/json")
                return
            self._send(404, b"Not found", "text/plain; charset=utf-8")

        def do_POST(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            try:
                body = self._read_json()
                if path == "/api/scan":
                    result = app.scan(body)
                elif path == "/api/resize":
                    result = app.resize(body)
                else:
                    self._send(404, b"Not found", "text/plain; charset=utf-8")
                    return
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                self._send(400, json.dumps({"error": str(exc)}).encode("utf-8"), "application/json")
                return
            self._send(200, json.dumps(result).encode("utf-8"), "application/json")

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(config: DeskConfig, journal: Journal | None, port: int, demo_default: bool) -> None:
    server = make_server(config, journal, port, demo_default)
    host, bound = server.server_address[:2]
    print(f"Desk is at http://{host}:{bound}")
    server.serve_forever()


_PAGE_PATH = Path(__file__).resolve().parent / "static" / "index.html"
