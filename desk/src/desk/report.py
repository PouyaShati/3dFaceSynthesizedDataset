"""Markdown plans. One file is the only action list for that session."""

from __future__ import annotations

from datetime import date

from desk.config import DeskConfig
from desk.exits import ExitAction
from desk.harvest import HarvestRow
from desk.journal import Gate
from desk.picker import Order, Skip
from desk.universe import SearchRow


def _money(value: float) -> str:
    return f"{value:.2f}"


def _px(value: float) -> str:
    return f"{value:.4f}"


def render_daily(
    *,
    session: date,
    config: DeskConfig,
    gate: Gate,
    actions: list[ExitAction],
    orders: list[Order],
    skips: list[Skip],
    open_count: int,
    cancelled: list[str],
    search_summary: str = "",
) -> str:
    lines = [
        f"# Daily plan {session.isoformat()}",
        "",
        f"Account: {config.account_type} {config.currency}",
        f"Equity: {_money(config.equity)}",
        f"Open positions: {open_count} / {config.max_positions}",
        (
            f"Journal: {gate.closed_count} closed, net after costs {_money(gate.net_after_costs)}, "
            f"gate {gate.reason}."
        ),
    ]
    if search_summary:
        lines.append(search_summary)
    lines.append("")
    if config.account_type == "tfsa":
        lines.extend(
            [
                "TFSA warning: this short-term book is pointed at a TFSA. "
                "Frequent short-term trading there can be treated as business activity. "
                "The non-registered account is the book these rules were written for.",
                "",
            ]
        )
    if gate.reason.startswith("freeze"):
        lines.extend(
            [
                "New entries are frozen. Keep managing open positions. "
                "The journal is not positive after commissions, or the currency conversion "
                "was charged on every closed trade.",
                "",
            ]
        )
    lines.append("## Manage open positions")
    if not actions:
        lines.append("- No stop or target change on open positions.")
    else:
        for action in actions:
            lines.append(f"- {action.symbol}: {action.detail}")
    if cancelled:
        lines.append("")
        lines.append("## Cancelled from the prior plan")
        for item in cancelled:
            lines.append(f"- {item}")
    lines.extend(["", "## New orders for the next session"])
    if not orders:
        lines.append("- No new order.")
    else:
        for index, order in enumerate(orders, start=1):
            signal = order.signal
            partial = (
                f" Sell half near {_px(signal.partial_price)} (2 percent), then trail."
                if signal.partial_price is not None
                else f" Exit at {_px(signal.target)} (3 percent)."
            )
            conversion = " Conversion is required." if order.convert else " No currency conversion."
            lines.append(
                f"{index}. {signal.symbol} buy {order.shares} at {_px(signal.entry)} "
                f"stop {_px(signal.stop)} ({signal.stop_pct * 100:.2f} percent). "
                f"Risk {_money(order.dollar_risk)} ({order.dollar_risk / config.equity * 100:.2f} percent of equity)."
                f"{partial}{conversion}"
            )
            lines.append(f"   Thesis: {signal.thesis}")
    lines.extend(["", "## Skipped"])
    if not skips:
        lines.append("- Nothing skipped.")
    else:
        for skip in skips:
            lines.append(f"- {skip.symbol}: {skip.reason}. {skip.detail}")
    lines.extend(
        [
            "",
            "## Do not",
            "- Do not invent a second list later in the session. The morning review reprints this file.",
            "- Add nothing to a loser. Move a stop only in your favor.",
            "- Leave capital that is not in these positions in cash or the long-term ETFs.",
            "",
        ]
    )
    return "\n".join(lines)


_STAGE_TITLES = {
    "in_trend": "In trend, handed to the pullback test",
    "no_trend": "Liquid, but not above a rising 50-day average",
    "atr_low": "Too quiet for a 2 percent target",
    "atr_high": "Too wide for a 1 percent stop",
    "illiquid": "Dollar volume cannot hold the position",
    "price": "Price too low for a 1 percent stop",
    "short_history": "Not enough daily history",
    "no_bars": "No prices",
    "data_error": "Price download failed",
    "excluded": "Not a common listing",
}


