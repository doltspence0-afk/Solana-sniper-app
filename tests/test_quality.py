import json, os, tempfile
from support import *
import netclient, settings
NOW = 5000
STRONG = lambda m="S1", **k: pair(m, **k)
WEAK = [pair("W1", age=1), pair("W2", liq=2000), pair("W3", vol=500), pair("W4", ch=120), pair("W5", buys=30, sells=90),
        pair("W6", m5=40), pair("W7", ch=-30), pair("W8", buys=5, sells=5), pair("W9", age=2, liq=1000, vol=10), pair("W10", liq=None)]
run = lambda st, cands, **k: b.run(st, k.pop("now", NOW), cands, k.pop("rc", lambda m: GOOD), cfg=k.pop("cfg", NOCFG))

class Gates(Base):
    def test_clean_candidate_passes(self): self.assertEqual(b.gates(pair(), NOW), [])
    def test_every_failure_is_listed(self):
        p = pair(age=1, liq=1000, vol=100, ch=120, buys=10, sells=40, m5=30); text = " | ".join(b.gates(p, NOW))
        for k in ("too new", "liquidity", "24h volume", "chasing: +120% in 1h", "chasing: +30% in 5m", "thin activity"): self.assertIn(k, text)
    def test_individual_rules(self):
        self.assertIn("sell pressure", b.gates(pair(buys=100, sells=100), NOW)[0]); self.assertIn("falling", b.gates(pair(ch=-20), NOW)[0])
        self.assertIn("chasing: +200% in 6h", " ".join(b.gates({**pair(), "priceChange": dict(h1=10, m5=1, h6=200)}, NOW)))
        self.assertEqual(b.gates(pair(liq=None), NOW), ["market data incomplete"]); self.assertIn("token age unknown", b.gates({**pair(), "pairCreatedAt": None}, NOW))

class Authorities(Base):
    def rpc(self, result, status=200):
        b.CLIENT = netclient.Client(opener=lambda u, h, d=None: (status, json.dumps(result).encode(), {}), sleep=lambda s: None, clock=Clk().clock, jitter=False)
        return REAL_AUTH("M" * 40)
    def acct(self, prog="spl-token", mint=None, freeze=None): return {"result": {"value": {"data": {"program": prog, "parsed": {"info": {"mintAuthority": mint, "freezeAuthority": freeze}}}}}}
    def test_renounced_is_clean(self): self.assertEqual(b.auth_fails(self.rpc(self.acct())), [])
    def test_active_authorities_fail(self):
        f = " ".join(b.auth_fails(self.rpc(self.acct(mint="X", freeze="Y")))); self.assertIn("mint authority", f); self.assertIn("freeze authority", f)
    def test_token_2022_rejected(self): self.assertIn("spl-token-2022", b.auth_fails(self.rpc(self.acct(prog="spl-token-2022")))[0])
    def test_unverifiable_is_none(self):
        self.assertIsNone(self.rpc({"result": {"value": None}})); self.assertIsNone(self.rpc({}, 503)); self.assertIsNone(b.auth_fails(None))
    def test_request_is_a_documented_rpc_call(self):
        seen = []
        b.CLIENT = netclient.Client(opener=lambda u, h, d=None: (seen.append((u, json.loads(d))) or (200, b"{}", {})), sleep=lambda s: None, clock=Clk().clock)
        REAL_AUTH("M" * 40); self.assertEqual(seen[0][1]["method"], "getAccountInfo"); self.assertEqual(seen[0][1]["params"][1], {"encoding": "jsonParsed"})

class Scoring(Base):
    def test_components_sum_and_are_bounded(self):
        d = b.score_detail(pair(), GOOD, NOW); self.assertAlmostEqual(d["total"], sum(v for v, _ in d["parts"].values()), 1)
        self.assertEqual(len(d["parts"]), 7); self.assertEqual(sum(m for _, m in d["parts"].values()), 100); self.assertTrue(75 <= d["total"] <= 100)
        self.assertEqual(b.score(pair(), GOOD, NOW), d["total"])
    def test_chasing_and_sell_pressure_score_lower(self):
        base = b.score(pair(), GOOD, NOW)
        self.assertLess(b.score(pair(ch=70), GOOD, NOW), base); self.assertLess(b.score(pair(buys=110, sells=150), GOOD, NOW), base)
        self.assertLess(b.score(pair(), dict(GOOD, risks=[dict(level="warn")] * 2), NOW), base)

