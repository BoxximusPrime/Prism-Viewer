"""Build Prism's opt-in tab artwork and a specimen from the same shipped pixels.

Run with the existing Pillow dependency: python scripts/generate_prism_tab_textures.py
The 12px end caps stay fixed when LLUIImage stretches the center horizontally.
"""

from pathlib import Path

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "indra/newview/skins/default/textures/containers"
PREVIEW = ROOT / "docs/concepts/prism-tabs"
SCALE = 4
TAB_SIZE = (128, 32)
FRAME_SIZE = (96, 80)
STYLES = {
    "Off": ("#2b2d35", "#191a1f", "#50535f", False),
    "Hover": ("#383a43", "#222329", "#85838a", False),
    "Selected": ("#3b3021", "#1e1c1a", "#c99548", True),
    "Selected_Hover": ("#493923", "#252019", "#e0ae60", True),
    "Pressed": ("#292218", "#1c1916", "#a97938", True),
    "Disabled": ("#1c1d22", "#17181c", "#30323a", False),
    "Selected_Disabled": ("#26221c", "#1c1a18", "#665339", True),
}


def gradient(size, top, bottom):
    """Vertical color ramp, also used for the transparent frame's alpha."""
    a, b = ImageColor.getcolor(top, "RGBA"), ImageColor.getcolor(bottom, "RGBA")
    image = Image.new("RGBA", size)
    draw = ImageDraw.Draw(image)
    for y in range(size[1]):
        t = y / (size[1] - 1)
        draw.line((0, y, size[0], y), fill=tuple(round(x + (z - x) * t) for x, z in zip(a, b)))
    return image


