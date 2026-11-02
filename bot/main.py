"""Solana Sniper Desk - PAPER TRADING ONLY. No wallet/private-key code exists by design."""
import json, math, os, shutil, sys, time
import netclient, settings
MODE = "paper"
if MODE != "paper":
    raise SystemExit("Real trading is not implemented. Refusing to run.")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(ROOT, "docs", "state.json")
CFG_PATH = os.path.join(ROOT, "docs", "config.json")
BAK_PATH = os.path.join(ROOT, "data", "state.bak.json")
SECRET_ENV = ("RUGCHECK_API_KEY",)
CFG = dict(start_balance=10000.0, size_pct=0.10, fee=0.003, slip_base=0.005, sl=0.05, tp=0.10,
           max_trades_day=3, max_open=3, daily_loss_pct=0.03, max_dd_pct=0.15, min_vol=40000,
           min_liq=20000, max_top10=30.0, max_1h=80.0, min_lock=90.0, min_score=70,
           max_price_age=900, max_candidates=30, max_rc_calls=10)
CFG_DEFAULTS = dict(CFG)
DEX = "https://api.dexscreener.com"

CLIENT = netclient.Client()

def get(url, headers=None):
    return CLIENT.get_json(url, headers)

def rc_headers():
    k = os.environ.get("RUGCHECK_API_KEY")
    return {"X-API-KEY": k} if k else None  # optional; only sent if you set the secret

def new_state():
    b = CFG["start_balance"]
    return dict(mode="PAPER", balance=b, peak=b, day="", day_start=b, trades_today=0, positions=[],
                closed=[], rejected=[], decisions=[], traded=[], halted=False, halt_reason="",
                warnings=[], last_scan=None, last_ok=None, scanned=[], start=b, http={}, eq_hist=[], paused=False, cfg={})

class StateCorrupt(Exception):
    pass

NUM = (int, float)
REQUIRED = dict(balance=NUM, peak=NUM, day_start=NUM, start=NUM, trades_today=int, positions=list, closed=list,
                rejected=list, decisions=list, traded=list, halted=bool, warnings=list, scanned=list)
POS_KEYS = ("entry", "qty", "cost", "last", "last_seen", "liq")

def validate_state(st):
    if not isinstance(st, dict): raise StateCorrupt("state is not an object")
    st.setdefault("start", 10000.0); st.setdefault("http", {}); st.setdefault("eq_hist", []); st.setdefault("paused", False); st.setdefault("cfg", {})
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
    for k, n in (("rejected", 200), ("decisions", 100), ("closed", 500), ("warnings", 30), ("scanned", 15)):
        st[k] = st[k][-n:] if k != "scanned" else st[k][:n]
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

def buy(st, p, now):
    price = float(p["priceUsd"]); liq = p["liquidity"]["usd"]
    spend = st["balance"] * CFG["size_pct"]
    fill = price * (1 + slip(spend, liq))
    qty = (spend * (1 - CFG["fee"])) / fill
    st["balance"] -= spend
    st["traded"].append(p["baseToken"]["address"])
    st["trades_today"] += 1
    st["positions"].append(dict(mint=p["baseToken"]["address"], symbol=p["baseToken"]["symbol"],
                                entry=fill, qty=qty, cost=spend, last=price, last_seen=now, liq=liq, opened=int(now), ph=[[int(now), price]]))
    log(st, "decisions", agent="EXECUTOR", msg=f"PAPER BUY {p['baseToken']['symbol']} ${spend:.2f} @ {fill:.8g}")

def sell(st, pos, price, reason, now, liq=None):
    fill = price * (1 - slip(pos["qty"] * price, liq or pos["liq"]))  # gap-aware: fills at observed price, not trigger
    net = pos["qty"] * fill * (1 - CFG["fee"])
    st["balance"] += net
    st["positions"].remove(pos)
    st["closed"].append(dict(symbol=pos["symbol"], mint=pos["mint"], entry=pos["entry"], exit=fill,
                             pnl=net - pos["cost"], pnl_pct=(net / pos["cost"] - 1) * 100, reason=reason, closed=int(now)))
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

def score(p, rc):
    """ANALYST 0-100. Holder growth needs history we don't have, so it is not scored."""
    liq = min(p["liquidity"]["usd"] / 200000, 1) * 25
    ch = p["priceChange"]["h1"]; mom = min(max(ch, 0), 30) / 30 * 20
    t = (p.get("txns") or {}).get("h1") or {}; b, s = t.get("buys", 0), t.get("sells", 0)
    act = min((b + s) / 300, 1) * 20
    buyers = min(max((b / (b + s) - 0.4) / 0.3, 0), 1) * 20 if b + s else 0
    warns = sum(1 for r in rc.get("risks") or [] if r.get("level") == "warn")
    return round(liq + mom + act + buyers + max(0, 15 - 5 * warns), 1)

