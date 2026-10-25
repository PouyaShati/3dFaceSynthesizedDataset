"""Daily bars and earnings dates. Tests use an in-memory provider."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Protocol

from desk.models import Bar


class MarketData(Protocol):
    def bars(self, symbol: str, asof: date) -> list[Bar]:
        """Completed daily bars on or before `asof`, oldest first."""

    def earnings_status(self, symbol: str, asof: date) -> str:
        """`known` or `unknown`. Unknown symbols stay off the action list."""

    def earnings_date(self, symbol: str, asof: date) -> date | None:
        """Nearest known earnings date, or None when the date is unknown."""


class StaticMarket:
    """Fixture provider. Bars and earnings are supplied by the caller."""

    def __init__(
        self,
        series: dict[str, list[Bar]],
        earnings: dict[str, date | None] | None = None,
        known: dict[str, bool] | None = None,
    ) -> None:
        self._series = series
        self._earnings = earnings or {}
        self._known = known or {}

    def bars(self, symbol: str, asof: date) -> list[Bar]:
        return [bar for bar in self._series.get(symbol, []) if bar.day <= asof]

    def earnings_status(self, symbol: str, asof: date) -> str:
        del asof
        if symbol in self._known:
            return "known" if self._known[symbol] else "unknown"
        if symbol not in self._earnings:
            return "unknown"
        return "known" if self._earnings[symbol] is not None else "unknown"

    def earnings_date(self, symbol: str, asof: date) -> date | None:
        if self.earnings_status(symbol, asof) != "known":
            return None
        return self._earnings.get(symbol)


class YahooMarket:
    """yfinance daily history. Imported only when this provider is constructed."""

    def __init__(self) -> None:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise RuntimeError(
                "Yahoo prices need the optional yahoo extra: pip install 'desk[yahoo]'"
            ) from exc
        self._yf = yf

    def bars(self, symbol: str, asof: date) -> list[Bar]:
        history = self._yf.Ticker(symbol).history(
            start=asof - timedelta(days=420),
            end=asof + timedelta(days=1),
            interval="1d",
            auto_adjust=True,
        )
        bars: list[Bar] = []
        if history is None or history.empty:
            return bars
        for stamp, row in history.iterrows():
            day = stamp.date() if hasattr(stamp, "date") else stamp
            if isinstance(day, datetime):
                day = day.date()
            if day > asof:
                continue
            bars.append(
                Bar(
                    day=day,
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=float(row["Volume"]),
                )
            )
        bars.sort(key=lambda bar: bar.day)
        return bars

    def earnings_status(self, symbol: str, asof: date) -> str:
        return "known" if self.earnings_date(symbol, asof) is not None else "unknown"

    def earnings_date(self, symbol: str, asof: date) -> date | None:
        try:
            frame = self._yf.Ticker(symbol).get_earnings_dates(limit=12)
        except Exception:
            return None
        if frame is None or getattr(frame, "empty", True):
            return None
        dates: list[date] = []
        for stamp in frame.index:
            day = stamp.date() if hasattr(stamp, "date") else None
            if isinstance(day, datetime):
                day = day.date()
            if isinstance(day, date):
                dates.append(day)
        if not dates:
            return None
        return min(dates, key=lambda day: abs((day - asof).days))
