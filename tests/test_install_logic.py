import os, re, shutil, subprocess, sys, tempfile, unittest, zipfile
from support import ROOT
import wf_sim
sys.path.insert(0, os.path.join(ROOT, "tools")); import build_release
WF = open(os.path.join(ROOT, ".github", "workflows", "scan.yml")).read()
JOB_ENV, STEPS = wf_sim.parse(WF); BY_ID = {s["id"]: s for s in STEPS if s["id"]}
NEED = all(shutil.which(x) for x in ("bash", "unzip", "sha256sum", "comm"))

def mkrepo(version="4", files=None):
    d = tempfile.mkdtemp(); base = {"bot/VERSION": version + "\n", "bot/main.py": "print('main')\n", "tests/test_a.py": "x=1\n", "tools/t.py": "y=1\n", "docs/index.html": "<html>", "README.md": "readme"}
    for k, v in {**base, **(files or {})}.items():
        os.makedirs(os.path.dirname(os.path.join(d, k)) or d, exist_ok=True); open(os.path.join(d, k), "w").write(v)
    return d
def seal(d): open(os.path.join(d, "MANIFEST.sha256"), "w").write("".join(build_release.manifest_lines(d)))
def mkzip(d, name, version, extra=None):
    files = {"bot/main.py": f"print('v{version}')\n", "bot/VERSION": f"{version}\n", "tests/test_a.py": f"v={version}\n", "docs/state.json": "ZIP-STATE", "docs/config.json": "ZIP-CFG", ".github/workflows/scan.yml": "ZIP-WF", "data/state.bak.json": "ZIP-BAK", **(extra or {})}
    os.makedirs(os.path.dirname(os.path.join(d, name)) or d, exist_ok=True)
    with zipfile.ZipFile(os.path.join(d, name), "w") as z:
        for k, v in files.items(): z.writestr(k, v)
def sh(step_id, d, **env):
    t = tempfile.mkdtemp(); r = subprocess.run(["bash", "-e", "-c", BY_ID[step_id]["run"]], cwd=d, capture_output=True, text=True, env=dict(os.environ, RUNNER_TEMP=t, **JOB_ENV, **env))
    return r.returncode, r.stdout + r.stderr
rd = lambda d, p: open(os.path.join(d, p)).read()

@unittest.skipUnless(NEED, "bash/unzip/sha256sum needed")
class Unpack(unittest.TestCase):
    def live(self): return mkrepo("2", {"docs/state.json": "LIVE-STATE", "docs/config.json": "LIVE-CFG", "data/state.bak.json": "LIVE-BAK", ".github/workflows/scan.yml": "LIVE-WF", "tests/stale_old_test.py": "boom"})
    def test_any_zip_name_is_found_and_only_code_is_replaced(self):
        for name in ("sniper-desk-v4.zip", "solana-paper-desk (1).zip", "sub/dir.zip"):
            d = self.live(); mkzip(d, name, 4); rc, out = sh("unpack", d); self.assertEqual(rc, 0, out)
            self.assertEqual((rd(d, "bot/VERSION").strip(), rd(d, "docs/state.json"), rd(d, "docs/config.json"), rd(d, "data/state.bak.json"), rd(d, ".github/workflows/scan.yml")), ("4", "LIVE-STATE", "LIVE-CFG", "LIVE-BAK", "LIVE-WF"), name)
            self.assertFalse(os.path.exists(os.path.join(d, name))); self.assertFalse(os.path.exists(os.path.join(d, "tests/stale_old_test.py")), "stale files from older versions must be removed")
    def test_newest_version_wins_whatever_the_order(self):
        d = self.live(); mkzip(d, "a-old.zip", 3); mkzip(d, "z-new.zip", 4); mkzip(d, "m-legacy.zip", 0, {"bot/VERSION": ""}); rc, out = sh("unpack", d)
        self.assertEqual((rc, rd(d, "bot/VERSION").strip(), rd(d, "bot/main.py")), (0, "4", "print('v4')\n"), out)
    def test_older_zip_cannot_downgrade(self):
        d = mkrepo("4"); mkzip(d, "old.zip", 2); rc, out = sh("unpack", d)
        self.assertEqual((rc, rd(d, "bot/VERSION").strip(), rd(d, "bot/main.py")), (0, "4", "print('main')\n")); self.assertIn("ignored", out); self.assertFalse(os.path.exists(os.path.join(d, "old.zip")))
    def test_unrelated_zip_ignored_and_no_zip_is_noop(self):
        d = mkrepo("4"); zipfile.ZipFile(os.path.join(d, "photos.zip"), "w").writestr("a.txt", "x"); rc, out = sh("unpack", d)
        self.assertEqual(rc, 0); self.assertTrue(os.path.exists(os.path.join(d, "photos.zip"))); self.assertEqual(rd(d, "bot/main.py"), "print('main')\n")
        self.assertEqual(sh("unpack", mkrepo("4"))[0], 0)

