"""Tax-lot checklist for the non-registered book. This is not tax advice."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from desk.config import DeskConfig
from desk.costs import conversion_cost, needs_conversion, round_trip_commission


@dataclass(frozen=True)
class Lot:
    symbol: str
    account: str
    acquired: date
    shares: float
    acb: float
    currency: str


@dataclass(frozen=True)
class HarvestRow:
    symbol: str
    account: str
    status: str
    shares: float
    acb: float
    price: float
    loss: float
    earliest_rebuy: date | None
    reason: str
    replacement: str = ""


def load_lots(path: Path) -> list[Lot]:
    if not path.is_file():
        raise FileNotFoundError(f"Lots file not found: {path}")
    lots: list[Lot] = []
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"symbol", "account", "acquired", "shares", "acb", "currency"}
        if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
            raise ValueError("lots CSV needs symbol, account, acquired, shares, acb, currency")
        for row in reader:
            lots.append(
                Lot(
                    symbol=str(row["symbol"]).strip(),
                    account=str(row["account"]).strip(),
                    acquired=date.fromisoformat(str(row["acquired"]).strip()),
                    shares=float(row["shares"]),
                    acb=float(row["acb"]),
                    currency=str(row["currency"]).strip().upper(),
                )
            )
    return lots


def _in_window_buys(
    symbol: str,
    asof: date,
    lots: list[Lot],
    journal_buys: list[tuple[str, date, str]],
    selling: Lot,
) -> list[str]:
    start = asof - timedelta(days=30)
    notes: list[str] = []
    for lot in lots:
        if lot.symbol != symbol:
            continue
        if lot is selling:
            continue
        if start <= lot.acquired <= asof:
            notes.append(
                f"{lot.account} lot of {lot.symbol} acquired {lot.acquired.isoformat()}"
            )
    for bought_symbol, bought_on, account in journal_buys:
        if bought_symbol != symbol:
            continue
        if start <= bought_on <= asof:
            notes.append(f"journal buy in {account} on {bought_on.isoformat()}")
    return notes


def evaluate_harvest(
    lots: list[Lot],
    prices: dict[str, float],
    open_symbols: set[str],
    journal_buys: list[tuple[str, date, str]],
    asof: date,
    config: DeskConfig,
) -> list[HarvestRow]:
    rows: list[HarvestRow] = []
    for lot in lots:
        if lot.account != "non_registered":
            reason = (
                "A loss in a TFSA is not deductible, so this lot is not a harvest candidate."
                if lot.account == "tfsa"
                else "Only the non-registered account can harvest a capital loss."
            )
            rows.append(
                HarvestRow(
                    symbol=lot.symbol,
                    account=lot.account,
                    status="excluded",
                    shares=lot.shares,
                    acb=lot.acb,
                    price=prices.get(lot.symbol, 0.0),
                    loss=0.0,
                    earliest_rebuy=None,
                    reason=reason,
                )
            )
            continue
        if lot.symbol in open_symbols:
            rows.append(
                HarvestRow(
                    symbol=lot.symbol,
                    account=lot.account,
                    status="excluded",
                    shares=lot.shares,
                    acb=lot.acb,
                    price=prices.get(lot.symbol, lot.acb),
                    loss=0.0,
                    earliest_rebuy=None,
                    reason="This symbol is an open short-term trade. Leave it out of the harvest list.",
                )
            )
            continue
        if lot.symbol not in prices:
            rows.append(
                HarvestRow(
                    symbol=lot.symbol,
                    account=lot.account,
                    status="excluded",
                    shares=lot.shares,
                    acb=lot.acb,
                    price=0.0,
                    loss=0.0,
                    earliest_rebuy=None,
                    reason="No price for this symbol.",
                )
            )
            continue
        price = prices[lot.symbol]
        loss = (lot.acb - price) * lot.shares
        if loss <= 0:
            continue
        convert = needs_conversion(lot.currency, config.currency)
        friction = round_trip_commission(config) + conversion_cost(price * lot.shares, config, convert)
        if loss <= friction + config.min_harvest_loss:
            rows.append(
                HarvestRow(
                    symbol=lot.symbol,
                    account=lot.account,
                    status="excluded",
                    shares=lot.shares,
                    acb=lot.acb,
                    price=price,
                    loss=loss,
                    earliest_rebuy=None,
                    reason="The unrealized loss does not clear commissions, conversion, and the dollar floor.",
                )
            )
            continue
        window_buys = _in_window_buys(lot.symbol, asof, lots, journal_buys, lot)
        earliest = asof + timedelta(days=30)
        own_recent = asof - timedelta(days=30) <= lot.acquired <= asof
        if window_buys:
            status = "blocked"
            reason = (
                "A buy of the same symbol in the 30 days before this sale may deny the loss "
                "if any identical shares are still held 30 days later: "
                + "; ".join(window_buys)
                + ". Also check a spouse, TFSA, and RRSP, which this file cannot see. "
                "Leave the replacement ticker blank until you confirm it is not identical property."
            )
        else:
            status = "candidate"
            reason = (
                "No acquisition of this symbol in the prior 30 days is on file. "
                "The loss still fails if you, a spouse, a TFSA, or an RRSP buy the same "
                f"property before {earliest.isoformat()} and still hold it on that date. "
                "Write a replacement only after you confirm it is not identical property."
            )
            if own_recent:
                reason = (
                    "This lot itself was acquired inside the prior 30 days. "
                    "Selling all of it avoids the rule only if no identical shares remain "
                    f"and nothing is bought again before {earliest.isoformat()}. "
                    "Check spouse, TFSA, and RRSP accounts."
                )
        rows.append(
            HarvestRow(
                symbol=lot.symbol,
                account=lot.account,
                status=status,
                shares=lot.shares,
                acb=lot.acb,
                price=price,
                loss=loss,
                earliest_rebuy=earliest,
                reason=reason,
                replacement="",
            )
        )
    return rows
