import json, os, re, shutil, struct, subprocess, unittest
from support import *
import settings
D = os.path.join(ROOT, "docs")
rd = lambda *p: open(os.path.join(ROOT, *p), encoding="utf-8", errors="ignore").read()
WF = rd(".github", "workflows", "scan.yml")

def png_size(path):
    d = open(path, "rb").read(32); assert d[:8] == b"\x89PNG\r\n\x1a\n"; return struct.unpack(">II", d[16:24])

class PWA(unittest.TestCase):
    def test_manifest_installable(self):
        m = json.loads(rd("docs", "manifest.webmanifest"))
        for k in ("name", "short_name", "start_url", "scope", "display", "icons", "background_color", "theme_color"): self.assertIn(k, m)
        self.assertEqual((m["display"], m["background_color"], m["theme_color"]), ("standalone", "#000000", "#000000"))
        self.assertTrue(m["start_url"].startswith("./") and m["scope"] == "./")       # relative: works under github.io/<repo>/
        sizes = {(i["sizes"], i["purpose"]) for i in m["icons"]}; self.assertIn(("192x192", "any"), sizes); self.assertIn(("512x512", "any"), sizes); self.assertIn(("512x512", "maskable"), sizes)
        for i in m["icons"]:
            w, h = i["sizes"].split("x"); self.assertEqual(png_size(os.path.join(D, i["src"])), (int(w), int(h)))
    def test_html_head_and_csp(self):
        h = rd("docs", "index.html")
        for needle in ('rel="manifest"', 'name="theme-color"', "viewport-fit=cover", "PAPER", 'href="#home"', 'href="#scanner"', 'href="#open"', 'href="#history"', 'href="#more"'): self.assertIn(needle, h)
        csp = re.search(r'Content-Security-Policy" content="([^"]+)"', h).group(1)
        self.assertIn("connect-src 'self' https://api.github.com", csp); self.assertNotIn("unsafe", csp); self.assertIn("default-src 'none'", csp)
        self.assertIsNone(re.search(r"<script(?![^>]*\bsrc=)[^>]*>", h)); self.assertNotIn("style=", h); self.assertNotIn("onclick", h)
        for src in re.findall(r'(?:src|href)="([^"#:]+)"', h): self.assertTrue(os.path.exists(os.path.join(D, src)), src)
    def test_service_worker(self):
        sw = rd("docs", "sw.js"); shell = re.search(r"SHELL = (\[.*?\]);", sw).group(1)
        for f in json.loads(shell):
            if f != "./": self.assertTrue(os.path.exists(os.path.join(D, f)), f)
        self.assertIn("u.origin !== location.origin", sw); self.assertNotIn("api.github.com", re.sub(r"/\*.*?\*/", "", sw, flags=re.S))   # token traffic never intercepted/cached
        self.assertIn("offline.html", sw); self.assertIn("x-sw-cache", sw); self.assertTrue(os.path.exists(os.path.join(D, "offline.html")))
    def test_app_js_hardening(self):
        js = rd("docs", "app.js")
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "eval(", "document.write", "new Function", "console."): self.assertNotIn(bad, js)
        urls = re.findall(r'fetch\(([^,)]+)', js); self.assertTrue(all(("state.json" in u or "config.json" in u or "api.github.com" in u) for u in urls), urls)
        self.assertEqual(set(re.findall(r'"(gh_\w+)"', js)), {"gh_token", "gh_owner", "gh_repo"})
        self.assertNotRegex(js, r"github_pat_[A-Za-z0-9]"); self.assertIn("Authorization", js)
        for r in ("home", "scanner", "open", "history", "perf", "agents", "settings"): self.assertRegex(js, rf"\b{r}\b")
    @unittest.skipUnless(shutil.which("node"), "node missing")
    def test_js_syntax(self):
        for f in ("app.js", "sw.js", "calc.js"): self.assertEqual(subprocess.run(["node", "--check", os.path.join(D, f)]).returncode, 0, f)

