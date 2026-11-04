"""Solana Sniper Desk - PAPER TRADING ONLY. No wallet/private-key code exists by design."""
import json, math, os, re, shutil, sys, time
import netclient, settings
MODE = "paper"
if MODE != "paper":
    raise SystemExit("Real trading is not implemented. Refusing to run.")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(ROOT, "docs", "state.json")
CFG_PATH = os.path.join(ROOT, "docs", "config.json")
BAK_PATH = os.path.join(ROOT, "data", "state.bak.json")
_vp = os.path.join(ROOT, "bot", "VERSION")
VERSION = open(_vp).read().strip() if os.path.exists(_vp) else "0"
SECRET_ENV = ("RUGCHECK_API_KEY",)
CFG = dict(start_balance=10000.0, size_pct=0.10, fee=0.003, slip_base=0.005, sl=0.05, tp=0.10,
           max_trades_day=3, max_open=3, daily_loss_pct=0.03, max_dd_pct=0.15, min_vol=40000,
           min_liq=30000, max_top10=30.0, max_1h=80.0, min_lock=90.0, min_score=75,
           max_price_age=900, max_candidates=45, max_rc_calls=10,
           risk_pct=0.01, max_exposure=0.30, max_impact=0.01, min_trade=50.0,
           min_age_h=6.0, min_trades_1h=100, min_buy_ratio=0.52, max_5m=12.0, max_6h=150.0, min_1h=-15.0)
CFG_DEFAULTS = dict(CFG)
DEX = "https://api.dexscreener.com"

CLIENT = netclient.Client()

def get(url, headers=None):
    return CLIENT.get_json(url, headers)

def rc_headers():
    k = os.environ.get("RUGCHECK_API_KEY")
    return {"X-API-KEY": k} if k else None  # optional; only sent if you set the secret

def EXTRA():
    return dict(last_run=None, run_status="", run_hist=[], consec_fail=0, evals=[], shadow={"pending": [], "stats": {}}, dq_block="", halt_cleared_at=0, gates={}, version="")

def new_state():
    b = CFG["start_balance"]
    return dict(mode="PAPER", balance=b, peak=b, day="", day_start=b, trades_today=0, positions=[],
                closed=[], rejected=[], decisions=[], traded=[], halted=False, halt_reason="",
                warnings=[], last_scan=None, last_ok=None, scanned=[], start=b, http={}, eq_hist=[], paused=False, cfg={}, **EXTRA())

class StateCorrupt(Exception):
    pass

NUM = (int, float)
REQUIRED = dict(balance=NUM, peak=NUM, day_start=NUM, start=NUM, trades_today=int, positions=list, closed=list,
                rejected=list, decisions=list, traded=list, halted=bool, warnings=list, scanned=list)
POS_KEYS = ("entry", "qty", "cost", "last", "last_seen", "liq")

def validate_state(st):
    if not isinstance(st, dict): raise StateCorrupt("state is not an object")
    st.setdefault("start", 10000.0); st.setdefault("http", {}); st.setdefault("eq_hist", []); st.setdefault("paused", False); st.setdefault("cfg", {})
    for k, v in EXTRA().items(): st.setdefault(k, v)
    for k in ("evals", "run_hist"):
        if not isinstance(st[k], list): st[k] = []
    if not isinstance(st["shadow"], dict) or not isinstance(st["shadow"].get("pending"), list) or not isinstance(st["shadow"].get("stats"), dict):
        st["shadow"] = {"pending": [], "stats": {}}
    for k, t in REQUIRED.items():
        v = st.get(k)
        if not isinstance(v, t) or (t is not bool and isinstance(v, bool)): raise StateCorrupt(f"bad field: {k}")
        if t is NUM and not math.isfinite(v): raise StateCorrupt(f"non-finite: {k}")
    if st["balance"] < 0 or st["start"] <= 0 or st["peak"] <= 0 or st["day_start"] <= 0:
        raise StateCorrupt("impossible balance")
    for p in st["positions"]:
        if not isinstance(p, dict) or not p.get("mint") or not p.get("symbol"): raise StateCorrupt("bad position")
        for k in POS_KEYS:
            if not isinstance(p.get(k), NUM) or not math.isfinite(p[k]): raise StateCorrupt(f"bad position field: {k}")
    return st

def _read(path):
    with open(path) as f:
        return validate_state(json.load(f))