class Sizing(Base):
    def setUp(self): super().setUp(); b.CFG.update(b.CFG_DEFAULTS)
    def test_binding_limits(self):
        st = b.new_state()
        self.assertEqual(b.plan_size(st, pair(liq=100000))[1], "cash %")
        self.assertEqual(b.plan_size(st, pair(liq=20000)), (200.0, "price impact"))      # 1% of liquidity
        self.assertEqual(b.plan_size(st, pair(liq=3000))[0], 0.0)                         # below $50 -> no trade
        b.CFG["risk_pct"] = 0.002; self.assertEqual(b.plan_size(st, pair())[1], "risk budget")
    def test_exposure_cap(self):
        b.CFG.update(b.CFG_DEFAULTS); st = b.new_state(); st["positions"] = [dict(cost=2950.0, qty=1, last=1.0)]; st["balance"] = 7050.0
        self.assertEqual(b.plan_size(st, pair()), (0.0, "exposure cap"))

class QualityOverQuantity(Base):
    def test_zero_trades_when_nothing_qualifies_and_every_rejection_is_explained(self):
        st = b.new_state(); run(st, WEAK)
        self.assertEqual((len(st["positions"]), st["traded"], st["balance"]), (0, [], 10000.0))
        self.assertEqual(len(st["evals"]), 10); self.assertTrue(all(e["fails"] and e["verdict"] in ("reject", "unverified") for e in st["evals"]))
        self.assertEqual(len(st["rejected"]), 10); self.assertTrue(all(r["reason"] for r in st["rejected"])); self.assertEqual(st["run_status"], "ok")
    def test_buys_only_the_strong_one(self):
        st = b.new_state(); run(st, WEAK + [STRONG()])
        self.assertEqual(st["traded"], ["S1"]); e = st["evals"][0]; self.assertEqual((e["verdict"], e["mint"]), ("bought", "S1")); self.assertGreaterEqual(e["score"], 75)
        self.assertIn("size $", e["fails"][0]); self.assertAlmostEqual(st["positions"][0]["cost"], 1000.0)
    def test_unreadable_authorities_means_no_trade(self):
        b.authorities = lambda m: None; st = b.new_state(); run(st, [STRONG()])
        self.assertEqual(st["traded"], []); self.assertEqual(st["evals"][0]["verdict"], "unverified")
    def test_active_mint_authority_rejects(self):
        b.authorities = lambda m: dict(program="spl-token", mint="Z", freeze=None); st = b.new_state(); run(st, [STRONG()])
        self.assertEqual(st["traded"], []); self.assertIn("mint authority", st["evals"][0]["fails"][0])
    def test_low_score_rejected_with_breakdown(self):
        st = b.new_state(); run(st, [STRONG()], cfg=dict(paused=False, settings=dict(min_score=95)))
        self.assertEqual(st["traded"], []); self.assertIn("score", st["evals"][0]["fails"][0]); self.assertEqual(len(st["evals"][0]["parts"]), 7)
    def test_paused_still_evaluates_but_marks_qualified(self):
        st = b.new_state(); run(st, [STRONG()], cfg=dict(paused=True, settings={})); self.assertEqual((st["traded"], st["evals"][0]["verdict"]), ([], "qualified"))
    def test_data_quality_suspends_entries(self):
        cands = [pair(f"Q{i}") for i in range(6)] + [STRONG()]; st = b.new_state(); run(st, cands, rc=lambda m: None)
        self.assertEqual(st["traded"], []); self.assertIn("RugCheck unavailable", st["dq_block"])
    def test_too_few_candidates_suspends_and_total_outage_is_flagged(self):
        b.fetch_pairs = lambda m: {"S1": STRONG()}; b.get = lambda *a, **k: None; st = b.new_state(); b.run(st, NOW, None, lambda m: GOOD, cfg=NOCFG)
        self.assertIn("too few candidates", st["dq_block"]); self.assertEqual(st["traded"], [])
        b.fetch_pairs = lambda m: {}; st = b.new_state(); b.run(st, NOW, None, lambda m: GOOD, cfg=NOCFG)
        self.assertIn("SCOUT", st["warnings"][-1]["msg"]); self.assertEqual((st["run_status"], st["consec_fail"], st["last_ok"]), ("no market data", 1, None))
    def test_fees_recorded_on_closed_trades(self):
        st = b.new_state(); run(st, [STRONG()]); b.fetch_pairs = lambda m: {"S1": pair("S1", price=1.3)}; b.manage(st, NOW + 60)
        c = st["closed"][0]; self.assertGreater(c["fees"], 0); self.assertEqual(c["reason"], "TAKE-PROFIT")

