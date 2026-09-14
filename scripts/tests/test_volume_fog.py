"""Compile the production fog tag parser and validate edits/malformed input."""
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
SOURCE = r'''
#include "llvolumefogparams.h"
#include <cassert>
#include <iostream>
int main() {
    LLVolumeFogParams p;
    assert(parseVolumeFogDescription("[vfog:0.5,<255,0,255>,6]",p));
    assert(p.density==.5f && p.color[0]==1.f && p.color[1]==0.f && p.color[2]==1.f && p.softness==6.f);
    assert(parseVolumeFogDescription("Club [VFOG: .03, <128, 200, 255> ] [no-shadow]",p));
    assert(p.softness==0.f && p.color[0]==128.f/255.f);
    assert(parseVolumeFogDescription("[vfog:0,<0,0,0>,0]",p) && p.density==0.f);
    assert(parseVolumeFogDescription("[vfog:1e-2,<255,255,255>,.5]",p));
    assert(parseVolumeFogDescription("[vfog:10,<255,255,255>,1024]",p));
    const char* invalid[] = {
        "", "[vfog]", "vfog:0.5,<255,0,255>,6", "[vfog:0.5,<255,0,255>,6",
        "[vfog:-1,<255,0,255>]", "[vfog:10.1,<255,0,255>]", "[vfog:0.5,<256,0,255>]",
        "[vfog:0.5,<255,-1,255>]", "[vfog:0.5,<255,0,255>,-6]", "[vfog:0.5,<255,0,255>,1025]",
        "[vfog:nan,<255,0,255>]", "[vfog:inf,<255,0,255>]", "[vfog:1e100,<255,0,255>]",
        "[vfog:0.5,<255,nan,255>]", "[vfog:0.5,<255,0,255>,inf]", "[vfog:0.5,<255,0>]",
        "[vfog:0.5,255,0,255]", "[vfog:0.5,<255,0,255>,]", "[vfog:0.5,<255,0,255>,1,2]",
        "[vfog:0.5,<255,0,255> trailing]", "[vfog:0.5;<255,0,255>]"
    };
    for (auto text:invalid) {
        p.density=1; p.softness=8;
        assert(!parseVolumeFogDescription(text,p));
        assert(p.density==0 && p.softness==0);
    }
    std::cout<<"PASS: 26 production parser cases, including removal/reset and invalid numeric values\n";
}
'''

with tempfile.TemporaryDirectory(prefix="volume-fog-parser-") as directory:
    cpp, exe = Path(directory)/"test.cpp", Path(directory)/"test.exe"
    cpp.write_text(SOURCE, encoding="utf-8")
    subprocess.run(["g++", "-std=c++17", "-O2", "-I", str(ROOT/"indra/newview"), str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
settings = ET.parse(ROOT/"indra/newview/app_settings/settings.xml")
keys = [key.text for key in settings.findall("./map/key")]
assert len(keys) == len(set(keys))
assert "RenderVolumeFog" in keys
panel = ET.parse(ROOT/"indra/newview/skins/default/xui/en/panel_preferences_graphics1.xml")
fog_tab = panel.find(".//panel[@name='graphics_volume_fog_panel']")
assert fog_tab is not None and fog_tab.get("label") == "Volumetric Fog"
controls = {node.get("control_name"): node for node in fog_tab if node.get("control_name")}
assert set(controls) == {"RenderVolumeFog", "RenderVolumeFogIntensity", "RenderVolumeFogQuality",
                         "RenderVolumeFogLightCount", "RenderVolumeFogShadows", "RenderVolumeFogLightStrength"}
assert all(name in keys for name in controls)
assert [item.get("value") for item in controls["RenderVolumeFogQuality"].findall("combo_box.item")] == ["0","1","2","3"]
all_names = [node.get("name") for node in panel.iter() if node.get("name")]
assert all(all_names.count(node.get("name")) == 1 for node in fog_tab if node.get("name"))
print("PASS: unique settings, fog tab bindings and all four quality options")