def load(path=STATE_PATH, bak=BAK_PATH):
    """Never silently resets: a corrupt file falls back to the last good backup, else raises StateCorrupt."""
    if not os.path.exists(path):
        if os.path.exists(bak):
            try: return _read(bak)
            except (ValueError, OSError, StateCorrupt): raise StateCorrupt("state missing and backup invalid")
        return new_state()
    try:
        return _read(path)
    except (ValueError, OSError, StateCorrupt):
        try:
            st = _read(bak); log(st, "warnings", msg="state.json was corrupt; restored from backup"); return st
        except (ValueError, OSError, StateCorrupt):
            raise StateCorrupt("state.json corrupt and no valid backup; refusing to reset balances")

def scrub(text):
    for name in SECRET_ENV:
        v = os.environ.get(name)
        if v and len(v) >= 6: text = text.replace(v, "[redacted]")
    return text

def save(st, path=STATE_PATH, bak=BAK_PATH):
    for k, n in (("rejected", 200), ("decisions", 100), ("closed", 500), ("warnings", 30), ("scanned", 15), ("evals", 40)):
        st[k] = st[k][-n:] if k not in ("scanned", "evals") else st[k][:n]
    validate_state(st)  # refuse to write garbage
    text = scrub(json.dumps(st, separators=(",", ":")))
    os.makedirs(os.path.dirname(path), exist_ok=True); os.makedirs(os.path.dirname(bak), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text); f.flush(); os.fsync(f.fileno())
    try:
        _read(path); shutil.copyfile(path, bak + ".tmp"); os.replace(bak + ".tmp", bak)  # keep last good copy
    except (OSError, ValueError, StateCorrupt):
        pass
    os.replace(tmp, path)

def equity(st):
    return st["balance"] + sum(p["qty"] * p["last"] for p in st["positions"])

def slip(size, liq):
    return CFG["slip_base"] + (size / liq if liq else 0.05)

def log(st, key, **kw):
    kw["t"] = int(time.time())
    st[key].append(kw)

def buy(st, p, now, size=None):
    price = float(p["priceUsd"]); liq = p["liquidity"]["usd"]
    spend = size if size is not None else st["balance"] * CFG["size_pct"]
    fill = price * (1 + slip(spend, liq))
    qty = (spend * (1 - CFG["fee"])) / fill
    st["balance"] -= spend
    st["traded"].append(p["baseToken"]["address"])
    st["trades_today"] += 1
    st["positions"].append(dict(mint=p["baseToken"]["address"], symbol=p["baseToken"]["symbol"], entry=fill, qty=qty, cost=spend,
                                last=price, last_seen=now, liq=liq, opened=int(now), ph=[[int(now), price]], fee_in=spend * CFG["fee"]))
    log(st, "decisions", agent="EXECUTOR", msg=f"PAPER BUY {p['baseToken']['symbol']} ${spend:.2f} @ {fill:.8g}")

def sell(st, pos, price, reason, now, liq=None):
    fill = price * (1 - slip(pos["qty"] * price, liq or pos["liq"]))  # gap-aware: fills at observed price, not trigger
    net = pos["qty"] * fill * (1 - CFG["fee"])
    st["balance"] += net
    st["positions"].remove(pos)
    st["closed"].append(dict(symbol=pos["symbol"], mint=pos["mint"], entry=pos["entry"], exit=fill,
                             pnl=net - pos["cost"], pnl_pct=(net / pos["cost"] - 1) * 100, reason=reason, closed=int(now), fees=round(pos.get("fee_in", 0) + pos["qty"] * fill * CFG["fee"], 4)))
    log(st, "decisions", agent="EXECUTOR", msg=f"PAPER SELL {pos['symbol']} ({reason}) pnl ${net - pos['cost']:.2f}")

def fetch_pairs(mints):
    out = {}
    for i in range(0, len(mints), 30):
        data = get(f"{DEX}/tokens/v1/solana/{','.join(mints[i:i+30])}")
        for p in data or []:
            m = (p.get("baseToken") or {}).get("address")
            liq = (p.get("liquidity") or {}).get("usd") or 0
            if m and (m not in out or liq > (out[m].get("liquidity") or {}).get("usd", 0)):
                out[m] = p
    return out