def scout():
    addrs = []
    for u in ("/token-profiles/latest/v1", "/token-boosts/top/v1"):
        for x in get(DEX + u) or []:
            if x.get("chainId") == "solana" and x.get("tokenAddress") not in addrs:
                addrs.append(x["tokenAddress"])
    return list(fetch_pairs(addrs[:CFG["max_candidates"]]).values())

def _f(x):
    try:
        v = float(x); return v if math.isfinite(v) else None
    except (TypeError, ValueError): return None

def run(st, now=None, candidates=None, rc_get=None, cfg=None):
    now = now or time.time()
    cfg = cfg if cfg is not None else settings.load(CFG_PATH)
    CFG.clear(); CFG.update(CFG_DEFAULTS); CFG.update(cfg["settings"])  # user settings, bounds-checked in settings.py
    eff = {k: CFG[k] for k in settings.BOUNDS}
    if st.get("cfg") and st["cfg"] != eff:
        log(st, "decisions", agent="CONTROL", msg="settings changed: " + ", ".join(f"{k}={eff[k]}" for k in eff if st["cfg"].get(k) != eff[k]))
    if bool(st.get("paused")) != cfg["paused"]:
        log(st, "decisions", agent="CONTROL", msg="new entries PAUSED by user" if cfg["paused"] else "new entries RESUMED by user")
    if cfg.get("invalid"): log(st, "warnings", msg="config.json invalid: staying paused")
    st["cfg"], st["paused"] = eff, cfg["paused"]
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    if st["day"] != day:
        st["day"], st["trades_today"], st["day_start"] = day, 0, equity(st)
    st["last_scan"] = int(now)
    manage(st, now)
    cands = scout() if candidates is None else candidates
    if not cands and candidates is None:
        log(st, "warnings", msg="SCOUT: no data (API outage?)"); return st
    bt = lambda p: (p.get("baseToken") or {}) if isinstance(p, dict) else {}
    cands = [p for p in cands if bt(p).get("address") and bt(p).get("symbol")]
    verdicts = {}
    rc_get = rc_get or (lambda m: get(f"https://api.rugcheck.xyz/v1/tokens/{m}/report", rc_headers()))
    calls = 0
    for p in cands:
        m, sym = p["baseToken"]["address"], p["baseToken"]["symbol"]
        if m in st["traded"]:
            verdicts[m] = ("traded", "already traded"); continue
        block = can_enter(st)
        if block:
            if not any(d.get("msg") == f"entries blocked: {block}" and d["t"] > now - 3600 for d in st["decisions"][-10:]):
                log(st, "decisions", agent="RISK", msg=f"entries blocked: {block}")
            break
        cache = {}
        def rc_fn():
            nonlocal calls
            if "v" not in cache:
                if calls >= CFG["max_rc_calls"]: cache["v"] = None
                else: calls += 1; cache["v"] = rc_get(m)
            return cache["v"]
        verdict, why = filt(p, rc_fn)
        if verdict != "ok":
            verdicts[m] = (verdict, why)
            log(st, "rejected", symbol=sym, mint=m, verdict=verdict, reason=why); continue
        sc = score(p, cache["v"])
        if sc < CFG["min_score"]:
            verdicts[m] = ("reject", f"score {sc} < {CFG['min_score']}")
            log(st, "rejected", symbol=sym, mint=m, verdict="reject", reason=f"score {sc} < {CFG['min_score']}"); continue
        log(st, "decisions", agent="ANALYST", msg=f"{sym} scored {sc}")
        buy(st, p, now); verdicts[m] = ("bought", f"score {sc}")
    st["scanned"] = [dict(pair=p.get("pairAddress"), symbol=bt(p)["symbol"], mint=bt(p)["address"],
                          price=_f(p.get("priceUsd")), liq=_f((p.get("liquidity") or {}).get("usd")),
                          vol=_f((p.get("volume") or {}).get("h24")), ch1h=_f((p.get("priceChange") or {}).get("h1")),
                          mc=_f(p.get("marketCap")), verdict=verdicts.get(bt(p)["address"], ("not checked", ""))[0],
                          why=verdicts.get(bt(p)["address"], ("", ""))[1],
                          age_h=round((now * 1000 - p["pairCreatedAt"]) / 3.6e6, 1) if isinstance(p.get("pairCreatedAt"), (int, float)) else None)
                     for p in cands[:15]]
    st["last_ok"] = int(now)
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
    try:
        run(st)
    except Exception as e:
        log(st, "warnings", msg=f"scan failed: {type(e).__name__}")
    st["http"] = CLIENT.stats
    save(st)
