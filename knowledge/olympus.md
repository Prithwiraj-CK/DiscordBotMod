# Olympus

Web app: https://olympusx.app

## What it is

A Polymarket copy-trading platform. It watches leader wallets on Polymarket and
automatically mirrors their trades for followers. Unlike Valhalla, Olympus is a
web app rather than a Discord-native bot, at https://olympusx.app. Sign-in is
handled by Privy, on the site itself; there is nothing to install.

Latency matters here: this is copy trading, so execution speed affects fills.

## How it is built

Useful for judging whether a problem is the user's setup or ours.

**Frontend** (`apps/web-v2`, Next.js). The signed-in app covers markets and
market pages, sports (by league and event), crypto, bonds, perps, multiply,
leverage, combos, consensus, LP rewards, the leaderboard and top wallets,
per-trader pages, multi-wallet, search and rewards.

**API** (`apps/api`, Hono + tRPC) and **worker** (`apps/worker`) share a
PostgreSQL database through Drizzle ORM, with Redis for queues and caching and
ClickHouse for analytics. The worker owns the things that run on their own:
the leader listener, the failsafe sweep, the scheduler, perps automation and
perps protection.

**Chain and market access**: `viem`/`ethers` against Polygon, a Polymarket API
package for markets and the CLOB, Privy for wallets and auth.

**Wallets**: every user has a signing key (a Privy embedded wallet) and a
separate trading address where funds and positions actually live. The signer
never holds trading funds. When someone reports a balance on "the wrong
address", this distinction is usually why, and it is an escalation.

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

## Results, and which leaders to follow

Plenty of people here do well with it. The **olympus wallets** channel in this server is where the real numbers are.

Name it in plain words. Do NOT write it as a <#id> channel mention and do NOT
write a discord.com/channels/... URL. This server's AutoMod blocks both, and a
reply containing one is silently never posted.

That channel is the answer to all of these: is it profitable, does it work, is it worth it, which leaders should i
follow, where can i see performance. A channel name with no link is useless to
someone who cannot find it. Outcomes depend on which leaders someone follows and their own
settings, so there is no single number and no promise for any one user.

## Combos

A combo is a **multi-leg parlay**: several market outcomes bundled into one
YES (or NO) position, built on the Combos page. It is not a basket of separate
trades. Every leg has to come in for it to pay, which is what makes the odds
long, and it settles through a different venue to normal orders.

Anyone describing it as "buying several markets at once" has the wrong idea and
is worth correcting: the all-or-nothing part is the whole point.

## Perps, and perps automation

Perps are leveraged perpetual futures on real-world assets, settled in pUSD,
with no expiry. Six instruments: SP500, GOLD, WTIOIL, NAS100, SILVER and BTC.
Leverage caps vary by instrument (SP500 goes to 20x).

**Perps automation** opens perps positions for you from RSI rules. A rule says:
when the latest closed candle's RSI falls inside my band, open a position with
my margin and leverage, then arm dollar take-profit and stop-loss. Set them up
in the Perps Automation tab.

What people get wrong about it:

- **RSI is the only strategy that works.** The tab also shows MACD Crossover,
  EMA Golden Cross and Bollinger Band Touch. Those are placeholders and are not
  implemented, so a rule built on them will never fire.
- **One direction per market.** Several rules on the same instrument are fine,
  including different timeframes, but they must all be the same direction. A
  short BTC rule is refused while any long BTC rule exists, because a perps
  position nets per instrument.
- **It only uses closed candles**, so it will not fire mid-candle.
- **Cooldown is the candle interval**, and it survives restarts. A 1h rule
  fires at most once an hour.
- **It skips an instrument that already has a position open**, so a rule can
  look "not working" when it is just waiting for the existing position to close.
- It is labelled **early beta**, and it moves real collateral.

Explain how it works and what the settings do. Never tell anyone what bands,
leverage or margin to use, or whether to switch it on: that is a trading
decision and it is theirs.

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

**In-Play Delay** - Polymarket holds orders on live sports and esports markets
in a non-matching state for a few seconds. An order that never clears that state
in time is treated as rejected. This is Polymarket's behaviour, not ours.

**Maker Copy-Buy** - a copy-buy priced at or below the best bid, so it rests on
the book instead of crossing the spread. It avoids taker fees, at the cost of an
uncertain and sometimes very late fill, or none at all.

## Fees

Charged on copy trades (buy, sell, redeem), recorded as trades execute and
collected once daily on-chain, not per trade. A user will not see a separate
charge next to each fill.

- Normal trade fee: 0.75% base, 0.20% reduced. Discord role, admin and other
  discounts can apply.
- LP fill fee: a fixed 0.2% on both legs of an LP order. No discounts apply.
- LP reward share: a flat 5% of settled liquidity rewards, taken in the daily
  sweep. No discounts apply.

## Welcome bonus

There is exactly one. A verified deposit of at least $50 into the user's trading
wallet within seven days of the wallet being created raises that user's
**referral commission** from 25% to 30%. The seven days start automatically when
the wallet is created; no action is needed.

It is not a trading-fee discount, not a zero-fee period, and it does not
activate from trading.

## Common questions

**Why did my copy not match the leader's size?** Copy sizing is driven by the
follower's own settings and the Copy-Sell Percentage, not a 1:1 share match.
If the numbers still look wrong, escalate rather than explaining the discrepancy.

**Why do I hold something my leader already sold?** That is an Orphan or Stray.
The failsafe is designed to catch it. Escalate specific instances.

**Why did my order never fill?** On live sports markets, the in-play delay can
push an order past its window. A maker copy-buy also simply may not fill if the
book never comes to it. Both are expected behaviour, but a specific unfilled
order is still an escalation.

**Why has my winning position not paid out?** Redemption is automatic but can
stall, most often when the wallet cannot cover gas.

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
