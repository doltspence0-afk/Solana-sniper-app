# Sniper Desk: Solana PAPER-trading app (installable PWA)
Paper trading only. No wallet, key or swap code exists, and a test enforces that. Free stack: GitHub Actions + GitHub Pages.
Real-money trading is a *design only*: see REAL_MONEY_DESIGN.md.

## UPDATE an existing deployment (what you do on the phone)
1. In your repo: **Add file -> Upload files** -> upload `solana-paper-desk.zip` (same name) -> Commit. (It never overwrites your `state.json`/`config.json`.)
2. Open `.github/workflows/scan.yml` -> pencil icon -> select all -> paste the NEW workflow text from the chat -> Commit.
3. **Actions -> paper-desk -> Run workflow**. Wait for a green tick, then open the app -> More -> **Scanner & API health**.
4. If the run is red: tap it, open the red step, and send me the last ~20 lines of its log.
Fresh install: same steps as before (upload zip, create `.github/workflows/scan.yml`, Pages -> main /docs).

## What the strategy does now (quality over quantity)
Every coin must pass ALL mandatory checks, otherwise zero trades is the correct result: age >= 6h, liquidity/volume minimums, >= 100 trades/h with >= 52% buys, not chasing
(h1 <= +80%, 5m <= +12%, 6h <= +150%, not falling > 15%/h), mint & freeze authority renounced (read from Solana RPC), standard SPL-token mint, LP >= 90% locked and top-10 holders <= 30% (RugCheck), no RugCheck danger flags, score >= 75.
The 0-100 score is shown component by component. Weights are heuristics, NOT backtested.
Position size = smallest of cash %, risk budget (1% of equity lost at the stop), 1% of pool liquidity, and a 30% total-exposure cap. Entries are suspended if data quality degrades.
Exits are still fixed stop-loss/take-profit: adaptive exits need evidence we do not have yet.
Every evaluated coin keeps its accept/reject reasons (Opportunities page). "Forward evidence" (Performance page) records what passed/failed coins did 6h later.

## Controls (need the optional GitHub token, as before)
Scan now, Pause/Resume entries (open trades still monitored), **EMERGENCY STOP** (two taps: closes all paper positions and halts), Clear halt, and limits.
Emergency stop file alternative: add an empty file named `HALT` to the repo root.

## Verification status
| Item | Status |
|---|---|
| Engine, gates, authorities parsing, sizing, halt, heartbeat, settings, rate limiter, state recovery, UI logic, PWA, workflow config, secret scans | 89 automated tests (hermetic: they never read your live config/state) |
| DexScreener endpoints/fields | Checked against official docs; **not called live** from the build environment |
| Solana RPC `getAccountInfo` for mint/freeze authority | Standard documented RPC call; public endpoint availability from GitHub runners **unverified** |
| RugCheck endpoint/fields/key requirement | **Unverified** (third-party sources only) |
| GeckoTerminal trending/new pools response shape | **Unverified** (ignored safely if different) |
| GitHub dispatch API | Checked against docs.github.com; browser CORS/run-status polling **unverified** |
| Smart-money wallet tracking | **Not built** (needs a wallet-history data source; see chat) |
| Historical backtester | **Not built** (free history lacks lock/holder data and has survivorship bias) |
| Real phone / real GitHub run of this version | **Not tested** |

## Limits
GitHub's scheduler is best-effort (this version asks for every 15 min, off the busy :00/:30 marks). Stops and targets only trigger when a scan runs. Paper fills ignore failed transactions and MEV.
Troubleshooting: the **Scanner & API health** page states whether the scheduler, a failed step, or the market APIs are the problem.
