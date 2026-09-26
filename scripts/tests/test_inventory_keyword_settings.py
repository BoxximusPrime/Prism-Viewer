"""Validate inventory keyword settings bindings and scrollable control layout.

Run with: python scripts/tests/test_inventory_keyword_settings.py
No viewer build or external packages required.
"""
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
VIEWER = ROOT / "indra/newview"


def main():
    settings = ET.parse(VIEWER / "app_settings/settings.xml").getroot().find("map")
    nodes = list(settings)
    saved = {nodes[i].text: nodes[i + 1] for i in range(0, len(nodes), 2)}
    colors = ET.parse(VIEWER / "skins/default/colors.xml").getroot()
    color_names = {color.get("name") for color in colors}
    ui = ET.parse(VIEWER / "skins/default/xui/en/floater_inventory_settings.xml").getroot()
    scroll = ui.find("scroll_container")
    panel = scroll.find("panel")
    assert int(scroll.get("top")) + int(scroll.get("height")) <= int(ui.get("height"))
    assert int(panel.get("height")) > int(scroll.get("height"))

    # Resolve the relative XUI positions used by this panel to catch controls
    # extending beyond the scrollable content or a swatch covering its editor.
    rects = {}
    left = top = right = bottom = 0
    for control in panel:
        a = control.attrib
        top = int(a["top"]) if "top" in a else (
            top + int(a["top_delta"]) if "top_delta" in a else bottom + int(a.get("top_pad", 0)))
        left = int(a["left"]) if "left" in a else (
            left + int(a["left_delta"]) if "left_delta" in a else right + int(a.get("left_pad", 0)))
        right, bottom = left + int(a["width"]), top + int(a["height"])
        assert 0 <= left < right <= int(panel.get("width")), a["name"]
        assert 0 <= top < bottom <= int(panel.get("height")), a["name"]
        rects[a["name"]] = (left, top, right, bottom)

    for editor, setting, swatch, color in (
        ("priority_keywords", "InventoryDemoHelperKeywords", "priority_swatch", "InventoryPriorityColor"),
        ("folder_keywords", "InventoryFolderHighlightKeywords", "folder_keyword_swatch", "InventoryFolderKeywordColor"),
    ):
        field = panel.find(f"line_editor[@name='{editor}']")
        assert field.get("control_name") == setting
        values = list(saved[setting])
        definition = {values[i].text: values[i + 1].text for i in range(0, len(values), 2)}
        assert definition["Type"] == "String" and definition["Persist"] == "1"
        picker = panel.find(f"color_swatch[@name='{swatch}']")
        assert picker.get("can_apply_immediately") == "true"
        assert color in color_names
        for event, function in (("init", "getUIColor"), ("commit", "applyUIColor")):
            callback = picker.find(f"color_swatch.{event}_callback")
            assert callback.get("function") == f"ScriptPref.{function}"
            assert callback.get("parameter") == color
        field_rect, picker_rect = rects[editor], rects[swatch]
        assert field_rect[2] < picker_rect[0] and field_rect[1] == picker_rect[1]
    assert rects["priority_keywords"][3] < rects["folder_highlight_label"][1]
    print("Inventory keyword bindings, color controls, and scrollable layout: PASS")


if __name__ == "__main__":
    main()