class ForwardEvidence(Base):
    def test_pending_to_stats_without_lookahead(self):
        st = b.new_state(); run(st, [STRONG(), pair("W1", age=1)])
        self.assertEqual([i["mint"] for i in st["shadow"]["pending"]], ["S1"])       # only candidates that passed the cheap gates
        b.fetch_pairs = lambda ms: {"S1": pair("S1", price=1.05)}
        b.shadow_update(st, NOW + 1800, b.fetch_pairs([])); self.assertIsNone(st["shadow"]["pending"][0].get("r1"))
        b.shadow_update(st, NOW + 3700, b.fetch_pairs([])); self.assertAlmostEqual(st["shadow"]["pending"][0]["r1"], 5.0, 1)
        b.shadow_update(st, NOW + 22000, b.fetch_pairs([]))
        self.assertEqual(st["shadow"]["pending"], []); self.assertEqual(st["shadow"]["stats"]["bought"]["n"], 1)

class Halt(Base):
    def test_emergency_stop_flattens_blocks_and_clears(self):
        st = b.new_state(); run(st, [STRONG()]); self.assertEqual(len(st["positions"]), 1)
        b.fetch_pairs = lambda m: {"S1": pair("S1", price=1.01)}
        run(st, [pair("S2")], cfg=dict(paused=False, settings={}, halt=True, clear_halt_ts=0), now=NOW + 900)
        self.assertEqual(st["positions"], []); self.assertTrue(st["halted"]); self.assertTrue(st["closed"][0]["reason"].startswith("HALT")); self.assertNotIn("S2", st["traded"])
        run(st, [pair("S2")], cfg=dict(paused=False, settings={}, halt=True, clear_halt_ts=0), now=NOW + 1800); self.assertNotIn("S2", st["traded"])
        run(st, [pair("S2")], cfg=dict(paused=False, settings={}, halt=False, clear_halt_ts=NOW + 2000), now=NOW + 2700)
        self.assertFalse(st["halted"]); self.assertIn("S2", st["traded"])
    def test_halt_commands(self):
        p = os.path.join(tempfile.mkdtemp(), "c.json")
        self.assertTrue(settings.apply_command("halt", "", p, 5)["halt"]); c = settings.apply_command("clear_halt", "", p, 9)
        self.assertEqual((c["halt"], c["clear_halt_ts"]), (False, 9)); self.assertTrue(settings.load(p)["halt"] is False)
        self.assertFalse(settings.apply_command("resume", "", p, 10)["halt"])

class Heartbeat(Base):
    def test_run_history_and_failure_heartbeat(self):
        st = b.new_state()
        for i in range(3): run(st, [pair("W1", age=1)], now=NOW + i * 900)
        self.assertEqual(st["run_hist"], [NOW, NOW + 900, NOW + 1800]); self.assertEqual((st["run_status"], st["consec_fail"]), ("ok", 0))
        b.heartbeat(st, "self-test failed", NOW + 2700); self.assertEqual((st["run_status"], st["consec_fail"], st["last_run"]), ("failed: self-test failed", 1, NOW + 2700))
        self.assertEqual(st["last_ok"], NOW + 1800)      # a failed run must not look like a successful scan
        run(st, [pair("W1", age=1)], now=NOW + 3600); self.assertEqual((st["run_status"], st["consec_fail"]), ("ok", 0))
    def test_old_deployed_state_still_loads(self):
        old = {k: v for k, v in b.new_state().items() if k in ("mode", "balance", "peak", "day", "day_start", "trades_today", "positions", "closed", "rejected", "decisions", "traded", "halted", "halt_reason", "warnings", "last_scan", "last_ok", "scanned")}
        p = os.path.join(tempfile.mkdtemp(), "s.json"); json.dump(old, open(p, "w")); st = b.load(p, p + ".bak")
        for k in b.EXTRA(): self.assertIn(k, st)
        run(st, [pair("W1", age=1)]); b.save(st, p, p + ".bak")
if __name__ == "__main__":
    import unittest; unittest.main()
