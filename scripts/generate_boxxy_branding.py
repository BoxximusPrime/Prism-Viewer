from pathlib import Path
import shutil
import sys

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(sys.argv[1])
ICONS = ROOT / "indra/newview/icons"
WINDOW_TEXTURES = ROOT / "indra/newview/skins/default/textures/windows"


def fitted_icon(size: int, padding: float = 0.06) -> Image.Image:
    source = Image.open(SOURCE).convert("RGBA")
    alpha_bounds = source.getchannel("A").getbbox()
    if alpha_bounds:
        source = source.crop(alpha_bounds)
    edge = round(size * (1 - padding * 2))
    source.thumbnail((edge, edge), Image.Resampling.LANCZOS)
    output = Image.new("RGBA", (size, size))
    output.alpha_composite(source, ((size - source.width) // 2, (size - source.height) // 2))
    return output


def save_ico(path: Path, master: Image.Image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    master.save(path, format="ICO", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])


def save_bmp(path: Path, master: Image.Image) -> None:
    background = Image.new("RGB", (256, 256), "#11182b")
    icon = master.resize((256, 256), Image.Resampling.LANCZOS)
    background.paste(icon, mask=icon.getchannel("A"))
    path.parent.mkdir(parents=True, exist_ok=True)
    background.save(path, format="BMP")


def save_icns(path: Path, master: Image.Image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    master.save(path, format="ICNS")


def save_login_brand(path: Path, master: Image.Image) -> None:
    canvas = Image.new("RGBA", (1024, 512))
    glows = Image.new("RGBA", canvas.size)
    draw = ImageDraw.Draw(glows)
    draw.ellipse((122, 18, 682, 482), fill=(0, 226, 255, 92))
    draw.ellipse((338, 36, 890, 496), fill=(126, 47, 255, 82))
    draw.ellipse((548, 74, 1000, 458), fill=(255, 105, 82, 70))
    glows = glows.filter(ImageFilter.GaussianBlur(105))
    canvas.alpha_composite(glows)

    icon = master.resize((330, 330), Image.Resampling.LANCZOS)
    canvas.alpha_composite(icon, ((canvas.width - icon.width) // 2, 88))
    canvas.save(path)


def save_logo_in_canvas(path: Path, size: tuple[int, int], master: Image.Image) -> None:
    canvas = Image.new("RGBA", size)
    edge = round(min(size) * 0.88)
    icon = master.resize((edge, edge), Image.Resampling.LANCZOS)
    canvas.alpha_composite(icon, ((size[0] - edge) // 2, (size[1] - edge) // 2))
    canvas.save(path)


def main() -> None:
    master = fitted_icon(1024)
    master_path = ICONS / "boxxy_icon_master.png"
    master_path.parent.mkdir(parents=True, exist_ok=True)
    master.save(master_path)


    for channel in ("test", "beta", "project", "release"):
        directory = ICONS / channel
        for size in (16, 32, 48, 128, 256, 512):
            target = directory / f"secondlife_{size}.png"
            if target.exists() or channel != "release":
                master.resize((size, size), Image.Resampling.LANCZOS).save(target)
        save_ico(directory / "secondlife.ico", master)
        save_bmp(directory / "secondlife_256.BMP", master)
        save_icns(directory / "secondlife.icns", master)

    release = ICONS / "release"
    master.save(release / "secondlife_1024.png")
    for name, size in {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }.items():
        master.resize((size, size), Image.Resampling.LANCZOS).save(release / "secondlife.iconset" / name)

    for path in (
        ROOT / "indra/newview/res/ll_icon.ico",
        ROOT / "indra/newview/res/icon1.ico",
        ROOT / "indra/newview/res/ll_icon_small.ico",
        ROOT / "indra/newview/installers/windows/install_icon.ico",
        ROOT / "indra/newview/installers/windows/uninstall_icon.ico",
    ):
        save_ico(path, master)

    for path in (
        ROOT / "indra/newview/res/ll_icon.BMP",
        ROOT / "indra/newview/res/install_icon.BMP",
        ROOT / "indra/newview/res/uninstall_icon.BMP",
        ROOT / "indra/newview/res-sdl/ll_icon.BMP",
        ROOT / "indra/newview/installers/windows/install_icon.BMP",
        ROOT / "indra/newview/installers/windows/uninstall_icon.BMP",
    ):
        save_bmp(path, master)

    for path in (
        ROOT / "indra/newview/secondlife.icns",
        ROOT / "indra/newview/secondlife_firstlook.icns",
        ROOT / "indra/newview/installers/darwin/release-dmg/_VolumeIcon.icns",
    ):
        save_icns(path, master)

    master.save(WINDOW_TEXTURES / "startup_logo.png")
    save_logo_in_canvas(WINDOW_TEXTURES / "login_sl_logo.png", (225, 94), master)
    save_logo_in_canvas(WINDOW_TEXTURES / "login_sl_logo_horizontal.png", (160, 77), master)
    save_logo_in_canvas(WINDOW_TEXTURES / "login_sl_logo_small.png", (165, 73), master)
    save_login_brand(WINDOW_TEXTURES / "boxxy_login_brand.png", master)


if __name__ == "__main__":
    main()