def render_universe(*, session: date, config: DeskConfig, rows: list[SearchRow]) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.stage] = counts.get(row.stage, 0) + 1
    usd = "included because usd_cash is above zero" if config.usd_cash > 0 else "excluded until usd_cash is above zero"
    lines = [
        f"# Universe search {session.isoformat()}",
        "",
        "This search keeps names that can express a 1 percent stop and a 2 to 3 percent target.",
        f"Price at least {config.min_price:.2f}. 14-day ATR between {config.min_atr_pct * 100:.2f} and {config.max_atr_pct * 100:.2f} percent of price.",
        (
            f"Average dollar volume at least {_money(config.min_avg_dollar_volume)}, and large enough "
            f"that a position sized from a 1 percent stop is at most {config.max_participation * 100:.1f} percent of a typical day."
        ),
        "Direction is the strategy rule: close above a rising 50-day average.",
        f"CAD names come from the Toronto large-cap file. USD names are {usd}.",
        "",
        f"Scanned: {len(rows)}",
        f"In trend: {counts.get('in_trend', 0)}",
        "",
    ]
    for stage, title in _STAGE_TITLES.items():
        group = [row for row in rows if row.stage == stage]
        if not group:
            continue
        lines.append(f"## {title}")
        for row in group:
            label = f"{row.symbol} {row.name}".strip()
            lines.append(f"- {label} ({row.currency}): {row.detail}")
        lines.append("")
    if not rows:
        lines.append("Search is off. The daily plan uses the watchlist only.")
        lines.append("")
    return "\n".join(lines)


def render_weekly(
    *,
    week_key: str,
    gate: Gate,
    open_count: int,
    closed_r: list[float],
    fx_charged: int,
) -> str:
    wins = sum(1 for value in closed_r if value > 0)
    average_r = sum(closed_r) / len(closed_r) if closed_r else 0.0
    lines = [
        f"# Weekly scorecard {week_key}",
        "",
        f"Open positions: {open_count}",
        f"Closed trades: {gate.closed_count}",
        f"Net after commissions and conversion: {_money(gate.net_after_costs)}",
        f"Winning closes: {wins}",
        f"Average R on closed trades: {average_r:.2f}",
        f"Conversion charged on {fx_charged} of {gate.closed_count} closed trades.",
        f"Gate: {gate.reason}.",
        "",
    ]
    if gate.reason == "pass":
        lines.append(
            "Results are positive after costs and conversion was not paid on every trade. "
            "The breakout setup stays off until you set enable_breakout to true."
        )
    elif gate.reason == "collecting":
        lines.append(
            f"Keep collecting until {gate.closed_count} reaches the journal minimum. "
            "One setup only."
        )
    else:
        lines.append("Do not take new entries. The gate is closed.")
    lines.append("")
    return "\n".join(lines)


def render_harvest(*, session: date, rows: list[HarvestRow], account_type: str) -> str:
    lines = [
        f"# Tax-lot harvest {session.isoformat()}",
        "",
        "Checklist only. Confirm the superficial-loss rule and identical property with a tax professional.",
        "TFSA losses are not harvest candidates. Short-term open trades are not harvest candidates.",
        "",
    ]
    if account_type == "tfsa":
        lines.extend(
            [
                "The short-term book is a TFSA. This report still reviews the lots file, "
                "and it still excludes TFSA lots.",
                "",
            ]
        )
    if not rows:
        lines.append("No excluded lots and no loss large enough to list.")
        lines.append("")
        return "\n".join(lines)
    for row in rows:
        rebuy = row.earliest_rebuy.isoformat() if row.earliest_rebuy else "n/a"
        lines.append(
            f"- {row.symbol} ({row.account}) {row.status}: "
            f"shares {row.shares:g}, ACB {_px(row.acb)}, price {_px(row.price)}, "
            f"loss {_money(row.loss)}, earliest repurchase {rebuy}, replacement [{row.replacement}]"
        )
        lines.append(f"  {row.reason}")
    lines.append("")
    return "\n".join(lines)
