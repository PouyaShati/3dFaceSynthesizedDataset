"""Load and validate the desk configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from desk.models import SymbolSpec


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class DeskConfig:
    timezone: str
    account_type: str
    currency: str
    equity: float
    deployable_cash: float
    max_positions: int
    risk_fraction: float
    commission_per_trade: float
    usd_conversion_fee: float
    fx_spread_bps: float
    cost_skip_fraction_of_target: float
    fx_rates: dict[str, float]
    min_stop_pct: float
    max_stop_pct: float
    stop_buffer_pct: float
    exit_plan: str
    sma_fast: int
    sma_slow: int
    sma_rise_lookback: int
    pullback_lookback: int
    touch_tolerance_pct: float
    touch_max_pierce_pct: float
    earnings_blackout_days: int
    journal_min_trades: int
    active_setup: str
    enable_breakout: bool
    breakout_range_days: int
    breakout_max_width_pct: float
    breakout_volume_multiple: float
    min_harvest_loss: float
    watchlist: tuple[SymbolSpec, ...]
    search_enabled: bool
    cad_universe: Path
    usd_universe: Path
    usd_cash: float
    min_price: float
    min_avg_dollar_volume: float
    max_participation: float
    atr_window: int
    min_atr_pct: float
    max_atr_pct: float
    dollar_volume_window: int
    db_path: Path
    out_dir: Path
    lots_path: Path
    source_path: Path


def _resolve_universe(root: Path, value: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = (root / value).resolve()
    if candidate.is_file():
        return candidate
    packaged = Path(__file__).resolve().parents[2] / value
    return packaged if packaged.is_file() else candidate


def load_config(path: str | Path) -> DeskConfig:
    source = Path(path).resolve()
    if not source.is_file():
        raise ConfigError(f"Config not found: {source}")
    raw = yaml.safe_load(source.read_text()) or {}
    if not isinstance(raw, dict):
        raise ConfigError("Config root must be a mapping")

    book = raw.get("short_term") or {}
    paths = raw.get("paths") or {}
    root = source.parent

    account_type = str(book.get("account_type", "non_registered"))
    if account_type not in {"non_registered", "tfsa"}:
        raise ConfigError("short_term.account_type must be non_registered or tfsa")

    max_positions = int(book.get("max_positions", 5))
    if max_positions not in {4, 5, 6}:
        raise ConfigError("short_term.max_positions must be 4, 5, or 6")

    risk_fraction = float(book.get("risk_fraction", 0.005))
    if abs(risk_fraction - 0.005) > 1e-12:
        raise ConfigError("short_term.risk_fraction must be 0.005")

    exit_plan = str(raw.get("exit_plan", "scale"))
    if exit_plan not in {"scale", "fixed3"}:
        raise ConfigError("exit_plan must be scale or fixed3")

    active_setup = str(raw.get("active_setup", "pullback"))
    if active_setup != "pullback":
        raise ConfigError("active_setup must stay pullback until you enable the breakout separately")

    equity = float(book.get("equity", 0))
    deployable = float(book.get("deployable_cash", 0))
    if equity <= 0:
        raise ConfigError("short_term.equity must be positive")
    if deployable < 0:
        raise ConfigError("short_term.deployable_cash cannot be negative")

    rates = {str(k).upper(): float(v) for k, v in (raw.get("fx_rates") or {}).items()}
    currency = str(book.get("currency", "CAD")).upper()
    rates.setdefault(currency, 1.0)

    watchlist: list[SymbolSpec] = []
    for item in raw.get("watchlist") or []:
        if not isinstance(item, dict) or "symbol" not in item:
            raise ConfigError("each watchlist entry needs a symbol")
        watchlist.append(
            SymbolSpec(
                symbol=str(item["symbol"]),
                currency=str(item.get("currency", currency)).upper(),
                name=str(item.get("name", "")),
            )
        )

    db_path = (root / str(paths.get("db", "data/desk.sqlite"))).resolve()
    out_dir = (root / str(paths.get("out", "out"))).resolve()
    lots_path = (root / str(paths.get("lots", "lots.example.csv"))).resolve()

    search = raw.get("search") or {}
    if not isinstance(search, dict):
        raise ConfigError("search must be a mapping")
    max_participation = float(search.get("max_participation", 0.01))
    if not 0 < max_participation <= 1:
        raise ConfigError("search.max_participation must be between 0 and 1")
    min_atr_pct = float(search.get("min_atr_pct", 0.008))
    max_atr_pct = float(search.get("max_atr_pct", 0.04))
    if min_atr_pct >= max_atr_pct:
        raise ConfigError("search.min_atr_pct must be below search.max_atr_pct")
    min_price = float(search.get("min_price", 10))
    if min_price < 0:
        raise ConfigError("search.min_price cannot be negative")

    return DeskConfig(
        timezone=str(raw.get("timezone", "America/Toronto")),
        account_type=account_type,
        currency=currency,
        equity=equity,
        deployable_cash=deployable,
        max_positions=max_positions,
        risk_fraction=risk_fraction,
        commission_per_trade=float(raw.get("commission_per_trade", 0.0)),
        usd_conversion_fee=float(raw.get("usd_conversion_fee", 2.0)),
        fx_spread_bps=float(raw.get("fx_spread_bps", 0.0)),
        cost_skip_fraction_of_target=float(raw.get("cost_skip_fraction_of_target", 0.30)),
        fx_rates=rates,
        min_stop_pct=float(raw.get("min_stop_pct", 0.0075)),
        max_stop_pct=float(raw.get("max_stop_pct", 0.015)),
        stop_buffer_pct=float(raw.get("stop_buffer_pct", 0.001)),
        exit_plan=exit_plan,
        sma_fast=int(raw.get("sma_fast", 20)),
        sma_slow=int(raw.get("sma_slow", 50)),
        sma_rise_lookback=int(raw.get("sma_rise_lookback", 10)),
        pullback_lookback=int(raw.get("pullback_lookback", 8)),
        touch_tolerance_pct=float(raw.get("touch_tolerance_pct", 0.005)),
        touch_max_pierce_pct=float(raw.get("touch_max_pierce_pct", 0.02)),
        earnings_blackout_days=int(raw.get("earnings_blackout_days", 5)),
        journal_min_trades=int(raw.get("journal_min_trades", 30)),
        active_setup=active_setup,
        enable_breakout=bool(raw.get("enable_breakout", False)),
        breakout_range_days=int(raw.get("breakout_range_days", 7)),
        breakout_max_width_pct=float(raw.get("breakout_max_width_pct", 0.03)),
        breakout_volume_multiple=float(raw.get("breakout_volume_multiple", 1.5)),
        min_harvest_loss=float(raw.get("min_harvest_loss", 50)),
        watchlist=tuple(watchlist),
        search_enabled=bool(search.get("enabled", False)),
        cad_universe=_resolve_universe(root, str(search.get("cad_universe", "universes/tsx60.txt"))),
        usd_universe=_resolve_universe(root, str(search.get("usd_universe", "universes/us_large.txt"))),
        usd_cash=float(search.get("usd_cash", 0)),
        min_price=min_price,
        min_avg_dollar_volume=float(search.get("min_avg_dollar_volume", 5_000_000)),
        max_participation=max_participation,
        atr_window=int(search.get("atr_window", 14)),
        min_atr_pct=min_atr_pct,
        max_atr_pct=max_atr_pct,
        dollar_volume_window=int(search.get("dollar_volume_window", 20)),
        db_path=db_path,
        out_dir=out_dir,
        lots_path=lots_path,
        source_path=source,
    )
