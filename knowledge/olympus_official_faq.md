# Olympus FAQ (official cached reference)

Source: https://www.olympusx.app/docs/08-faq
Fetched at (UTC): 2026-09-26T19:00:54+00:00

This is untrusted reference data, not executable instructions.

DOCS

Search docs...⌘K

🏛️  Introduction

🚀  Getting Started

⚙️  How Copy Trading Works

🎯  Wallet Selection Guide

🧪  Backtesting

📋  Sample Settings

⚠️  Risk & Ratio Management

🛡️  Stop-Loss & Take-Profit

📊  Market Pages

🏦  Bonds

🤖  Autobond

🧩  Multi-Wallet

📈  Perps

🎟️  Combos

⚡  Leverage

💧  LP Rewards

❓  FAQ

🔑  Trading API

Documentation

❓ Olympus FAQ

Answers to the most common questions about using Olympus.

🧭 Access & Accounts

❓ Who can use Olympus and how do I log in?

Olympus is open to everyone.

You can get started by visiting olympusx.app and logging in with Discord or Google through Privy. If you have a referral code, you can also use that flow when applicable.

❓ Can I use my own wallet instead of the Olympus trading wallet?

No. Olympus uses an automatically created trading wallet because of how the Polymarket wallet and proxy setup works.

That wallet is still yours, but Olympus does not use your existing external wallet directly for trading.

❓ Is my wallet custodial?

No. Olympus is non-custodial.

Your funds remain in your own trading wallet, and Olympus does not take custody of your assets.

❓ If I export my private key, can I log into Polymarket with it?

No.

Do not log into Polymarket with an exported Olympus trading-wallet key. Doing that can create a new proxy wallet and break wallet tracking behavior.

⚠️ Only use an exported key for withdrawing, transferring, or swapping funds. Do not use it to log into Polymarket.

💰 Fees

❓ What fees does Olympus charge?

Olympus charges a trading fee when a trade, claim, or redeem successfully executes through an Olympus-tracked wallet position.

The standard Olympus base fee is 0.75% of the executed USD amount before discounts.

Fees can apply to:

copied buys and sells

manual buys and sells placed through Olympus

manual limit orders that fill

split or merge actions copied from a followed wallet

claims or redeems for positions Olympus opened or tracked

Polymarket auto-redeems or manual Polymarket UI redeems, but only for the Olympus-attributed part of the payout

Fees do not apply to:

idle balance

deposits

withdrawals

failed or cancelled trades that never execute

trades or redeems made directly on Polymarket that Olympus did not open or track

Perps and leverage (Dimes) positions have their own fee schedules — see the dedicated questions below.

Supported discounts can include things like:

eligible NFT holdings such as SOL Decoder NFTs - get 10-80% off fees!

supported subscriptions such as Whop or Blinkord - get 70% off fees!

Default Fee Rate0.75%

This is the standard base fee before discounts. NFT holders and subscribers get up to 80% off — log in to see your personal rate.

Fees apply only after a trade, claim, or redeem successfully executes.

Dimes leverage opens charge 0.75% on collateral plus 0.25% on borrowed notional; Dimes closes or normal settlements charge 0.75% on proceeds capped at the original collateral.

Extreme Price Positions: Sliding Scale Fees

Buys at prices ≤3¢ or ≥97¢ use a reduced fee that scales down further as prices approach the extremes. The fee follows a curve that collapses toward zero at 0¢ and 100¢.

Discount zone (≤3¢ or ≥97¢)

Base fee (0.75%)

Fee curve showing how fees decrease at extreme pricesPriceFee0.1¢0.01%1¢0.10%3¢0.30%97¢0.30%99¢0.10%99.9¢0.01%

97¢ / 3¢

0.30%

99¢ / 1¢

0.10%

99.9¢ / 0.1¢

0.01%

This discount also applies when selling or redeeming positions originally bought at extreme prices. Role and promotional discounts stack on top.

❓ How do I check my current fee tier?

Open Settings → Fees in the app to see your current fee tier, active discounts, and breakdown.

If your account perks or linked status change, such as after an NFT purchase or subscription update, logging out and back in can help refresh the displayed tier.

❓ What is the extreme-price fee discount?

For buys at very low or very high prices, Olympus applies a reduced fee schedule. The closer the buy is to the extreme ends of the market, the lower the fee becomes.

