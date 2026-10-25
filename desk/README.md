# Short-term trade desk

Rules engine for one daily-trend long setup. It writes the next session's action list after the close. It does not place broker orders, and it is not tax or investment advice.

The short-term book is the non-registered account. Long-term ETFs stay outside this scanner. A TFSA loss cannot be harvested. Pointing the short-term book at a TFSA prints a warning, because frequent short-term trading there can be treated as business activity.

## Stock-picking process

The watchlist in `config.yaml` is the only universe. The desk does not add symbols and does not ship a recommended list. Each weekday after the close, names move through these gates in order. A name that fails a gate is written under Skipped and is not an order.

1. Already open. A symbol below its entry is `add_to_loser`. Any other open symbol is `already_open`. Nothing is added.
2. Daily trend. The close is above the 50-day average and that average is higher than it was ten sessions ago.
3. Setup A only, until the journal gate passes and you set `enable_breakout: true`. Setup A is a pullback toward the 20-day average that has stopped falling: a recent bar touched that average from above, today's close is up, and today's low is not a new pullback low.
4. Earnings. A known earnings date inside five trading days is skipped. An unknown earnings date stays off the action list.
5. Stop. The stop is the pullback low minus 0.1 percent. The distance from the close to that stop must be between 0.75 percent and 1.5 percent, so a 2R to 3R target lands near a 2 to 3 percent price move.
6. Costs. Round-trip commission plus a currency conversion, when the symbol currency does not match cash already held, must leave most of a 2 percent gain. The default conversion is a flat 2 currency units each way. Matching cash means that fee is not charged on the trade.
7. Rank. Names that pass are ordered by matching currency, then by a stop closest to 1 percent, then by the steeper rising 50-day average.
8. Size and cap. `shares = (0.005 * equity) / (entry - stop)`, rounded down. One share that would risk more than 0.5 percent is skipped. If deployable cash is short, the share count is reduced and the risk is smaller. At most 4 to 6 positions are open. The rest of the account stays in cash or the long-term ETFs.

Setup B, a breakout from a tight multi-day range on higher volume, uses the same trend, stop, cost, and size rules. It returns no orders while `enable_breakout` is false or the journal has not passed.

## Payoff and stops

`exit_plan: scale` sells half near 2 percent and then trails the rest under the recent three-day low. The stop moves only up, and only after the half sale is recorded.

`exit_plan: fixed3` exits the whole position at 3 percent when that price is at least twice the initial risk.

A stop-out on the daily bar takes priority over a target on the same bar. A next-session open at or through the stop cancels that idea. Do not chase it.

## Schedule

Times are America/Toronto. Run each command once. A second run the same session reprints the file it already wrote.

```bash
cd desk
pip install -e .
cp config.example.yaml config.yaml
# edit equity, cash, fees, and your watchlist

# weekdays 16:20, after the daily bar
desk --config config.yaml run daily

# weekdays 09:00, reprint only
desk --config config.yaml show today

# Friday 16:40
desk --config config.yaml run weekly

# first Sunday of the month, and from 15 November
desk --config config.yaml run harvest
```

Prices for a live run need the optional Yahoo extra: `pip install -e '.[yahoo]'`.

## Journal

Record the fill you actually take. The tool will refuse a share count that risks more than 0.5 percent, a second position in an open symbol, a seventh position, and any new entry after the gate freezes.

```bash
desk --config config.yaml journal add --symbol EXAMPLE.TO --entry 50 --stop 49.50 --date 2026-10-23 --thesis "Pullback to the 20-day average stopped falling."
desk --config config.yaml journal half --id 1
desk --config config.yaml journal close --id 1 --exit-price 51 --date 2026-10-24
```

After 30 closed paper or live trades, new entries continue only when the net result after commissions and conversion is positive and the conversion fee was not charged on every closed trade. Until then the breakout stays off. Open positions still get their stop and exit lines when the gate is frozen.

## Tax-lot harvest

`lots.csv` columns: `symbol,account,acquired,shares,acb,currency`. The report lists non-registered losses that clear commissions, conversion, and the dollar floor. TFSA and other registered lots are excluded. A symbol with an open short-term trade is excluded.

A buy of the same symbol in the 30 calendar days before the review, in any lot or journaled trade on file, blocks the candidate. The report also gives the earliest repurchase date, 30 calendar days after the review, and an empty replacement field. You confirm that a replacement is not identical property, and you check spouse, TFSA, and RRSP accounts this file cannot see.

## Tests

```bash
cd desk
python -m pytest
```

The tests use fixture prices. They do not call the network.
