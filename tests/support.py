import os, sys, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bot"))
import main as b

def pair(m="M1", liq=100000, vol=90000, ch=10, price=1.0, buys=200, sells=80, pa=None, age=24, now=5000, m5=1.0):
    return dict(baseToken=dict(address=m, symbol=m), priceUsd=str(price), liquidity=dict(usd=liq), pairAddress=pa or m * 2,
                volume=dict(h24=vol), priceChange=dict(h1=ch, m5=m5, h6=ch), txns=dict(h1=dict(buys=buys, sells=sells)),
                pairCreatedAt=int((now - age * 3600) * 1000))
GOOD = dict(markets=[dict(pubkey="AMM", lp=dict(lpLockedPct=100))], topHolders=[dict(address="AMM", pct=40), dict(address="a", pct=5)], risks=[])
NOCFG = dict(paused=False, settings={})

class Clk:
    def __init__(s): s.t = 0.0; s.sleeps = []
    def clock(s): return s.t
    def sleep(s, x): s.sleeps.append(x); s.t += x

REAL_AUTH = b.authorities
OK_AUTH = lambda m: dict(program="spl-token", mint=None, freeze=None)

class Base(unittest.TestCase):
    """Hermetic: never reads the live config.json / HALT file, never touches the network."""
    def setUp(self):
        import tempfile
        self._o = (b.get, b.fetch_pairs, b.CLIENT, dict(b.CFG), b.authorities, b.CFG_PATH, b.ROOT)
        b.authorities = OK_AUTH; b.CFG_PATH = "/nonexistent/config.json"; b.ROOT = tempfile.mkdtemp()
    def tearDown(self):
        b.get, b.fetch_pairs, b.CLIENT = self._o[:3]; b.CFG.clear(); b.CFG.update(self._o[3]); b.authorities, b.CFG_PATH, b.ROOT = self._o[4:]

def populated_state():
    """Real engine output: one TP win, one SL loss, one open position, with equity history."""
    st = b.new_state(); o = (b.fetch_pairs, dict(b.CFG))
    try:
        for i, m in enumerate(("WIN", "LOSE", "OPEN")):
            b.buy(st, pair(m, price=1.0), 1000 + i)
        b.fetch_pairs = lambda ms: {"WIN": pair("WIN", price=1.25), "LOSE": pair("LOSE", price=0.9), "OPEN": pair("OPEN", price=1.03)}
        b.manage(st, 2000)
        st["last_ok"] = 2000; st["last_scan"] = 2000
        st["eq_hist"] = [[1000, 10000.0], [1500, 10020.0], [2000, round(b.equity(st), 4)]]
        st["scanned"] = [dict(pair="P" * 44, symbol="AAA", mint="a", price=1.5, liq=90000.0, vol=120000.0, ch1h=12.0, mc=None, verdict="reject", why="LP only 0% locked", age_h=3.2)]
        b.log(st, "rejected", symbol="AAA", mint="a", verdict="reject", reason="LP only 0% locked")
    finally:
        b.fetch_pairs = o[0]
    return st
