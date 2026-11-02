"use strict";
const NS = "http://www.w3.org/2000/svg", $ = (s) => document.querySelector(s), K = window.CALC;
const el = (t, c, x) => { const e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; };
const kid = (p, ...c) => { c.flat(Infinity).forEach((x) => { if (x) p.append(x); }); return p; };
const svg = (t, a) => { const e = document.createElementNS(NS, t); for (const k in a) e.setAttribute(k, a[k]); return e; };
const LS = { get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); return true; } catch (e) { return false; } },
  del(k) { try { localStorage.removeItem(k); } catch (e) {} } };
let S = null, C = null, cached = false, failed = false, online = true, deferred = null, msgEl = null;
const now = () => Date.now() / 1000, sgn = (n) => (n >= 0 ? "pos" : "neg");
const px = (v) => (v == null ? "–" : v >= 1 ? v.toFixed(4) : v.toPrecision(4));
const num = (v) => (v == null ? "–" : Math.round(v).toLocaleString("en-US"));
const when = (t) => new Date(t * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
const card = (...c) => kid(el("section", "card"), c);
const row = (l, v, cls) => kid(el("div", "row"), el("span", "l", l), el("span", "v " + (cls || ""), v));
const pill = (t, c) => el("span", "pill " + c, t);
const empty = (t) => el("div", "empty", t);

function chart(pts, h) {
  h = h || 120;
  if (!pts || pts.length < 2) return empty("Not enough data yet. Charts fill in as scans run.");
  const W = 320, xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), lo = Math.min(...ys), hi = Math.max(...ys);
  const r = hi - lo || Math.abs(hi) * 0.01 || 1;
  const X = (t) => 6 + ((t - x0) / (x1 - x0 || 1)) * (W - 12), Y = (v) => h - 8 - ((v - lo) / r) * (h - 16);
  const d = pts.map((p, i) => (i ? "L" : "M") + X(p[0]).toFixed(1) + " " + Y(p[1]).toFixed(1)).join("");
  const e = svg("svg", { viewBox: "0 0 " + W + " " + h, class: "chart", role: "img", "aria-label": "chart" });
  e.append(svg("path", { d, fill: "none", stroke: ys[ys.length - 1] >= ys[0] ? "#00e676" : "#ff5252", "stroke-width": 2, "stroke-linejoin": "round" }));
  return e;
}
function bars(vals) {
  if (!vals.length) return empty("No closed trades yet.");
  const W = 320, h = 100, m = Math.max(...vals.map(Math.abs)) || 1, bw = Math.min(18, (W - 8) / vals.length - 2);
  const e = svg("svg", { viewBox: "0 0 " + W + " " + h, class: "chart", role: "img", "aria-label": "profit and loss per trade" });
  e.append(svg("line", { x1: 0, x2: W, y1: h / 2, y2: h / 2, stroke: "#26382c", "stroke-width": 1 }));
  vals.forEach((v, i) => { const bh = Math.max(1, (Math.abs(v) / m) * (h / 2 - 4));
    e.append(svg("rect", { x: 4 + i * (bw + 2), y: v >= 0 ? h / 2 - bh : h / 2, width: bw, height: bh, fill: v >= 0 ? "#00e676" : "#ff5252" })); });
  return e;
}
function dexLink(pair) {
  if (!/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(pair || "")) return null;
  const a = el("a", "link", "Open chart on DexScreener ↗");
  a.setAttribute("href", "https://dexscreener.com/solana/" + pair); a.setAttribute("target", "_blank"); a.setAttribute("rel", "noopener noreferrer");
  return a;
}
function banners() {
  const b = el("div", "banners"), add = (t, c) => b.append(el("div", "banner " + c, t));
  if (!online) add("OFFLINE. No connection." + (S ? " Showing the last data this phone saved." : ""), "warn");
  else if (failed && S) add("Could not refresh. Showing data already loaded.", "warn");
  else if (cached) add("Showing saved data (not fresh).", "warn");
  if (!S) return b;
  const f = K.freshness(S, now());
  if (f.level === "warn") add("Scan delayed: last successful scan " + K.ago((f.ageMin) * 60) + ". GitHub's scheduler is best-effort.", "warn");
  if (f.level === "stale") add("DATA STALE: last successful scan " + K.ago(f.ageMin * 60) + ". Open trades are NOT being monitored right now.", "bad");
  if (f.level === "never") add("No successful scan yet.", "warn");
  if (S.halted) add("HALTED: " + (S.halt_reason || "emergency shutdown") + ". No new trades.", "bad");
  if (S.paused) add("New entries are PAUSED. Open trades are still monitored.", "warn");
  (S.warnings || []).slice(-2).forEach((w) => add("Warning: " + w.msg, "warn"));
  return b;
}
const pages = {
  home() {
    const m = K.summarize(S), p = K.perf(S), v = el("div");
    const hero = card(el("div", "lab", "VIRTUAL EQUITY · PAPER TRADING"), el("div", "big", K.money(m.equity)),
      el("div", "sub " + sgn(m.total), K.money(m.total) + " (" + K.pct((m.total / m.start) * 100) + ") since start"),
      el("div", "sub " + sgn(m.today), "Today " + K.money(m.today) + " (includes unrealised)"));
    hero.classList.add("hero");
    const g = el("div", "grid");
    [["Open trades", S.positions.length + "/" + ((S.cfg || {}).max_open || 3)], ["Trades today", S.trades_today + "/" + ((S.cfg || {}).max_trades_day || 3)],
     ["Win rate", p.winRate == null ? "–" : Math.round(p.winRate) + "%"], ["Cash", K.money(S.balance)]].forEach((x) => g.append(kid(el("div", "tile"), el("span", "l", x[0]), el("b", 0, x[1]))));
    kid(v, hero, card(el("h3", 0, "Equity curve (virtual)"), chart(S.eq_hist)), g,
      card(el("div", "note", "All trades are simulated with virtual money. Prices come from DexScreener's public API. Real-money trading is not implemented in this app.")));
    return v;
  },
  scanner() {
    const v = el("div"); v.append(el("h2", 0, "Coin scanner"));
    if (!S.scanned.length) return kid(v, card(empty("Nothing scanned yet.")));
    S.scanned.forEach((x) => {
      const cls = { bought: "g", ok: "g", reject: "r", unverified: "a" }[x.verdict] || "n";
      v.append(card(kid(el("div", "top"), el("b", 0, x.symbol), pill(x.verdict, cls)),
        row("Price", "$" + px(x.price)), row("1h change", x.ch1h == null ? "–" : K.pct(x.ch1h), x.ch1h == null ? "" : sgn(x.ch1h)),
        row("Liquidity", "$" + num(x.liq)), row("24h volume", "$" + num(x.vol)), row("Age", x.age_h == null ? "–" : x.age_h + " h"),
        x.why ? el("div", "why", x.why) : null, dexLink(x.pair)));
    });
    return v;
  },
  open() {
    const v = el("div"), cfg = S.cfg || {}, sl = cfg.sl || 0.05, tp = cfg.tp || 0.1; v.append(el("h2", 0, "Open trades · paper"));
    if (!S.positions.length) return kid(v, card(empty("No open paper trades.")));
    S.positions.forEach((p) => {
      const val = p.qty * p.last, pnl = val - p.cost, st = K.positionStale(p, now());
      v.append(card(kid(el("div", "top"), el("b", 0, p.symbol), pill(K.pct((pnl / p.cost) * 100), pnl >= 0 ? "g" : "r")),
        row("Unrealised P&L", K.money(pnl), sgn(pnl)), row("Entry (simulated fill)", "$" + px(p.entry)), row("Last price", "$" + px(p.last), st ? "neg" : ""),
        row("Stop ≈", "$" + px(p.entry * (1 - sl))), row("Target ≈", "$" + px(p.entry * (1 + tp))), row("Opened", when(p.opened)),
        st ? el("div", "banner bad", "Price is stale (" + K.ago(now() - p.last_seen) + "). Stops cannot trigger without fresh prices.") : null,
        chart((p.ph || []).map((q) => [q[0], q[1]]), 70),
        el("div", "note", "Exits are only checked when a scan runs, and real fills could be worse than shown.")));
    });
    return v;
  },
  history() {
    const v = el("div"); v.append(el("h2", 0, "Trade history · paper"));
    if (!S.closed.length) return kid(v, card(empty("No closed trades yet.")));
    S.closed.slice(-100).reverse().forEach((c) => v.append(card(kid(el("div", "top"), el("b", 0, c.symbol), pill(c.reason, c.pnl >= 0 ? "g" : "r")),
      row("P&L", K.money(c.pnl) + " (" + K.pct(c.pnl_pct) + ")", sgn(c.pnl)), row("Entry → exit", "$" + px(c.entry) + " → $" + px(c.exit)), row("Closed", when(c.closed)))));
    return v;
  },
  perf() {
    const p = K.perf(S), v = el("div"), f = (x, fn) => (x == null ? "–" : fn(x)); v.append(el("h2", 0, "Performance · paper"));
    kid(v, card(el("h3", 0, "Equity curve (virtual)"), chart(S.eq_hist)),
      card(row("Closed trades", String(p.n)), row("Win rate", f(p.winRate, (x) => x.toFixed(0) + "%")), row("Realised P&L", K.money(p.realised), sgn(p.realised)),
        row("Average win", f(p.avgWin, K.money), "pos"), row("Average loss", f(p.avgLoss, K.money), "neg"), row("Best trade", f(p.best, K.money)), row("Worst trade", f(p.worst, K.money)),
        row("Profit factor", f(p.profitFactor, (x) => x.toFixed(2))), row("Max drawdown (per scan)", p.maxDrawdownPct.toFixed(2) + "%")),
      card(el("h3", 0, "P&L per trade (last 30)"), bars(S.closed.slice(-30).map((c) => c.pnl))),
      card(el("div", "note", "Paper results ignore queueing, failed transactions and MEV. They are not a prediction of real results.")));
    return v;
  },
  agents() {
    const v = el("div"); v.append(el("h2", 0, "Agent activity"));
    const cnt = {}; S.decisions.forEach((d) => { cnt[d.agent] = (cnt[d.agent] || 0) + 1; });
    v.append(card(el("h3", 0, "Recent decisions"), Object.keys(cnt).length ? row("Counts", Object.keys(cnt).map((k) => k + " " + cnt[k]).join(" · ")) : null,
      S.decisions.length ? null : empty("No decisions yet."),
      S.decisions.slice(-30).reverse().map((d) => kid(el("div", "log"), pill(d.agent, "n"), el("span", 0, d.msg), el("small", 0, when(d.t))))));
    v.append(card(el("h3", 0, "Rejected tokens"), S.rejected.length ? null : empty("None yet."),
      S.rejected.slice(-30).reverse().map((r) => kid(el("div", "log"), pill(r.verdict, r.verdict === "unverified" ? "a" : "r"), el("span", 0, r.symbol + ": " + r.reason)))));
    return v;
  },
  more() {
    const v = el("div"); v.append(el("h2", 0, "More"));
    [["#perf", "Performance", "Win rate, drawdown, charts"], ["#agents", "Agent activity", "Decisions and rejections"], ["#settings", "Settings", "Install, controls, limits"]].forEach((x) => {
      const a = el("a", "card linkrow"); a.setAttribute("href", x[0]); kid(a, el("b", 0, x[1]), el("small", 0, x[2])); v.append(a); });
    return v;
  },
  settings: settingsPage
};
const repoInfo = () => ({ o: LS.get("gh_owner") || location.hostname.split(".")[0], r: LS.get("gh_repo") || location.pathname.split("/")[1] || "" });
const validRepo = (o, r) => /^[A-Za-z0-9-]{1,39}$/.test(o) && /^[A-Za-z0-9._-]{1,100}$/.test(r);
const why = (s) => ({ 401: "Token rejected (expired or mistyped).", 403: "Token lacks permission. It needs Actions: Read and write on this repository.",
  404: "Repository or workflow not found. Check owner/repo and that .github/workflows/scan.yml exists.", 422: "GitHub refused the request (workflow not enabled or branch problem)." }[s] || "GitHub returned error " + s);
