"""Tiny GitHub-Actions emulator for scan.yml: parses steps, applies GitHub's if/success()/failure()/always() rules, runs `run:` blocks in bash."""
import os, re, subprocess, textwrap

def parse(wf):
    head, body = wf.split("    steps:\n", 1)
    job_env = dict(re.findall(r'(?m)^      ([A-Z_]+): "?([^"\n]+)"?$', head.split("    env:\n", 1)[1])) if "    env:\n" in head else {}
    steps = []
    for ch in re.split(r"(?m)^      - ", body)[1:]:
        g = lambda k: (re.search(rf"(?m)^\s*{k}: (.+)$", ch) or [None, None])[1]
        m = re.search(r"run: \|\n((?:          .*\n|\n)+)", ch + "\n"); one = re.search(r"(?m)^\s*run: (?!\|)(.+)$", ch)
        env_block = re.search(r"env:\n((?:          .+\n)+)", ch + "\n")
        steps.append(dict(id=g("id"), name=g("name"), cond=g("if"), uses=g("uses"), run=textwrap.dedent(m.group(1)) if m else (one.group(1) if one else None),
                          env=dict(re.findall(r"(?m)^\s+([A-Z_]+): (.+)$", env_block.group(1))) if env_block else {}))
    return job_env, steps

def cond_ok(cond, outcome, failed, event):
    if cond is None: return not failed
    py = cond.replace("&&", " and ").replace("||", " or ").replace("always()", "True").replace("failure()", str(failed)).replace("success()", str(not failed))
    py = re.sub(r"steps\.(\w+)\.outcome", lambda m: repr(outcome.get(m[1], "skipped")), py).replace("github.event_name", repr(event))
    val = bool(eval(py, {"__builtins__": {}}, {}))
    return val if re.search(r"failure\(\)|always\(\)|success\(\)", cond) else (not failed and val)   # implicit success() as on GitHub

def run_job(wf, event, executor):
    _, steps = parse(wf); outcome, failed, ran = {}, False, []
    for i, s in enumerate(steps):
        sid = s["id"] or f"step{i}"
        if not cond_ok(s["cond"], outcome, failed, event): outcome[sid] = "skipped"; continue
        ok = executor(s); outcome[sid] = "success" if ok else "failure"; ran.append(sid); failed = failed or not ok
    return outcome, ran

def bash_executor(cwd, runner_temp, inputs=None, extra_env=None, shims=None):
    job_env, _ = parse(open(os.path.join(os.path.dirname(__file__), "..", ".github", "workflows", "scan.yml")).read())
    def ex(s):
        if s["run"] is None: return True
        env = dict(os.environ, RUNNER_TEMP=runner_temp, **job_env, **(extra_env or {}))
        if shims: env["PATH"] = shims + os.pathsep + env["PATH"]
        for k, v in s["env"].items(): env[k] = (inputs or {}).get(re.sub(r".*inputs\.(\w+).*", r"\1", v), "") if "${{" in v else v
        r = subprocess.run(["bash", "-e", "-c", s["run"]], cwd=cwd, env=env, capture_output=True, text=True); s["out"] = r.stdout + r.stderr
        return r.returncode == 0
    return ex
