"""Session calendar. Weekends are closed. Holidays are not modeled."""

from __future__ import annotations

from datetime import date, timedelta


class MarketClosed(Exception):
    def __init__(self, session: date):
        self.session = session
        super().__init__(f"Market is closed on {session.isoformat()}")


def is_trading_day(session: date) -> bool:
    return session.weekday() < 5


def require_trading_day(session: date) -> None:
    if not is_trading_day(session):
        raise MarketClosed(session)


def trading_days_apart(start: date, end: date) -> int:
    """Signed count of trading days from start to end. Same day is 0."""
    if start == end:
        return 0
    step = 1 if end > start else -1
    cursor = start
    count = 0
    while cursor != end:
        cursor += timedelta(days=step)
        if is_trading_day(cursor):
            count += 1
    return count if end > start else -count


def in_earnings_blackout(session: date, earnings: date, days: int) -> bool:
    return abs(trading_days_apart(session, earnings)) <= days


def add_calendar_days(session: date, days: int) -> date:
    return session + timedelta(days=days)


def previous_trading_day(session: date) -> date:
    cursor = session
    while True:
        cursor -= timedelta(days=1)
        if is_trading_day(cursor):
            return cursor
