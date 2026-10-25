"""Build the one daily plan, the weekly scorecard, and the harvest checklist."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from desk.calendar import previous_trading_day, require_trading_day
from desk.config import DeskConfig
from desk.data import MarketData, YahooMarket
from desk.exits import propose_actions
from desk.harvest import evaluate_harvest, load_lots
from desk.journal import Journal
from desk.picker import Order, Skip, screen, select_orders
from desk.report import render_daily, render_harvest, render_universe, render_weekly
from desk.universe import SearchResult, search_market


@dataclass(frozen=True)
class Written:
    path: Path
    created: bool


def _write_once(journal: Journal, kind: str, session_key: str, path: Path, text: str) -> Written:
    existing = journal.plan_path(kind, session_key)
    if existing:
        return Written(Path(existing), created=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    journal.record_run(kind, session_key, str(path))
    return Written(path, created=True)


def _cancel_gapped_orders(market: MarketData, journal: Journal, asof: date) -> list[str]:
    prior = previous_trading_day(asof)
    notes: list[str] = []
    for row in journal.proposed_symbols(prior.isoformat()):
        stop = row["stop"]
        if stop is None:
            continue
        bars = market.bars(str(row["symbol"]), asof)
        today = [bar for bar in bars if bar.day == asof]
        if not today:
            continue
        opened = today[-1].open
        if opened <= float(stop) + 1e-12:
            detail = (
                f"{row['symbol']} opened at {opened:.4f}, through the stop {float(stop):.4f}. "
                "The idea is cancelled. Do not chase it."
            )
            journal.cancel_signal(prior.isoformat(), str(row["symbol"]), detail)
            notes.append(detail)
    return notes


def _publish_universe(config: DeskConfig, journal: Journal, asof: date, text: str) -> Path:
    path = config.out_dir / f"universe-{asof.isoformat()}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    key = asof.isoformat()
    if not journal.has_run("universe", key):
        journal.record_run("universe", key, str(path))
    return path


def run_daily(config: DeskConfig, market: MarketData, journal: Journal, asof: date) -> Written:
    require_trading_day(asof)
    key = asof.isoformat()
    existing = journal.plan_path("daily", key)
    if existing:
        return Written(Path(existing), created=False)

    cancelled = _cancel_gapped_orders(market, journal, asof)
    open_trades = journal.open_trades()
    actions = []
    for trade in open_trades:
        bars = market.bars(trade.symbol, asof)
        proposed = propose_actions(trade, bars, config.stop_buffer_pct)
        for action in proposed:
            if action.kind == "raise_stop" and action.new_stop is not None:
                journal.update_stop(trade.id, action.new_stop)
        actions.extend(proposed)

    gate = journal.gate(config.journal_min_trades)
    found = search_market(config, market, asof)
    if config.search_enabled:
        _publish_universe(
            config,
            journal,
            asof,
            render_universe(session=asof, config=config, rows=found.rows),
        )
    orders: list[Order] = []
    skips: list[Skip] = []
    if not gate.allow_new_entries:
        skips.append(
            Skip(
                "*",
                gate.reason,
                "New entries are frozen after the journal review.",
            )
        )
    else:
        signals, setup_skips = screen(
            config,
            market,
            asof,
            open_trades,
            allow_breakout=gate.allow_breakout and config.enable_breakout,
            symbols=found.tradable,
        )
        skips.extend(setup_skips)
        currencies = {spec.symbol: spec.currency for spec in found.tradable}
        sized, size_skips = select_orders(config, signals, currencies, open_trades)
        orders = sized
        skips.extend(size_skips)

    text = render_daily(
        session=asof,
        config=config,
        gate=gate,
        actions=actions,
        orders=orders,
        skips=skips,
        open_count=len(open_trades),
        cancelled=cancelled,
        search_summary=found.summary,
    )
    path = config.out_dir / f"plan-{key}.md"
    written = _write_once(journal, "daily", key, path, text)
    if written.created:
        for order in orders:
            signal = order.signal
            journal.save_signal(
                key,
                symbol=signal.symbol,
                status="proposed",
                setup=signal.setup,
                entry=signal.entry,
                stop=signal.stop,
                target=signal.target,
                shares=order.shares,
                thesis=signal.thesis,
                exit_plan=signal.exit_plan,
                detail=f"shares {order.shares}",
            )
        for skip in skips:
            journal.save_signal(
                key,
                symbol=skip.symbol,
                status="skipped",
                reason=skip.reason,
                detail=skip.detail,
            )
    return written


def run_universe(config: DeskConfig, market: MarketData, journal: Journal, asof: date) -> Written:
    """Write the search report without creating orders.

    A second call the same day returns the file already written. The daily run
    still refreshes that file from the closing prices before it picks orders.
    """
    key = asof.isoformat()
    existing = journal.plan_path("universe", key)
    if existing:
        return Written(Path(existing), created=False)
    found: SearchResult = search_market(config, market, asof)
    if config.search_enabled:
        text = render_universe(session=asof, config=config, rows=found.rows)
    else:
        names = ", ".join(spec.symbol for spec in found.tradable) or "none"
        text = (
            f"# Universe search {key}\n\n"
            "Search is off. The daily plan uses the watchlist only.\n\n"
            f"Watchlist: {names}\n"
        )
    path = _publish_universe(config, journal, asof, text)
    return Written(path, created=True)


def run_weekly(config: DeskConfig, journal: Journal, asof: date) -> Written:
    iso = asof.isocalendar()
    key = f"{iso.year}-W{iso.week:02d}"
    existing = journal.plan_path("weekly", key)
    if existing:
        return Written(Path(existing), created=False)
    gate = journal.gate(config.journal_min_trades)
    closed = journal.closed_trades()
    text = render_weekly(
        week_key=key,
        gate=gate,
        open_count=len(journal.open_trades()),
        closed_r=[trade.result_r for trade in closed],
        fx_charged=sum(1 for trade in closed if trade.fx_cost > 0),
    )
    path = config.out_dir / f"week-{key}.md"
    return _write_once(journal, "weekly", key, path, text)


def run_harvest(config: DeskConfig, market: MarketData, journal: Journal, asof: date) -> Written:
    key = asof.isoformat()
    existing = journal.plan_path("harvest", key)
    if existing:
        return Written(Path(existing), created=False)
    lots = load_lots(config.lots_path)
    prices: dict[str, float] = {}
    for lot in lots:
        bars = market.bars(lot.symbol, asof)
        if bars:
            prices[lot.symbol] = bars[-1].close
    rows = evaluate_harvest(
        lots,
        prices,
        {trade.symbol for trade in journal.open_trades()},
        journal.acquisitions(),
        asof,
        config,
    )
    text = render_harvest(session=asof, rows=rows, account_type=config.account_type)
    path = config.out_dir / f"harvest-{key}.md"
    return _write_once(journal, "harvest", key, path, text)


def default_market(config: DeskConfig) -> MarketData:
    del config
    return YahooMarket()
