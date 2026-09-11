"""Infer paired SSS entry/exit order from the inspected generateSSSDepth loop.

The trace does not label the pass. Pairing is an inference, with containment and
even-count assertions; results are elapsed scope budgets, not measured savings.
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / "w21-tracy-analysis"


def events(path, name):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return sorted((int(r["ns_since_start"]), int(r["ns_since_start"]) + int(r["exec_time_ns"]))
                      for r in csv.DictReader(stream, delimiter="|")
                      if r["name"] == name and r["thread"] == "1")


frames = events(BASE / "frames.psv", "FTM_FRAME")
sss = sorted(set(e for path in BASE.glob("events-*.psv")
                 for e in events(path, "LLPipeline::generateSSSDepth")))
shadow = events(BASE / "render-parents.psv", "LLPipeline::renderShadow")
alpha = events(ROOT / "sss-alpha-events.psv", "LLPipeline::renderAlphaObjects")
totals = {"entry": [], "exit": []}
counts = {"entry": 0, "exit": 0}
for frame in frames:
    parent = [e for e in sss if frame[0] <= e[0] and e[1] <= frame[1]]
    assert len(parent) == 1
    children = [e for e in shadow if parent[0][0] <= e[0] and e[1] <= parent[0][1]]
    assert len(children) in (2, 4, 6)
    frame_totals = {"entry": 0, "exit": 0}
    for index, child in enumerate(children):
        mode = "exit" if index % 2 else "entry"
        scopes = [e for e in alpha if child[0] <= e[0] and e[1] <= child[1]]
        assert len(scopes) == 2, "Expected unrigged and rigged alpha traversal in each shadow pass"
        frame_totals[mode] += sum(end - start for start, end in scopes)
        counts[mode] += len(scopes)
    for mode in totals:
        totals[mode].append(frame_totals[mode])
result = {mode: {"calls": counts[mode], "mean_ms_per_frame": sum(values) / len(frames) / 1e6,
                 "max_ms_per_frame": max(values) / 1e6}
          for mode, values in totals.items()}
(ROOT / "sss-alpha-phase-summary.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
