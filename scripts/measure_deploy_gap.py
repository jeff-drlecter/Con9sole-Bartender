"""Observe a single-machine rollout from the runner. Print only lifecycle timestamps."""
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import sys
import time


ANSI = re.compile(r"\x1b\[[0-9;]*m")
STOP = re.compile(r"INFO\s+Sending signal SIG(?:INT|TERM) to main child process w/ PID \d+")
READY = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} INFO con9sole-bartender: Release ready commit=([0-9a-f]{40})")


def lifecycle_events(raw, machine, commit, since):
    # flyctl 0.5.7 emits consecutive pretty-printed JSON objects, including buffered history.
    decoder = json.JSONDecoder()
    pos = 0
    while pos < len(raw):
        if raw[pos].isspace():
            pos += 1
            continue
        entry, pos = decoder.raw_decode(raw, pos)
        if entry.get("instance") != machine:
            continue
        message = ANSI.sub("", entry.get("message", "")).strip()
        if STOP.fullmatch(message):
            kind = "stop"
        else:
            ready = READY.fullmatch(message)
            if not ready or ready[1] != commit:
                continue
            kind = "ready"
        timestamp = datetime.fromisoformat(entry["timestamp"])
        if timestamp >= since:
            yield kind, timestamp


def summary(events):
    stops = sorted(t for kind, t in events if kind == "stop")
    ready = sorted(t for kind, t in events if kind == "ready")
    if len(stops) != 1 or len(ready) != 1 or ready[0] <= stops[0]:
        return f"Unavailable: expected one ordered shutdown and ready pair (shutdown={len(stops)}, ready={len(ready)})."
    seconds = (ready[0] - stops[0]).total_seconds()
    return (f"**{seconds:.2f} seconds** from Fly shutdown signal to Discord ready with the welcome button registered.\n\n"
            f"- Shutdown: `{stops[0].isoformat()}`\n- Ready: `{ready[0].isoformat()}`")


def observe(machine, commit, since, finished):
    events = set()
    deadline = None
    while True:
        if finished.exists() and deadline is None:
            if finished.read_text().strip() != "0":
                return "Unavailable: deployment did not succeed."
            deadline = time.monotonic() + 20
        try:
            result = subprocess.run(
                ["flyctl", "logs", "--app", "con9sole-bartender", "--machine", machine, "--json", "--no-tail"],
                check=True, capture_output=True, text=True, timeout=6,
            )
            events.update(lifecycle_events(result.stdout, machine, commit, since))
        except (subprocess.SubprocessError, OSError, ValueError):
            pass  # Fetch the bounded buffer again. Never publish raw logs or Fly errors.
        if deadline is not None and (len({k for k, _ in events}) == 2 or time.monotonic() >= deadline):
            return summary(events)
        time.sleep(2)


if __name__ == "__main__":
    machine, commit, since, finished = sys.argv[1:]
    print("### Discord deployment gap\n")
    print(observe(machine, commit, datetime.fromisoformat(since), Path(finished)))