def tab_texture(style):
    top, bottom, edge, selected = STYLES[style]
    w, h = (v * SCALE for v in TAB_SIZE)
    left, right = 3 * SCALE, w - 3 * SCALE - 1
    y = (0 if selected else 4) * SCALE + SCALE // 2
    mask = Image.new("L", (w, h))
    draw = ImageDraw.Draw(mask)
    # Extend the rounded shape below the image: a tab has no lower rounded corners.
    bounds = (left, y, right, h + 8 * SCALE)
    draw.rounded_rectangle(bounds, radius=6 * SCALE, fill=255)
    if not selected:
        draw.rectangle((0, h - SCALE, w, h), fill=0)
    image = gradient((w, h), top, bottom)
    image.putalpha(mask)
    outline = Image.new("RGBA", (w, h))
    ImageDraw.Draw(outline).rounded_rectangle(bounds, radius=6 * SCALE, outline=edge, width=SCALE)
    outline.putalpha(ImageChops.multiply(outline.getchannel("A"), mask))
    image = Image.alpha_composite(image, outline)
    # A restrained amber glint; the inactive silhouette is deliberately four pixels lower.
    if selected and "Disabled" not in style:
        ImageDraw.Draw(image).line((12 * SCALE, y + SCALE, w - 12 * SCALE, y + SCALE),
                                   fill="#e7bc78" if style != "Pressed" else "#bd8a42", width=SCALE // 2)
    return image.resize(TAB_SIZE, Image.Resampling.LANCZOS)


def frame_texture():
    w, h = (v * SCALE for v in FRAME_SIZE)
    bounds = (SCALE // 2, SCALE // 2, w - SCALE // 2 - 1, h + 12 * SCALE)
    mask = Image.new("L", (w, h))
    ImageDraw.Draw(mask).rounded_rectangle(bounds, radius=10 * SCALE, fill=255)
    # A faint surface wash gives the border a home without boxing in the content.
    image = Image.new("RGBA", (w, h), "#323039")
    wash = Image.new("L", (w, h))
    fade = Image.new("L", (w, h))
    wd, fd = ImageDraw.Draw(wash), ImageDraw.Draw(fade)
    for y in range(h):
        t = y / (h - 1)
        wd.line((0, y, w, y), fill=round(65 * (1 - t) ** 2))
        fd.line((0, y, w, y), fill=round(230 * (1 - t) ** 1.7))
    image.putalpha(ImageChops.multiply(mask, wash))
    stroke = Image.new("L", (w, h))
    ImageDraw.Draw(stroke).rounded_rectangle(bounds, radius=10 * SCALE, outline=255, width=SCALE)
    border = Image.new("RGBA", (w, h), "#817365")
    border.putalpha(ImageChops.multiply(stroke, fade))
    return Image.alpha_composite(image, border).resize(FRAME_SIZE, Image.Resampling.LANCZOS)


def stretch(image, width):
    """Match the shipped horizontal LLUIImage slices (12px end caps)."""
    w, h = image.size
    result = Image.new("RGBA", (width, h))
    result.paste(image.crop((0, 0, 12, h)), (0, 0))
    result.paste(image.crop((12, 0, w - 12, h)).resize((width - 24, h)), (12, 0))
    result.paste(image.crop((w - 12, 0, w, h)), (width - 12, 0))
    return result


def specimen(tabs, frame):
    image = Image.new("RGBA", (1120, 740), "#111216")
    draw = ImageDraw.Draw(image)
    font_path = ROOT / "indra/newview/boxxy_fonts/SourceSans3VF-Upright.ttf"
    def font(size):
        face = ImageFont.truetype(str(font_path), size)
        face.set_variation_by_axes([400])
        return face
    draw.text((52, 36), "PRISM  /  CONTROL STUDY", font=font(13), fill="#c6a16b")
    draw.text((50, 65), "A lighter edge.", font=font(32), fill="#f0eee9")
    draw.text((52, 113), "Charcoal tabs, warm amber, and a frame that quietly disappears.", font=font(16), fill="#9596a0")

    def group(x, y, width, labels, selected=0):
        image.alpha_composite(stretch(frame, width), (x, y + 31))
        for i, (label, tab_width) in enumerate(labels):
            tx = x + 5 + sum(size for _, size in labels[:i])
            state = "Selected" if i == selected else "Off"
            image.alpha_composite(stretch(tabs[state], tab_width), (tx, y))
            draw.text((tx + tab_width / 2, y + 16), label, anchor="mm", font=font(13),
                      fill="#f4d3a2" if i == selected else "#c1c2cb")

    group(52, 190, 1016, [("General", 120), ("Object", 112), ("Features", 120), ("Texture", 120), ("Content", 120)], 1)
    draw.text((78, 250), "Open space for the panel below.", font=font(15), fill="#b8b8c2")
    draw.text((78, 277), "The selected tab meets the rail; the sides fade over 80 px.", font=font(13), fill="#747681")
    draw.text((52, 359), "STATE PALETTE", font=font(12), fill="#a7a4a0")
    states = [("Off", "Rest"), ("Hover", "Hover"), ("Selected", "Selected"),
              ("Selected_Hover", "Selected hover"), ("Pressed", "Pressed"),
              ("Disabled", "Disabled"), ("Selected_Disabled", "Selected disabled")]
    for i, (state, label) in enumerate(states):
        x = 52 + i * 146
        image.alpha_composite(tabs[state], (x, 398))
        ink = "#64646d" if "Disabled" in state else "#f4d3a2" if STYLES[state][3] else "#c1c2cb"
        draw.text((x + 64, 414), "Label", anchor="mm", font=font(13), fill=ink)
        draw.text((x + 64, 452), label, anchor="mm", font=font(11), fill="#8f909b")
    draw.text((52, 515), "COMPACT", font=font(12), fill="#a7a4a0")
    group(52, 550, 400, [("General", 110), ("Object", 102), ("Features", 118)])
    draw.text((520, 551), "32 px tabs  /  6 px corners  /  1 px edge", font=font(14), fill="#c1c0c7")
    draw.text((520, 579), "Native hover, press, selection and keyboard behavior.", font=font(13), fill="#858792")
    draw.text((52, 689), "Reusable artwork + isolated XUI specimen. Used in profiles and Build/Edit.", font=font(12), fill="#747681")
    return image.convert("RGB")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    PREVIEW.mkdir(parents=True, exist_ok=True)
    tabs = {name: tab_texture(name) for name in STYLES}
    frame = frame_texture()
    for name, image in tabs.items():
        image.save(OUT / f"Prism_Tab_{name}.png", optimize=True)
    frame.save(OUT / "Prism_Tab_Frame.png", optimize=True)
    specimen(tabs, frame).save(PREVIEW / "specimen.png", optimize=True)


if __name__ == "__main__":
    main()
