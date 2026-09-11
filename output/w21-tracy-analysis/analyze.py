"""Analyze native Tracy 0.11.1 exports; timings are elapsed CPU zones, not CPU samples."""
import bisect
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent


def rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        yield from csv.DictReader(stream, delimiter="|")


def percentile(values, p):
    values = sorted(values)
    position = (len(values) - 1) * p
    low = int(position)
    return values[low] + (values[min(low + 1, len(values) - 1)] - values[low]) * (position - low)


def stats(values):
    return {"mean_ms": mean(values) / 1e6, "median_ms": percentile(values, .5) / 1e6,
            "p95_ms": percentile(values, .95) / 1e6, "p99_ms": percentile(values, .99) / 1e6,
            "max_ms": max(values) / 1e6}


# The broad native 'Render' filter also matches millions of tiny render helpers.
# Retain only the parent scopes needed for frame attribution.
render_names = {"Render", "Render Cube Face", "render_ui", "render_ui_2d",
                "LLPipeline::renderDeferredLighting", "LLPipeline::renderGeomDeferred",
                "LLPipeline::renderGeomPostDeferred", "LLPipeline::renderShadow",
                "LLPipeline::generateImpostor", "LLDrawPoolAlpha::renderPostDeferred",
                "LLDrawPoolAlpha::renderAlpha"}
compact = ROOT / "render-parents.psv"
if not compact.exists():
    with compact.open("w", encoding="utf-8", newline="") as stream:
        writer = None
        for row in rows(ROOT / "events-02.psv"):
            if row["name"] not in render_names:
                continue
            if writer is None:
                writer = csv.DictWriter(stream, fieldnames=list(row), delimiter="|")
                writer.writeheader()
            writer.writerow(row)

events = defaultdict(list)
seen = set()
for path in [ROOT / "frames.psv", compact] + sorted(ROOT.glob("events-*.psv")):
    if path.name == "events-02.psv":
        continue
    for row in rows(path):
        # stateSort is overloaded; only its outer camera/result scope is relevant.
        if row["name"] == "LLPipeline::stateSort" and row["src_line"] != "3198":
            continue
        key = (row["name"], row["src_file"], int(row["src_line"]), int(row["ns_since_start"]),
               int(row["exec_time_ns"]), int(row["thread"]))
        if key in seen:
            continue
        seen.add(key)
        assert key[4] >= 0, "Incomplete/negative zone must not enter the statistics"
        events[key[0]].append((key[3], key[3] + key[4], key[5]))
for values in events.values():
    values.sort()

frames = events["FTM_FRAME"]
assert len({f[2] for f in frames}) == 1
thread = frames[0][2]
assert all(a[1] <= b[0] for a, b in zip(frames, frames[1:])), "Frame scopes overlap"
starts = [f[0] for f in frames]
durations = [f[1] - f[0] for f in frames]
total = sum(durations)
per_frame = [defaultdict(int) for _ in frames]
per_count = [defaultdict(int) for _ in frames]
for name, values in events.items():
    for start, end, event_thread in values:
        if event_thread != thread:
            continue
        index = bisect.bisect_right(starts, start) - 1
        if index >= 0 and end <= frames[index][1]:
            per_frame[index][name] += end - start
            per_count[index][name] += 1

def contained(children, parents):
    """Attribute child duration to non-overlapping same-thread parent instances."""
    parents = sorted(p for p in parents if p[2] == thread)
    parent_starts = [p[0] for p in parents]
    amounts = [0] * len(parents)
    counts = [0] * len(parents)
    for start, end, event_thread in children:
        i = bisect.bisect_right(parent_starts, start) - 1
        if event_thread == thread and i >= 0 and end <= parents[i][1]:
            amounts[i] += end - start
            counts[i] += 1
    return {"parent_count": len(parents), "child_count": sum(counts),
            "total_ms": sum(amounts) / 1e6, "mean_ms_per_parent": mean(amounts) / 1e6,
            "mean_count_per_parent": mean(counts)}

