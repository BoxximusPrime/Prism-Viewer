"""Generate the default skin's rounded, stretch-safe floater backgrounds."""

from pathlib import Path

from PIL import Image, ImageChops, ImageColor, ImageDraw


SIZE = 64
SCALE = 4
RADIUS = 9
HEADER_HEIGHT = 26
OUTPUT_DIR = (
    Path(__file__).resolve().parents[1]
    / "indra/newview/skins/default/textures/windows"
)
BUTTON_OUTPUT_DIR = OUTPUT_DIR.parent / "widgets"
ICON_OUTPUT_DIR = OUTPUT_DIR.parent / "icons"


def rounded_window(
    *, body: str, header: tuple[str, str] | None, border: str, divider: str | None
) -> Image.Image:
    size = SIZE * SCALE
    inset = SCALE // 2
    radius = RADIUS * SCALE
    bounds = (inset, inset, size - inset - 1, size - inset - 1)

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(bounds, radius=radius, fill=255)

    image = Image.new("RGBA", (size, size), body)
    if header:
        top = ImageColor.getrgb(header[0])
        bottom = ImageColor.getrgb(header[1])
        draw = ImageDraw.Draw(image)
        for y in range(HEADER_HEIGHT * SCALE + 1):
            blend = y / (HEADER_HEIGHT * SCALE)
            color = tuple(round(a + (b - a) * blend) for a, b in zip(top, bottom))
            draw.line((0, y, size, y), fill=color)
    image.putalpha(mask)

    draw = ImageDraw.Draw(image)
    if divider:
        y = HEADER_HEIGHT * SCALE
        draw.line((RADIUS * SCALE, y, size - RADIUS * SCALE, y), fill=divider, width=SCALE)
    draw.rounded_rectangle(bounds, radius=radius, outline=border, width=SCALE)

    return image.resize((SIZE, SIZE), Image.Resampling.LANCZOS)


def rounded_control(
    *, top: str, bottom: str, border: str, width: int = 32, height: int = 23
) -> Image.Image:
    output_size = (width, height)
    width, height = width * SCALE, height * SCALE
    inset = SCALE // 2
    bounds = (inset, inset, width - inset - 1, height - inset - 1)

    top_rgb = ImageColor.getrgb(top)
    bottom_rgb = ImageColor.getrgb(bottom)
    image = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        blend = y / (height - 1)
        color = tuple(round(a + (b - a) * blend) for a, b in zip(top_rgb, bottom_rgb))
        draw.line((0, y, width, y), fill=color)

    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle(bounds, radius=5 * SCALE, fill=255)
    image.putalpha(mask)
    ImageDraw.Draw(image).rounded_rectangle(
        bounds, radius=5 * SCALE, outline=border, width=SCALE
    )
    return image.resize(output_size, Image.Resampling.LANCZOS)


def tinted_icon(source: Path, color: str) -> Image.Image:
    luminance, alpha = Image.open(source).convert("LA").split()
    image = Image.new("RGBA", luminance.size, ImageColor.getrgb(color))
    image.putalpha(ImageChops.multiply(luminance, alpha))
    return image