class Deploy(unittest.TestCase):
    def test_workflow_safety(self):
        self.assertRegex(WF, r"concurrency:\n  group: paper-desk\n  cancel-in-progress: false"); self.assertRegex(WF, r"permissions:\n  contents: write\n")
        self.assertEqual(len(re.findall(r"^permissions:", WF, re.M)), 1); self.assertIn("workflow_dispatch", WF); self.assertIn("cron:", WF)
        self.assertNotIn("secrets.", WF); self.assertNotIn("pull_request", WF)
        for l in (x for x in WF.splitlines() if "${{" in x):
            self.assertTrue(re.match(r"\s+[A-Z_]+: \$\{\{ inputs\.\w+ \}\}$", l) or "github.event_name" in l, l)   # inputs only via env, never inside shell text
        self.assertIn("-x '.github/*'", WF); self.assertIn("git pull --rebase", WF); self.assertIn("for i in 1 2 3", WF)
        order = [WF.index(s) for s in ("unittest discover", "bot/control.py", "bot/main.py\n", "main.py --check", "git commit")]; self.assertEqual(order, sorted(order))
        for u in re.findall(r"uses: (\S+)", WF): self.assertRegex(u, r"@v\d+$")
    def test_app_and_workflow_agree(self):
        js = rd("docs", "app.js"); self.assertIn("workflows/scan.yml", js); self.assertTrue(os.path.exists(os.path.join(ROOT, ".github/workflows/scan.yml")))
        self.assertIn("inputs: { command: cmd, payload:", js)
        for k in ("      command:", "      payload:"): self.assertIn(k, WF)
        opts = re.search(r"options: \[(.*?)\]", WF).group(1).replace(" ", "").split(",")
        p = os.path.join(__import__("tempfile").mkdtemp(), "c.json")
        for o in opts: settings.apply_command(o, '{"sl": 0.04}' if o == "settings" else "", p, 1)   # every offered command is implemented
        for cmd in re.findall(r'(?:run\("[^"]+", |dispatch\()"(\w+)"', js): self.assertIn(cmd, opts, cmd)
    def test_pages_ready(self):
        for f in ("index.html", "state.json", "config.json", ".nojekyll", "manifest.webmanifest", "sw.js"): self.assertTrue(os.path.exists(os.path.join(D, f)), f)
        self.assertTrue(settings.load(os.path.join(D, "config.json")) == {"paused": False, "settings": {}, "updated": None})
    def test_real_trading_is_impossible(self):
        self.assertEqual(b.MODE, "paper")
        words = ("solders", "solana.rpc", "Keypair", "sendTransaction", "signTransaction", "private_key", "privateKey", "mnemonic", "seed phrase", "jup.ag/swap", "swap/v")
        for d, _, fs in os.walk(ROOT):
            if any(x in d for x in (".git", "__pycache__", "tests")): continue
            for f in fs:
                if f.endswith((".py", ".js", ".html", ".yml")):
                    t = rd(os.path.relpath(os.path.join(d, f), ROOT))
                    for w in words: self.assertNotIn(w, t, f"{f} mentions {w}")
        self.assertIn("Refusing to run", rd("bot", "main.py"))

class Security(unittest.TestCase):
    PAT = {"private key": r"-----BEGIN [A-Z ]*PRIVATE KEY", "github token": r"\b(?:ghp|gho|ghs|ghu|github_pat)_[A-Za-z0-9_]{20,}", "api key": r"\bsk-[A-Za-z0-9_-]{20,}",
           "aws": r"\bAKIA[0-9A-Z]{16}\b", "solana secret": r"\b[1-9A-HJ-NP-Za-km-z]{80,90}\b", "keypair json": r"\[\s*(?:\d{1,3}\s*,\s*){63}\d{1,3}\s*\]",
           "hardcoded secret": r"""(?i)(?:api[_-]?key|secret|password|passwd|token)\s*[:=]\s*["'][A-Za-z0-9_\-]{12,}["']"""}
    def files(self):
        for d, _, fs in os.walk(ROOT):
            if ".git" in d.split(os.sep) or "__pycache__" in d: continue
            for f in fs:
                if f.endswith((".png", ".zip", ".pyc")): continue
                yield os.path.relpath(os.path.join(d, f), ROOT)
    def test_no_secrets_anywhere_in_repo(self):
        for f in self.files():
            t = rd(f)
            for n, p in self.PAT.items(): self.assertIsNone(re.search(p, t), f"{n} pattern in {f}")
            for e in re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", t): self.assertTrue(e.endswith("users.noreply.github.com"), f"{e} in {f}")
    def test_public_state_has_only_whitelisted_fields(self):
        st = json.loads(rd("docs", "state.json")); self.assertLessEqual(set(st), set(b.new_state()))
        for sensitive in ("token", "key", "secret", "password", "email"): self.assertFalse([k for k in st if sensitive in k.lower()])
    def test_gitignore_protects_secrets(self):
        g = rd(".gitignore"); self.assertIn(".env", g); self.assertIn("*.key", g)
if __name__ == "__main__":
    unittest.main()