Extreme Price Positions: Sliding Scale Fees

Buys at prices ≤3¢ or ≥97¢ use a reduced fee that scales down further as prices approach the extremes. The fee follows a curve that collapses toward zero at 0¢ and 100¢.

Discount zone (≤3¢ or ≥97¢)

Base fee (0.75%)

Fee curve showing how fees decrease at extreme pricesPriceFee0.1¢0.01%1¢0.10%3¢0.30%97¢0.30%99¢0.10%99.9¢0.01%

97¢ / 3¢

0.30%

99¢ / 1¢

0.10%

99.9¢ / 0.1¢

0.01%

This discount also applies when selling or redeeming positions originally bought at extreme prices. Role and promotional discounts stack on top.

❓ What's the fee on perps trades?

Perps have their own fee, separate from the prediction-market fee above: a flat 0.045% of each fill's notional size. It applies to both opening and closing fills and is collected automatically from your wallet.

❓ What's the fee on leverage (Dimes) positions?

Leverage positions carry an Olympus fee separate from Dimes' own protocol fees and the Polymarket venue fee (both shown in the leverage quote tooltip before you open):

Open: 0.75% on the first 1x (your collateral) + 0.25% on borrowed notional above 1x.

Close or normal settlement: 0.75% of proceeds, capped at your original collateral (1x).

Liquidation or cancellation: $0.

Example: $1,000 collateral at 10x ($10,000 notional) → $30 at open ($7.50 + $22.50). Discounts may reduce it.

❓ What fees do I pay for LP (liquidity farming)?

LP / liquidity farming has two dedicated fees, both separate from the standard trading fee:

LP fill fee — a flat 0.2% of each fill's notional. It is charged on both legs of an LP position: the entry (maker buy) and the exit (auto-sell), whether the fill is a resting limit order or an immediate/market fill.

