import json, os, tempfile
from support import *
import settings

class T(Base):
    def p(self): return os.path.join(tempfile.mkdtemp(), "config.json")
    def test_bounds_and_types(self):
        self.assertEqual(settings.clean({"sl": 0.03, "max_open": 2}), {"sl": 0.03, "max_open": 2})
        for bad in ({"sl": 0.5}, {"sl": 0.001}, {"nope": 1}, {"sl": True}, {"sl": "0.05"}, {"max_open": 2.5}, {"tp": float("nan")}, [], {"min_vol": 5}):
            with self.assertRaises(ValueError, msg=str(bad)): settings.clean(bad)
    def test_commands(self):
        p = self.p()
        self.assertTrue(settings.apply_command("pause", "", p, 5)["paused"])
        self.assertFalse(settings.apply_command("resume", "", p, 6)["paused"])
        c = settings.apply_command("settings", json.dumps({"sl": 0.02}), p, 7); self.assertEqual(c["settings"], {"sl": 0.02})
        self.assertEqual(settings.load(p)["settings"], {"sl": 0.02})
        with self.assertRaises(ValueError): settings.apply_command("settings", '{"sl": 9}', p, 8)
        with self.assertRaises(ValueError): settings.apply_command("settings", "not json", p, 8)
        with self.assertRaises(ValueError): settings.apply_command("trade_for_real", "", p, 8)
        self.assertEqual(settings.load(p)["settings"], {"sl": 0.02})  # rejected commands change nothing
        self.assertEqual(settings.apply_command("reset_settings", "", p, 9)["settings"], {})
    def test_invalid_config_fails_safe_paused(self):
        p = self.p(); open(p, "w").write('{"paused": false, "settings": {"sl": 99}}')
        self.assertTrue(settings.load(p)["paused"]); open(p, "w").write("{broken")
        self.assertTrue(settings.load(p)["paused"])
        self.assertFalse(settings.load("/nonexistent/c.json")["paused"])
    def test_run_applies_settings_and_resets(self):
        b.fetch_pairs = lambda m: {}
        st = b.new_state(); b.run(st, 5000, [pair("A")], lambda m: GOOD, cfg=dict(paused=False, settings=dict(sl=0.02, max_open=1)))
        self.assertEqual(st["cfg"]["sl"], 0.02); self.assertEqual(len(st["positions"]), 1)
        b.fetch_pairs = lambda m: {"A": pair("A", price=0.97)}   # -3% => stop at 2%
        b.run(st, 5100, [pair("Z", vol=1)], cfg=dict(paused=False, settings=dict(sl=0.02, max_open=1)))
        self.assertEqual(st["closed"][0]["reason"], "STOP-LOSS")
        b.run(st, 5200, [pair("Z", vol=1)], cfg=NOCFG); self.assertEqual(st["cfg"]["sl"], 0.05)  # back to default
        self.assertTrue(any(d["agent"] == "CONTROL" and "sl=0.05" in d["msg"] for d in st["decisions"]))  # audit trail
        self.assertEqual(b.CFG["sl"], 0.05)
    def test_pause_blocks_entries_but_still_exits(self):
        st = b.new_state(); b.fetch_pairs = lambda m: {}
        b.run(st, 5000, [pair("A")], lambda m: GOOD, cfg=NOCFG); self.assertEqual(len(st["positions"]), 1)
        b.fetch_pairs = lambda m: {"A": pair("A", price=1.3)}
        b.run(st, 5100, [pair("B")], lambda m: GOOD, cfg=dict(paused=True, settings={}))
        self.assertEqual(st["closed"][0]["reason"], "TAKE-PROFIT"); self.assertEqual(len(st["positions"]), 0)
        self.assertNotIn("B", st["traded"]); self.assertTrue(st["paused"])
        self.assertTrue(any("PAUSED" in d["msg"] for d in st["decisions"]))
        self.assertTrue(any("paused by user" in d["msg"] for d in st["decisions"]))
    def test_js_and_python_bounds_agree(self):
        import shutil, subprocess
        if not shutil.which("node"): self.skipTest("node missing")
        out = subprocess.run(["node", os.path.join(ROOT, "tests", "calc_cli.js")], input=json.dumps({"fn": "SETTINGS", "args": []}), capture_output=True, text=True).stdout
        js = {d["key"]: d for d in json.loads(out)}
        self.assertEqual(set(js), set(settings.BOUNDS))
        for k, (lo, hi) in settings.BOUNDS.items():
            self.assertEqual((js[k]["min"], js[k]["max"]), (lo, hi), k)
            self.assertEqual(js[k]["def"], b.CFG_DEFAULTS[k], k)   # app defaults == engine defaults
if __name__ == "__main__":
    import unittest; unittest.main()