def manage(st, now):
    """RISK MANAGER: exits, staleness, drawdown."""
    pairs = {}
    if st["positions"]:
        pairs = fetch_pairs([p["mint"] for p in st["positions"]])
        for pos in list(st["positions"]):
            p = pairs.get(pos["mint"])
            try:
                price = float(p["priceUsd"]); liq = p["liquidity"]["usd"]
            except (TypeError, KeyError, ValueError):
                if now - pos["last_seen"] > CFG["max_price_age"]:
                    log(st, "warnings", msg=f"STALE price for {pos['symbol']}; not selling blind")
                continue
            pos["last"], pos["last_seen"] = price, now
            pos["ph"] = (pos.get("ph") or [])[-59:] + [[int(now), price]]
            if price <= pos["entry"] * (1 - CFG["sl"]):
                sell(st, pos, price, "STOP-LOSS", now, liq)
            elif price >= pos["entry"] * (1 + CFG["tp"]):
                sell(st, pos, price, "TAKE-PROFIT", now, liq)
    eq = equity(st)
    st["peak"] = max(st["peak"], eq)
    if (st["peak"] - eq) / st["peak"] >= CFG["max_dd_pct"] and not st["halted"]:
        st["halted"], st["halt_reason"] = True, f"max drawdown hit ({eq:.2f})"
        log(st, "warnings", msg="EMERGENCY SHUTDOWN: " + st["halt_reason"])
    return pairs

def can_enter(st):
    if st.get("paused"): return "paused by user"
    if st["halted"]: return "bot halted: " + st["halt_reason"]
    if os.path.exists(os.path.join(ROOT, "HALT")): return "HALT file present"
    if st["trades_today"] >= CFG["max_trades_day"]: return "daily trade limit"
    if len(st["positions"]) >= CFG["max_open"]: return "max open positions"
    if (st["day_start"] - equity(st)) / st["day_start"] >= CFG["daily_loss_pct"]: return "daily loss limit"
    return None

def filt(p, rc_fn):
    """FILTER. Returns ('ok'|'reject'|'unverified', reason). Unverified is never traded."""
    try:
        liq, vol, ch = p["liquidity"]["usd"], p["volume"]["h24"], p["priceChange"]["h1"]
        px = float(p["priceUsd"])
        if None in (liq, vol, ch) or not math.isfinite(px) or px <= 0: raise ValueError
    except (KeyError, TypeError, ValueError):
        return "unverified", "missing market data"
    if vol < CFG["min_vol"]: return "reject", f"24h volume ${vol:,.0f} < ${CFG['min_vol']:,}"
    if ch > CFG["max_1h"]: return "reject", f"already +{ch:.0f}% in 1h"
    if liq < CFG["min_liq"]: return "reject", f"liquidity ${liq:,.0f} too low"
    rc = rc_fn()
    if not rc: return "unverified", "no RugCheck report"
    mk, th = rc.get("markets"), rc.get("topHolders")
    if not mk or th is None: return "unverified", "lock/holder data missing"
    try:
        locked = max(m["lp"]["lpLockedPct"] for m in mk)
    except (KeyError, TypeError): return "unverified", "LP lock data missing"
    if locked < CFG["min_lock"]: return "reject", f"LP only {locked:.0f}% locked"
    infra = {m.get(k) for m in mk for k in ("pubkey", "liquidityA", "liquidityB")} - {None}
    top10 = sum(h["pct"] for h in [h for h in th if h.get("address") not in infra and h.get("owner") not in infra][:10])
    if top10 > CFG["max_top10"]: return "reject", f"top10 holders own {top10:.1f}%"
    if rc.get("rugged"): return "reject", "flagged rugged"
    danger = [r["name"] for r in rc.get("risks") or [] if r.get("level") == "danger"]
    if danger: return "reject", "suspicious: " + ", ".join(danger)
    return "ok", ""

RPC = "https://api.mainnet-beta.solana.com"
GATE_KEYS = ("min_age_h", "min_trades_1h", "min_buy_ratio", "max_5m", "max_6h", "min_1h", "max_1h", "max_impact", "min_lock")
def _f(x):
    try:
        v = float(x); return v if math.isfinite(v) else None
    except (TypeError, ValueError): return None

def pct(p, k):
    return _f((p.get("priceChange") or {}).get(k))