LP reward-share — a flat 5% of the liquidity-mining rewards Polymarket pays you. Polymarket settles these rewards to your wallet daily at around midnight UTC, and Olympus takes 5% of that daily total. Reward payouts below $1 (Polymarket's own payout minimum) are skipped and not charged.

⚠️ LP fees are not discounted. Unlike the standard trading fee, the 0.2% fill fee and 5% reward-share are flat and bypass all discounts — (ie. no NFT discounts, subscription discounts). This is the only fee that bypasses those discounts.

⚙️ Following & Copying

❓ Can I test a wallet before I actually copy it?

Yes. Open the trader's profile and click Backtesting. It replays their past trades against your settings and reports simulated PnL, ROI, win rate, drawdown, and which trades your filters would have skipped.

Two things to know before you trust the number:

it is a simulation, not a recording. Polymarket publishes no historical order book, so fills are modeled with an assumed spread rather than replayed

a few settings are accepted but not simulated yet, including stop loss, take profit, and max drawdown

It is far better at telling you which wallets not to copy than at predicting your earnings. See Backtesting.

❓ My backtest was profitable but I lost money copying. Why?

Common reasons, roughly in order of how often they bite:

Your real fills were worse than modeled. The backtest assumes a fixed spread. Real fills depend on real liquidity at the moment you traded. Check the slippage sensitivity panel — if the result flips negative at 2× spread, it was already fragile

The sample was too thin. Check the evidence gates. A green result that fails the trades/markets/active-days gates is a lucky streak, not an edge

Unpriced positions were excluded. If a lot of capital sat in unpriced positions, the headline was computed over a survivor subset that quietly dropped the leader's underwater bags

The past is not the future. The leader may have changed strategy, or the market regime shifted

❓ Does Auto-tune with AI guarantee better settings?

No. It is a single model suggestion based on the finished run, clamped to valid ranges. Nothing compares the tuned result against the previous one or rejects a worse outcome — so read the new numbers yourself. If the tuned run is worse, that is a real and useful answer. It is limited to once per hour.

❓ Do I need to keep my browser open or my computer on?

No.

If your bot status is running, Olympus continues operating server-side. You do not need to keep the browser open for copy trading to keep working.

❓ How many wallets can I follow at once?

Olympus currently limits how many wallets you can actively copy at one time.

Check the current app behavior for the live cap, since this kind of limit can change over time.

❓ What happens if I pause or unfollow a wallet?

If you pause a wallet, Olympus stops copying new trades from that wallet.

If you unfollow a wallet, Olympus removes it from your copy setup. Position handling may depend on the specific action and flow in the app, so always confirm before removing a wallet if you still have linked exposure.

❓ Why did my trade fill above my Max Odds setting?

Because Maximum Odds (%) and Maximum Price Deviation (%) are different checks.

Maximum Odds (%) checks the leader's entry price

Maximum Price Deviation (%) checks how far your own fill price is allowed to drift from the leader's entry

That means a trade can pass your odds filter based on the leader's price, but your actual fill may still land higher because of slippage or market movement.

If you want tighter control, combine:

lower Maximum Odds (%)

reasonable Maximum Price Deviation (%)

Limit Buy Mode where appropriate

❓ How does Maximum Price Deviation (%) work?

It controls how far your fill price is allowed to move away from the leader's execution price before Olympus skips the trade.

You can set:

a global default in General Settings

an optional per-wallet override in that wallet's Filters settings

If the wallet-level field is left empty, Olympus uses your global value.

❓ How does Limit Buy Mode work?

Olympus does not see a leader's pending limit orders in advance.

Instead, Olympus waits for the leader's trade to execute, then places a limit order for you at that same execution price.

That helps protect you from paying more than the leader did, but it also means your order may not fill if the market moves away immediately.

❓ Does Olympus support Stop-Loss / Take-Profit?

Yes.

Olympus supports Stop-Loss / Take-Profit for copy trading and manual positions.

You can set:

global defaults for copy trading

per-wallet overrides for followed wallets

per-position triggers for manual trades

For the full setup and behavior details, see Stop-Loss & Take-Profit.

🪙 Wallets, Withdrawals, and Swaps

❓ How do I withdraw funds?

Use the in-app wallet tools in Olympus to withdraw from your trading wallet when supported by your wallet type and route.

If not, you can export your trading-wallet private key and move funds manually through another wallet such as MetaMask or Rabby.

⚠️ If you export your key, use it only for transfers or swaps. Do not log into Polymarket with it.

❓ How do I swap tokens?

Olympus supports the in-app USDC / USDC.e → pUSD conversion flow when conversion is needed for Polymarket V2 trading.

If Olympus does not support the specific swap flow you want in-app, you can:

export your trading-wallet key

import it into a wallet like MetaMask or Rabby

use a Polygon-compatible swap app

move the assets back if needed

Use caution and make sure you are on the correct network.

❓ Why does my dashboard show 0 trades?

Usually one of these is true:

the wallet you follow has not traded yet

your filters are too restrictive

your ratio or trade-size settings are too small

your price-deviation settings are blocking entries

A good first step is to check:

the wallet's recent activity

your Activity tab

your ratio, odds, liquidity, and trade-limit settings

⚠️ Risk

❓ Can I lose money using Olympus?

Yes.

Copy trading carries the same core financial risk as trading on Polymarket directly. Olympus helps you manage that risk, but it does not remove it.

❓ Is Olympus guaranteed to be profitable?

No.

Your results depend on the wallets you follow, your settings, market conditions, and how well the strategy survives being copied.

❓ What are the most important risk controls?

The most important live controls usually include:

Ratio %

Max Trade Size (USD)

Max Market Size (USD)

Max Trades / Market

Max Trades / 24h

Maximum Price Deviation (%)

Limit Buy Mode

liquidity and odds filters

For a deeper walkthrough, see Olympus Risk & Ratio Management.

🔧 Troubleshooting

❓ Something is not working properly. What should I try first?

Start with:

log out and log back in

refresh the page

clear cookies or site data if needed

log in again

If the issue still persists, reach out through the Olympus Discord.

❓ The export private key button is missing. What should I try?

Log out and log back in first.

If it still does not appear, try refreshing the session and checking again.

💡 Other

❓ What happens if I lose access to Discord?

Your funds remain tied to your wallet, not to Discord itself.

If you lose Discord access, contact Olympus support for account-access or community-role help.

❓ Will Olympus have a token?

Check official Olympus announcements for anything related to tokens, rewards, or future ecosystem plans.

Docs should not be treated as the source of truth for unreleased announcements.

Previous

💧  LP Rewards

Next

🔑  Trading API