summary = {
    "frame_count": len(frames), "main_thread_export_id": thread,
    "frame_zone_seconds": total / 1e9,
    "first_to_last_frame_seconds": (frames[-1][1] - frames[0][0]) / 1e9,
    "first_frame_since_process_start_seconds": starts[0] / 1e9,
    "approx_fps_from_mean_frame_zone": 1e9 / mean(durations),
    "frame_stats": stats(durations),
    "frames_over_33_33_ms": sum(v > 1e9 / 30 for v in durations),
    "frames_over_16_67_ms": sum(v > 1e9 / 60 for v in durations),
    "gaps_over_1ms": [(i, (b[0] - a[1]) / 1e6) for i, (a, b) in enumerate(zip(frames, frames[1:])) if b[0] - a[1] > 1e6],
    "zones": {}, "containment": {},
}
for name in events:
    values = [f[name] for f in per_frame]
    if not sum(values):
        continue
    summary["zones"][name] = {"count": sum(f[name] for f in per_count),
                              "share_of_frame_percent": 100 * sum(values) / total,
                              "total_ms": sum(values) / 1e6, **stats(values),
                              "all_export_threads": sorted({z[2] for z in events[name]})}

relationships = [
    ("LLPipeline::renderShadow", "LLPipeline::generateSSSDepth"),
    ("LLPipeline::stateSort", "LLPipeline::generateSSSDepth"),
    ("LLPipeline::rebuildPriorityGroups", "LLPipeline::generateSSSDepth"),
    ("LLPipeline::renderDeferredLighting", "Render"),
    ("LLPipeline::renderDeferredLighting", "df Snapshot"),
    ("LLFace::calcPixelArea", "LLViewerTextureList::updateImages"),
    ("LLFace::calcPixelArea", "LLVOAvatar::idleUpdate"),
    ("LLFace::calcPixelArea", "LLPipeline::stateSort"),
    ("LLDrawPoolAlpha::renderAlpha", "Exact OIT conditional fallback submission"),
    ("LLDrawPoolAlpha::renderAlpha", "LLPipeline::generateSSSDepth"),
    ("Exact OIT collect completed stats", "LLPipeline::renderDeferredLighting"),
    ("Exact OIT GPU scheduled finish", "LLPipeline::renderDeferredLighting"),
]
for child, parent in relationships:
    summary["containment"][child + " inside " + parent] = contained(events[child], events[parent])

# All these scopes are siblings on the main-frame path. Lighting below selects
# only invocations inside Render, excluding the later reflection probe update.
allocations = []
for i, frame in enumerate(frames):
    f = per_frame[i]
    render = [r for r in events["Render"] if r[2] == thread and frame[0] <= r[0] and r[1] <= frame[1]]
    assert len(render) == 1, "Expected one complete main Render scope in each frame"
    lighting = sum(end - start for start, end, t in events["LLPipeline::renderDeferredLighting"]
                   if t == thread and render[0][0] <= start and end <= render[0][1])
    allocation = {
        "SSS depth": f["LLPipeline::generateSSSDepth"],
        "Lighting and transparency": lighting,
        "UI and HUD rendering": f["render_ui"],
        "Texture updates": f["LLViewerTextureList::updateImages"],
        "Main opaque geometry": f["display - 5"],
        "Main scene sorting": f["display - 4"],
        "Reflection update": f["df Snapshot"],
        "Avatar and object updates": f["FTM_OBJECTLIST_UPDATE"],
        "Other simulation and UI updates": f["df idle"] - f["FTM_OBJECTLIST_UPDATE"],
    }
    allocation["Other frame work"] = durations[i] - sum(allocation.values())
    assert min(allocation.values()) >= 0, "Overlapping allocation categories"
    assert sum(allocation.values()) == durations[i]
    allocations.append(allocation)
