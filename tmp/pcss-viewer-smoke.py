"""One-shot preference/startup check through the viewer's built-in LEAP API."""
import json
from pathlib import Path
import sys
import time
import llsd

OUT = Path("E:/BoxxyViewer/tmp")
log = None if "noop" in sys.argv else (OUT / "pcss-viewer-smoke.jsonl").open("w", encoding="utf-8")

def get():
    header = bytearray()
    while True:
        char = sys.stdin.buffer.read(1)
        if not char:
            raise EOFError()
        if char == b":":
            break
        header += char
    return llsd.parse(sys.stdin.buffer.read(int(header)))

reply = get()["pump"]
if "noop" in sys.argv:
    sys.exit(0)
serial = 0

def send(pump, data):
    packet = llsd.format_notation(dict(pump=pump, data=data))
    sys.stdout.buffer.write(str(len(packet)).encode() + b":" + packet)
    sys.stdout.buffer.flush()

def request(pump, op, **data):
    global serial
    serial += 1
    data.update(op=op, reply=reply, reqid=serial)
    send(pump, data)
    while True:
        result = get().get("data", {})
        if result.get("reqid") == serial:
            log.write(json.dumps(dict(op=op, **result), default=str) + "\n")
            log.flush()
            assert "error" not in result, result
            return result

def setting(key, value):
    return request("LLViewerControl", "set", group="Global", key=key, value=value)

def show_tab():
    send("LLFloaterReg", dict(op="showInstance", name="preferences", focus=True))
    assert request("LLFloaterReg", "instanceVisible", name="preferences")["visible"]
    request("LLFloaterReg", "clickButton", name="preferences", button="vtab_display")
    request("LLFloaterReg", "clickButton", name="preferences", button="htab_graphics_pcss_panel")
    time.sleep(1)

def snapshot(name):
    tree = request("LLWindow", "getSubtree", under="/main_view/menu_stack/world_panel/Floater View/Preferences")
    (OUT / (name + ".json")).write_text(json.dumps(tree), encoding="utf-8")
    result = request("LLViewerWindow", "saveSnapshot", filename=str(OUT / name), showui=True, showhud=False)
    assert result["ok"], result

def enabled(name, expected):
    info = request("LLWindow", "getInfo", path="/main_view/menu_stack/world_panel/Floater View/Preferences/pref core/display/graphics_tab_container/graphics_pcss_panel/" + name)
    assert info["enabled"] == expected, (name, info)

time.sleep(2)
paths = request("LLWindow", "getPaths")["paths"]
notice_buttons = [path for path in paths if path.endswith("/OK_okbutton")]
if len(notice_buttons) == 1:
    info = request("LLWindow", "getInfo", path=notice_buttons[0])
    if info["available"]:
        request("LLWindow", "mouseDown", path=notice_buttons[0], button="LEFT")
        request("LLWindow", "mouseUp", path=notice_buttons[0], button="LEFT")
for note in request("LLNotifications", "listChannelNotifications", channel="Visible").get("notifications", []):
    if note.get("name") == "FoundLegacyNsisInstallation":
        send("LLNotifications", dict(op="respond", uuid=note["id"], response={"OK_okbutton": True}))
setting("RenderShadowDetail", 2)
setting("RenderPCSSEnabled", True)
show_tab()
if "visual" in sys.argv:
    snapshot("pcss-preferences-clean.png")
    log.write(json.dumps(dict(result="PASS: clean PCSS tab capture")) + "\n")
    log.close()
    send("LLAppViewer", dict(op="requestQuit"))
    sys.exit(0)
snapshot("pcss-preferences-on.png")
enabled("RenderPCSSMinSoftness", True)
enabled("RenderPCSSProjectorSize", True)
send("LLFloaterReg", dict(op="hideInstance", name="preferences"))
setting("RenderPCSSEnabled", False)
show_tab()
snapshot("pcss-preferences-off.png")
enabled("RenderPCSSMinSoftness", False)
enabled("RenderPCSSProjectorSize", False)
setting("RenderPCSSEnabled", True)
setting("RenderPCSSLightSize", 2.0)
setting("RenderPCSSMaxSoftness", 0.5)
setting("RenderPCSSMinSoftness", 0.1)
setting("RenderPCSSProjectorSize", 0.5)
setting("RenderPCSSBias", 2.5)
setting("RenderPCSSQuality", 2)
request("LLFloaterReg", "clickButton", name="preferences", button="Cancel")
for key, expected in (("RenderPCSSEnabled", False), ("RenderPCSSLightSize", .53),
                      ("RenderPCSSMinSoftness", .02), ("RenderPCSSProjectorSize", .1),
                      ("RenderPCSSMaxSoftness", 1.0), ("RenderPCSSBias", 5.0), ("RenderPCSSQuality", 1)):
    value = request("LLViewerControl", "get", group="Global", key=key)["value"]
    assert abs(value - expected) < .0001, (key, value, expected)
setting("RenderShadowDetail", 1)
setting("RenderPCSSEnabled", True)
show_tab()
enabled("RenderPCSSMinSoftness", True)
enabled("RenderPCSSProjectorSize", False)
snapshot("pcss-preferences-sun-only.png")
request("LLFloaterReg", "clickButton", name="preferences", button="Cancel")
setting("RenderShadowDetail", 0)
show_tab()
snapshot("pcss-preferences-shadows-off.png")
enabled("RenderPCSSMinSoftness", False)
enabled("RenderPCSSProjectorSize", False)
request("LLFloaterReg", "clickButton", name="preferences", button="Cancel")
log.write(json.dumps(dict(result="PASS: PCSS tab builds; on/off/shadows-off snapshots and Cancel restores all seven settings")) + "\n")
log.close()
send("LLAppViewer", dict(op="requestQuit"))
