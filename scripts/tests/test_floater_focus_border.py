"""Check the window outline asset and scaling; --write regenerates the UI mask."""
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from PIL import Image

root = Path(__file__).resolve().parents[2]
skin = root / 'indra/newview/skins/default'
windows = skin / 'textures/windows'
background = Image.open(windows / 'Window_Foreground.png').convert('RGBA')
width, height = background.size
alpha = background.getchannel('A')
outline = Image.new('RGBA', background.size, (255, 255, 255, 0))
for y in range(height):
    fade = max(0, min(1, (20 - y) / 10))
    for x in range(width):
        # One-pixel inner edge, retaining the original corner antialiasing.
        inner = min(alpha.getpixel((x + dx, y + dy))
                    if 0 <= x + dx < width and 0 <= y + dy < height else 0
                    for dx, dy in [(0, 0), (-1, 0), (1, 0), (0, -1), (0, 1)])
        edge = round((alpha.getpixel((x, y)) - inner) * fade)
        outline.putpixel((x, y), (255, 255, 255, edge))
path = windows / 'Window_Focus_Top_Border.png'
if '--write' in sys.argv:
    outline.save(path)
assert Image.open(path).convert('RGBA').tobytes() == outline.tobytes()
assert outline.getpixel((width // 2, 0))[3] > 0
assert outline.getpixel((width // 2, 5))[3] == 0
assert outline.getpixel((0, 10))[3] > outline.getpixel((0, 15))[3] > 0
assert outline.getchannel('A').crop((0, 20, width, height)).getbbox() is None
textures = {node.attrib['name']: node.attrib for node in ET.parse(skin / 'textures/textures.xml').getroot()}
highlight = textures['Window_Focus_Top_Border']
for name in ['Window_Foreground', 'Window_Background', 'Window_NoTitle_Foreground', 'Window_NoTitle_Background']:
    original = Image.open(windows / (name + '.png')).getchannel('A')
    assert original.tobytes() == alpha.tobytes(), name
    for key in ['scale.left', 'scale.top', 'scale.right', 'scale.bottom']:
        assert highlight[key] == textures[name][key], (name, key)
    assert all(edge <= surface for edge, surface in zip(outline.getchannel('A').getdata(), original.getdata()))
print('All four window outlines match; top-only mask, side fade and nine-slice bounds passed.')