def age_h(p, now):
    t = p.get("pairCreatedAt")
    return (now * 1000 - t) / 3.6e6 if isinstance(t, (int, float)) and not isinstance(t, bool) else None

def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))

# ---------------- SCOUT ----------------
def scout():
    """Discovery. DexScreener profile/boost lists are PAID promotions (adverse selection), so GeckoTerminal's
    trending/new pools are added as a neutral source. All candidates are re-priced through DexScreener."""
    addrs = []
    def add(a):
        if isinstance(a, str) and re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", a) and a not in addrs: addrs.append(a)
    for u in ("/token-profiles/latest/v1", "/token-boosts/top/v1"):
        for x in get(DEX + u) or []:
            if isinstance(x, dict) and x.get("chainId") == "solana": add(x.get("tokenAddress"))
    for u in ("trending_pools", "new_pools"):   # response shape from memory, NOT verified against official docs; failures are ignored
        d = get(f"https://api.geckoterminal.com/api/v2/networks/solana/{u}")
        try:
            for it in d["data"]:
                i = it["relationships"]["base_token"]["data"]["id"]
                if i.startswith("solana_"): add(i[7:])
        except (TypeError, KeyError): pass
    return list(fetch_pairs(addrs[:CFG["max_candidates"]]).values())

# ---------------- FILTER (extra mandatory gates) ----------------
def gates(p, now):
    """Cheap mandatory checks. Returns EVERY failure so each rejection is fully explained."""
    liq = _f((p.get("liquidity") or {}).get("usd")); vol = _f((p.get("volume") or {}).get("h24"))
    h1, m5, h6, a = pct(p, "h1"), pct(p, "m5"), pct(p, "h6"), age_h(p, now)
    t = (p.get("txns") or {}).get("h1") or {}; bu, se = t.get("buys"), t.get("sells")
    if None in (liq, vol, h1): return ["market data incomplete"]
    f = []
    if a is None: f.append("token age unknown")
    elif a < CFG["min_age_h"]: f.append(f"too new: {a:.1f}h < {CFG['min_age_h']:g}h")
    if liq < CFG["min_liq"]: f.append(f"liquidity ${liq:,.0f} < ${CFG['min_liq']:,.0f}")
    if vol < CFG["min_vol"]: f.append(f"24h volume ${vol:,.0f} < ${CFG['min_vol']:,.0f}")
    if h1 > CFG["max_1h"]: f.append(f"chasing: +{h1:.0f}% in 1h")
    if h1 < CFG["min_1h"]: f.append(f"falling: {h1:.0f}% in 1h")
    if m5 is not None and m5 > CFG["max_5m"]: f.append(f"chasing: +{m5:.0f}% in 5m")
    if h6 is not None and h6 > CFG["max_6h"]: f.append(f"chasing: +{h6:.0f}% in 6h")
    if not isinstance(bu, int) or not isinstance(se, int): f.append("buy/sell counts missing")
    elif bu + se < CFG["min_trades_1h"]: f.append(f"thin activity: {bu + se} trades in 1h")
    elif bu / (bu + se) < CFG["min_buy_ratio"]: f.append(f"sell pressure: only {bu / (bu + se):.0%} buys")
    return f

def authorities(m):
    """On-chain check via public Solana RPC (getAccountInfo, jsonParsed). None = could not verify."""
    d = CLIENT.get_json(RPC, body={"jsonrpc": "2.0", "id": 1, "method": "getAccountInfo", "params": [m, {"encoding": "jsonParsed"}]})
    try:
        v = d["result"]["value"]; info = v["data"]["parsed"]["info"]
        return dict(program=v["data"]["program"], mint=info["mintAuthority"], freeze=info["freezeAuthority"])
    except (TypeError, KeyError): return None

def auth_fails(a):
    if a is None: return None
    f = []
    if a["program"] != "spl-token": f.append(f"{a['program']} mint (extensions such as transfer fees not assessed)")
    if a["mint"]: f.append("mint authority active (supply can be inflated)")
    if a["freeze"]: f.append("freeze authority active (wallets can be frozen)")
    return f

# ---------------- ANALYST ----------------
def top10_pct(rc):
    mk, th = rc.get("markets") or [], rc.get("topHolders") or []
    infra = {m.get(k) for m in mk for k in ("pubkey", "liquidityA", "liquidityB")} - {None}
    return sum(h.get("pct", 0) for h in [h for h in th if h.get("address") not in infra and h.get("owner") not in infra][:10])