@unittest.skipUnless(NEED, "bash/unzip/sha256sum needed")
class Preflight(unittest.TestCase):
    def test_clean_release_passes_and_live_data_is_ignored(self):
        d = mkrepo("4"); seal(d); self.assertEqual(sh("preflight", d)[0], 0)
        for f in ("docs/state.json", "docs/config.json", "data/state.bak.json", "HALT"):          # live data changing must never fail a release check
            os.makedirs(os.path.dirname(os.path.join(d, f)) or d, exist_ok=True); open(os.path.join(d, f), "w").write("changed")
        os.makedirs(os.path.join(d, "tests/__pycache__")); open(os.path.join(d, "tests/__pycache__/x.pyc"), "w").write("c"); self.assertEqual(sh("preflight", d)[0], 0)
    def test_wrong_version_missing_manifest(self):
        d = mkrepo("3"); seal(d); rc, out = sh("preflight", d); self.assertEqual(rc, 1); self.assertIn("version 3", out); self.assertIn("sniper-desk-v4.zip", out)
        d = mkrepo("4"); rc, out = sh("preflight", d); self.assertEqual(rc, 1); self.assertIn("MANIFEST.sha256 is missing", out)
        d = mkrepo("0"); os.remove(os.path.join(d, "bot/VERSION")); self.assertEqual(sh("preflight", d)[0], 1)    # pre-versioning repo
    def test_mixed_versions_are_detected(self):
        d = mkrepo("4"); seal(d); open(os.path.join(d, "docs/index.html"), "w").write("OLD"); rc, out = sh("preflight", d); self.assertEqual(rc, 1); self.assertIn("docs/index.html", out); self.assertIn("mixed versions", out)
        d = mkrepo("4"); seal(d); os.remove(os.path.join(d, "tests/test_a.py")); self.assertEqual(sh("preflight", d)[0], 1)                      # missing file
        d = mkrepo("4"); seal(d); open(os.path.join(d, "tests/test_stale.py"), "w").write("old"); rc, out = sh("preflight", d); self.assertEqual(rc, 1); self.assertIn("tests/test_stale.py", out)   # stray old file
    def test_release_version_matches_workflow(self):
        self.assertEqual(open(os.path.join(ROOT, "bot", "VERSION")).read().strip(), JOB_ENV["EXPECTED_VERSION"])

class FailureReporting(unittest.TestCase):
    """Emulates GitHub's rules: a failed step skips later steps unless their `if` says otherwise."""
    def go(self, event="schedule", fail=()):
        return wf_sim.run_job(WF, event, lambda s: (s["id"] or "") not in fail)
    def test_happy_path(self):
        o, ran = self.go("schedule"); n = self.names(o)
        self.assertEqual([o[k] for k in ("unpack", "preflight", "tests", "scan", "check")], ["success"] * 5)
        self.assertEqual((o["control"], n["Record failure so the app can show why"], n["Commit results"]), ("skipped", "skipped", "success"))
    def names(self, o): return {s["name"]: o.get(s["id"] or f"step{i}") for i, s in enumerate(STEPS)}
    def test_each_failure_point(self):
        hb, cm = "Record failure so the app can show why", "Commit results"
        for fail, scan_ran in (("tests", False), ("control", False), ("scan", True), ("check", True)):
            o, ran = self.go("workflow_dispatch", {fail}); n = self.names(o)
            self.assertEqual(n[hb], "success", fail); self.assertEqual(n[cm], "success", fail)            # failure is recorded AND state still committed
            self.assertEqual("scan" in ran, scan_ran, fail)
        o, _ = self.go("workflow_dispatch", {"tests"}); self.assertEqual((o["scan"], o["control"], o["check"]), ("skipped",) * 3)   # no trading after a failed self-test
    def test_dispatch_vs_schedule(self):
        self.assertEqual(self.go("workflow_dispatch")[0]["control"], "success"); self.assertEqual(self.go("schedule")[0]["control"], "skipped")
    def test_preflight_failure_stops_everything_but_is_not_recorded_as_a_bot_failure(self):
        o, _ = self.go("schedule", {"preflight"}); n = self.names(o)
        self.assertEqual((o["tests"], o["scan"], n["Record failure so the app can show why"]), ("skipped", "skipped", "skipped")); self.assertEqual(n["Commit results"], "success")
    def test_unpack_failure_commits_nothing(self):
        o, _ = self.go("schedule", {"unpack"}); self.assertEqual(self.names(o)["Commit results"], "skipped")
    def test_reason_file_logic_in_scripts(self):
        t = tempfile.mkdtemp()
        for sid, text in (("tests", "self-test failed"), ("control", "command rejected"), ("scan", "scan crashed"), ("check", "state check failed")):
            self.assertIn(text, BY_ID[sid]["run"]); self.assertIn('"$RUNNER_TEMP/reason"', BY_ID[sid]["run"])
        hb = [s for s in STEPS if s["name"] and s["name"].startswith("Record failure")][0]["run"]; self.assertIn("--heartbeat", hb); self.assertIn("unexpected failure", hb)
    def test_every_workflow_command_is_implemented_and_nothing_else_is_interpolated(self):
        import settings
        opts = re.search(r"options: \[(.*?)\]", WF).group(1).replace(" ", "").split(","); p = os.path.join(tempfile.mkdtemp(), "c.json")
        for o in opts: settings.apply_command(o, '{"sl": 0.04}' if o == "settings" else "", p, 1)
        self.assertEqual(len(re.findall(r"\$\{\{", WF)), 2); self.assertEqual(set(re.findall(r"\$\{\{ (\S+) \}\}", WF)), {"inputs.command", "inputs.payload"})
if __name__ == "__main__":
    unittest.main()
