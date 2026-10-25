"""SQLite journal: thesis, entry, stop, target, costs, and the 30-trade gate."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from desk.models import OpenTrade


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    session_key TEXT NOT NULL,
    plan_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (kind, session_key)
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY,
    session_key TEXT NOT NULL,
    symbol TEXT NOT NULL,
    setup TEXT,
    status TEXT NOT NULL,
    reason TEXT,
    entry REAL,
    stop REAL,
    target REAL,
    shares INTEGER,
    thesis TEXT,
    exit_plan TEXT,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    account TEXT NOT NULL,
    setup TEXT NOT NULL,
    mode TEXT NOT NULL,
    thesis TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    entry_price REAL NOT NULL,
    stop REAL NOT NULL,
    initial_stop REAL NOT NULL,
    target REAL NOT NULL,
    shares INTEGER NOT NULL,
    exit_plan TEXT NOT NULL,
    status TEXT NOT NULL,
    half_sold INTEGER NOT NULL DEFAULT 0,
    half_price REAL,
    exit_date TEXT,
    exit_price REAL,
    result_dollars REAL,
    result_r REAL,
    commissions REAL NOT NULL,
    fx_cost REAL NOT NULL,
    currency TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class ClosedTrade:
    id: int
    symbol: str
    result_dollars: float
    commissions: float
    fx_cost: float
    result_r: float


@dataclass(frozen=True)
class Gate:
    closed_count: int
    net_after_costs: float
    conversion_on_every_trade: bool
    allow_new_entries: bool
    allow_breakout: bool
    reason: str


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


class Journal:
    def __init__(self, path: Path) -> None:
        self.path = path
        with _connect(path) as connection:
            connection.executescript(SCHEMA)

    def has_run(self, kind: str, session_key: str) -> bool:
        with _connect(self.path) as connection:
            row = connection.execute(
                "SELECT plan_path FROM runs WHERE kind = ? AND session_key = ?",
                (kind, session_key),
            ).fetchone()
        return row is not None

    def plan_path(self, kind: str, session_key: str) -> str | None:
        with _connect(self.path) as connection:
            row = connection.execute(
                "SELECT plan_path FROM runs WHERE kind = ? AND session_key = ?",
                (kind, session_key),
            ).fetchone()
        return None if row is None else str(row["plan_path"])

    def record_run(self, kind: str, session_key: str, plan_path: str) -> None:
        stamp = datetime.now(timezone.utc).isoformat()
        with _connect(self.path) as connection:
            connection.execute(
                "INSERT INTO runs (kind, session_key, plan_path, created_at) VALUES (?, ?, ?, ?)",
                (kind, session_key, plan_path, stamp),
            )

    def save_signal(
        self,
        session_key: str,
        *,
        symbol: str,
        status: str,
        setup: str | None = None,
        reason: str | None = None,
        entry: float | None = None,
        stop: float | None = None,
        target: float | None = None,
        shares: int | None = None,
        thesis: str | None = None,
        exit_plan: str | None = None,
        detail: str | None = None,
    ) -> None:
        with _connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO signals (
                    session_key, symbol, setup, status, reason, entry, stop, target,
                    shares, thesis, exit_plan, detail
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_key,
                    symbol,
                    setup,
                    status,
                    reason,
                    entry,
                    stop,
                    target,
                    shares,
                    thesis,
                    exit_plan,
                    detail,
                ),
            )

    def cancel_signal(self, session_key: str, symbol: str, detail: str) -> None:
        with _connect(self.path) as connection:
            connection.execute(
                """
                UPDATE signals
                SET status = 'cancelled', detail = ?
                WHERE session_key = ? AND symbol = ? AND status = 'proposed'
                """,
                (detail, session_key, symbol),
            )

    def proposed_symbols(self, session_key: str) -> list[sqlite3.Row]:
        with _connect(self.path) as connection:
            rows = connection.execute(
                "SELECT * FROM signals WHERE session_key = ? AND status = 'proposed'",
                (session_key,),
            ).fetchall()
        return list(rows)

    def add_trade(
        self,
        *,
        symbol: str,
        account: str,
        setup: str,
        mode: str,
        thesis: str,
        entry_date: date,
        entry_price: float,
        stop: float,
        target: float,
        shares: int,
        exit_plan: str,
        commissions: float,
        fx_cost: float,
        currency: str,
    ) -> int:
        with _connect(self.path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO trades (
                    symbol, account, setup, mode, thesis, entry_date, entry_price, stop,
                    initial_stop, target, shares, exit_plan, status, half_sold,
                    commissions, fx_cost, currency
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', 0, ?, ?, ?)
                """,
                (
                    symbol,
                    account,
                    setup,
                    mode,
                    thesis,
                    entry_date.isoformat(),
                    entry_price,
                    stop,
                    stop,
                    target,
                    shares,
                    exit_plan,
                    commissions,
                    fx_cost,
                    currency,
                ),
            )
            return int(cursor.lastrowid)

    def open_trades(self) -> list[OpenTrade]:
        with _connect(self.path) as connection:
            rows = connection.execute(
                "SELECT * FROM trades WHERE status = 'open' ORDER BY id"
            ).fetchall()
        return [_open_trade(row) for row in rows]

    def closed_trades(self) -> list[ClosedTrade]:
        with _connect(self.path) as connection:
            rows = connection.execute(
                "SELECT * FROM trades WHERE status = 'closed' ORDER BY id"
            ).fetchall()
        return [
            ClosedTrade(
                id=int(row["id"]),
                symbol=str(row["symbol"]),
                result_dollars=float(row["result_dollars"] or 0),
                commissions=float(row["commissions"]),
                fx_cost=float(row["fx_cost"]),
                result_r=float(row["result_r"] or 0),
            )
            for row in rows
        ]

    def get_trade(self, trade_id: int) -> OpenTrade | None:
        with _connect(self.path) as connection:
            row = connection.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
        if row is None or row["status"] != "open":
            return None
        return _open_trade(row)

    def update_stop(self, trade_id: int, new_stop: float) -> bool:
        trade = self.get_trade(trade_id)
        if trade is None or new_stop <= trade.stop + 1e-12:
            return False
        with _connect(self.path) as connection:
            connection.execute("UPDATE trades SET stop = ? WHERE id = ?", (new_stop, trade_id))
        return True

    def mark_half(self, trade_id: int, price: float) -> bool:
        trade = self.get_trade(trade_id)
        if trade is None or trade.half_sold or trade.shares < 2:
            return False
        with _connect(self.path) as connection:
            connection.execute(
                "UPDATE trades SET half_sold = 1, half_price = ? WHERE id = ?",
                (price, trade_id),
            )
        return True

    def close_trade(
        self,
        trade_id: int,
        *,
        exit_date: date,
        exit_price: float,
        fx_rate: float,
    ) -> ClosedTrade | None:
        trade = self.get_trade(trade_id)
        if trade is None:
            return None
        if trade.half_sold and trade.half_price is not None:
            half_shares = trade.shares // 2
            rest = trade.shares - half_shares
            gross_quote = half_shares * (trade.half_price - trade.entry_price) + rest * (
                exit_price - trade.entry_price
            )
        else:
            gross_quote = trade.shares * (exit_price - trade.entry_price)
        gross = gross_quote * fx_rate
        risk_dollars = trade.shares * trade.risk_per_share * fx_rate
        result_r = 0.0 if risk_dollars == 0 else (gross - trade.commissions - trade.fx_cost) / risk_dollars
        with _connect(self.path) as connection:
            connection.execute(
                """
                UPDATE trades
                SET status = 'closed', exit_date = ?, exit_price = ?,
                    result_dollars = ?, result_r = ?
                WHERE id = ?
                """,
                (exit_date.isoformat(), exit_price, gross, result_r, trade_id),
            )
        return ClosedTrade(
            id=trade_id,
            symbol=trade.symbol,
            result_dollars=gross,
            commissions=trade.commissions,
            fx_cost=trade.fx_cost,
            result_r=result_r,
        )

    def acquisitions(self) -> list[tuple[str, date, str]]:
        """Symbol, entry date, and account for every journaled buy."""
        with _connect(self.path) as connection:
            rows = connection.execute(
                "SELECT symbol, entry_date, account FROM trades ORDER BY entry_date"
            ).fetchall()
        return [(str(row["symbol"]), date.fromisoformat(row["entry_date"]), str(row["account"])) for row in rows]

    def gate(self, minimum: int) -> Gate:
        closed = self.closed_trades()
        count = len(closed)
        net = sum(trade.result_dollars - trade.commissions - trade.fx_cost for trade in closed)
        conversion_every = count > 0 and all(trade.fx_cost > 0 for trade in closed)
        if count < minimum:
            return Gate(
                closed_count=count,
                net_after_costs=net,
                conversion_on_every_trade=conversion_every,
                allow_new_entries=True,
                allow_breakout=False,
                reason="collecting",
            )
        if net > 0 and not conversion_every:
            return Gate(
                closed_count=count,
                net_after_costs=net,
                conversion_on_every_trade=False,
                allow_new_entries=True,
                allow_breakout=True,
                reason="pass",
            )
        reason = "freeze_costs" if net <= 0 else "freeze_conversion"
        return Gate(
            closed_count=count,
            net_after_costs=net,
            conversion_on_every_trade=conversion_every,
            allow_new_entries=False,
            allow_breakout=False,
            reason=reason,
        )


def _open_trade(row: sqlite3.Row) -> OpenTrade:
    half_price = row["half_price"]
    return OpenTrade(
        id=int(row["id"]),
        symbol=str(row["symbol"]),
        account=str(row["account"]),
        setup=str(row["setup"]),
        mode=str(row["mode"]),
        thesis=str(row["thesis"]),
        entry_date=date.fromisoformat(row["entry_date"]),
        entry_price=float(row["entry_price"]),
        stop=float(row["stop"]),
        initial_stop=float(row["initial_stop"]),
        target=float(row["target"]),
        shares=int(row["shares"]),
        exit_plan=str(row["exit_plan"]),
        status=str(row["status"]),
        half_sold=bool(row["half_sold"]),
        half_price=None if half_price is None else float(half_price),
        currency=str(row["currency"]),
        commissions=float(row["commissions"]),
        fx_cost=float(row["fx_cost"]),
    )
