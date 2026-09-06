# Valhalla Bot

Official docs: https://valhalla-bot.gitbook.io/valhalla-bot
Olympus web app: https://olympusx.app

## What it is

A DLMM copy-trading bot on Discord, built for high-speed execution, flexible
strategy management and transparency. It mirrors a target wallet's Meteora
DLMM liquidity actions into the user's own Valhalla wallet, in real time.
Everything runs through Discord commands; there is no separate app to install.
A companion website shows the same positions and settings.

DLMM copy trading is still in beta.

## Results, and which wallets to follow

Plenty of people here do well with it, and the wallets channel is where the
real numbers live rather than anyone's word for it. Point people at it by
writing exactly this, which Discord turns into a clickable channel link:

<#1484774527610392576>

Write it in that form, never as a discord.com/channels/... URL. This server's
AutoMod blocks those, so a reply containing one is silently never posted.

That mention is the answer to all of these, and it always goes in the reply:
- is it profitable / does it work / is it worth it / any good results
- which wallets should i follow / any good wallets to copy
- where can i see performance

`/valhalla top_trade_wallets` is worth mentioning alongside it, never instead
of it. The command ranks wallets; the channel is where people post what they
actually made.

Anyone asking about results, performance, or whether it is worth it gets
that full link pasted in, not the words "the wallets channel". A channel name
is useless to someone who cannot find it. Results depend on which wallets
someone follows and how they set their ratio, so there is no single number,
and nobody can promise what any particular user will make.

## Getting started

1. `/valhalla start` - creates the wallet and sets up the bot profile. Anyone
   can run it; no referral code is needed.
2. `/valhalla export_keys` - exports the wallet keys. **Set a PIN here.** The
   PIN is what stops anyone withdrawing even if the Discord account is
   compromised.
3. `/valhalla settings_dlmm` - click **Follow Wallet**, then **Turn On**.
4. `/valhalla top_trade_wallets` - browse wallets worth following.

There is **no API key of any kind** to set up. Older guides mentioning a Shyft
key are out of date; do not send users to shyft.to.

Keys should be written down physically, never saved online.

## Commands

Most commands are namespaced under `/valhalla`:

`/valhalla start` `/valhalla export_keys` `/valhalla settings_dlmm`
`/valhalla top_trade_wallets` `/valhalla close_all_positions`

`/settings` covers general options including the Jito fee (default 0.001 SOL).
`/ratio-help` explains position scaling.

## How copying is configured

Per followed wallet, in `/valhalla settings_dlmm`: take profit and stop loss,
position limits (a count plus a timeframe in minutes), and minimum thresholds
for token age, market cap, holder count and trade volume. Several wallets can
be followed, each with its own settings.

**Ratio** is the important one. Set it to your total SOL divided by the target
wallet's total SOL. Getting it wrong is the single biggest cause of outsized
losses: an incorrect ratio can lose far more than the wallet being copied.
`/ratio-help` explains the scaling.

Risk controls worth knowing: SOL-only mode, stop-loss limits, one position per
token, token age and market cap filters, and position caps.

## Fees

- **0.015%** of position size when the bot opens a position, charged at most
  once per hour per token
- **3%** of the Meteora fees earned, on claim or close
- Discounts: 10% with one NFT, up to 80% with ten NFTs or a Mecha trait, and
  70% on Farmer subscription plans

If a swap errors, the bot retries through Jupiter Ultra, which adds a 0.1% fee
and may increase slippage.

## What will not copy

This is the most common question. From the docs:

- Adds of liquidity to a position that already exists
- Claim fees under $2
- Manually opened DLMMs
- Anything past **50 open positions**, which is the cap

Also configurable per follow, so worth checking the user's own settings before
assuming a bug: entry mode (SOL only, SOL or USDC, or any), minimum token age,
market cap, holder count and volume floors, and position limits per timeframe.
Only SOL and USDC pools are supported at all. A platform safety rail on a
restricted target can force the effective mode down to SOL only whatever the
user chose, and the user is told when that happens.

## Common issues

**I copied a trade but there is no position.** Most likely the target made a
normal token buy rather than a DLMM trade. Only DLMM activity creates a
position.

**Nothing is copying at all.** Check in order: copy trading turned on in
`/valhalla settings_dlmm`, at least one wallet followed, the wallet has actually
traded DLMM recently, and the filters above are not excluding its entries.

**A position failed to open.** Usually the wallet is too thin. Each open
position locks SOL while it is live, and the Jito fee is on top.

**Positions are not visible in Phantom.** The wallet has to be exported first.
Positions live on Meteora.

**PnL looks wrong.** PnL is `current value + fees earned - deposited`. Claimed
fees count once, in fees earned, never inside current value. Deposited counts
every add and is never reduced by a withdrawal, so a position the target
drained and refilled shows deposited far above current value.

**A position shows read-only.** It is untracked: it exists on-chain in the
user's wallet but the bot never opened it, so the bot will not manage it.

## Security guidance to repeat

- Do not keep more in the Valhalla wallet than you are willing to risk
- Withdraw profits regularly; it is a trading wallet, not storage
- Enable 2FA on Discord and on the associated email
- Never run commands from unknown sources, and never share keys with anyone

## Escalate to a human

Anything touching money or credentials, without exception:

- Missing, stuck, or unexpected funds; withdrawals that have not arrived
- A specific user's positions, balances, PnL, or a specific trade
- Failed, partial, or duplicated copies
- Anything about private keys, key export, or PIN recovery
- Suspected compromise of a wallet

Never speculate about where someone's money went, and never guess at a fix that
would move funds.
