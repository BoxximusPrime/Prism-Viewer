"""Offline Area Search UI smoke test; run as a viewer --leap plugin with isolated settings.

On Windows supply a second --leap of this script with --noop: the viewer's
command-line parser treats two LEAP commands as strings rather than LLSD notation.
"""
import atexit
import json
from pathlib import Path
import sys
import time
import llsd

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "tmp/area-search-ui"
OUTPUT.mkdir(parents=True, exist_ok=True)


def receive():
    header = bytearray()
    while True:
        char = sys.stdin.buffer.read(1)
        if not char:
            raise EOFError()
        if char == b":":
            break
        header += char
    return llsd.parse(sys.stdin.buffer.read(int(header)))


reply = receive()["pump"]
if "--noop" in sys.argv:
    sys.exit(0)
log = (OUTPUT / "results.jsonl").open("w", encoding="utf-8")
serial = 0


def send(pump, data):
    packet = llsd.format_notation(dict(pump=pump, data=data))
    sys.stdout.buffer.write(str(len(packet)).encode() + b":" + packet)
    sys.stdout.buffer.flush()


def request(pump, op, **data):
    global serial
    serial += 1
    send(pump, dict(data, op=op, reply=reply, reqid=serial))
    while True:
        result = receive().get("data", {})
        if result.get("reqid") == serial:
            log.write(json.dumps(dict(op=op, **result), default=str) + "\n")
            log.flush()
            assert "error" not in result, result
            return result


def activate(path):
    request("LLWindow", "keyDown", path=path, keysym="Space")
    request("LLWindow", "keyUp", keysym="Space")


atexit.register(lambda: send("LLAppViewer", dict(op="requestQuit")))
time.sleep(5)
for notification in request("LLNotifications", "listChannelNotifications", channel="AlertModal").get("notifications", []):
    if notification.get("name") in ("FoundLegacyNsisInstallation", "PrismGraphicsDefaultsUpdate"):
        send("LLNotifications", dict(op="cancel", uuid=notification["id"]))
send("LLFloaterReg", dict(op="showInstance", name="area_search", focus=True))
time.sleep(1)
assert request("LLFloaterReg", "instanceVisible", name="area_search")["visible"]
base = next(p for p in request("LLWindow", "getPaths")["paths"] if p.endswith("/area_search")) + "/"
request("LLViewerWindow", "saveSnapshot", filename=str(OUTPUT / "floater.png"), showui=True, showhud=False)


def info(name):
    return request("LLWindow", "getInfo", path=base + name)


def header_layout():
    floater = info("")["rect"]
    results = info("objects")["rect"]
    positions = {}
    for name in ("radius", "payable", "owner_label", "owner_name", "choose_owner", "clear_owner"):
        rect = info(name)["rect"]
        assert rect["bottom"] > results["top"], (name, rect, results)
        positions[name] = floater["top"] - rect["top"]
    return positions


def resize_window(dx=0, dy=0):
    # Restoring a saved rectangle exercises the real reshape/anchor path without
    # relying on OS mouse focus when the test viewer runs in the background.
    rect = info("")["rect"]
    request("LLFloaterReg", "clickButton", name="area_search", button="llfloater_close_btn")
    request("LLViewerControl", "set", group="PerAccount", key="floater_rect_area_search",
            value=[rect["left"], rect["top"], rect["right"] + dx, rect["bottom"] + dy])
    send("LLFloaterReg", dict(op="showInstance", name="area_search", focus=True))


original_rect = info("")["rect"]
original_layout = header_layout()
resize_window(dy=-120)
taller_rect = info("")["rect"]
assert taller_rect["top"] - taller_rect["bottom"] > original_rect["top"] - original_rect["bottom"] + 80
assert header_layout() == original_layout
resize_window(dx=150)
wider_rect = info("")["rect"]
assert wider_rect["right"] - wider_rect["left"] > original_rect["right"] - original_rect["left"] + 100
assert header_layout() == original_layout
assert request("LLViewerWindow", "saveSnapshot", filename=str(OUTPUT / "floater-resized.png"),
               showui=True, showhud=False)["ok"]
resize_window(dy=240)
assert header_layout() == original_layout
resize_window(dy=-120)
resize_window(dx=-150)
assert header_layout() == original_layout


for name in ("query", "fuzzy", "payable", "scripted", "for_sale", "mine", "radius", "objects", "refresh",
             "owner_name", "choose_owner"):
    assert info(name)["available"], name
assert info("owner_name")["value"] == "Not selected"
assert not info("clear_owner")["enabled"]
assert "Log in" in info("status")["value"]
assert float(info("radius")["value"]) == 96
for name in ("fuzzy", "payable", "scripted", "for_sale", "mine"):
    assert not info(name)["value"]
    activate(base + name + "/CheckboxCtrl Button")
    assert info(name)["value"], name
    activate(base + name + "/CheckboxCtrl Button")
    assert not info(name)["value"], name

request("LLFloaterReg", "clickButton", name="area_search", button="choose_owner")
assert request("LLFloaterReg", "instanceVisible", name="avatar_picker", key="area_search")["visible"]
request("LLFloaterReg", "clickButton", name="avatar_picker", key="area_search", button="cancel_btn")
assert not request("LLFloaterReg", "instanceVisible", name="avatar_picker", key="area_search")["visible"]
assert info("owner_name")["value"] == "Not selected"

query = next(p for p in request("LLWindow", "getPaths", under=base + "query")["paths"] if p.endswith("/filter edit box"))
request("LLWindow", "pasteText", path=query, text="chair AND (")
assert "Invalid query" in info("status")["value"]
request("LLWindow", "selectAll", path=query)
request("LLWindow", "pasteText", path=query, text='(chair OR "red sofa") NOT demo')
assert "Log in" in info("status")["value"]
request("LLFloaterReg", "clickButton", name="area_search", button="refresh")
assert request("LLViewerWindow", "saveSnapshot", filename=str(OUTPUT / "floater.png"),
               showui=True, showhud=False)["ok"]
request("LLFloaterReg", "clickButton", name="area_search", button="llfloater_minimize_btn")
rect = info("")["rect"]
assert rect["top"] - rect["bottom"] < 50
activate(base + "llfloater_restore_btn")
request("LLFloaterReg", "clickButton", name="area_search", button="choose_owner")
request("LLFloaterReg", "clickButton", name="area_search", button="llfloater_close_btn")
assert not request("LLFloaterReg", "instanceVisible", name="area_search")["visible"]
assert not request("LLFloaterReg", "instanceVisible", name="avatar_picker", key="area_search")["visible"]
send("LLFloaterReg", dict(op="showInstance", name="area_search", focus=True))
assert request("LLFloaterReg", "instanceVisible", name="area_search")["visible"]
assert "Log in" in info("status")["value"]
log.write(json.dumps({"result": "PASS: resize anchors, controls, owner picker/cancel/parent close, filter toggles, query errors/recovery, refresh, minimize/restore, close/reopen"}) + "\n")
log.close()
