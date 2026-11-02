"""Run by the GitHub workflow for app commands. Inputs come only from environment variables (never shell-interpolated)."""
import os, sys, time
import settings
CFG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "config.json")
if __name__ == "__main__":
    try:
        c = settings.apply_command(os.environ.get("CMD", ""), os.environ.get("PAYLOAD", ""), CFG_PATH, time.time())
        print("OK paused=%s settings=%s" % (c["paused"], c["settings"]))
    except ValueError as e:
        print("REJECTED:", e); sys.exit(1)
