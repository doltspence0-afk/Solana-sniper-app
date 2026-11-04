// Runs docs/app.js against a minimal fake DOM so runtime errors (ReferenceError/TypeError) show up without a browser.
const fs = require("fs"), vm = require("vm"), path = require("path");
const fx = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
class E { constructor(t, txt) { this.tag = t; this.kids = []; this.attrs = {}; this._t = txt || ""; this.className = ""; this.listeners = {}; this.value = "";
    const s = this; this.classList = { add(c) { s.className += " " + c; }, remove() {}, toggle() {} }; }
  append(...n) { n.forEach((x) => this.kids.push(typeof x === "string" ? new E("#t", x) : x)); }
  replaceChildren(...n) { this.kids = []; this.append(...n); }
  setAttribute(k, v) { this.attrs[k] = v; } getAttribute(k) { return this.attrs[k]; } addEventListener(t, f) { this.listeners[t] = f; }
  set textContent(v) { this._t = String(v); this.kids = []; } get textContent() { return this._t + this.kids.map((k) => k.textContent).join(" "); } }
const reg = {}, q = (s) => reg[s] || (reg[s] = new E("q"));
global.document = { createElement: (t) => new E(t), createElementNS: (n, t) => new E(t), querySelector: q, querySelectorAll: () => [], addEventListener() {}, body: new E("body"), hidden: false };
global.window = global; global.CALC = require("../docs/calc.js");
global.location = { hash: "#home", hostname: "alice.github.io", pathname: "/repo/" };
global.navigator = { onLine: true, serviceWorker: { register: () => Promise.resolve() } };
global.matchMedia = () => ({ matches: false });
global.localStorage = (() => { const m = {}; return { getItem: (k) => (k in m ? m[k] : null), setItem: (k, v) => { m[k] = v; }, removeItem: (k) => { delete m[k]; } }; })();
global.addEventListener = () => {}; global.setInterval = () => 0;
global.fetch = async () => ({ ok: false, status: 404, headers: { get: () => null }, json: async () => ({}) });
vm.runInThisContext(fs.readFileSync(path.join(__dirname, "../docs/app.js"), "utf8"));
const walk = (e, f) => { f(e); e.kids.forEach((k) => walk(k, f)); };
const out = [];
for (const [name, d] of Object.entries(fx)) for (const r of ["home", "scanner", "open", "history", "perf", "agents", "health", "more", "settings"]) {
  const rec = { state: name, route: r, ok: true, text: "", hrefs: [], tags: [] };
  try { __pd.setData(d.S, d.C); const e = __pd.pages[r](); rec.text = e.textContent; walk(e, (n) => { rec.tags.push(n.tag); if (n.attrs.href) rec.hrefs.push(n.attrs.href); });
    location.hash = "#" + r; __pd.render(); rec.view = q("#view").textContent; rec.age = q("#scanage").textContent; rec.dot = q("#dot").className; }
  catch (err) { rec.ok = false; rec.err = String(err && err.stack || err); }
  out.push(rec);
}
console.log(JSON.stringify(out));
