# Olympus

## What it is

A Polymarket copy-trading platform. It watches leader wallets on Polymarket and
automatically mirrors their trades for followers. Unlike Valhalla, Olympus is a
web app rather than a Discord-native bot. Sign-in is handled by Privy.

Latency matters here: this is copy trading, so execution speed affects fills.

## What users get

- Copy-trading dashboard: follow leaders, configure per-leader settings
- Multi-wallet support
- LP rewards
- PvE intel: osint, flow spikes, top traders, posts, tweets
- Perps, combos, and sports markets
- An in-app "Ask AI" assistant (floating button, bottom right of any signed-in
  page) that can search markets, read prices and orderbooks, summarize a
  portfolio, and propose orders

The Ask AI assistant **never places an order on its own.** It emits a
"Confirm to place" card and the user clicks Confirm. If someone reports it
trading without them, that is a bug worth escalating immediately.

## Key terms

**Leader** - a wallet a follower has chosen to mirror. Also called the target
wallet.

**Follower** - a user mirroring a leader. One user can follow several leaders,
and each (user, leader) pair has its own settings.

**Leader Position** - how many shares the leader actually holds in a token right
now. Same value for every follower of that leader. It is the correct basis for
"what fraction of their position did the leader just exit".

**Attributed Shares** - how many shares a follower holds that came from copying
one particular leader in one particular token. This is what a copy-sell reduces.

**Copy-Sell Percentage** - the fraction of their position a leader closed in a
single trade. A copy-sell reduces the follower's Attributed Shares by that same
fraction.

**Orphan Share** - a share the follower still holds whose leader has already
exited. Not something the follower chose; it exists because the copy machinery
slipped.

**Failsafe** - a periodic sweep comparing what a follower actually holds on-chain
against what the records say they should hold, then closing the difference. A
**Stray** is a holding whose leader has sold. An **Orphan** is a holding with no
attribution record at all.

## Common questions

**Why did my copy not match the leader's size?** Copy sizing is driven by the
follower's own settings and the Copy-Sell Percentage, not a 1:1 share match.
If the numbers still look wrong, escalate rather than explaining the discrepancy.

**Why do I hold something my leader already sold?** That is an Orphan or Stray.
The failsafe is designed to catch it. Escalate specific instances.

**Did the AI assistant place this trade?** It cannot place trades unconfirmed.
Escalate.

## Escalate to a human

This is a live trading product with real money. Escalate anything that is:

- About a specific user's positions, balances, PnL, fills, or a specific trade
- A trade that did not copy, copied twice, or copied at an unexpected size
- Missing or unexpected funds, withdrawals, redemptions
- Anything asking whether to buy, sell, or hold, or what a market will do
- A suspected outage or systemic copy failure

Never give trading or financial advice, and never speculate about the cause of a
money discrepancy. Escalating is always the correct answer here.