async function gh(path, opts) {
  const t = LS.get("gh_token"); if (!t) throw new Error("No token saved on this phone.");
  const { o, r } = repoInfo(); if (!validRepo(o, r)) throw new Error("Owner/repo looks invalid.");
  return fetch("https://api.github.com/repos/" + o + "/" + r + path, Object.assign({ headers: { Accept: "application/vnd.github+json", Authorization: "Bearer " + t, "X-GitHub-Api-Version": "2022-11-28" } }, opts || {}));
}
async function dispatch(cmd, payload) {
  const ri = await gh(""); if (!ri.ok) throw new Error(why(ri.status));
  const ref = (await ri.json()).default_branch || "main", t0 = Date.now();
  const d = await gh("/actions/workflows/scan.yml/dispatches", { method: "POST", body: JSON.stringify({ ref, inputs: { command: cmd, payload: payload || "" } }) });
  if (d.status !== 204) throw new Error(why(d.status));
  return t0;
}
async function track(t0, say) {
  for (let i = 0; i < 30; i++) {
    await new Promise((res) => setTimeout(res, i ? 6000 : 3000));
    const x = await gh("/actions/workflows/scan.yml/runs?event=workflow_dispatch&per_page=3");
    if (!x.ok) return say("Command sent, but run status is unavailable: " + why(x.status), "warn");
    const run = (await x.json()).workflow_runs.find((w) => Date.parse(w.created_at) >= t0 - 10000);
    if (!run) { say("Command sent. Waiting for GitHub to start the run…", ""); continue; }
    if (run.status !== "completed") { say("Run " + run.status.replace("_", " ") + "…", ""); continue; }
    if (run.conclusion === "success") { say("Done. This app updates after GitHub Pages redeploys (usually 1–3 min).", "pos"); setTimeout(() => load(true), 90000); return; }
    return say("Run ended: " + run.conclusion + ". Open the Actions tab on GitHub for details (a rejected setting fails the run).", "neg");
  }
  say("Still running. Check the Actions tab.", "warn");
}
function settingsPage() {
  const v = el("div"), say = (t, c) => { if (msgEl) { msgEl.textContent = t; msgEl.className = "msg " + (c || ""); } };
  v.append(el("h2", 0, "Settings"));
  const standalone = matchMedia("(display-mode: standalone)").matches;
  const inst = card(el("h3", 0, "Install app"));
  if (standalone) inst.append(el("div", "msg pos", "Installed. You are using the app."));
  else if (deferred) { const b = el("button", "btn", "Install Sniper Desk"); b.addEventListener("click", async () => { deferred.prompt(); await deferred.userChoice; deferred = null; render(); }); inst.append(b); }
  else inst.append(el("div", "note", "Samsung Internet: tap the menu (≡) → Add page to → Home screen. Chrome: tap ⋮ → Install app (or Add to Home screen)."));
  const has = !!LS.get("gh_token"), { o, r } = repoInfo(), ctl = card(el("h3", 0, "Controls (needs a GitHub token)"));
  ctl.append(el("div", "note", "Buttons here ask GitHub to run your workflow. The token you paste is kept only on this phone and sent only to api.github.com. It is never in the app files or the repository."));
  const io = el("input", "inp"), ir = el("input", "inp"), it = el("input", "inp");
  io.value = o; ir.value = r; it.setAttribute("type", "password"); it.setAttribute("autocomplete", "off"); it.setAttribute("placeholder", has ? "Token saved (hidden)" : "github_pat_…");
  io.setAttribute("aria-label", "GitHub owner"); ir.setAttribute("aria-label", "Repository"); it.setAttribute("aria-label", "Token");
  const save = el("button", "btn alt", "Save"), test = el("button", "btn alt", "Test connection"), forget = el("button", "btn alt", "Forget token");
  save.addEventListener("click", () => {
    if (!validRepo(io.value.trim(), ir.value.trim())) return say("Owner/repo looks invalid.", "neg");
    LS.set("gh_owner", io.value.trim()); LS.set("gh_repo", ir.value.trim());
    const t = it.value.trim(); if (t) { if (!/^[A-Za-z0-9_]{20,255}$/.test(t)) return say("That doesn't look like a GitHub token.", "neg"); LS.set("gh_token", t); it.value = ""; }
    say("Saved on this phone.", "pos"); render();
  });
  test.addEventListener("click", async () => { try { const x = await gh("/actions/workflows/scan.yml"); say(x.ok ? "Connected. Workflow found." : why(x.status), x.ok ? "pos" : "neg"); } catch (e) { say(e.message, "neg"); } });
  forget.addEventListener("click", () => { LS.del("gh_token"); say("Token removed from this phone.", "pos"); render(); });
  const run = (label, cmd, payload, cls) => { const b = el("button", "btn " + (cls || ""), label); if (!has) b.setAttribute("disabled", "disabled");
    b.addEventListener("click", async () => { try { say("Sending…", ""); const t0 = await dispatch(cmd, payload()); await track(t0, say); } catch (e) { say(e.message, "neg"); } }); return b; };
  msgEl = el("div", "msg", has ? "Ready." : "Add a token to enable the buttons below.");
  kid(ctl, el("label", 0, "GitHub username"), io, el("label", 0, "Repository name"), ir, el("label", 0, "Fine-grained token"), it, kid(el("div", "btns"), save, test, forget), msgEl,
    kid(el("div", "btns"), run("Scan now", "scan", () => ""), run(S && S.paused ? "Resume entries" : "Pause entries", S && S.paused ? "resume" : "pause", () => "", "alt")));
  const form = card(el("h3", 0, "Trading limits (paper)")), inputs = {}, eff = (S && S.cfg) || {};
  K.SETTINGS.forEach((d) => { const i = el("input", "inp"); i.setAttribute("inputmode", "decimal"); i.setAttribute("type", "number"); i.setAttribute("step", d.pct ? d.step * 100 : d.step);
    const cur = eff[d.key] != null ? eff[d.key] : d.def; i.value = String(d.pct ? +(cur * 100).toFixed(3) : cur); inputs[d.key] = i;
    form.append(el("label", 0, d.label + "  (" + (d.pct ? d.min * 100 + "–" + d.max * 100 : d.min + "–" + d.max) + ")"), i); });
  const pend = C && S && S.cfg && Object.keys(C.settings || {}).filter((k) => S.cfg[k] !== C.settings[k]);
  if (pend && pend.length) form.append(el("div", "banner warn", "Requested, not yet applied: " + pend.join(", ")));
  const collect = () => { const out = {}; K.SETTINGS.forEach((d) => { const n = parseFloat(inputs[d.key].value); out[d.key] = d.pct ? Math.round((n / 100) * 1e6) / 1e6 : n; }); return out; };
  form.append(kid(el("div", "btns"), run("Apply settings", "settings", () => { const o2 = collect(), e = K.validate(o2); if (e.length) throw new Error(e[0]); return JSON.stringify(o2); }), run("Reset to defaults", "reset_settings", () => "", "alt")),
    el("div", "note", "Limits are re-checked on the server side. Stop-loss, take-profit and filter rules only change within the safe ranges shown."));
  kid(v, inst, ctl, form, card(el("h3", 0, "About"), row("Mode", "PAPER TRADING ONLY"), row("Real-money trading", "not implemented"), row("Data", "DexScreener public API")));
  return v;
}
function nodata() {
  return card(el("h3", 0, failed ? "No data available" : "Waiting for first scan"),
    empty(online ? "state.json could not be loaded yet. If you just deployed, run the workflow once and wait for GitHub Pages." : "You are offline and this phone has no saved data yet."));
}
function render() {
  const r = (location.hash || "#home").slice(1), page = pages[r] || pages.home, f = K.freshness(S, now());
  $("#dot").className = "dot " + f.level; $("#scanage").textContent = S && S.last_ok ? "Last scan " + K.ago(f.ageMin * 60) : "No scan yet";
  let body; try { body = S || r === "settings" || r === "more" ? page() : nodata(); } catch (e) { body = card(el("div", "banner bad", "Display error: " + e.message)); }
  $("#view").replaceChildren(banners(), body);
  const key = ["perf", "agents", "settings"].includes(r) ? "more" : r;
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("on", a.getAttribute("href") === "#" + key));
  document.body.classList.remove("boot");
}
async function load(silent) {
  try {
    const [a, b] = await Promise.all([fetch("state.json?ts=" + Date.now(), { cache: "no-store" }), fetch("config.json?ts=" + Date.now(), { cache: "no-store" })]);
    if (!a.ok) throw new Error("state " + a.status);
    const s = await a.json(); if (!s || !Array.isArray(s.positions) || !Array.isArray(s.closed)) throw new Error("bad state");
    S = s; cached = a.headers.get("x-sw-cache") === "1"; C = b.ok ? await b.json() : null; failed = false;
  } catch (e) { failed = true; }
  if (silent && (location.hash || "").slice(1) === "settings") { $("#dot").className = "dot " + K.freshness(S, now()).level; return; }
  render();
}
window.addEventListener("hashchange", render);
window.addEventListener("online", () => { online = true; load(); });
window.addEventListener("offline", () => { online = false; render(); });
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); deferred = e; });
window.addEventListener("appinstalled", () => { deferred = null; });
document.addEventListener("visibilitychange", () => { if (!document.hidden) load(true); });
online = navigator.onLine !== false;
$("#refresh").addEventListener("click", () => load());
setInterval(() => load(true), 60000);
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
window.__pd = { pages, render, setData(s, c) { S = s; C = c; } };
load();
