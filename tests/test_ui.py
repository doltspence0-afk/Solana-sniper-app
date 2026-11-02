import json, os, re, shutil, subprocess, tempfile, time, unittest
from support import *

NODE = shutil.which("node")
def calc(fn, *args):
    r = subprocess.run([NODE, os.path.join(ROOT, "tests", "calc_cli.js")], input=json.dumps({"fn": fn, "args": list(args)}), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)

@unittest.skipUnless(NODE, "node not installed")
class CalcTests(Base):
    def test_equity_matches_engine_and_accounting_identity(self):
        st = populated_state(); m = calc("summarize", st)
        self.assertAlmostEqual(m["equity"], b.equity(st), 9)
        realised = sum(c["pnl"] for c in st["closed"]); unreal = sum(p["qty"] * p["last"] - p["cost"] for p in st["positions"])
        self.assertAlmostEqual(m["total"], realised + unreal, 6)   # balance + positions - start == closed P&L + open P&L
        self.assertEqual(len(st["closed"]), 2); self.assertEqual({c["reason"] for c in st["closed"]}, {"TAKE-PROFIT", "STOP-LOSS"})
    def test_today_pnl_uses_day_start(self):
        st = populated_state(); st["day_start"] = 9900.0; self.assertAlmostEqual(calc("summarize", st)["today"], b.equity(st) - 9900.0, 9)
    def test_perf_numbers(self):
        st = populated_state(); p = calc("perf", st); w = [c["pnl"] for c in st["closed"] if c["pnl"] > 0]; l = [c["pnl"] for c in st["closed"] if c["pnl"] <= 0]
        self.assertEqual((p["n"], p["wins"], p["losses"], p["winRate"]), (2, 1, 1, 50.0))
        self.assertAlmostEqual(p["profitFactor"], sum(w) / -sum(l), 9); self.assertAlmostEqual(p["avgLoss"], sum(l), 9)
        self.assertGreater(p["best"], 0); self.assertLess(p["worst"], 0)
    def test_empty_perf_has_no_fake_numbers(self):
        p = calc("perf", b.new_state()); self.assertEqual((p["n"], p["winRate"], p["best"], p["profitFactor"]), (0, None, None, None))
    def test_drawdown(self):
        self.assertAlmostEqual(calc("maxDrawdownPct", [[0, 100], [1, 120], [2, 90], [3, 110]]), 25.0)
    def test_freshness_thresholds(self):
        n = 100000
        f = lambda age: calc("freshness", {"last_ok": n - age * 60}, n)["level"]
        self.assertEqual((f(5), f(31), f(95)), ("ok", "warn", "stale")); self.assertEqual(calc("freshness", {"last_ok": None}, n)["level"], "never")
        self.assertTrue(calc("positionStale", {"last_seen": n - 901}, n)); self.assertFalse(calc("positionStale", {"last_seen": n - 60}, n))
    def test_validate(self):
        self.assertEqual(calc("validate", {"sl": 0.05, "max_open": 3}), []); self.assertTrue(calc("validate", {"sl": 0.9}))
        self.assertTrue(calc("validate", {"max_open": 2.5})); self.assertTrue(calc("validate", {"min_score": 10}))
    def test_formatting(self):
        self.assertEqual((calc("money", -1234.5), calc("money", 0), calc("pct", 1.234), calc("ago", 30), calc("ago", 300)), ("-$1,234.50", "$0.00", "+1.23%", "just now", "5 min ago"))

