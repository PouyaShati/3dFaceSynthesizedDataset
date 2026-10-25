"""Shared records for bars, setups, and open trades."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Bar:
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class SetupSignal:
    symbol: str
    setup: str
    entry: float
    stop: float
    target: float
    partial_price: float | None
    exit_plan: str
    stop_pct: float
    risk_per_share: float
    thesis: str
    sma_slope: float


@dataclass(frozen=True)
class SetupRejection:
    symbol: str
    setup: str
    reason: str


@dataclass(frozen=True)
class SymbolSpec:
    symbol: str
    currency: str
    name: str = ""


@dataclass
class OpenTrade:
    id: int
    symbol: str
    account: str
    setup: str
    mode: str
    thesis: str
    entry_date: date
    entry_price: float
    stop: float
    initial_stop: float
    target: float
    shares: int
    exit_plan: str
    status: str
    half_sold: bool
    half_price: float | None
    currency: str
    commissions: float
    fx_cost: float

    @property
    def risk_per_share(self) -> float:
        return self.entry_price - self.initial_stop
