# Sniper Desk: Solana PAPER-trading app (installable PWA)

Paper trading only. No wallet, private key or swap code exists in this project, and a test enforces that.
Free stack: GitHub Actions (runs the bot every ~10 min) + GitHub Pages (hosts the app). No card, no paid APIs.

## Setup on a Samsung phone (about 10 minutes)
1. Make a free account at github.com. Create a **Public** repository (e.g. `sniper-desk`).
2. Repo page -> **Add file -> Upload files** -> pick `solana-paper-desk.zip` -> **Commit changes**. (Keep it as a zip.)
3. **Add file -> Create new file**. Name it exactly `.github/workflows/scan.yml` (typing `/` makes folders). Paste the workflow text from the chat message. **Commit**.
4. **Actions** tab -> **paper-desk** -> **Run workflow** -> Run. Wait for a green tick (1-2 min). The first run unpacks the zip, runs the self-tests, then runs a paper scan.
5. **Settings -> Pages** -> Source: *Deploy from a branch* -> Branch `main`, folder `/docs` -> Save. After 1-3 min the page shows your link: `https://YOURNAME.github.io/REPO/`.
6. Open that link in **Samsung Internet** (menu -> Add page to -> Home screen) or **Chrome** (⋮ -> Install app). It opens full-screen like a normal app.

## Optional: make the buttons work (Scan now, Pause, Settings)
GitHub -> your profile photo -> Settings -> Developer settings -> Personal access tokens -> **Fine-grained tokens** -> Generate.
Repository access: *Only select repositories* -> your repo. Permissions -> Repository -> **Actions: Read and write**. Expiry: 90 days. Copy the token.
In the app: More -> Settings -> paste into *Fine-grained token* -> Save -> Test connection.
The token is stored only on your phone, sent only to api.github.com, and cannot be read from the public files. Without a token the app is read-only (buttons stay disabled).
What the buttons really do: each one asks GitHub to run the workflow with a command. The server re-validates every value (see `bot/settings.py`). Pause stops *new* entries; open trades are still monitored.
Results appear in the app after the run finishes and GitHub Pages redeploys (usually 1-3 min). If the status says "cancelled", tap again (GitHub keeps one waiting run).

## What is and isn't verified
| Item | Status |
|---|---|
| Trading engine, filters, limits, settings, rate limiter, state recovery, UI logic, PWA files, workflow config, secret scans | Automated tests (`python -m unittest discover tests`), run on every workflow run |
| DexScreener endpoints/fields/rate limits | Checked against docs.dexscreener.com; **not called live** from the build environment |
| GitHub workflow-dispatch API and token permission | Checked against docs.github.com. Browser CORS use, run-status polling: **not verified** |
| RugCheck endpoint, fields, whether a key is needed | **Unverified** (only third-party sources, which disagree). If it fails, tokens become "unverified" and are never traded. See *API health* in the app |
| App on a real Samsung phone, install prompt, GitHub deployment | **Not tested.** Needs your device and account |
| Backtesting | **Not built yet** |

## Limits
* Not 24/7: GitHub's scheduler is best-effort, so gaps of 10-60+ min happen. The app shows a stale-data warning, and stops/targets only trigger when a scan runs.
* Paper fills ignore failed transactions, MEV and queueing; results do not predict real trading.
* The repo and `docs/state.json` are public (paper data only; no secrets are stored anywhere in it).
* ~144 commits/day from the bot (history grows slowly). You can edit the cron in `scan.yml`.
* Emergency stop: add an empty file named `HALT` to the repo root, or disable the workflow.

## Troubleshooting
* App says "No data": run the workflow once; wait for Pages. * Workflow red: open the run and read the failing step (a failed self-test blocks scanning by design).
* Buttons disabled: add the token. "403": token needs Actions: Read and write on this repo. "404": check username/repo and that `scan.yml` exists.
* "DATA STALE": scheduler delayed or APIs down; open trades are not monitored until the next successful scan.
* Old version showing: close the app fully and reopen (the service worker updates in the background).
