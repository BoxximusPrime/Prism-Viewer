from pathlib import Path
import re
import xml.etree.ElementTree as ET

base = Path('indra/newview/skins/default/xui')

def attrs(tag):
    return dict(re.findall(r'([\w.]+)="([^"]*)"', tag))

def set_attr(tag, key, value):
    pattern = rf'{re.escape(key)}="[^"]*"'
    if re.search(pattern, tag):
        return re.sub(pattern, f'{key}="{value}"', tag)
    return tag.replace('>', f' {key}="{value}">', 1)

def rounded(match):
    tag = match.group(0)
    a = attrs(tag)
    is_border = tag.startswith('<view_border')
    if is_border and a.get('name') not in {
        'object_flags_border', 'position_border', 'size_border', 'rotation_border',
        'shape_border', 'surface_group_border', 'texture_group_border', 'mapping_group_border'
    }:
        return tag
    if not is_border and a.get('border') != 'true':
        return tag
    if a.get('name') == 'contents_inventory':
        return tag
    tag = re.sub(r'\s+bevel_style="[^"]*"', '', tag)
    tag = tag.replace('<view_border', '<panel').replace('/>', '>')
    if a.get('name', '').endswith('_group_border'):
        tag = set_attr(tag, 'width', '504')
        a['width'] = '504'
    for key, value in {
        'border': 'false', 'background_visible': 'true', 'mouse_opaque': 'false',
        'bg_alpha_image': 'Rounded_Rect', 'bg_alpha_image_overlay': 'EditSectionBorder',
    }.items():
        tag = set_attr(tag, key, value)
    inner = (f'\n                        <panel name="{a["name"]}_fill" left="1" top="1"'
             f' width="{int(a["width"])-2}" height="{int(a["height"])-2}"'
             ' layout="topleft" follows="all" mouse_opaque="false" border="false"'
             ' background_visible="true" bg_alpha_image="Rounded_Rect"'
             ' bg_alpha_image_overlay="EditSectionBackground" />')
    return tag + inner + ('\n                    </panel>' if is_border else '')

for name in ('floater_tools.xml', 'panel_tools_texture.xml'):
    path = base / 'en' / name
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'<(?:panel|view_border)\b[^>]*>', rounded, text)
    def heading(m):
        tag = m.group(0)
        if attrs(tag).get('font.style') == 'BOLD':
            tag = set_attr(tag, 'font.size', 'Small')
            tag = set_attr(tag, 'text_color', 'EditSectionHeading')
        return tag
    text = re.sub(r'<text\b[^>]*>', heading, text)
    path.write_text(text, encoding='utf-8')
    ET.parse(path)

# Use the same native button treatment as the manipulation mode row.
path = base / 'en/panel_tools_texture.xml'
text = path.read_text(encoding='utf-8')
def segment(m):
    tag = m.group(0)
    a = attrs(tag)
    label = a['label']
    width = int(a['width']) - 3
    return (tag.replace('/>', '>') +
        '\n                  <radio_item.label_text visible="false" left="0" bottom="0" width="1" height="1" />' +
        f'\n                  <radio_item.check_button left="0" bottom="0" width="{width}" height="24"'
        f' label="{label}" label_selected="{label}" font="DejaVu" font.size="LSmall" scale_image="true"'
        ' image_unselected="PushButton_Off" image_selected="PushButton_Selected"'
        ' image_disabled="PushButton_Disabled" image_disabled_selected="PushButton_Selected_Disabled"'
        ' image_pressed="PushButton_Selected" image_pressed_selected="PushButton_Selected_Press" />'
        '\n                </radio_item>')
text = re.sub(r'<radio_item\b[^>]*/>', segment, text)
path.write_text(text, encoding='utf-8')
ET.parse(path)
for path in base.glob('*/panel_tools_texture.xml'):
    if path.parent.name == 'en':
        continue
    text = path.read_text(encoding='utf-8')
    def translated_segment(m):
        tag = m.group(0)
        label = attrs(tag).get('label')
        if not label:
            return tag
        return (tag.replace('/>', '>') +
            f'<radio_item.check_button label="{label}" label_selected="{label}" /></radio_item>')
    text = re.sub(r'<radio_item\b[^>]*/>', translated_segment, text)
    path.write_text(text, encoding='utf-8')
    ET.parse(path)