def inventory_folder(*, opened: bool, badge: str | None = None) -> Image.Image:
    """Draw a crisp 16px folder that matches the dark viewer chrome."""
    scale = 4
    image = Image.new("RGBA", (16 * scale, 16 * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    point = lambda xy: tuple(value * scale for value in xy)

    back = [point(xy) for xy in ((1, 4), (1, 3), (6, 3), (8, 5), (15, 5), (15, 14), (1, 14))]
    draw.polygon(back, fill="#566170", outline="#252a32", width=scale)
    draw.line((point((2, 5)), point((14, 5))), fill="#778494", width=scale)

    if opened:
        front = [point(xy) for xy in ((1, 7), (6, 7), (7, 6), (15, 6), (13, 14), (2, 14))]
        draw.polygon(front, fill="#657282", outline="#252a32", width=scale)
        draw.line((point((3, 8)), point((13, 8))), fill="#8793a1", width=scale)
    else:
        draw.rounded_rectangle(
            (*point((1, 6)), *point((15, 14))),
            radius=scale,
            fill="#657282",
            outline="#252a32",
            width=scale,
        )
        draw.line((point((2, 7)), point((14, 7))), fill="#8793a1", width=scale)

    ink = "#d5a34f"
    shadow = "#252a32"
    if badge == "system":
        draw.ellipse((*point((7, 8)), *point((13, 14))), fill=shadow)
        draw.ellipse((*point((8, 9)), *point((12, 13))), outline=ink, width=scale)
        draw.line((point((10, 8)), point((10, 14))), fill=ink, width=scale)
        draw.line((point((7, 11)), point((13, 11))), fill=ink, width=scale)
    elif badge == "look":
        draw.arc((*point((7, 7)), *point((11, 11))), 195, 500, fill=ink, width=scale)
        draw.line((point((9, 10)), point((4, 13))), fill=ink, width=scale)
        draw.line((point((9, 10)), point((14, 13))), fill=ink, width=scale)
        draw.line((point((4, 13)), point((14, 13))), fill=ink, width=scale)
    elif badge == "lost":
        draw.ellipse((*point((7, 7)), *point((14, 14))), fill=shadow)
        draw.arc((*point((9, 8)), *point((12, 11))), 190, 520, fill=ink, width=scale)
        draw.line((point((10, 11)), point((10, 12))), fill=ink, width=scale)
        draw.point(point((10, 13)), fill=ink)
    elif badge == "stock":
        draw.rectangle((*point((7, 8)), *point((14, 14))), fill=shadow)
        for x, y in ((8, 9), (11, 9), (8, 12), (11, 12)):
            draw.rectangle((*point((x, y)), *point((x + 1, y + 1))), fill=ink)
    elif badge == "version":
        for offset in (0, 2, 4):
            draw.line((point((7, 9 + offset)), point((13, 9 + offset))), fill=shadow, width=2 * scale)
            draw.line((point((8, 8 + offset)), point((14, 8 + offset))), fill=ink, width=scale)
    elif badge == "link":
        draw.arc((*point((6, 8)), *point((11, 13))), 45, 225, fill=ink, width=scale)
        draw.arc((*point((9, 9)), *point((14, 14))), 225, 405, fill=ink, width=scale)

    return image.resize((16, 16), Image.Resampling.LANCZOS)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    styles = {
        "Window_Foreground.png": dict(
            body="#111216",
            header=("#24262d", "#1a1b21"),
            border="#484b55",
            divider="#34363f",
        ),
        "Window_Background.png": dict(
            body="#0e0f12",
            header=("#1b1c22", "#14151a"),
            border="#30323a",
            divider="#282a31",
        ),
        "Window_NoTitle_Foreground.png": dict(
            body="#111216", header=None, border="#484b55", divider=None
        ),
        "Window_NoTitle_Background.png": dict(
            body="#0e0f12", header=None, border="#30323a", divider=None
        ),
    }
    for filename, style in styles.items():
        rounded_window(**style).save(OUTPUT_DIR / filename, optimize=True)

    tinted_icon(OUTPUT_DIR / "Icon_Close_Foreground.png", "#ff5c62").save(
        OUTPUT_DIR / "Icon_Close_Hover.png", optimize=True
    )

    BUTTON_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    button_styles = {
        "PushButton_Off.png": dict(top="#2b2d35", bottom="#202127", border="#4b4e59"),
        "PushButton_Over.png": dict(top="#383b45", bottom="#292b33", border="#6a6e7c"),
        "PushButton_Press.png": dict(top="#332919", bottom="#211c15", border="#b47d30"),
        "PushButton_Selected.png": dict(top="#332919", bottom="#211c15", border="#b47d30"),
        "PushButton_Selected_Press.png": dict(top="#241d13", bottom="#191611", border="#d09539"),
        "PushButton_On.png": dict(top="#332919", bottom="#211c15", border="#b47d30"),
        "PushButton_On_Selected.png": dict(top="#44351e", bottom="#2b2318", border="#d09539"),
        "PushButton_Disabled.png": dict(top="#1b1c21", bottom="#17181c", border="#30323a"),
        "PushButton_Selected_Disabled.png": dict(top="#211c15", bottom="#191611", border="#554124"),
    }
    for filename, style in button_styles.items():
        rounded_control(**style).save(BUTTON_OUTPUT_DIR / filename, optimize=True)

    text_field_styles = {
        "TextField_Off.png": dict(top="#1d1f25", bottom="#17181d", border="#41444e"),
        "TextField_Active.png": dict(top="#25272e", bottom="#1b1d22", border="#b47d30"),
        "TextField_Disabled.png": dict(top="#15161a", bottom="#111216", border="#2d2f36"),
        "TextField_Highlight.png": dict(top="#292b33", bottom="#1d1f25", border="#d09539"),
        "TextField_Search_Off.png": dict(top="#1d1f25", bottom="#17181d", border="#41444e"),
        "TextField_Search_Active.png": dict(top="#25272e", bottom="#1b1d22", border="#b47d30"),
        "TextField_Search_Disabled.png": dict(top="#15161a", bottom="#111216", border="#2d2f36"),
        "TextField_Search_Highlight.png": dict(top="#292b33", bottom="#1d1f25", border="#d09539"),
    }
    for filename, style in text_field_styles.items():
        rounded_control(**style, width=256).save(
            BUTTON_OUTPUT_DIR / filename, optimize=True
        )

    ICON_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    folder_styles = {
        "Inv_FolderClosed.png": (False, None),
        "Inv_FolderOpen.png": (True, None),
        "Inv_LinkFolder.png": (False, "link"),
        "Inv_LookFolderClosed.png": (False, "look"),
        "Inv_LookFolderOpen.png": (True, "look"),
        "Inv_LostClosed.png": (False, "lost"),
        "Inv_LostOpen.png": (True, "lost"),
        "Inv_StockFolderClosed.png": (False, "stock"),
        "Inv_StockFolderOpen.png": (True, "stock"),
        "Inv_SysClosed.png": (False, "system"),
        "Inv_SysOpen.png": (True, "system"),
        "Inv_VersionFolderClosed.png": (False, "version"),
        "Inv_VersionFolderOpen.png": (True, "version"),
    }
    for filename, (opened, badge) in folder_styles.items():
        inventory_folder(opened=opened, badge=badge).save(
            ICON_OUTPUT_DIR / filename, optimize=True
        )


if __name__ == "__main__":
    main()
