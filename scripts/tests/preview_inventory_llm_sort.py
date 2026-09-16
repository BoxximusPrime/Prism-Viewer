"""Stage an inert XUI specimen built from the actual floater and row layouts."""
from pathlib import Path
import copy
import xml.etree.ElementTree as ET
ROOT = Path(__file__).resolve().parents[2]
skin = ROOT / "indra/newview/skins/default/xui/en"
tree = ET.parse(skin / "floater_inventory_llm_sort.xml")
floater = tree.getroot()
floater.set("name", "inventory_llm_sort_specimen")
floater.set("title", "LLM Sort — Layout preview (sample data)")
floater.remove(floater.find("./panel[@name='root_picker']"))
def node(name):
    return floater.find(f".//*[@name='{name}']")
node("root_path").text = "My Inventory / Clothing"
node("categories").text = "Existing categories: Tops · Bottoms"
node("model").text = "Local model"
node("all").set("label", "All (5)")
node("all").set("initial_value", "true")
node("attention").set("label", "Needs attention (2)")
node("count").text = "0 of 5 reviewed"
node("status").text = "Sample data only. Preview controls do not modify inventory."
rows = node("rows")
row_template = ET.parse(skin / "panel_inventory_llm_sort_row.xml").getroot()
samples = [("Linen Shirt — Cream", "tops", "Tops"), ("Cargo Pants — Black", "bottoms", "Bottoms"),
           ("Oversized Knit Sweater", "tops", "Tops"), ("Leather Ankle Boots", "shoes", "new"),
           ("Mira — Midnight (boxed)", "", "unsure")]
for i, (name, icon, category) in enumerate(samples):
    row = copy.deepcopy(row_template)
    row.set("name", "sample_" + str(i)); row.set("left", "0"); row.set("top", str(i * 88))
    rows.append(row)
    def child(name): return row.find(f".//*[@name='{name}']")
    child("item_name").text = name
    child("category_icon").set("image_name", "SortCategory_" + icon if icon else "Inv_Object")
    combo = child("destination")
    label = "+ New folder…" if category == "new" else "Choose folder…" if category == "unsure" else category
    ET.SubElement(combo, "combo_box.item", {"label": label, "value": label})
    if category == "new":
        child("new_name").set("visible", "true"); child("new_name").set("value", "Shoes")
        child("new_badge").set("visible", "true")
        child("approve").set("label", "Create & Move"); child("approve").set("image_color", "0.85 0.66 0.33 1")
        child("reason").text = "No matching category under Clothing"
        # Also preview this row through LLPanel::buildFromFile, as the real review does.
        # Nesting it in a floater can hide a missing root layout through inheritance.
        standalone = copy.deepcopy(row)
        standalone.set("top", "0")
        standalone_tree = ET.ElementTree(standalone)
        ET.indent(standalone_tree)
        standalone_tree.write(ROOT / "build-vc170-64/newview/Release/skins/default/xui/en/panel_inventory_llm_sort_specimen.xml",
                              encoding="utf-8", xml_declaration=True)
    elif category == "unsure":
        child("reason").text = "Name is unclear. Choose a folder."
        child("approve").set("enabled", "false")
    else: child("reason").text = "Matches the item name"
destination = ROOT / "build-vc170-64/newview/Release/skins/default/xui/en/floater_inventory_llm_sort_specimen.xml"
ET.indent(tree)
tree.write(destination, encoding="utf-8", xml_declaration=True)
print(destination)
