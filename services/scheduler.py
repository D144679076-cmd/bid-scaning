"""In-app scheduler (M7) — replaces systemd timers inside the container.

Stdlib-only: threads + per-job next-fire from cadence table. Logs to
data/logs/<job>.log exactly like the systemd units did, so bidscan logs
and watchdog log-freshness checks keep working unchanged.

Run: python3 services/scheduler.py   (entrypoint of the app container)

Version stamp: VERSION file baked at build (ARG GIT_VERSION) else
`bid-scan dev`. 
"""

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "data" / "logs"

# job → (script, interval seconds). Overridable via SCHED_CADENCE json.
CADENCE = {
    "pipeline":  ("run_pipeline.py", 30 * 60),
    "callbacks": ("alerts/callbacks.py", 60),
    "sender":    ("senders/freelancer_sender.py", 5 * 60),
    "digest":    ("alerts/digest.py", 24 * 60 * 60),
    "followup":  (None, 30 * 60),          # module: run via -m
    "watchdog":  ("services/watchdog.py", 10 * 60),
}
DIGEST_HOUR = 9  # 09:00 daily (digest is interval-fired once per hour check)


def _version() -> str:
    v = ROOT / "VERSION"
    if v.exists():
        return v.read_text().strip()
    if (ROOT / ".git").exists():
        try:
            out = subprocess.run(
                ["git", "describe", "--tags", "--always", "--dirty"],
                cwd=ROOT, capture_output=True, text=True, timeout=5)
            if out.returncode == 0:
                return out.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return "unversioned"


def _next_fire(interval: int, *, at_hour: int | None = None) -> float:
    now = time.time()
    if at_hour is None:
        return now + interval
    # fire at the next HH:00:00 local wall clock matching at_hour
    lt = time.localtime(now)
    fire = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, at_hour,
                        0, 0, lt.tm_wday, lt.tm_yday, lt.tm_isdst))
    return fire if fire > now + 60 else fire + 24 * 3600


def _pipeline_disabled() -> bool:
    # manual-only mode (docs/plan-manual-scan.md): data/scheduler.json
    # {"pipeline_disabled": true} → no scheduled/boot pipeline cycles;
    # only /scan (flock-guarded) runs them. Re-read every check.
    f = ROOT / "data" / "scheduler.json"
    try:
        return json.loads(f.read_text()).get("pipeline_disabled", False)
    except (OSError, ValueError):
        return False


def _run_job(name: str) -> None:
    if name == "pipeline" and _pipeline_disabled():
        return  # manual-only mode: /scan only (docs/plan-manual-scan.md)
    LOGS.mkdir(exist_ok=True, parents=True)
    OUT = LOGS / f"{name}.log"
    cmd = (["python3", "-m", "pipeline.followup"] if name == "followup"
           else ["python3", str(ROOT / CADENCE[name][0])])
    with OUT.open("a") as fh:
        fh.write(f"\n===== {time.strftime('%F %T')} {name} ({_version()}) =====\n")
        fh.flush()
        proc = subprocess.run(cmd, cwd=ROOT, stdout=fh, stderr=fh, timeout=2100)
        fh.write(f"exit={proc.returncode}\n")


def _loop(name: str, *, at_hour: int | None) -> None:
    interval = CADENCE[name][1]
    next_at = _next_fire(86400, at_hour=at_hour) if at_hour is not None \
        else _next_fire(interval)
    while True:
        wait = max(next_at - time.time(), 1)
        time.sleep(min(wait, 60))
        if time.time() < next_at:
            continue
        _run_job(name)
        next_at = (_next_fire(86400, at_hour=DIGEST_HOUR) if name == "digest"
                   else time.time() + interval)


def main() -> int:
    # one live cycle at boot so the app is alive immediately, then fine loops
    print(f"[scheduler] bid-scan {_version()} — boot pipeline cycle", flush=True)
    threading.Thread(target=_run_job, args=("pipeline",), daemon=True).start()
    jobs = {"pipeline": None, "callbacks": None, "sender": None,
            "watchdog": None,
            "followup": None, "digest": 9}  # digest: fire at 09:00
    for name, at_hour in jobs.items():
        t = threading.Thread(target=_loop, args=(name,),
                             kwargs={"at_hour": at_hour}, daemon=True)
        t.start()
        print(f"[scheduler] loop started: {name}", flush=True)
    try:
        while True:
            time.sleep(300)
    except (KeyboardInterrupt, SystemExit):
        return 0


if __name__ == "__main__":
    sys.exit(main())
