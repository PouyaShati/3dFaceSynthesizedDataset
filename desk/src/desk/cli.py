"""Command line. Each job does one scheduled task and does not place orders."""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from desk.calendar import MarketClosed, require_trading_day
from desk.config import ConfigError, DeskConfig, load_config
from desk.costs import needs_conversion, round_trip_cost
from desk.journal import Journal
from desk.plan import default_market, run_daily, run_harvest, run_universe, run_weekly
from desk.universe import UniverseError, listed_symbols
from desk.risk import position_shares


def _session_date(value: str | None, timezone_name: str) -> date:
    if value:
        return date.fromisoformat(value)
    return datetime.now(ZoneInfo(timezone_name)).date()


def _print_written(label: str, path, created: bool) -> None:
    state = "wrote" if created else "already recorded"
    print(f"{label}: {state} {path}")


def _journal_add(config: DeskConfig, journal: Journal, args: argparse.Namespace) -> int:
    gate = journal.gate(config.journal_min_trades)
    if not gate.allow_new_entries:
        print("New entries are frozen. The journal gate did not pass.", file=sys.stderr)
        return 1
    specs = listed_symbols(config)
    if args.symbol not in specs:
        print(f"{args.symbol} is not in the search universe or the watchlist.", file=sys.stderr)
        return 1
    spec = specs[args.symbol]
    entry_day = date.fromisoformat(args.date)
    entry = float(args.entry)
    stop = float(args.stop)
    if stop >= entry:
        print("Stop must sit below the entry.", file=sys.stderr)
        return 1
    open_trades = journal.open_trades()
    for trade in open_trades:
        if trade.symbol == args.symbol:
            if entry < trade.entry_price:
                print("Add nothing to a loser.", file=sys.stderr)
            else:
                print("That symbol already has an open position.", file=sys.stderr)
            return 1
    if len(open_trades) >= config.max_positions:
        print(f"Open positions are already at the cap of {config.max_positions}.", file=sys.stderr)
        return 1
    reserved = sum(trade.shares * trade.entry_price for trade in open_trades)
    cash = config.deployable_cash - reserved
    allowed = position_shares(config.equity, config.risk_fraction, entry, stop, max(cash, 0.0))
    if allowed is None:
        print("The stop risks more than 0.5 percent of equity, or cash cannot fund a share.", file=sys.stderr)
        return 1
    shares = allowed if args.shares is None else int(args.shares)
    if shares < 1 or shares > allowed:
        print(f"Shares must be from 1 to {allowed}, the 0.5 percent size.", file=sys.stderr)
        return 1
    exit_plan = args.exit_plan or config.exit_plan
    if exit_plan not in {"scale", "fixed3"}:
        print("Exit plan must be scale or fixed3.", file=sys.stderr)
        return 1
    risk = entry - stop
    if args.target is None:
        target = entry * 1.03 if exit_plan == "fixed3" else entry + 3 * risk
    else:
        target = float(args.target)
    convert = needs_conversion(spec.currency, config.currency)
    fx_cost = 0.0 if not convert else round_trip_cost(shares, entry, config, True) - 2 * config.commission_per_trade
    commissions = 2 * config.commission_per_trade
    thesis = args.thesis or (
        f"{args.symbol} daily trend long. Entry {entry:.4f}, stop {stop:.4f}, target {target:.4f}."
    )
    trade_id = journal.add_trade(
        symbol=args.symbol,
        account=config.account_type,
        setup=args.setup,
        mode=args.mode,
        thesis=thesis,
        entry_date=entry_day,
        entry_price=entry,
        stop=stop,
        target=target,
        shares=shares,
        exit_plan=exit_plan,
        commissions=commissions,
        fx_cost=fx_cost,
        currency=spec.currency,
    )
    print(f"Opened trade {trade_id}: {args.symbol} {shares} @ {entry:.4f} stop {stop:.4f}")
    return 0


def _journal_close(config: DeskConfig, journal: Journal, args: argparse.Namespace) -> int:
    trade = journal.get_trade(int(args.id))
    if trade is None:
        print(f"No open trade {args.id}.", file=sys.stderr)
        return 1
    rate = config.fx_rates.get(trade.currency.upper(), 1.0)
    closed = journal.close_trade(
        trade.id,
        exit_date=date.fromisoformat(args.date),
        exit_price=float(args.exit_price),
        fx_rate=rate,
    )
    if closed is None:
        print(f"No open trade {args.id}.", file=sys.stderr)
        return 1
    net = closed.result_dollars - closed.commissions - closed.fx_cost
    print(
        f"Closed trade {closed.id}: gross {closed.result_dollars:.2f} "
        f"net {net:.2f} ({closed.result_r:.2f} R)"
    )
    return 0


