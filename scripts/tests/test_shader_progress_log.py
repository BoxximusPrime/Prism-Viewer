"""Verify actual runtime program counts after startup or a settings reload.

Run the viewer with --logfile <path>, then run this script with that path.
Use GLTFEnabled, LocalTerrainPaintEnabled and RenderGTAOEnabled both on and
off across runs. A new shader missing from the progress plan fails this check.
"""
import re
import sys
from pathlib import Path


def check(path):
    log = Path(path).read_text(encoding="utf-8", errors="replace")
    plans = re.findall(r"Shader compilation planned: (\d+) programs", log)
    results = re.findall(
        r"Shader compilation finished: (\d+)/(\d+) programs; loaded=(\S+)", log
    )
    assert plans, "No shader compilation started"
    assert len(results) == len(plans), "Compilation did not finish"
    for plan, (completed, total, loaded) in zip(plans, results):
        assert loaded in ("1", "true"), "Shader loading failed"
        assert int(completed) == int(total) == int(plan), (completed, total, plan)
    assert "Shader program count differs from plan" not in log
    print(f"{path}: {len(results)} compilation pass(es), exact totals verified")


if __name__ == "__main__":
    assert len(sys.argv) > 1, "Pass one or more viewer log files"
    for path in sys.argv[1:]:
        check(path)
