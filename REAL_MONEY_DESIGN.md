# Phase 6 design: future real-money trading (NOT implemented, NOT activated)

Nothing in this repo can sign or send a transaction, and a test enforces that. This file is a plan only.
Prices/limits below marked (unverified) were not checked against current official sources.

## Gate before any real money (all required)
1. 30+ days of continuous forward paper trading with the current rules, and 100+ closed trades.
2. Positive result *after* fees and the slippage model, profit factor > 1.3, max drawdown inside your limit.
3. "Forward evidence" (Performance page) shows accepted coins beating rejected ones over a meaningful sample (n in the hundreds, not tens).
4. Quote-only shadow phase (below) shows real swap quotes match the paper slippage model.
If any gate fails, real trading stays off. Passing a gate does not guarantee profit.

## Why GitHub Actions cannot do this
* Scheduling is best-effort (gaps of 15-60+ min observed in practice), so stop-losses would fire late or not at all.
* A hot-wallet key on shared runners is a bigger risk than it is worth; Actions also cannot confirm transactions or watch positions continuously.
* So real trading needs an always-on process. **Some hosting cost is effectively unavoidable**, unless you already own a device you can leave on 24/7.

## Infrastructure options (costs are rough and unverified)
| Option | Extra cost | Notes |
|---|---|---|
| Spare always-on device you own (old Android with Termux, Raspberry Pi, PC) | ~£0 plus electricity | Needs stable power/Wi-Fi; you must secure the device |
| Small VPS | roughly £4-6/month (unverified) | Most reliable for a beginner; requires a payment method |
| "Free" cloud tiers | £0 on paper | Many require card verification, which you ruled out; can change or sleep |
| RPC provider | free tiers exist (unverified limits) | Public Solana RPC is rate-limited and unreliable under load; paid plans cost more |
Real trading also costs: swap fees, priority fees/tips, slippage, failed-transaction fees, and realistic losses.

## Architecture (separate execution service; the Actions bot keeps doing research)
* **Wallet**: a *new dedicated* wallet funded only with money you can afford to lose. Key lives only in the host's environment (never GitHub, never the app). No withdrawal-capable keys beyond that wallet.
* **Swaps**: aggregator quote -> build transaction -> simulate -> send with priority fee -> confirm. Check current aggregator terms/free-tier limits first (unverified).
* **Sell-ability test**: before every buy, simulate/quote a sell of the same size; refuse if it fails (honeypot protection).
* **Confirmation**: poll signature status to "finalized"; handle expiry/retry with idempotency so a retry can never double-buy.
* **Reconciliation**: every cycle compare on-chain token balances to the internal ledger; any mismatch halts trading and alerts you.
* **Risk enforcement in the executor itself**: max position, max exposure, daily loss, kill switch (file/remote), max slippage per swap, never average down.
* **Monitoring loop**: price checks every few seconds for open positions, stop/target orders evaluated locally, heartbeat + alerts (e.g. free Telegram bot).
* **Failure modes to design for**: can't-sell tokens, freeze authority, sandwich/MEV attacks, RPC outages, stuck transactions, wrong decimals.

## Staged rollout
1. **Quote-only shadow**: log real swap quotes next to each paper fill; measure slippage error. No transactions.
2. **Dust live**: $5-10 positions for 2+ weeks; verify confirmation, reconciliation and kill switch actually work.
3. **Small live** with hard daily loss cap; scale only if all gates keep passing.
You also should consider tax and any regulatory duties in your country; this is not tax or legal advice.