def score_detail(p, rc, now):
    """Transparent 0-100 score. Weights are heuristics, NOT backtested; the app shows every component."""
    liq, vol, h1, m5 = p["liquidity"]["usd"], p["volume"]["h24"], p["priceChange"]["h1"], pct(p, "m5")
    t = p["txns"]["h1"]; bu, se = t["buys"], t["sells"]; a = age_h(p, now) or 0
    turn = vol / liq if liq else 0
    tp = 15 * clamp(turn / 0.5) if turn <= 8 else 15 * clamp(1 - (turn - 8) / 8)
    mo = 15 if 2 <= h1 <= 25 else 15 * h1 / 2 if 0 <= h1 < 2 else 15 * clamp(1 - (h1 - 25) / 35) if h1 > 25 else 5 * clamp(1 + h1 / 10)
    if m5 is not None and m5 < 0: mo = max(0, mo - 5)
    warns = sum(1 for r in rc.get("risks") or [] if r.get("level") == "warn")
    raw = {"liquidity": (20 * clamp(liq / 150000), 20), "turnover": (tp, 15),
           "buy pressure": (20 * clamp((bu / (bu + se) - 0.5) / 0.2) if bu + se else 0, 20), "momentum": (mo, 15),
           "maturity": (10 * clamp((a - 6) / 42), 10), "holders": (10 * clamp((30 - top10_pct(rc)) / 25), 10),
           "risk flags": (max(0, 10 - 5 * warns), 10)}
    parts = {k: [round(v, 1), m] for k, (v, m) in raw.items()}
    return {"total": round(sum(v for v, _ in parts.values()), 1), "parts": parts}

def score(p, rc, now=None):
    return score_detail(p, rc, now or time.time())["total"]

# ---------------- EXECUTOR / RISK ----------------
def plan_size(st, p):
    """Risk-based sizing: the smallest of cash %, risk budget (risk_pct of equity lost at the stop), price impact, exposure cap."""
    eq = equity(st); liq = p["liquidity"]["usd"]
    caps = {"cash %": st["balance"] * CFG["size_pct"], "risk budget": CFG["risk_pct"] * eq / CFG["sl"], "price impact": liq * CFG["max_impact"],
            "exposure cap": CFG["max_exposure"] * eq - sum(x["cost"] for x in st["positions"]), "cash": st["balance"]}
    name = min(caps, key=caps.get); size = caps[name]
    return (round(size, 2) if size >= CFG["min_trade"] else 0.0), name

def flatten(st, now, pairs):
    for pos in list(st["positions"]):
        p = pairs.get(pos["mint"]) or {}
        sell(st, pos, _f(p.get("priceUsd")) or pos["last"], "HALT: " + (st["halt_reason"] or "stopped")[:36], now,
             _f((p.get("liquidity") or {}).get("usd")) or pos["liq"])

def shadow_add(st, p, verdict, sc, now):
    """Forward evidence: remember candidates that passed the cheap gates and see what they did later (no survivorship bias)."""
    sh = st["shadow"]; m = p["baseToken"]["address"]; px = _f(p.get("priceUsd"))
    if px and len(sh["pending"]) < 40 and not any(i["mint"] == m for i in sh["pending"]):
        sh["pending"].append(dict(mint=m, symbol=p["baseToken"]["symbol"], t=int(now), price=px, verdict=verdict, score=sc))

def shadow_update(st, now, pairs):
    sh, keep = st["shadow"], []
    for it in sh["pending"]:
        pr = _f((pairs.get(it["mint"]) or {}).get("priceUsd")); age = now - it["t"]
        if pr and it["price"] > 0:
            r = (pr / it["price"] - 1) * 100
            if age >= 3600 and it.get("r1") is None: it["r1"] = round(r, 2)
            if age >= 21600:
                g = sh["stats"].setdefault(it["verdict"], {"n": 0, "sum6": 0.0, "wins": 0}); g["n"] += 1; g["sum6"] = round(g["sum6"] + r, 2); g["wins"] += r > 0
                continue
        if age < 172800: keep.append(it)
    sh["pending"] = keep

