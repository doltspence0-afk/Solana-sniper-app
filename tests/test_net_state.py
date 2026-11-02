import json, os, tempfile
from support import *
import netclient

def opener_seq(seq, log=None, clk=None):
    it = iter(seq)
    def op(url, h):
        if log is not None: log.append((clk.t if clk else 0, url, dict(h)))
        s = next(it); body = json.dumps(s[1]).encode() if len(s) > 1 and not isinstance(s[1], bytes) else (s[1] if len(s) > 1 else b"")
        return s[0], body, (s[2] if len(s) > 2 else {})
    return op

def client(seq, clk, **kw):
    kw.setdefault("min_gap", {"api.dexscreener.com": 0.0}); kw.setdefault("jitter", False)
    return netclient.Client(opener=opener_seq(seq, kw.pop("log", None), clk), sleep=clk.sleep, clock=clk.clock, **kw)
U = "https://api.dexscreener.com/x"

class NetTests(Base):
    def test_429_retry_after(self):
        k = Clk(); c = client([(429, {}, {"Retry-After": "2"}), (200, {"a": 1})], k)
        self.assertEqual(c.get_json(U), {"a": 1}); self.assertEqual(k.sleeps, [2.0]); self.assertEqual(c.stats["api.dexscreener.com"], {"429": 1, "ok": 1})
    def test_exponential_backoff_on_5xx(self):
        k = Clk(); c = client([(500,), (503,), (200, [])], k); self.assertEqual(c.get_json(U), []); self.assertEqual(k.sleeps, [1.0, 2.0])
    def test_retry_after_is_capped(self):
        k = Clk(); c = client([(429, {}, {"Retry-After": "9999"}), (200, {})], k, cap=30.0); c.get_json(U); self.assertEqual(k.sleeps, [30.0])
    def test_no_retry_on_404_and_bad_json(self):
        k = Clk(); calls = []; c = client([(404,)], k, log=calls); self.assertIsNone(c.get_json(U)); self.assertEqual(len(calls), 1)
        c = client([(200, b"<html>")], k, log=calls); self.assertIsNone(c.get_json(U)); self.assertEqual(c.stats["api.dexscreener.com"], {"ok": 1, "badjson": 1})
    def test_gives_up_after_retries_and_network_errors_retried(self):
        k = Clk(); calls = []; c = client([(0,), (0,), (503,), (503,)], k, retries=3, log=calls)
        self.assertIsNone(c.get_json(U)); self.assertEqual(len(calls), 4)
    def test_min_gap_between_calls(self):
        k = Clk(); calls = []; c = client([(200, {}), (200, {})], k, min_gap={"api.dexscreener.com": 1.2}, log=calls)
        c.get_json(U); c.get_json(U); self.assertGreaterEqual(calls[1][0] - calls[0][0], 1.2 - 1e-9)
    def test_sleep_budget(self):
        k = Clk(); c = client([(500,)] * 4, k, budget=0.5); self.assertIsNone(c.get_json(U)); self.assertIn("budget", c.stats["api.dexscreener.com"])
    def test_jitter_within_bounds(self):
        k = Clk(); c = client([(500,), (200, {})], k, jitter=True); c.get_json(U); self.assertTrue(0.5 <= k.sleeps[0] <= 1.0)

DEX_PROFILES = [dict(chainId="solana", tokenAddress="T1"), dict(chainId="ethereum", tokenAddress="E1"), dict(chainId="solana", tokenAddress="T2")]
DEX_PAIRS = [pair("T1", liq=1000), pair("T1", liq=90000, price=2.5), dict(baseToken=dict(address="T2", symbol="T2"), priceUsd=None, liquidity=None, volume=None, priceChange=None)]

