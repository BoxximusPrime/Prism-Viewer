"""Prepare the login artwork, logo, and rounded UI surface."""
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artwork/prism"
TEXTURES = ROOT / "indra/newview/skins/default/textures/windows"


def edge_fade(length, fraction):
    ramp = Image.new("L", (length, 1))
    values = []
    for i in range(length):
        t = min(1, min(i, length - 1 - i) / (length * fraction))
        values.append(round(255 * t * t * (3 - 2 * t)))
    ramp.putdata(values)
    return ramp


def prepare_login_button():
    """Native skin geometry: emerald facets with a quiet center for the label."""
    scale = 3
    size = (356 * scale, 44 * scale)
    for state, brightness in (("normal", 1.0), ("hover", 1.15), ("pressed", 0.78)):
        image = Image.new("RGBA", size)
        draw = ImageDraw.Draw(image)
        for y in range(size[1]):
            t = y / (size[1] - 1)
            color = tuple(min(255, round((a + (b - a) * t) * brightness))
                          for a, b in zip((91, 226, 153), (32, 172, 104)))
            draw.line((0, y, size[0], y), fill=color + (255,))
        facets = Image.new("RGBA", size)
        face = ImageDraw.Draw(facets)
        for points, color in (
            (((0, 0), (78, 0), (39, 44), (0, 44)), (4, 68, 44, 34)),
            (((0, 0), (42, 0), (78, 44)), (223, 255, 239, 35)),
            (((42, 0), (105, 0), (78, 44)), (218, 255, 240, 20)),
            (((278, 0), (319, 44), (356, 44), (356, 0)), (5, 89, 64, 34)),
            (((306, 0), (356, 0), (326, 44)), (217, 255, 239, 42)),
            (((326, 44), (356, 0), (356, 44)), (3, 67, 50, 45)),
        ):
            face.polygon([(x * scale, y * scale) for x, y in points], fill=color)
        image = Image.alpha_composite(image, facets)
        draw = ImageDraw.Draw(image)
        # Fine bevel, kept inside the six-pixel rounded outline.
        draw.rounded_rectangle((scale // 2, scale // 2, size[0] - 2, size[1] - 2),
                               radius=6 * scale, outline=(177, 255, 216, 180), width=scale)
        mask = Image.new("L", size)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1),
                                               radius=6 * scale, fill=255)
        image.putalpha(mask)
        image.resize((356, 44), Image.Resampling.LANCZOS).save(
            TEXTURES / f"prism_login_button_{state}.png")


def main():
    prepare_login_button()
    image = Image.open(ART / "prism-login-background-source.png").convert("RGB")
    image = image.resize((1920, 1080), Image.Resampling.LANCZOS)
    horizontal = edge_fade(image.width, 0.12).resize(image.size)
    vertical = edge_fade(image.height, 0.06).transpose(Image.Transpose.ROTATE_90).resize(image.size)
    mask = ImageChops.multiply(horizontal, vertical)
    image = Image.composite(image, Image.new("RGB", image.size, "#101416"), mask)
    image.save(TEXTURES / "prism_login_background.png")
    Image.open(ART / "prism-emerald-mark-v1.png").resize((256, 256), Image.Resampling.LANCZOS).save(
        TEXTURES / "prism_login_logo.png")
    surface = Image.new("RGBA", (128, 128))
    ImageDraw.Draw(surface).rounded_rectangle((0, 0, 127, 127), radius=24, fill="white")
    surface.resize((32, 32), Image.Resampling.LANCZOS).save(TEXTURES / "prism_login_surface.png")
    assert all(image.getpixel((x, y)) == (16, 20, 22)
               for x, y in [(0, 540), (1919, 540), (960, 0), (960, 1079)])


if __name__ == "__main__":
    main()