def evalrec(p, now, verdict, fails, sc=None, parts=None):
    bt = p["baseToken"]; a = age_h(p, now)
    return dict(t=int(now), symbol=bt["symbol"], mint=bt["address"], pair=p.get("pairAddress"), price=_f(p.get("priceUsd")),
                liq=_f((p.get("liquidity") or {}).get("usd")), vol=_f((p.get("volume") or {}).get("h24")), ch1h=pct(p, "h1"),
                age_h=round(a, 1) if a is not None else None, verdict=verdict, score=sc, parts=parts, fails=fails)

def heartbeat(st, reason, now=None):
    now = now or time.time()
    st["last_run"] = int(now); st["run_hist"] = (st["run_hist"] + [int(now)])[-48:]
    st["run_status"] = "failed: " + re.sub(r"[^\w .:()-]", "", reason)[:60]; st["consec_fail"] += 1
    log(st, "warnings", msg="run " + st["run_status"])

def run(st, now=None, candidates=None, rc_get=None, cfg=None):
    now = now or time.time()
    st["last_run"] = int(now); st["run_hist"] = (st["run_hist"] + [int(now)])[-48:]
    cfg = cfg if cfg is not None else settings.load(CFG_PATH)
    CFG.clear(); CFG.update(CFG_DEFAULTS); CFG.update(cfg["settings"])  # user settings, bounds-checked in settings.py
    eff = {k: CFG[k] for k in settings.BOUNDS}
    if st.get("cfg") and st["cfg"] != eff:
        log(st, "decisions", agent="CONTROL", msg="settings changed: " + ", ".join(f"{k}={eff[k]}" for k in eff if st["cfg"].get(k) != eff[k]))
    if bool(st.get("paused")) != cfg["paused"]:
        log(st, "decisions", agent="CONTROL", msg="new entries PAUSED by user" if cfg["paused"] else "new entries RESUMED by user")
    if cfg.get("invalid"): log(st, "warnings", msg="config.json invalid: staying paused")
    st["cfg"], st["paused"], st["gates"], st["version"] = eff, cfg["paused"], {k: CFG[k] for k in GATE_KEYS}, VERSION
    ch = cfg.get("clear_halt_ts", 0)
    if ch > st["halt_cleared_at"]:
        st["halt_cleared_at"] = ch
        if st["halted"]:
            st["halted"], st["halt_reason"], st["peak"] = False, "", equity(st)
            log(st, "decisions", agent="CONTROL", msg="halt cleared by user")
    if cfg.get("halt") and not st["halted"]:
        st["halted"], st["halt_reason"] = True, "emergency stop by user"
        log(st, "decisions", agent="CONTROL", msg="EMERGENCY STOP: closing all paper positions")
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    if st["day"] != day:
        st["day"], st["trades_today"], st["day_start"] = day, 0, equity(st)
    st["last_scan"] = int(now)
    pairs = manage(st, now)
    if st["halted"] and st["positions"]: flatten(st, now, pairs)
    if st["shadow"]["pending"]: shadow_update(st, now, fetch_pairs([i["mint"] for i in st["shadow"]["pending"]]))
    cands = scout() if candidates is None else candidates
    if not cands and candidates is None:
        log(st, "warnings", msg="SCOUT: no data (API outage?)"); st["run_status"] = "no market data"; st["consec_fail"] += 1; return st
    bt = lambda p: (p.get("baseToken") or {}) if isinstance(p, dict) else {}
    cands = [p for p in cands if bt(p).get("address") and bt(p).get("symbol")]
    st["dq_block"] = f"too few candidates ({len(cands)})" if candidates is None and len(cands) < 3 else ""
    rc_get = rc_get or (lambda m: get(f"https://api.rugcheck.xyz/v1/tokens/{m}/report", rc_headers()))
    evals, verdicts, c, logged = [], {}, dict(rc=0, rcf=0, au=0, auf=0), False
    def note(p, verdict, fails, sc=None, parts=None):
        evals.append(evalrec(p, now, verdict, fails, sc, parts)); verdicts[p["baseToken"]["address"]] = (verdict, "; ".join(fails))
    def reject(p, verdict, fails, sc=None, parts=None):
        note(p, verdict, fails, sc, parts); log(st, "rejected", symbol=p["baseToken"]["symbol"], mint=p["baseToken"]["address"], verdict=verdict, reason="; ".join(fails))
    for p in cands:
        m, sym = p["baseToken"]["address"], p["baseToken"]["symbol"]
        if m in st["traded"]:
            verdicts[m] = ("traded", "already traded"); continue
        fails = gates(p, now)
        if fails: reject(p, "unverified" if fails == ["market data incomplete"] else "reject", fails); continue
        cache = {}
        def rc_fn():
            if "v" not in cache:
                if c["rc"] >= CFG["max_rc_calls"]: cache["v"] = None
                else:
                    c["rc"] += 1; cache["v"] = rc_get(m)
                    if not cache["v"]: c["rcf"] += 1
            return cache["v"]
        verdict, why = filt(p, rc_fn)
        if c["rc"] >= 4 and c["rcf"] / c["rc"] >= 0.8: st["dq_block"] = f"RugCheck unavailable ({c['rcf']}/{c['rc']} calls failed)"
        if verdict != "ok":
            shadow_add(st, p, verdict, None, now); reject(p, verdict, [why]); continue
        c["au"] += 1; au = auth_fails(authorities(m))
        if au is None:
            c["auf"] += 1
            if c["au"] >= 4 and c["auf"] / c["au"] >= 0.8: st["dq_block"] = f"Solana RPC unavailable ({c['auf']}/{c['au']} calls failed)"
            shadow_add(st, p, "unverified", None, now); reject(p, "unverified", ["could not read mint/freeze authorities"]); continue
        if au:
            shadow_add(st, p, "reject", None, now); reject(p, "reject", au); continue
        det = score_detail(p, cache["v"], now); sc = det["total"]
        if sc < CFG["min_score"]:
            shadow_add(st, p, "reject", sc, now); reject(p, "reject", [f"score {sc} < {CFG['min_score']}"], sc, det["parts"]); continue
        block = can_enter(st) or st["dq_block"]
        if block:
            if not logged: log(st, "decisions", agent="RISK", msg=f"entries blocked: {block}"); logged = True
            shadow_add(st, p, "qualified", sc, now); note(p, "qualified", [f"not bought: {block}"], sc, det["parts"]); continue
        size, lim = plan_size(st, p)
        if size <= 0:
            reject(p, "reject", [f"position would be under ${CFG['min_trade']:.0f} (limit: {lim})"], sc, det["parts"]); continue
        log(st, "decisions", agent="ANALYST", msg=f"{sym} scored {sc}")
        buy(st, p, now, size); shadow_add(st, p, "bought", sc, now); note(p, "bought", [f"size ${size:,.0f} (limit: {lim})"], sc, det["parts"])
    evals.sort(key=lambda e: ({"bought": 0, "qualified": 1}.get(e["verdict"], 2), -(e["score"] or 0)))
    st["evals"] = evals[:40]
    st["scanned"] = [dict(pair=p.get("pairAddress"), symbol=bt(p)["symbol"], mint=bt(p)["address"], price=_f(p.get("priceUsd")),
                          liq=_f((p.get("liquidity") or {}).get("usd")), vol=_f((p.get("volume") or {}).get("h24")), ch1h=pct(p, "h1"),
                          mc=_f(p.get("marketCap")), verdict=verdicts.get(bt(p)["address"], ("not checked", ""))[0],
                          why=verdicts.get(bt(p)["address"], ("", ""))[1], age_h=round(age_h(p, now), 1) if age_h(p, now) is not None else None)
                     for p in cands[:15]]
    st["last_ok"], st["run_status"], st["consec_fail"] = int(now), "ok", 0
    if not st["eq_hist"] or st["eq_hist"][-1][0] != int(now):
        st["eq_hist"] = (st["eq_hist"] + [[int(now), round(equity(st), 4)]])[-400:]
    return st

if __name__ == "__main__":
    try:
        st = load()
    except StateCorrupt as e:
        print("FATAL:", e); sys.exit(1)
    if "--check" in sys.argv:
        print("state OK"); sys.exit(0)
    if "--heartbeat" in sys.argv:
        heartbeat(st, os.environ.get("REASON", "unknown")); st["http"] = CLIENT.stats; save(st); print("heartbeat recorded"); sys.exit(0)
    try:
        run(st)
    except Exception as e:
        log(st, "warnings", msg=f"scan failed: {type(e).__name__}"); st["run_status"] = f"failed: scan crashed ({type(e).__name__})"; st["consec_fail"] += 1
    st["http"] = CLIENT.stats
    save(st)