def fixtures():
    n = time.time(); fresh = populated_state(); fresh["last_ok"] = fresh["last_scan"] = int(n - 120)
    for p in fresh["positions"]: p["last_seen"] = n - 60; p["opened"] = int(n - 3600)
    fresh["cfg"] = {k: b.CFG_DEFAULTS[k] for k in b.settings.BOUNDS}
    stale = populated_state()
    pause = json.loads(json.dumps(fresh)); pause.update(paused=True, halted=True, halt_reason="max drawdown hit (8000.00)"); b.log(pause, "warnings", msg="STALE price for OPEN; not selling blind")
    nulls = json.loads(json.dumps(fresh)); nulls["scanned"] = [dict(pair=None, symbol="<img src=x onerror=alert(1)>", mint="m", price=None, liq=None, vol=None, ch1h=None, mc=None, verdict="unverified", why="missing market data", age_h=None)]
    for p in nulls["positions"]: p.pop("ph", None)
    return {"empty": b.new_state(), "fresh": fresh, "stale": stale, "paused": pause, "nulls": nulls}

@unittest.skipUnless(NODE, "node not installed")
class UISmoke(Base):
    @classmethod
    def setUpClass(cls):
        fx = {k: {"S": v, "C": {"paused": v.get("paused", False), "settings": {}}} for k, v in fixtures().items()}
        p = os.path.join(tempfile.mkdtemp(), "fx.json"); json.dump(fx, open(p, "w"))
        r = subprocess.run([NODE, os.path.join(ROOT, "tests", "dom_smoke.js"), p], capture_output=True, text=True); assert r.returncode == 0, r.stderr
        cls.R = {(x["state"], x["route"]): x for x in json.loads(r.stdout)}
    def test_every_page_renders_without_errors_or_garbage(self):
        for k, x in self.R.items():
            self.assertTrue(x["ok"], f"{k}: {x.get('err')}")
            for bad in ("undefined", "NaN", "Infinity", "[object"): self.assertNotIn(bad, x["text"] + x["view"], f"{k} shows {bad}")
    def test_all_seven_sections_exist(self):
        self.assertEqual({r for _, r in self.R} - {"more"}, {"home", "scanner", "open", "history", "perf", "agents", "settings"})
    def test_paper_labels_and_real_numbers(self):
        st = fixtures()["fresh"]; eq = b.equity(st)
        self.assertIn("PAPER TRADING", self.R[("fresh", "home")]["text"]); self.assertIn(f"${eq:,.2f}", self.R[("fresh", "home")]["text"])
        self.assertIn("$10,000.00", self.R[("empty", "home")]["text"])                    # first-run: starting virtual balance, not fake profit
        self.assertIn("No closed trades yet", self.R[("empty", "history")]["text"]); self.assertIn("No open paper trades", self.R[("empty", "open")]["text"])
        self.assertIn("TAKE-PROFIT", self.R[("fresh", "history")]["text"]); self.assertIn("STOP-LOSS", self.R[("fresh", "history")]["text"])
        self.assertIn("EXECUTOR", self.R[("fresh", "agents")]["text"]); self.assertIn("LP only 0% locked", self.R[("fresh", "agents")]["text"])
        s = self.R[("fresh", "settings")]["text"]; self.assertIn("PAPER TRADING ONLY", s); self.assertIn("not implemented", s)
    def test_stale_and_warning_banners(self):
        self.assertIn("DATA STALE", self.R[("stale", "home")]["view"]); self.assertNotIn("DATA STALE", self.R[("fresh", "home")]["view"])
        self.assertEqual(self.R[("stale", "home")]["dot"].split()[-1], "stale"); self.assertEqual(self.R[("fresh", "home")]["dot"].split()[-1], "ok")
        v = self.R[("paused", "home")]["view"]; self.assertIn("PAUSED", v); self.assertIn("HALTED", v); self.assertIn("STALE price", v)
        self.assertIn("No successful scan yet", self.R[("empty", "home")]["view"])
    def test_untrusted_text_is_never_html(self):
        x = self.R[("nulls", "scanner")]; self.assertIn("<img src=x", x["text"]); self.assertNotIn("img", x["tags"])
    def test_only_safe_links(self):
        for k, x in self.R.items():
            for h in x["hrefs"]: self.assertTrue(h.startswith("#") or re.fullmatch(r"https://dexscreener\.com/solana/[1-9A-HJ-NP-Za-km-z]{32,44}", h), f"{k}: {h}")
if __name__ == "__main__":
    unittest.main()
