# Valhalla Bot

## What it is

A Discord bot for copy-trading on Solana. It mirrors a target wallet's Meteora
DLMM/DAMM liquidity actions and token swaps into the user's own Valhalla wallet,
in real time. Everything happens through Discord slash commands; there is no
separate app to install.

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

## Common issues

**Nothing is copying.** Usual causes, in order: copy trading is disabled in
`/settings`, the wallet is under the SOL minimum, no wallets are followed, or the
followed wallet simply has not traded on Meteora recently.

**A position failed to open.** Most often insufficient SOL for the temporary
deposit each position requires.

**Positions are not visible in Phantom.** The wallet has to be exported to
Phantom first. Positions live on Meteora.

**A followed wallet looks inactive.** Copies only fire on real on-chain activity.
No trades from the target means nothing to mirror.

## Escalate to a human

Anything touching money or credentials, without exception:

- Missing, stuck, or unexpected funds; withdrawals that have not arrived
- A specific user's positions, balances, PnL, or a specific trade
- Failed, partial, or duplicated copies
- Anything about private keys, key export, or passcode recovery
- Suspected compromise of a wallet

Never speculate about where someone's money went, and never guess at a fix that
would move funds.