def _journal_half(journal: Journal, args: argparse.Namespace) -> int:
    trade = journal.get_trade(int(args.id))
    if trade is None:
        print(f"No open trade {args.id}.", file=sys.stderr)
        return 1
    price = float(args.price) if args.price is not None else trade.entry_price * 1.02
    if not journal.mark_half(trade.id, price):
        print("Half sale was not recorded. The position may already be scaled or is a single share.", file=sys.stderr)
        return 1
    print(f"Recorded half sale on trade {trade.id} at {price:.4f}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="desk", description="Scheduled long-only trade desk. No orders are sent.")
    parser.add_argument("--config", default="config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run one scheduled job")
    run_sub = run.add_subparsers(dest="job", required=True)
    daily = run_sub.add_parser("daily", help="Write the next-session plan after the close")
    daily.add_argument("--date", help="Session date YYYY-MM-DD")
    weekly = run_sub.add_parser("weekly", help="Write the journal scorecard")
    weekly.add_argument("--date", help="Any date in the week YYYY-MM-DD")
    harvest = run_sub.add_parser("harvest", help="Write the non-registered tax-lot checklist")
    harvest.add_argument("--date", help="Review date YYYY-MM-DD")
    universe = run_sub.add_parser("universe", help="Search the liquid universe without placing orders")
    universe.add_argument("--date", help="Session date YYYY-MM-DD")

    show = sub.add_parser("show", help="Reprint a plan without scanning")
    show_sub = show.add_subparsers(dest="what", required=True)
    today = show_sub.add_parser("today", help="Reprint the daily plan")
    today.add_argument("--date", help="Session date YYYY-MM-DD")

    journal = sub.add_parser("journal", help="Record a paper or live fill")
    journal_sub = journal.add_subparsers(dest="action", required=True)
    add = journal_sub.add_parser("add", help="Record an entry")
    add.add_argument("--symbol", required=True)
    add.add_argument("--entry", required=True)
    add.add_argument("--stop", required=True)
    add.add_argument("--date", required=True)
    add.add_argument("--shares", type=int)
    add.add_argument("--target")
    add.add_argument("--thesis", default="")
    add.add_argument("--mode", choices=("paper", "live"), default="paper")
    add.add_argument("--setup", default="pullback")
    add.add_argument("--exit-plan", dest="exit_plan")
    close = journal_sub.add_parser("close", help="Record an exit")
    close.add_argument("--id", required=True)
    close.add_argument("--exit-price", required=True)
    close.add_argument("--date", required=True)
    half = journal_sub.add_parser("half", help="Record the 2 percent scale sale")
    half.add_argument("--id", required=True)
    half.add_argument("--price")

    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    journal_db = Journal(config.db_path)
    try:
        if args.command == "run" and args.job == "daily":
            session = _session_date(args.date, config.timezone)
            require_trading_day(session)
            written = run_daily(config, default_market(config), journal_db, session)
            _print_written("daily", written.path, written.created)
            return 0
        if args.command == "run" and args.job == "weekly":
            written = run_weekly(config, journal_db, _session_date(args.date, config.timezone))
            _print_written("weekly", written.path, written.created)
            return 0
        if args.command == "run" and args.job == "universe":
            written = run_universe(
                config,
                default_market(config),
                journal_db,
                _session_date(args.date, config.timezone),
            )
            _print_written("universe", written.path, written.created)
            return 0
        if args.command == "run" and args.job == "harvest":
            written = run_harvest(
                config,
                default_market(config),
                journal_db,
                _session_date(args.date, config.timezone),
            )
            _print_written("harvest", written.path, written.created)
            return 0
        if args.command == "show" and args.what == "today":
            session = _session_date(args.date, config.timezone)
            path = journal_db.plan_path("daily", session.isoformat())
            if path is None:
                print(f"No daily plan for {session.isoformat()}. The morning review does not scan.", file=sys.stderr)
                return 1
            print(Path(path).read_text(encoding="utf-8"))
            return 0
        if args.command == "journal" and args.action == "add":
            return _journal_add(config, journal_db, args)
        if args.command == "journal" and args.action == "close":
            return _journal_close(config, journal_db, args)
        if args.command == "journal" and args.action == "half":
            return _journal_half(journal_db, args)
    except MarketClosed as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except UniverseError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("Unknown command.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