class MarketIntegration(Base):
    def setUp(self):
        super().setUp(); self.k = Clk(); self.calls = []
        def op(url, h):
            self.calls.append((url, dict(h)))
            if "token-profiles" in url: return 200, json.dumps(DEX_PROFILES).encode(), {}
            if "token-boosts" in url: return 200, b"[]", {}
            if "/tokens/v1/solana/" in url: return 200, json.dumps(DEX_PAIRS).encode(), {}
            if "rugcheck" in url: return 200, json.dumps(GOOD).encode(), {}
            return 404, b"", {}
        b.CLIENT = netclient.Client(opener=op, sleep=self.k.sleep, clock=self.k.clock, jitter=False)
    def test_scout_parses_documented_shapes(self):
        ps = b.scout(); self.assertEqual({p["baseToken"]["address"] for p in ps}, {"T1", "T2"})
        self.assertEqual([p for p in ps if p["baseToken"]["address"] == "T1"][0]["priceUsd"], "2.5")  # best-liquidity pair
        self.assertTrue(all("E1" not in u for u, _ in self.calls))                                    # non-Solana ignored
    def test_null_fields_become_unverified_not_crash(self):
        st = b.new_state(); b.run(st, 5000, cfg=NOCFG)
        self.assertTrue(any(r["symbol"] == "T2" and r["verdict"] == "unverified" for r in st["rejected"]))
        self.assertTrue(all(isinstance(x["price"], (float, type(None))) for x in st["scanned"]))
        self.assertTrue(st["last_ok"])
    def test_rugcheck_key_only_sent_if_set_and_never_saved(self):
        os.environ.pop("RUGCHECK_API_KEY", None); self.assertIsNone(b.rc_headers())
        os.environ["RUGCHECK_API_KEY"] = "sekrit-key-123456"
        try:
            st = b.new_state(); b.run(st, 5000, cfg=NOCFG); b.log(st, "warnings", msg="oops sekrit-key-123456")
            self.assertTrue(any(h.get("X-API-KEY") == "sekrit-key-123456" for u, h in self.calls if "rugcheck" in u))
            p = os.path.join(tempfile.mkdtemp(), "s.json"); b.save(st, p, p + ".bak"); self.assertNotIn("sekrit-key", open(p).read())
        finally: os.environ.pop("RUGCHECK_API_KEY", None)
    def test_outage_is_survivable(self):
        b.CLIENT = netclient.Client(opener=lambda u, h: (503, b"", {}), sleep=self.k.sleep, clock=self.k.clock, jitter=False)
        st = b.new_state(); b.run(st, 5000, cfg=NOCFG); self.assertIsNone(st["last_ok"]); self.assertTrue(st["warnings"])

class StateTests(Base):
    def paths(self): d = tempfile.mkdtemp(); return os.path.join(d, "s.json"), os.path.join(d, "bak.json")
    def test_backup_restore_and_refusal_to_reset(self):
        p, bk = self.paths(); st = populated_state(); b.save(st, p, bk); st["balance"] -= 1; b.save(st, p, bk)
        open(p, "w").write('{"balance": 1, "tru'); r = b.load(p, bk)             # truncated write -> backup
        self.assertEqual(len(r["closed"]), 2); self.assertTrue(any("restored" in w["msg"] for w in r["warnings"]))
        open(bk, "w").write("garbage")
        with self.assertRaises(b.StateCorrupt): b.load(p, bk)                    # never silently resets balances
        os.remove(p); 
        with self.assertRaises(b.StateCorrupt): b.load(p, bk)
        os.remove(bk); self.assertEqual(b.load(p, bk)["balance"], 10000.0)       # genuine first run
    def test_invalid_state_is_never_written(self):
        p, bk = self.paths(); st = b.new_state(); b.save(st, p, bk); good = open(p).read()
        for field, val in (("balance", float("nan")), ("balance", -5), ("positions", "x"), ("halted", 1)):
            bad = b.new_state(); bad[field] = val
            with self.assertRaises(b.StateCorrupt): b.save(bad, p, bk)
        self.assertEqual(open(p).read(), good)
    def test_roundtrip_balances_positions_and_no_duplicates_after_restart(self):
        p, bk = self.paths(); st = populated_state(); b.save(st, p, bk); st2 = b.load(p, bk)
        self.assertEqual((st2["balance"], st2["positions"], st2["traded"]), (st["balance"], st["positions"], st["traded"]))
        b.fetch_pairs = lambda m: {}; b.run(st2, 9000, [pair("WIN")], lambda m: GOOD, cfg=NOCFG)   # restart must not re-buy
        self.assertEqual(st2["traded"].count("WIN"), 1)
if __name__ == "__main__":
    import unittest; unittest.main()
