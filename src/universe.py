"""ETF universes for the monthly dual-momentum rule.

US-listed funds are the default because they trade on one calendar in one
currency. The UCITS preset is only for brokers that block US ETFs. Canada is
left out of that preset on purpose: pick the listing from your own broker
rather than using an unverified ticker.
"""

from __future__ import annotations

from dataclasses import dataclass


# Internal weight column for "not in an equity ETF".
# When `Universe.cash` is set, this column is a traded fund (for example SGOV).
# When it is None, the column earns zero and is not charged a trading fee.
CASH_COLUMN = "CASH"


@dataclass(frozen=True)
class Universe:
    name: str
    equities: tuple[str, ...]
    roles: tuple[str, ...]
    cash: str | None
    note: str

    def __post_init__(self) -> None:
        if len(self.equities) < 2:
            raise ValueError("Need at least two equity ETFs to rank")
        if len(self.equities) != len(self.roles):
            raise ValueError("roles must line up with equities")
        if len(set(self.equities)) != len(self.equities):
            raise ValueError("Duplicate equity ticker")

    def download_tickers(self) -> tuple[str, ...]:
        if self.cash:
            return self.equities + (self.cash,)
        return self.equities

    def role_of(self, ticker: str) -> str:
        for symbol, role in zip(self.equities, self.roles):
            if symbol == ticker:
                return role
        if ticker == self.cash or ticker == CASH_COLUMN:
            return "cash"
        return ticker


US_LISTED = Universe(
    name="us_listed",
    equities=("QQQ", "VGK", "EWC"),
    roles=("US Nasdaq-100", "developed Europe", "Canada"),
    cash="SGOV",
    note=(
        "US-listed ETFs: QQQ, VGK, and EWC, with SGOV as the cash fund. "
        "Before SGOV has prices, cash earns zero in the model."
    ),
)

# London Yahoo symbols for liquid UCITS funds. Confirm the listing you can
# actually trade. No Canada ticker is included.
UCITS = Universe(
    name="ucits",
    equities=("CNDX.L", "VEUR.L"),
    roles=("US Nasdaq-100 UCITS", "developed Europe UCITS"),
    cash=None,
    note=(
        "UCITS preset uses CNDX.L (iShares Nasdaq 100 UCITS USD Acc) and "
        "VEUR.L (Vanguard FTSE Developed Europe UCITS). Confirm both on your "
        "broker. Canada is omitted. Cash earns zero and is not a traded fund. "
        "Add a Canada ticker yourself only after you confirm that listing."
    ),
)

PRESETS: dict[str, Universe] = {
    US_LISTED.name: US_LISTED,
    UCITS.name: UCITS,
}


def get_preset(name: str) -> Universe:
    try:
        return PRESETS[name]
    except KeyError as exc:
        known = ", ".join(PRESETS)
        raise KeyError(f"Unknown preset {name!r}. Choose from: {known}") from exc
