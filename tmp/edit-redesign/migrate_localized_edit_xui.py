"""Remap Edit floater translations onto its final English XUI hierarchy.

Dry-run is the default. Pass --write only after the English redesign is final.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET


TRANSLATED_ATTRS = ("label", "label_selected", "tool_tip")
IDENTITY_ATTRS = ("name", "value")
STRUCTURAL_STRINGS = {"panel.string", "floater.string"}
FILES = ("floater_tools.xml", "panel_tools_texture.xml")
PRIMARY_TOOL_BUTTONS = {
    "button focus", "button move", "button edit", "button create", "button land"
}
RENAMED_SOURCES = {
    "status_remaining_capacity": "remaining_capacity",
    "checkbox uniform": "checkbox uniform label",
    "mapping_repeats_label": "string repeats per meter",
}


def identity(node: ET.Element) -> tuple[str, str, str]:
    name = node.get("name", "")
    return node.tag, name, "" if name else node.get("value", "")


def match_key(node: ET.Element) -> tuple[str, str]:
    if node.get("name"):
        return "name", node.get("name")
    if node.get("value"):
        return "value", node.get("value")
    return "tag", node.tag


def semantic_parent(node: ET.Element, parents: dict[ET.Element, ET.Element]) -> str:
    parent = parents.get(node)
    while parent is not None:
        if parent.tag in {"combo_box", "radio_group", "radio_item"}:
            return parent.get("name") or parent.get("value", "")
        parent = parents.get(parent)
    return ""


def tab_scope(node: ET.Element, parents: dict[ET.Element, ET.Element]) -> str:
    current = node
    while current in parents:
        parent = parents[current]
        if parent.tag == "tab_container" and parent.get("name") == "Object Info Tabs":
            return current.get("name", "")
        current = parent
    return "__shared__"


def payload(node: ET.Element) -> dict[str, str]:
    result = {key: node.get(key) for key in TRANSLATED_ATTRS if node.get(key)}
    text = (node.text or "").strip()
    if text:
        result["#text"] = text
    return result


def source_index(scope: ET.Element) -> dict[tuple[str, str], list[ET.Element]]:
    result: dict[tuple[str, str], list[ET.Element]] = defaultdict(list)
    for node in scope.iter():
        if node.get("name") or node.get("value"):
            result[match_key(node)].append(node)
    return result


def find_source(
    target: ET.Element,
    index: dict[tuple[str, str], list[ET.Element]],
    source_parents: dict[ET.Element, ET.Element],
    target_parents: dict[ET.Element, ET.Element],
) -> ET.Element | None:
    candidates = index.get(match_key(target), [])
    renamed = not candidates and target.get("name") in RENAMED_SOURCES
    if renamed:
        candidates = index.get(("name", RENAMED_SOURCES[target.get("name")]), [])
    target_scope = tab_scope(target, target_parents)
    scoped = [node for node in candidates
              if tab_scope(node, source_parents) == target_scope]
    if scoped or not renamed:
        candidates = scoped
    target_parent = semantic_parent(target, target_parents)
    if target_parent:
        narrowed = [node for node in candidates
                    if semantic_parent(node, source_parents) == target_parent]
        if narrowed:
            candidates = narrowed
    if candidates:
        return candidates[0]

    # Some final radio layouts expose the visible caption on a nested
    # check_button. In that case inherit the matching legacy radio_item text.
    if target.tag == "radio_item.check_button":
        parent = target_parents.get(target)
        if parent is not None and parent.tag == "radio_item":
            radio_candidates = index.get(match_key(parent), [])
            scoped = [node for node in radio_candidates
                      if tab_scope(node, source_parents) == target_scope]
            if scoped:
                radio_candidates = scoped
            if radio_candidates:
                nested = radio_candidates[0].find("radio_item.check_button")
                return nested if nested is not None else radio_candidates[0]
    return None


def translated_value(
    source: ET.Element,
    target: ET.Element,
    key: str,
) -> str | None:
    value = payload(source).get(key)
    if not value:
        return None
    final_value = payload(target).get(key)
    if value == final_value:
        return None
    return value


def overlay_subtree(
    target: ET.Element,
    source_scope: ET.Element,
    ignored_unmatched_scopes: set[str] | None = None,
) -> tuple[ET.Element, int, list[str]]:
    source_parents = {child: parent for parent in source_scope.iter() for child in parent}
    target_parents = {child: parent for parent in target.iter() for child in parent}
    index = source_index(source_scope)
    used: set[ET.Element] = set()
    retained = 0

    def build(final: ET.Element) -> ET.Element | None:
        nonlocal retained
        result = ET.Element(final.tag)
        for key in IDENTITY_ATTRS:
            if final.get(key):
                result.set(key, final.get(key))
        source = find_source(final, index, source_parents, target_parents)
        if source is not None:
            used.add(source)
            for key in TRANSLATED_ATTRS:
                value = translated_value(source, final, key)
                if value:
                    result.set(key, value)
                    retained += 1
            text = translated_value(source, final, "#text")
            if text:
                result.text = text
                retained += 1
            if (final.tag == "button" and final.get("name") in PRIMARY_TOOL_BUTTONS
                    and not result.get("label") and source.get("tool_tip")):
                result.set("label", source.get("tool_tip"))
                retained += 1
            if final.tag == "radio_item.check_button":
                label = source.get("label")
                if label and label != final.get("label"):
                    result.set("label", label)
                    result.set("label_selected", source.get("label_selected", label))
                    retained += 2
        for final_child in final:
            child = build(final_child)
            if child is not None:
                result.append(child)
        has_translation = any(key in result.attrib for key in TRANSLATED_ATTRS)
        has_identity = any(key in result.attrib for key in IDENTITY_ATTRS)
        if result.text or len(result) or (has_translation and
                                          (has_identity or final.tag == "radio_item.check_button")):
            return result
        return None

    built = build(target)
    assert built is not None
    unmatched = []
    used_locations = {
        (match_key(node), semantic_parent(node, source_parents),
         tab_scope(node, source_parents))
        for node in used
    }
    for node in source_scope.iter():
        translated = payload(node)
        location = (match_key(node), semantic_parent(node, source_parents),
                    tab_scope(node, source_parents))
        if (translated and node not in used and
                location not in used_locations and
                tab_scope(node, source_parents) not in (ignored_unmatched_scopes or set())):
            untranslated = ", ".join(f"{key}={value!r}" for key, value in translated.items())
            unmatched.append(f"{tab_scope(node, source_parents)}:{identity(node)} [{untranslated}]")
    return built, retained, unmatched


def replace_overlay(final_root: ET.Element, locale_root: ET.Element) -> tuple[int, list[str]]:
    rebuilt, retained, unmatched = overlay_subtree(final_root, locale_root)
    locale_root[:] = list(rebuilt)
    keep = {"name"}
    for key in TRANSLATED_ATTRS:
        if locale_root.get(key):
            keep.add(key)
    locale_root.attrib = {key: value for key, value in locale_root.attrib.items() if key in keep}
    return retained, unmatched


def validate(final_root: ET.Element, locale_root: ET.Element, filename: str) -> None:
    final_ids = {match_key(node) for node in final_root.iter()}
    geometry = {"left", "top", "width", "height", "left_pad", "top_pad",
                "left_delta", "top_delta", "follows"}
    for node in locale_root.iter():
        assert not geometry.intersection(node.attrib), (filename, identity(node), node.attrib)
        if node.tag not in STRUCTURAL_STRINGS and (node.get("name") or node.get("value")):
            assert match_key(node) in final_ids, (filename, "orphan", identity(node))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--xui", type=Path,
                        default=Path(__file__).resolve().parents[2] /
                        "indra/newview/skins/default/xui")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    locale_dirs = sorted(path for path in args.xui.iterdir()
                         if path.is_dir() and path.name != "en")
    try:
        import sys
        sys.stdout.reconfigure(errors="backslashreplace")
    except AttributeError:
        pass

    changed = 0
    retained_total = 0
    unmatched_total = 0
    final_floater = ET.parse(args.xui / "en" / "floater_tools.xml").getroot()
    final_texture = ET.parse(args.xui / "en" / "panel_tools_texture.xml").getroot()
    repo = args.xui.resolve().parents[4]

    def legacy_tree(path: Path) -> ET.ElementTree | None:
        try:
            relative = path.resolve().relative_to(repo).as_posix()
            data = subprocess.check_output(
                ["git", "show", f"HEAD:{relative}"], cwd=repo,
                stderr=subprocess.DEVNULL)
            return ET.ElementTree(ET.fromstring(data))
        except (subprocess.CalledProcessError, ValueError):
            return ET.parse(path) if path.exists() else None

    for locale in locale_dirs:
        floater_path = locale / "floater_tools.xml"
        if not floater_path.exists():
            continue
        floater_tree = ET.parse(floater_path)
        source_floater_tree = legacy_tree(floater_path)
        assert source_floater_tree is not None
        old_floater = source_floater_tree.getroot()
        embedded_texture = old_floater.find(".//panel[@name='Texture']")

        rebuilt_floater, retained, unmatched = overlay_subtree(
            final_floater, old_floater, {"Texture"})
        locale_floater = floater_tree.getroot()
        locale_floater[:] = list(rebuilt_floater)
        locale_floater.attrib = {
            key: value for key, value in old_floater.attrib.items()
            if key == "name" or key in TRANSLATED_ATTRS
        }
        validate(final_floater, locale_floater, "floater_tools.xml")
        changed += 1
        retained_total += retained
        unmatched_total += len(unmatched)
        print(f"{locale.name}/floater_tools.xml: retained={retained}, unmatched={len(unmatched)}")
        for entry in unmatched:
            print(f"  unmatched: {entry}")

        texture_path = locale / "panel_tools_texture.xml"
        texture_tree = ET.parse(texture_path) if texture_path.exists() else None
        source_texture_tree = legacy_tree(texture_path)
        texture_source = ET.Element("panel", {"name": "Texture"})
        # Prefer the dedicated override, then use legacy translations embedded
        # in floater_tools.xml (notably the Danish locale).
        if source_texture_tree is not None:
            for child in source_texture_tree.getroot():
                texture_source.append(deepcopy(child))
            texture_source.attrib.update(source_texture_tree.getroot().attrib)
        if embedded_texture is not None:
            for child in embedded_texture:
                texture_source.append(deepcopy(child))

        rebuilt_texture, retained, unmatched = overlay_subtree(
            final_texture, texture_source)
        if texture_tree is None:
            texture_tree = ET.ElementTree(ET.Element("panel", {"name": "Texture"}))
        locale_texture = texture_tree.getroot()
        locale_texture[:] = list(rebuilt_texture)
        locale_texture.attrib = {
            key: value for key, value in texture_source.attrib.items()
            if key == "name" or key in TRANSLATED_ATTRS
        }
        validate(final_texture, locale_texture, "panel_tools_texture.xml")
        changed += 1
        retained_total += retained
        unmatched_total += len(unmatched)
        print(f"{locale.name}/panel_tools_texture.xml: retained={retained}, unmatched={len(unmatched)}")
        for entry in unmatched:
            print(f"  unmatched: {entry}")

        if args.write:
            for tree, path in ((floater_tree, floater_path), (texture_tree, texture_path)):
                ET.indent(tree, space="\t")
                tree.write(path, encoding="utf-8", xml_declaration=True,
                           short_empty_elements=True)

    mode = "updated" if args.write else "validated (dry run)"
    print(f"{changed} localized Edit XUI overlays {mode}; "
          f"retained={retained_total}, unmatched={unmatched_total}")


if __name__ == "__main__":
    main()
