"""Builds sniper-desk-v<VERSION>.zip plus MANIFEST.sha256 (a checksum of every code file). Dev tool: run from the repo root."""
import hashlib, os, sys, zipfile
LIVE = {"docs/state.json", "docs/config.json"}          # live data is never part of a release
def release_files(root):
    out = []
    for d, ds, fs in os.walk(root):
        rel_d = os.path.relpath(d, root).replace(os.sep, "/")
        ds[:] = [x for x in ds if x not in (".git", "__pycache__", "data", ".github")]
        for f in fs:
            rel = f if rel_d == "." else rel_d + "/" + f
            if f.endswith((".pyc", ".tmp", ".zip")) or f == "MANIFEST.sha256" or rel in LIVE: continue
            out.append(rel)
    return sorted(out)
def manifest_lines(root):
    return [hashlib.sha256(open(os.path.join(root, r), "rb").read()).hexdigest() + "  " + r + "\n" for r in release_files(root)]
def build(root, out_dir):
    version = open(os.path.join(root, "bot", "VERSION")).read().strip()
    open(os.path.join(root, "MANIFEST.sha256"), "w").write("".join(manifest_lines(root)))
    name = os.path.join(out_dir, f"sniper-desk-v{version}.zip"); wf = ".github/workflows/scan.yml"
    with zipfile.ZipFile(name, "w", zipfile.ZIP_DEFLATED) as z:
        for r in release_files(root) + ["MANIFEST.sha256", wf]: z.write(os.path.join(root, r), r)
    return name
if __name__ == "__main__":
    print(build(os.getcwd(), sys.argv[1] if len(sys.argv) > 1 else "."))
