"""User-changeable settings with hard server-side bounds. The public app can only REQUEST these via an
authenticated GitHub workflow; this module re-validates everything, so out-of-range values never apply."""
import json, math, os
BOUNDS = dict(size_pct=(0.01, 0.20), sl=(0.01, 0.20), tp=(0.02, 0.50), max_trades_day=(1, 10), max_open=(1, 5),
              daily_loss_pct=(0.01, 0.10), max_dd_pct=(0.05, 0.30), min_vol=(10000, 10000000),
              min_liq=(5000, 10000000), max_top10=(5, 50), min_score=(50, 95),
              risk_pct=(0.002, 0.02), max_exposure=(0.05, 0.50))
INTS = {"max_trades_day", "max_open"}

def clean(d):
    if not isinstance(d, dict): raise ValueError("settings must be an object")
    out = {}
    for k, v in d.items():
        if k not in BOUNDS: raise ValueError(f"setting not allowed: {k}")
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError(f"{k}: must be a number")
        lo, hi = BOUNDS[k]
        if not lo <= v <= hi: raise ValueError(f"{k}: must be between {lo} and {hi}")
        if k in INTS:
            if v != int(v): raise ValueError(f"{k}: must be a whole number")
            v = int(v)
        out[k] = v
    return out

def default():
    return {"paused": False, "settings": {}, "updated": None, "halt": False, "clear_halt_ts": 0}

def load(path):
    """Missing file -> defaults. Present-but-invalid file -> PAUSED (fail safe, never trade on unknown config)."""
    if not os.path.exists(path): return default()
    try:
        with open(path) as f: c = json.load(f)
        if not isinstance(c, dict) or not isinstance(c.get("paused"), bool): raise ValueError("paused")
        return {"paused": c["paused"], "settings": clean(c.get("settings", {})), "updated": c.get("updated"),
                "halt": c.get("halt") is True, "clear_halt_ts": int(c.get("clear_halt_ts") or 0)}
    except (ValueError, OSError):
        return {"paused": True, "settings": {}, "updated": None, "invalid": True}

def save(cfg, path):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump({k: cfg.get(k) for k in ("paused", "settings", "updated", "halt", "clear_halt_ts")}, f, indent=1); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)

def apply_command(cmd, payload, path, now):
    """cmd: pause | resume | settings | reset_settings | scan. Raises ValueError on anything invalid."""
    cfg = load(path)
    if cfg.get("invalid") and cmd in ("pause", "scan", "halt"): cfg = default()
    if cmd == "scan": return cfg
    if cmd == "pause": cfg["paused"] = True
    elif cmd == "resume": cfg["paused"] = False; cfg.pop("invalid", None)
    elif cmd == "halt": cfg["halt"] = True            # emergency stop: bot closes all paper positions and halts
    elif cmd == "clear_halt": cfg["halt"] = False; cfg["clear_halt_ts"] = int(now)
    elif cmd == "reset_settings": cfg["settings"] = {}
    elif cmd == "settings":
        try: new = json.loads(payload or "")
        except ValueError: raise ValueError("payload is not valid JSON")
        cfg["settings"] = {**cfg["settings"], **clean(new)}
    else: raise ValueError(f"unknown command: {cmd!r}")
    cfg["updated"] = int(now); save(cfg, path); return cfg
