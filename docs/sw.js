/* Service worker: caches the app shell; data is network-first with cached fallback. Cross-origin requests
   (api.github.com, i.e. anything carrying the token) are never intercepted or cached. */
const V = "pd-v2", SHELL = ["./", "index.html", "app.css", "app.js", "calc.js", "manifest.webmanifest", "offline.html", "icons/icon-192.png", "icons/icon-512.png"];
self.addEventListener("install", (e) => { e.waitUntil(caches.open(V).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener("activate", (e) => { e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== V).map((k) => caches.delete(k)))).then(() => self.clients.claim())); });
async function data(req, u) {
  const key = new Request(u.origin + u.pathname), c = await caches.open(V);
  try { const r = await fetch(req, { cache: "no-store" }); if (r.ok) c.put(key, r.clone()); return r; }
  catch (err) { const hit = await c.match(key); if (!hit) return new Response("offline", { status: 503 });
    const h = new Headers(hit.headers); h.set("x-sw-cache", "1"); return new Response(await hit.blob(), { status: 200, headers: h }); }
}
self.addEventListener("fetch", (e) => {
  const r = e.request, u = new URL(r.url);
  if (r.method !== "GET" || u.origin !== location.origin) return;
  if (/\/(state|config)\.json$/.test(u.pathname)) { e.respondWith(data(r, u)); return; }
  if (r.mode === "navigate") { e.respondWith(fetch(r).catch(() => caches.match("index.html").then((x) => x || caches.match("offline.html")))); return; }
  e.respondWith(caches.match(r).then((hit) => { const net = fetch(r).then((n) => { if (n.ok) caches.open(V).then((c) => c.put(r, n.clone())); return n; }).catch(() => hit); return hit || net; }));
});
