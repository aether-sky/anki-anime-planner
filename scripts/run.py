"""Run the whole chain: python run.py MAL_USERNAME [--rescan]

Only the MAL username is needed. Anki is read if AnkiConnect is reachable and skipped
otherwise; subtitle fetching is incremental, so the second run is much faster.
"""
import os, subprocess, sys
from common import CONFIG_PATH, load_config, save_json, log

HERE = os.path.dirname(os.path.abspath(__file__))
STEPS = ["collect_mal.py", "scan_disk.py", "match.py", "collect_anki.py", "fetch_subs.py", "score.py", "plan.py"]
OPTIONAL = {"collect_anki.py"}


def main():
    cfg = load_config()
    if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
        cfg["mal_user"] = sys.argv[1]
        save_json(CONFIG_PATH, cfg)
    if not cfg["mal_user"]:
        sys.exit("usage: python run.py MAL_USERNAME")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    for step in STEPS:
        args = [sys.executable, os.path.join(HERE, step)]
        if step == "scan_disk.py" and "--rescan" in sys.argv:
            args.append("--rescan")
        log(f"== {step}")
        result = subprocess.run(args, env=env)
        if result.returncode and step not in OPTIONAL:
            sys.exit(f"{step} failed; fix that and run again (finished steps are cached)")
        if result.returncode:
            log(f"   skipped: {step} did not succeed, continuing without it")


if __name__ == "__main__":
    main()
