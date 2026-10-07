"""Install only this server's project configuration, preserving other sections."""
import json
from pathlib import Path
import re
import sys
import tomllib

root = Path(__file__).resolve().parents[2]
config = root / ".codex/config.toml"
old = config.read_text(encoding="utf-8") if config.exists() else ""
tomllib.loads(old)  # Refuse to edit a malformed config.
header = "[mcp_servers.prism-viewer]"
section = (header + "\ncommand = " + json.dumps(Path(sys.executable).as_posix()) +
           "\nargs = [" + json.dumps((Path(__file__).parent / "server.py").as_posix()) +
           "]\ncwd = " + json.dumps(root.as_posix()) +
           "\nstartup_timeout_sec = 20\ntool_timeout_sec = 180\n")
pattern = r"(?m)^\[mcp_servers\.prism-viewer\][^\n]*\n[^\[]*"
if re.search(pattern, old):
    # Match until the next table header, not brackets in an args value.
    start = old.index(header)
    next_table = re.search(r"(?m)^\[", old[start+len(header):])
    end = start+len(header)+next_table.start() if next_table else len(old)
    updated = old[:start] + section + "\n" + old[end:]
else:
    updated = old.rstrip() + "\n\n" + section
tomllib.loads(updated)
config.parent.mkdir(exist_ok=True)
config.write_text(updated.lstrip(), encoding="utf-8")
print(f"Configured prism-viewer in {config}")
