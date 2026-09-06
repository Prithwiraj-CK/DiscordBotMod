# Valhalla Bot

## What it is

A Discord bot for copy-trading on Solana. It mirrors a target wallet's Meteora
DLMM/DAMM liquidity actions and token swaps into the user's own Valhalla wallet,
in real time. Everything happens through Discord slash commands; there is no
separate app to install. A companion website shows the same positions and
settings.

## How it is built

Useful for judging whether a problem is the user's setup or ours.

**Discord bot** (`discord.js`, TypeScript, run under PM2). `src/commands` holds
the slash commands, with `src/buttons`, `src/modals` and `src/select-menus`
providing the interactive panels behind `/settings`. Data lives in PostgreSQL
through TypeORM (`src/database/entities`), with Redis for caching and queues.

**Copy-trade pipeline** (`src/scripts/copy-trade`). A **watcher** subscribes to
target wallets on-chain over gRPC or WebSocket. When one trades, the action goes
onto a BullMQ queue in Redis, and a **worker** executes the mirrored trade. A
separate **failsafe** sweep catches positions the live path missed. Follow,
unfollow and enable/disable events reach the watcher over Redis pub/sub, so
changes take effect without a restart.

**Website** (`nextjs-privy-oauth`): a Next.js frontend, an API app and its own
worker, with Privy handling sign-in. Both the bot and the website call one
shared rules module (`@valhalla/application`) so the two cannot drift apart.

**Chain and market data**: Meteora SDKs for DLMM and DAMM, Jupiter for swaps and
routing, GMGN for token analytics, Shyft for wallet transaction history. RPC
health is monitored centrally with automatic failover.

Practical consequence: a copy that never happened is usually a *decision* by the
gates below, not a crash. A copy that started and failed is usually chain-side
(SOL, slippage, RPC).

## Getting started

1. `/start` creates a Valhalla wallet for the Discord account.
2. Fund it with **at least 0.1 SOL**. Each opened position temporarily needs
   about 0.06 SOL for the deposit, so a thinner balance will fail to open.
3. Connect a Shyft API key (free from shyft.to) in `/settings`.
4. Open `/settings`, click the **copy trade dlmm** button, enable copy trading
   and set a trade amount.
5. Follow at least one target wallet.

Users can export the wallet to Phantom to see bot-created positions directly on
Meteora. The wallet is theirs; Valhalla just drives it.

## Commands

`/start` `/settings` `/settings_dlmm` `/wallet` `/positions`
`/meteora_positions` `/get_pnl` `/top_trade_wallets` `/copy_trade_wallet_data`
`/buy_dlmm_tx` `/sell_and_positions` `/close_all_positions` `/withdraw`
`/export_keys` `/passcode` `/amount` `/to_address` `/tx`

Copy-trade setup lives behind `/settings` now. Older guides list standalone
`/copy-trade-wallets ...` and `/copy-trade-settings ...` commands. Those are
outdated. Point users at `/settings` instead.

## Key terms

**Target wallet** (or followed wallet) - the Solana wallet being mirrored.

**Follow / unfollow** - starting or stopping copy-trading of a target wallet. A
follow carries its own settings: label, trade ratios, trade amount, and filters
such as max market cap.

**Copy-trade settings** - account-level configuration: copying on or off, whether
swaps are copied, slippage, stop-loss and take-profit percentages, bundled-token
handling, minimum price range. Separate from the per-wallet settings on a follow.

**Watcher** - the always-on process that observes target wallets on-chain and
decides when a copy should happen.

**Passcode** - a user-chosen PIN authorizing sensitive actions such as withdraw
and private-key export. Stored hashed only, and never shown back to anyone.

## Why an entry was not copied

Most "it didn't copy" questions are one of these. All are per-follow unless
stated. If none fits, escalate rather than inventing a reason.

**Entry Mode** - which of a target's entries get copied: *SOL Only*, *SOL or
USDC*, or *Any*. SOL Only is an absolute guarantee the bot never swaps the
user's SOL into USDC.

**Pool Gate** - the pool must contain a quote asset the mode allows. Only SOL and
USDC pools are supported at all, whatever the mode.

**Shape Gate** (DLMM only) - the restrictive modes require the target to have
funded exactly one side of the position with a permitted quote asset. A
two-sided deposit does not qualify. Never applies to DAMM.

**Min Target Position Size** - a floor in SOL on the *target's* deposit, not the
user's spend. Gates opens only; adds are never size-checked.

**Max Token Deposited** ("Max per Token") - a per-user ceiling on total SOL in
one token across every position and every leader. A breach shrinks an add to the
room left, but refuses an open outright.

**Launch Sniper Gate** - refuses entry when the token's bundle-bot share (from
GMGN) is at or above a threshold the user sets. Off by default.

**Infinite Add Liquidity** - off means the position never grows after its entry.
There is no setting that copies only some adds.

**Clamping** - a platform safety rail on a restricted target forces the effective
mode down to SOL Only, whatever the user chose. Users are told when this happens.

## Common issues

**Nothing is copying.** Usual causes, in order: copy trading is disabled in
`/settings`, the wallet is under the SOL minimum, no wallets are followed, the
followed wallet has not traded on Meteora recently, or one of the gates above is
filtering the entries out.

**A position failed to open.** Most often insufficient SOL for the temporary
deposit each position requires.

**Positions are not visible in Phantom.** The wallet has to be exported to
Phantom first. Positions live on Meteora.

**A followed wallet looks inactive.** Copies only fire on real on-chain activity.
No trades from the target means nothing to mirror.

**PnL looks wrong.** PnL is `current value + fees earned - deposited`. Claimed
fees count once, in fees earned, never inside current value. Deposited counts
every add and is never reduced by a withdrawal, so a position the target drained
and refilled will show deposited far above current value. Wallet-explorer rows
for *target* wallets show Meteora's own figure instead, which includes
withdrawals, so the two will not always agree.

**A position shows read-only.** It is *untracked*: it exists on-chain in the
user's wallet but the bot never opened it, so the bot will not manage it.

## Escalate to a human

Anything touching money or credentials, without exception:

- Missing, stuck, or unexpected funds; withdrawals that have not arrived
- A specific user's positions, balances, PnL, or a specific trade
- Failed, partial, or duplicated copies
- Anything about private keys, key export, or passcode recovery
- Suspected compromise of a wallet

Never speculate about where someone's money went, and never guess at a fix that
would move funds.
