"""Adjusted-close download and a cached price panel.

The cached file stores the raw ticker closes. Cash is added later so a missing
cash fund does not wipe the equity history.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.universe import CASH_COLUMN, Universe


def _close_field(raw: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    """Return a ticker-column frame of adjusted closes."""
    field_names = ("Close", "Adj Close")
    if not isinstance(raw.columns, pd.MultiIndex):
        for name in field_names:
            if name in raw.columns:
                if len(tickers) != 1:
                    raise ValueError("A flat download frame must contain one ticker")
                return raw[[name]].rename(columns={name: tickers[0]})
        raise ValueError(f"Unexpected price columns: {list(raw.columns)}")
    level_sets = [set(raw.columns.get_level_values(i)) for i in range(raw.columns.nlevels)]
    for name in field_names:
        if name in level_sets[0]:
            return raw[name].copy()
        if len(level_sets) > 1 and name in level_sets[1]:
            return raw.xs(name, axis=1, level=1).copy()
    raise ValueError(f"No Close field in columns {raw.columns!r}")


def extract_adjusted_close(raw: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    """Pull the adjusted Close field out of a yfinance download frame."""
    if raw is None or raw.empty:
        raise ValueError("Price download was empty")
    close = _close_field(raw, tickers)
    missing = [ticker for ticker in tickers if ticker not in list(close.columns)]
    if missing:
        raise ValueError(f"Download did not include {missing}")
    close = close.loc[:, list(tickers)].apply(pd.to_numeric, errors="coerce")
    index = pd.to_datetime(close.index)
    if getattr(index, "tz", None) is not None:
        index = index.tz_convert(None)
    close.index = pd.DatetimeIndex(index).normalize()
    close = close.sort_index()
    close = close[~close.index.duplicated(keep="last")]
    close.index.name = "date"
    return close


def download_adjusted_closes(tickers: list[str], start: str) -> pd.DataFrame:
    import yfinance as yf

    try:
        raw = yf.download(
            tickers,
            start=start,
            auto_adjust=True,
            progress=False,
            threads=False,
            group_by="column",
        )
    except Exception as exc:
        raise RuntimeError(f"Price download failed for {tickers}: {exc}") from exc
    return extract_adjusted_close(raw, tickers)


def load_prices(
    universe: Universe,
    cache_dir: Path,
    refresh: bool = False,
    start: str = "2004-01-01",
) -> pd.DataFrame:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{universe.name}.csv"
    needed = list(universe.download_tickers())
    if path.exists() and not refresh:
        cached = pd.read_csv(path, index_col=0, parse_dates=True)
        if all(ticker in cached.columns for ticker in needed):
            frame = cached.loc[:, needed].sort_index()
            frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index)).normalize()
            return frame
    frame = download_adjusted_closes(needed, start=start)
    frame.to_csv(path)
    return frame


def _cash_level(cash_px: pd.Series) -> pd.Series:
    """Growth of 1 from a cash fund. Days without a prior price earn zero."""
    returns = cash_px.pct_change()
    valid = cash_px.notna() & cash_px.shift(1).notna()
    returns = returns.where(valid, 0.0).fillna(0.0)
    return (1.0 + returns).cumprod()


def prepare_prices(prices: pd.DataFrame, universe: Universe) -> pd.DataFrame:
    """Equity columns plus a CASH level, on sessions where every equity printed."""
    missing = [ticker for ticker in universe.equities if ticker not in prices.columns]
    if missing:
        raise ValueError(f"Price panel is missing {missing}")
    equities = prices.loc[:, list(universe.equities)].copy()
    equities.index = pd.DatetimeIndex(pd.to_datetime(equities.index))
    if getattr(equities.index, "tz", None) is not None:
        equities.index = equities.index.tz_convert(None)
    equities.index = equities.index.normalize()
    equities = equities.sort_index()
    equities = equities[~equities.index.duplicated(keep="last")]
    equities = equities.dropna(how="any")
    if equities.empty:
        raise ValueError("No sessions where every equity ETF has a price")
    out = equities.copy()
    if universe.cash and universe.cash in prices.columns:
        cash_px = prices[universe.cash].copy()
        cash_px.index = pd.DatetimeIndex(pd.to_datetime(cash_px.index)).normalize()
        cash_px = cash_px.sort_index()
        cash_px = cash_px[~cash_px.index.duplicated(keep="last")]
        out[CASH_COLUMN] = _cash_level(cash_px.reindex(out.index))
    else:
        out[CASH_COLUMN] = 1.0
    return out
