"""Attribute native motion zones to the same 170 complete frames as the w21 report."""
import bisect
import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        yield from csv.DictReader(stream, delimiter="|")


frames = sorted((int(r["ns_since_start"]), int(r["exec_time_ns"]), int(r["thread"]))
                for r in rows(ROOT.parent / "w21-tracy-analysis/frames.psv"))
assert len(frames) == 170 and len({f[2] for f in frames}) == 1
starts = [f[0] for f in frames]
events = defaultdict(lambda: {"count": 0, "time_ns": [0] * len(frames), "calls": [0] * len(frames)})
for row in rows(ROOT / "motion-events.psv"):
    start, duration, thread = (int(row[k]) for k in ("ns_since_start", "exec_time_ns", "thread"))
    index = bisect.bisect_right(starts, start) - 1
    if index < 0 or thread != frames[index][2] or start + duration > sum(frames[index][:2]):
        continue
    key = f'{row["name"]} ({row["src_line"]})'
    data = events[key]
    data["count"] += 1
    data["time_ns"][index] += duration
    data["calls"][index] += 1

summary = {}
for key, data in events.items():
    values = sorted(data["time_ns"])
    position = (len(values) - 1) * .95
    low = int(position)
    p95 = values[low] + (values[low + 1] - values[low]) * (position - low)
    summary[key] = {
        "calls": data["count"], "calls_per_frame": data["count"] / len(frames),
        "mean_ms_per_frame": sum(values) / len(frames) / 1e6,
        "p95_ms_per_frame": p95 / 1e6, "max_ms_per_frame": values[-1] / 1e6,
    }
summary = dict(sorted(summary.items(), key=lambda kv: -kv[1]["mean_ms_per_frame"]))
(ROOT / "motion-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
for key, data in list(summary.items())[:18]:
    print(f'{key}: {data["calls"]} calls, {data["mean_ms_per_frame"]:.6f} ms/frame')