summary["allocation"] = {
    name: {**stats([a[name] for a in allocations]),
           "share_percent": 100 * sum(a[name] for a in allocations) / total}
    for name in allocations[0]
}
summary["slowest_frames"] = [
    {"frame_index": i, "relative_seconds": (starts[i] - starts[0]) / 1e9,
     "frame_ms": durations[i] / 1e6,
     "allocation_ms": {k: v / 1e6 for k, v in allocations[i].items()},
     "oit_collect_ms": per_frame[i]["Exact OIT collect completed stats"] / 1e6,
     "oit_finish_ms": per_frame[i]["Exact OIT GPU scheduled finish"] / 1e6}
    for i in sorted(range(len(frames)), key=lambda i: durations[i], reverse=True)[:8]
]

sss_self = {int(row["ns_since_start"]): int(row["exec_time_ns"])
            for row in rows(ROOT / "sss-self-events.psv")}
for frame in summary["slowest_frames"]:
    i = frame["frame_index"]
    frame["sss_self_ms"] = sum(sss_self[start] for start, end, t in events["LLPipeline::generateSSSDepth"]
                               if t == thread and frames[i][0] <= start and end <= frames[i][1]) / 1e6
    frame["priority_rebuild_ms"] = per_frame[i]["LLPipeline::rebuildPriorityGroups"] / 1e6

worst = frames[summary["slowest_frames"][0]["frame_index"]]
summary["worst_frame_large_nested_zones"] = sorted([
    {"name": name, "offset_ms": (start - worst[0]) / 1e6, "duration_ms": (end - start) / 1e6}
    for name in ("LLPipeline::renderShadow", "LLPipeline::stateSort", "LLPipeline::postSort",
                 "LLPipeline::rebuildPriorityGroups", "LLVolumeGeometryManager::rebuildGeom")
    for start, end, t in events[name]
    if t == thread and worst[0] <= start and end <= worst[1] and end - start > 1e6
], key=lambda zone: zone["offset_ms"])

background = defaultdict(lambda: {"calls": 0, "self_ms": 0})
for path in sorted(ROOT.glob("background-*.psv")):
    for row in rows(path):
        name = row["name"]
        if name.startswith("LLThreadSafeQueue"):
            if not name.endswith("::pop"):
                continue
            name = "LLThreadSafeQueue::pop"
        key = (name, int(row["thread"]))
        background[key]["calls"] += 1
        background[key]["self_ms"] += int(row["exec_time_ns"]) / 1e6
summary["background_self_by_thread"] = [
    {"name": name, "thread_export_id": tid, **value}
    for (name, tid), value in background.items()
]

with (ROOT / "per-frame.csv").open("w", newline="", encoding="utf-8") as stream:
    writer = csv.writer(stream)
    writer.writerow(["frame_index", "relative_seconds", "frame_ms"] + [k + "_ms" for k in allocations[0]])
    for i, allocation in enumerate(allocations):
        writer.writerow([i, (starts[i] - starts[0]) / 1e9, durations[i] / 1e6] + [v / 1e6 for v in allocation.values()])

with (ROOT / "self-time-ranked.csv").open("w", newline="", encoding="utf-8") as stream:
    data = list(rows(ROOT / "zones-self.psv"))
    writer = csv.writer(stream)
    writer.writerow(["name", "src_file", "src_line", "self_total_ms", "calls", "self_mean_us", "self_max_ms"])
    for row in sorted(data, key=lambda r: int(r["total_ns"]), reverse=True):
        writer.writerow([row["name"], row["src_file"], row["src_line"], int(row["total_ns"]) / 1e6,
                         int(row["counts"]), int(row["total_ns"]) / int(row["counts"]) / 1e3,
                         int(row["max_ns"]) / 1e6])

(ROOT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps({k: v for k, v in summary.items() if k != "zones"}, indent=2))
