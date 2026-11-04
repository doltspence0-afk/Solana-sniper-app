import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bot"))
import main as b

from support import pair, GOOD, OK_AUTH
import tempfile as _tf

class T(unittest.TestCase):
    def setUp(self): self._o = (b.get, b.fetch_pairs, b.CLIENT, b.authorities, b.CFG_PATH, b.ROOT); b.authorities = OK_AUTH; b.CFG_PATH = '/nonexistent/c.json'; b.ROOT = _tf.mkdtemp()
    def tearDown(self): b.get, b.fetch_pairs, b.CLIENT, b.authorities, b.CFG_PATH, b.ROOT = self._o
    def st_with_pos(self, entry=1.0):
        st = b.new_state(); b.buy(st, pair(price=entry), 1000); return st
    def test_filter_ok_and_rejects(self):
        self.assertEqual(b.filt(pair(), lambda: GOOD)[0], "ok")
        self.assertIn("volume", b.filt(pair(vol=1000), lambda: GOOD)[1])
        self.assertIn("1h", b.filt(pair(ch=95), lambda: GOOD)[1])
        bad = dict(GOOD, topHolders=[dict(address="x", pct=31)]); self.assertIn("top10", b.filt(pair(), lambda: bad)[1])
        unl = dict(GOOD, markets=[dict(pubkey="AMM", lp=dict(lpLockedPct=0))]); self.assertEqual(b.filt(pair(), lambda: unl)[0], "reject")
        dg = dict(GOOD, risks=[dict(name="Mint Authority", level="danger")]); self.assertEqual(b.filt(pair(), lambda: dg)[0], "reject")
    def test_missing_data_unverified(self):
        self.assertEqual(b.filt(dict(baseToken={}), lambda: GOOD)[0], "unverified")
        self.assertEqual(b.filt(pair(), lambda: None)[0], "unverified")
        self.assertEqual(b.filt(pair(), lambda: dict(markets=[], topHolders=None))[0], "unverified")
    def test_stop_loss_gaps(self):
        st = self.st_with_pos(); b.fetch_pairs = lambda m: {"M1": pair(price=0.80)}
        b.manage(st, 1100); c = st["closed"][0]
        self.assertEqual(c["reason"], "STOP-LOSS"); self.assertLess(c["exit"], 0.80)
        self.assertEqual(st["positions"], [])
    def test_take_profit(self):
        st = self.st_with_pos(); b.fetch_pairs = lambda m: {"M1": pair(price=1.2)}
        b.manage(st, 1100); self.assertEqual(st["closed"][0]["reason"], "TAKE-PROFIT"); self.assertGreater(st["closed"][0]["pnl"], 0)
    def test_no_exit_inside_band_and_stale(self):
        st = self.st_with_pos(); b.fetch_pairs = lambda m: {"M1": pair(price=1.0)}; b.manage(st, 1100)
        self.assertEqual(len(st["positions"]), 1)
        b.fetch_pairs = lambda m: {}; b.manage(st, 1100 + 5000)
        self.assertEqual(len(st["positions"]), 1); self.assertTrue(st["warnings"])
    def test_daily_trade_limit_and_duplicate(self):
        b.fetch_pairs = lambda m: {}
        st = b.new_state(); cands = [pair(m=f"T{i}") for i in range(5)]
        b.run(st, 5000, cands, lambda m: GOOD)
        self.assertEqual(len(st["positions"]), 3)
        b.run(st, 5001, cands, lambda m: GOOD); self.assertEqual(len(st["traded"]), len(set(st["traded"])))
    def test_drawdown_halts(self):
        st = self.st_with_pos(); st["positions"][0]["last"] = 0.01; st["balance"] = 7000; b.fetch_pairs = lambda m: {}
        b.manage(st, 1100); self.assertTrue(st["halted"]); self.assertIn("halted", b.can_enter(st))
    def test_persistence_roundtrip(self):
        st = self.st_with_pos(); d = tempfile.mkdtemp(); p, bk = os.path.join(d, "s.json"), os.path.join(d, "s.bak.json"); b.save(st, p, bk)
        st2 = b.load(p, bk); self.assertEqual(st2["balance"], st["balance"]); self.assertEqual(st2["traded"], ["M1"])
        self.assertEqual(b.load("/nonexistent/x.json", "/nonexistent/x.bak.json")["balance"], 10000.0)
    def test_scout_outage(self):
        b.get = lambda *a, **k: None; st = b.new_state(); b.run(st, 5000); self.assertTrue(st["warnings"]); self.assertEqual(st["positions"], [])
    def test_fees_reduce_equity(self):
        st = self.st_with_pos(); self.assertLess(b.equity(st), 10000.0 + 1e-9)
if __name__ == "__main__": unittest.main()
