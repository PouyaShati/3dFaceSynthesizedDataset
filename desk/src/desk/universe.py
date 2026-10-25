"""Search the liquid universe that can actually pay a 1 percent stop and a 2-3 percent target."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from desk.config import DeskConfig
from desk.data import MarketData
from desk.indicators import trend_state
from desk.models import Bar, SymbolSpec

_BLOCKED_TOKENS = ("-WT", "-PR", "-RT", "-DB", ".WT", ".PR", ".RT")


class UniverseError(FileNotFoundError):
    pass


@dataclass(frozen=True)
class SearchRow:
    symbol: str
    name: str
    currency: str
    stage: str
    detail: str
    close: float | None = None
    atr_pct: float | None = None
    dollar_volume: float | None = None


@dataclass(frozen=True)
class SearchResult:
    rows: list[SearchRow]
    tradable: list[SymbolSpec]
    summary: str


def is_common_listing(symbol: str) -> bool:
    """Warrants, preferreds, rights, and debentures do not belong in this book."""
    root = symbol.upper()
    if root.endswith(".TO"):
        root = root[:-3]
    return not any(token in root for token in _BLOCKED_TOKENS)


def load_symbol_file(path: Path, currency: str) -> list[SymbolSpec]:
    if not path.is_file():
        raise UniverseError(f"Universe file not found: {path}")
    specs: list[SymbolSpec] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        symbol, _, name = text.partition(" ")
        specs.append(SymbolSpec(symbol.strip(), currency.upper(), name.strip()))
    return specs


def listed_symbols(config: DeskConfig) -> dict[str, SymbolSpec]:
    """Symbols the journal is allowed to record: the search files plus any pins."""
    specs: dict[str, SymbolSpec] = {}
    for spec in candidate_specs(config):
        specs[spec.symbol] = spec
    return specs


def candidate_specs(config: DeskConfig) -> list[SymbolSpec]:
    """Names to search. With search off, this is only the hand-written watchlist."""
    if not config.search_enabled:
        return list(config.watchlist)
    specs: list[SymbolSpec] = []
    seen: set[str] = set()
    for spec in load_symbol_file(config.cad_universe, "CAD"):
        if spec.symbol not in seen:
            specs.append(spec)
            seen.add(spec.symbol)
    if config.usd_cash > 0:
        for spec in load_symbol_file(config.usd_universe, "USD"):
            if spec.symbol not in seen:
                specs.append(spec)
                seen.add(spec.symbol)
    for pin in config.watchlist:
        if pin.symbol not in seen:
            specs.append(pin)
            seen.add(pin.symbol)
    return specs


def average_dollar_volume(bars: list[Bar], window: int) -> float | None:
    if window <= 0 or len(bars) < window:
        return None
    sample = bars[-window:]
    return sum(bar.close * bar.volume for bar in sample) / window


def atr_percent(bars: list[Bar], window: int) -> float | None:
    """Average true range over `window` sessions, divided by the latest close."""
    if window <= 0 or len(bars) < window + 1 or bars[-1].close <= 0:
        return None
    ranges: list[float] = []
    for index in range(1, len(bars)):
        bar = bars[index]
        previous_close = bars[index - 1].close
        true_range = max(
            bar.high - bar.low,
            abs(bar.high - previous_close),
            abs(bar.low - previous_close),
        )
        ranges.append(true_range)
    recent = ranges[-window:]
    if len(recent) < window:
        return None
    return (sum(recent) / window) / bars[-1].close


def classify(spec: SymbolSpec, bars: list[Bar], config: DeskConfig) -> SearchRow:
    """Structural gates that decide whether a name can express this strategy."""
    needed = max(
        config.sma_slow + config.sma_rise_lookback,
        config.dollar_volume_window,
        config.atr_window + 1,
    )
    if len(bars) < needed:
        return SearchRow(
            spec.symbol,
            spec.name,
            spec.currency,
            "short_history",
            f"Needs {needed} daily bars and has {len(bars)}.",
        )

    close = bars[-1].close
    if close < config.min_price:
        return SearchRow(
            spec.symbol,
            spec.name,
            spec.currency,
            "price",
            f"Close {close:.2f} is below the {config.min_price:.2f} minimum. A 1 percent stop would sit inside a wide spread.",
            close=close,
        )

    dollar_volume = average_dollar_volume(bars, config.dollar_volume_window)
    rate = config.fx_rates.get(spec.currency.upper(), 1.0)
    dollar_volume_account = 0.0 if dollar_volume is None else dollar_volume * rate
    notional = config.equity * config.risk_fraction / 0.01
    participation_floor = notional / config.max_participation
    volume_floor = max(config.min_avg_dollar_volume, participation_floor)
    if dollar_volume is None or dollar_volume_account < volume_floor:
        return SearchRow(
            spec.symbol,
            spec.name,
            spec.currency,
            "illiquid",
            (
                f"Average dollar volume {dollar_volume_account:,.0f} is below {volume_floor:,.0f}. "
                "A 1 percent stop on this account would be more than "
                f"{config.max_participation * 100:.1f} percent of a typical day, "
                "or the name is below the dollar-volume floor."
            ),
            close=close,
            dollar_volume=dollar_volume_account,
        )

    atr = atr_percent(bars, config.atr_window)
    if atr is None:
        return SearchRow(
            spec.symbol,
            spec.name,
            spec.currency,
            "short_history",
            "Not enough bars to measure the average true range.",
            close=close,
            dollar_volume=dollar_volume_account,
        )
    if atr < config.min_atr_pct:
        return SearchRow(
            spec.symbol,
            spec.name,
            spec.currency,
            "atr_low",
            (
                f"14-day ATR is {atr * 100:.2f} percent of price. "
                "A 2 percent target is too large a move for this quiet name."
            ),
            close=close,
            atr_pct=atr,
            dollar_volume=dollar_volume_account,
        )
    if atr > config.max_atr_pct:
        return SearchRow(
            spec.symbol,
            spec.name,
            spec.currency,
            "atr_high",
            (
                f"14-day ATR is {atr * 100:.2f} percent of price. "
                "A stop just beyond a pullback low would be wider than the 1.5 percent band."
            ),
            close=close,
            atr_pct=atr,
            dollar_volume=dollar_volume_account,
        )

    closes = [bar.close for bar in bars]
    trending, reason, _slope = trend_state(closes, config.sma_slow, config.sma_rise_lookback)
    if not trending:
        return SearchRow(
            spec.symbol,
            spec.name,
            spec.currency,
            "no_trend",
            f"Daily trend failed: {reason}.",
            close=close,
            atr_pct=atr,
            dollar_volume=dollar_volume_account,
        )
    return SearchRow(
        spec.symbol,
        spec.name,
        spec.currency,
        "in_trend",
        (
            f"Close {close:.2f}, ATR {atr * 100:.2f} percent, "
            f"average dollar volume {dollar_volume_account:,.0f}. "
            "Above a rising 50-day average. Waiting for the pullback test."
        ),
        close=close,
        atr_pct=atr,
        dollar_volume=dollar_volume_account,
    )


def search_market(config: DeskConfig, market: MarketData, asof: date) -> SearchResult:
    specs = candidate_specs(config)
    if not config.search_enabled:
        return SearchResult(rows=[], tradable=specs, summary="")

    rows: list[SearchRow] = []
    tradable: list[SymbolSpec] = []
    for spec in specs:
        if not is_common_listing(spec.symbol):
            rows.append(
                SearchRow(
                    spec.symbol,
                    spec.name,
                    spec.currency,
                    "excluded",
                    "Warrants, preferreds, rights, and debentures are outside this strategy.",
                )
            )
            continue
        try:
            bars = market.bars(spec.symbol, asof)
        except Exception as exc:
            rows.append(
                SearchRow(spec.symbol, spec.name, spec.currency, "data_error", str(exc))
            )
            continue
        if not bars:
            rows.append(
                SearchRow(
                    spec.symbol,
                    spec.name,
                    spec.currency,
                    "no_bars",
                    "No daily bars on or before the session.",
                )
            )
            continue
        row = classify(spec, bars, config)
        rows.append(row)
        if row.stage == "in_trend":
            tradable.append(spec)
    return SearchResult(rows=rows, tradable=tradable, summary=_summary(rows))


def _summary(rows: list[SearchRow]) -> str:
    scanned = len(rows)
    in_trend = sum(1 for row in rows if row.stage == "in_trend")
    return (
        f"Search: {scanned} names scanned, {in_trend} above a rising 50-day average "
        "and liquid enough for a 1 percent stop. The pullback test runs on that group only."
    )
