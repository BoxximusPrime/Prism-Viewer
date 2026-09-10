from pathlib import Path
import re
import xml.etree.ElementTree as ET

path = Path('indra/newview/skins/default/xui/en/floater_tools.xml')
text = path.read_text(encoding='utf-8')
body = ET.fromstring(text).find(".//panel[@name='general_scroll_body']")
changes = {
    'general_scroll_body': {'height': '660'},
    'identity_section': {'height': '88'},
    'identity_section_fill': {'height': '86'},
}
for child in body:
    if child.get('name') != 'identity_section' and child.get('top'):
        changes[child.get('name')] = {'top': str(int(child.get('top')) + 10)}

def update(m):
    tag = m.group(0)
    name = re.search(r'\bname="([^"]+)"', tag)
    for key, value in changes.get(name[1] if name else '', {}).items():
        tag = re.sub(rf'\b{key}="[^"]*"', f'{key}="{value}"', tag)
    return tag

text = re.sub(r'<[\w.]+\b[^>]*>', update, text)
path.write_text(text, encoding='utf-8')
ET.parse(path)
