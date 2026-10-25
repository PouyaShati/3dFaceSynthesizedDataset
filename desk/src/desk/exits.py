"""Exit instructions for an open long. The desk does not send orders."""

from __future__ import annotations

from dataclasses import dataclass

from desk.models import Bar, OpenTrade
from desk.risk import stop_in_favor


@dataclass(frozen=True)
class ExitAction:
    symbol: str
    kind: str
    price: float
    new_stop: float | None
    detail: str


def propose_actions(trade: OpenTrade, bars: list[Bar], stop_buffer_pct: float) -> list[ExitAction]:
    """What to do with an open position after the latest completed daily bar.

    A bar that trades through the stop is a stop-out, including when that same
    bar also trades through a profit target. The trail moves only after half
    the position has been sold, and only upward.
    """
    if not bars:
        return []
    today = bars[-1]
    if today.low <= trade.stop + 1e-12:
        return [
            ExitAction(
                symbol=trade.symbol,
                kind="stop_out",
                price=trade.stop,
                new_stop=None,
                detail=(
                    f"Low {today.low:.4f} reached the stop {trade.stop:.4f}. "
                    "Exit the position. Do not add."
                ),
            )
        ]

    actions: list[ExitAction] = []
    if trade.exit_plan == "fixed3":
        target = trade.entry_price * 1.03
        two_r = trade.entry_price + 2 * trade.risk_per_share
        if target + 1e-9 >= two_r and today.high >= target - 1e-12:
            actions.append(
                ExitAction(
                    symbol=trade.symbol,
                    kind="target_exit",
                    price=target,
                    new_stop=None,
                    detail=f"High reached the 3 percent target {target:.4f}. Exit the position.",
                )
            )
        return actions

    partial = trade.entry_price * 1.02
    if not trade.half_sold and today.high >= partial - 1e-12:
        actions.append(
            ExitAction(
                symbol=trade.symbol,
                kind="sell_half",
                price=partial,
                new_stop=None,
                detail=(
                    f"High reached the 2 percent scale price {partial:.4f}. "
                    "Sell half. Leave the stop where it is until that sale is recorded."
                ),
            )
        )

    if trade.half_sold:
        recent = bars[-3:]
        recent_low = min(bar.low for bar in recent)
        proposed = recent_low * (1 - stop_buffer_pct)
        if proposed < today.close and stop_in_favor(trade.stop, proposed) is not None:
            actions.append(
                ExitAction(
                    symbol=trade.symbol,
                    kind="raise_stop",
                    price=proposed,
                    new_stop=proposed,
                    detail=(
                        f"Trail the stop from {trade.stop:.4f} to {proposed:.4f}, "
                        "under the recent daily low. The stop only moves up."
                    ),
                )
            )
    return actions
