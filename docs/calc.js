/* Pure logic shared by the app and the tests (run under Node). No DOM access here. */
var CALC = (function () {
  var SETTINGS = [
    { key: "size_pct", label: "Position size (% of cash)", min: 0.01, max: 0.20, step: 0.005, pct: 1, def: 0.10 },
    { key: "sl", label: "Stop-loss (%)", min: 0.01, max: 0.20, step: 0.005, pct: 1, def: 0.05 },
    { key: "tp", label: "Take-profit (%)", min: 0.02, max: 0.50, step: 0.005, pct: 1, def: 0.10 },
    { key: "max_trades_day", label: "Max new trades per day", min: 1, max: 10, step: 1, def: 3 },
    { key: "max_open", label: "Max open positions", min: 1, max: 5, step: 1, def: 3 },
    { key: "daily_loss_pct", label: "Daily loss limit (%)", min: 0.01, max: 0.10, step: 0.005, pct: 1, def: 0.03 },
    { key: "max_dd_pct", label: "Max drawdown shutdown (%)", min: 0.05, max: 0.30, step: 0.01, pct: 1, def: 0.15 },
    { key: "min_vol", label: "Min 24h volume ($)", min: 10000, max: 10000000, step: 1000, def: 40000 },
    { key: "min_liq", label: "Min liquidity ($)", min: 5000, max: 10000000, step: 1000, def: 20000 },
    { key: "max_top10", label: "Max top-10 holders (%)", min: 5, max: 50, step: 1, def: 30 },
    { key: "min_score", label: "Min analyst score", min: 50, max: 95, step: 1, def: 70 }
  ];
  var sum = function (a) { return a.reduce(function (x, y) { return x + y; }, 0); };
  function summarize(s) {
    var start = typeof s.start === "number" ? s.start : 10000;
    var open = sum(s.positions.map(function (p) { return p.qty * p.last; }));
    var eq = s.balance + open;
    return { start: start, equity: eq, openValue: open, total: eq - start,
             today: eq - (typeof s.day_start === "number" ? s.day_start : start) };
  }
  function maxDrawdownPct(h) {
    var peak = -Infinity, mdd = 0;
    (h || []).forEach(function (pt) { peak = Math.max(peak, pt[1]); if (peak > 0) mdd = Math.max(mdd, (peak - pt[1]) / peak * 100); });
    return mdd;
  }
  function perf(s) {
    var pn = s.closed.map(function (c) { return c.pnl; });
    var w = pn.filter(function (x) { return x > 0; }), l = pn.filter(function (x) { return x <= 0; });
    var gw = sum(w), gl = -sum(l);
    return { n: pn.length, wins: w.length, losses: l.length, realised: sum(pn),
             winRate: pn.length ? w.length / pn.length * 100 : null,
             avgWin: w.length ? gw / w.length : null, avgLoss: l.length ? -gl / l.length : null,
             best: pn.length ? Math.max.apply(null, pn) : null, worst: pn.length ? Math.min.apply(null, pn) : null,
             profitFactor: gl > 0 ? gw / gl : null, maxDrawdownPct: maxDrawdownPct(s.eq_hist) };
  }
  function freshness(s, nowSec) {
    if (!s || !s.last_ok) return { level: "never", ageMin: null };
    var a = (nowSec - s.last_ok) / 60;
    return { level: a <= 30 ? "ok" : a <= 90 ? "warn" : "stale", ageMin: a };
  }
  function positionStale(p, nowSec) { return (nowSec - p.last_seen) > 900; }
  function validate(obj) {
    var errs = [];
    SETTINGS.forEach(function (d) {
      if (!(d.key in obj)) return;
      var v = obj[d.key];
      if (typeof v !== "number" || !isFinite(v)) errs.push(d.label + ": enter a number");
      else if (v < d.min - 1e-9 || v > d.max + 1e-9) errs.push(d.label + ": allowed " + (d.pct ? d.min * 100 + "–" + d.max * 100 : d.min + "–" + d.max));
      else if (d.step === 1 && v !== Math.round(v)) errs.push(d.label + ": whole number");
    });
    return errs;
  }
  function money(n) { return (n < 0 ? "-" : "") + "$" + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
  function pct(n) { return (n >= 0 ? "+" : "") + n.toFixed(2) + "%"; }
  function ago(sec) {
    var m = Math.floor(sec / 60);
    if (m < 1) return "just now";
    if (m < 60) return m + " min ago";
    if (m < 1440) return Math.floor(m / 60) + "h " + (m % 60) + "m ago";
    return Math.floor(m / 1440) + "d ago";
  }
  return { SETTINGS: SETTINGS, summarize: summarize, perf: perf, maxDrawdownPct: maxDrawdownPct, freshness: freshness,
           positionStale: positionStale, validate: validate, money: money, pct: pct, ago: ago };
})();
if (typeof module !== "undefined") module.exports = CALC;
