from pathlib import Path
import re
import xml.etree.ElementTree as E

path = Path('indra/newview/skins/default/xui/en/floater_tools.xml')
tree = E.parse(path, parser=E.XMLParser(target=E.TreeBuilder(insert_comments=True)))
tabs = tree.getroot().find("tab_container[@name='Object Info Tabs']")
for name in ('General', 'Object', 'Features', 'Contents'):
    old = next(c for c in tabs if c.get('name') == name)
    new = E.parse(Path('tmp/edit-redesign') / (name.lower() + '.xml')).getroot()
    index = list(tabs).index(old)
    tabs.remove(old)
    tabs.insert(index, new)
E.indent(tree, space='    ')
tree.write(path, encoding='utf-8', xml_declaration=True)

def multiline_attributes(match):
    indent, tag, attributes, end = match.groups()
    attrs = re.findall(r'[\w.:-]+="[^"]*"', attributes)
    if len(match.group()) < 120:
        return match.group()
    return indent + '<' + tag + '\n' + '\n'.join(indent + '    ' + a for a in attrs) + end

text = path.read_text(encoding='utf-8')
text = re.sub(r'(?m)^(\s*)<([\w.]+) ([^<>]*?)(\s*/?>)', multiline_attributes, text)
path.write_text(text + '\n', encoding='utf-8')
print('Integrated General, Object, Features, and Content tab fragments.')
