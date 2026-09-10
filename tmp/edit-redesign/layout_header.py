from pathlib import Path
import xml.etree.ElementTree as E

path = Path('indra/newview/skins/default/xui/en/floater_tools.xml')
tree = E.parse(path, parser=E.XMLParser(target=E.TreeBuilder(insert_comments=True)))
root = tree.getroot()
root.attrib.update(width='560', height='924', min_width='560', min_height='620',
                   can_resize='true', title='Edit object')
named = {c.get('name'): c for c in root if isinstance(c.tag, str)}

def place(node, left, top, width, height, **attrs):
    for key in ('left', 'top', 'right', 'bottom', 'left_pad', 'top_pad',
                'left_delta', 'top_delta', 'right_delta', 'bottom_delta'):
        node.attrib.pop(key, None)
    node.attrib.update(left=str(left), top=str(top), width=str(width),
                       height=str(height), layout='topleft', follows='left|top', **attrs)

def at(name, *args, **kwargs):
    place(named[name], *args, **kwargs)

background = E.Element('panel', dict(name='shared_tools_background', left='8', top='26',
    width='544', height='218', follows='left|top|right', layout='topleft',
    mouse_opaque='false', background_visible='true', bg_alpha_color='PanelDefaultBackgroundColor'))
root.insert(list(root).index(named['button focus']), background)

for i, name in enumerate(('focus', 'move', 'edit', 'create', 'land')):
    at('button ' + name, 12 + i * 108, 32, 104, 30,
       label=name.title(), image_overlay_alignment='left', pad_left='24',
       is_toggle='true', initial_value='true' if name == 'edit' else 'false')

def mode_buttons(name, widths):
    group = named[name]
    place(group, 12, 72, 536, 28)
    x = 0
    for item, width in zip(group.findall('radio_item'), widths):
        label = item.get('label')
        place(item, x, 0, width, 28)
        item.set('tool_tip', label)
        E.SubElement(item, 'radio_item.label_text', dict(visible='false', left='0', bottom='0', width='1', height='1'))
        E.SubElement(item, 'radio_item.check_button', dict(left='0', bottom='0', width=str(width), height='28',
            label=label, label_selected=label, font='DejaVu', **{'font.size':'LSmall'},
            scale_image='true', image_unselected='PushButton_Off', image_selected='PushButton_Selected',
            image_disabled='PushButton_Disabled', image_disabled_selected='PushButton_Selected_Disabled',
            image_pressed='PushButton_Selected', image_pressed_selected='PushButton_Selected_Press'))
        x += width + 4

mode_buttons('edit_radio_group', (94, 126, 176, 128))
named['edit_radio_group'].set('initial_value', 'radio position')
mode_buttons('focus_radio_group', (170, 170, 188))
mode_buttons('move_radio_group', (170, 170, 188))
at('slider zoom', 24, 120, 500, 24)

at('combobox grid mode', 12, 110, 214, 24, tool_tip='Grid ruler: World, Local, or Reference; choices depend on the selection')
at('checkbox snap to grid', 246, 111, 98, 22)
at('Options...', 394, 110, 154, 24, label='Grid options...')
for key in ('image_selected', 'image_unselected'):
    named['Options...'].attrib.pop(key, None)
at('checkbox edit linked parts', 12, 142, 270, 22)
at('link_btn', 346, 140, 98, 24)
at('unlink_btn', 450, 140, 98, 24)
at('checkbox uniform', 12, 174, 252, 22)
named['checkbox uniform'].attrib.pop('label_text.wrap', None)
named['checkbox uniform'].attrib.pop('label_text.width', None)
at('checkbox stretch textures', 286, 174, 262, 22)
at('text status', 12, 202, 536, 18, word_wrap='false')
at('selection_empty', 12, 224, 536, 18, text_color='LabelDisabledColor')
at('selection_count', 12, 224, 348, 18, text_color='LabelTextColor')
at('selection_faces', 366, 224, 182, 18, use_ellipses='true', text_color='LabelTextColor')
at('cost_text_border', 12, 250, 536, 0)

# Other primary modes occupy the same contextual toolbar area.
create_buttons = [c for c in root if isinstance(c.tag, str) and c.get('name', '').startswith('Tool')]
for i, node in enumerate(create_buttons):
    place(node, 16 + i % 5 * 48, 76 + i // 5 * 38, 36, 30, visible='false')
for i, name in enumerate(('checkbox sticky', 'checkbox copy selection', 'checkbox copy centers', 'checkbox copy rotates')):
    at(name, 290, 76 + i * 30, 258, 22, visible='false')
at('land_radio_group', 12, 74, 296, 108, visible='false')
for i, item in enumerate(named['land_radio_group'].findall('radio_item')):
    place(item, i // 4 * 150, i % 4 * 26, 146, 22)
at('Bulldozer:', 326, 76, 214, 18, visible='false', font='DejaVu', **{'font.style':'BOLD', 'font.size':'LSmall'})
at('Dozer Size:', 326, 104, 62, 18, visible='false')
at('slider brush size', 390, 100, 150, 24, visible='false')
at('Strength:', 326, 134, 62, 18, visible='false')
at('slider force', 390, 130, 150, 24, visible='false')
at('button apply to selection', 326, 168, 214, 24, visible='false')
for name in ('focus_radio_group', 'move_radio_group', 'slider zoom'):
    named[name].set('visible', 'false')

tabs = named['Object Info Tabs']
place(tabs, 12, 266, 536, 646, tab_height='28', tab_min_width='100', tab_max_width='108')
tabs.set('follows', 'all')

# Land keeps its own information panel, using the same section rhythm.
land = named['land info panel']
place(land, 12, 266, 536, 620, visible='false')
land.set('follows', 'all')
land_children = {c.get('name'): c for c in land}
positions = {
    'label_parcel_info': (12, 16, 512, 22),
    'label_area_price': (12, 48, 512, 20),
    'label_area': (12, 48, 512, 20),
    'button about land': (12, 80, 242, 24),
    'checkbox show owners': (274, 81, 250, 22),
    'label_parcel_modify': (12, 132, 512, 22),
    'button subdivide land': (12, 164, 242, 24),
    'button join land': (274, 164, 250, 24),
    'label_parcel_trans': (12, 216, 512, 22),
    'button buy land': (12, 248, 242, 24),
    'button abandon land': (274, 248, 250, 24),
}
for name, rect in positions.items():
    place(land_children[name], *rect)
    if name.startswith('label_parcel_'):
        land_children[name].set('font.style', 'BOLD')

E.indent(tree, space='    ')
tree.write(path, encoding='utf-8', xml_declaration=True)
