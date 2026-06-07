"""Turn a restyled PNG into a multi-resolution Windows .ico."""
from pathlib import Path

from PIL import Image

from config import ICO_SIZES, OUTPUT_DIR


def _estimate_background_color(img: Image.Image) -> tuple[int, int, int]:
    rgb = img.convert("RGB")
    w, h = rgb.size
    points = [
        (0, 0),
        (w - 1, 0),
        (0, h - 1),
        (w - 1, h - 1),
        (w // 2, 0),
        (w // 2, h - 1),
        (0, h // 2),
        (w - 1, h // 2),
    ]
    colors = [rgb.getpixel(point) for point in points]
    return tuple(sorted(channel)[len(channel) // 2] for channel in zip(*colors))


def _make_background_transparent(img: Image.Image) -> Image.Image:
    """Remove a mostly solid generated background when the source has no alpha."""
    rgba = img.convert("RGBA")
    if "A" in img.getbands() and rgba.getchannel("A").getextrema()[0] < 255:
        return rgba

    bg = _estimate_background_color(rgba)
    pixels = rgba.load()
    w, h = rgba.size
    threshold = 34
    soft_edge = 24
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            distance = max(abs(r - bg[0]), abs(g - bg[1]), abs(b - bg[2]))
            if distance <= threshold:
                pixels[x, y] = (r, g, b, 0)
            elif distance <= threshold + soft_edge:
                alpha = int(a * (distance - threshold) / soft_edge)
                pixels[x, y] = (r, g, b, alpha)
    return rgba


def _trim_and_square(img: Image.Image, remove_bg: bool = True) -> Image.Image:
    """Crop transparent borders, then pad to a centered square with a small margin.

    remove_bg=False keeps the generated (solid) background instead of chroma-keying
    it to transparent — used when the user disables auto background removal."""
    img = _make_background_transparent(img) if remove_bg else img.convert("RGBA")
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)
    w, h = img.size
    side = int(max(w, h) * 1.12)  # ~6% margin per side
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(img, ((side - w) // 2, (side - h) // 2), img)
    return canvas


def _quantize_rgb(img: Image.Image, colors: int) -> Image.Image:
    """Reduce to a small indexed palette (RGB only) while preserving alpha."""
    if not colors or colors <= 0:
        return img
    rgb = img.convert("RGB").quantize(
        colors=colors, method=Image.Quantize.MEDIANCUT
    ).convert("RGB")
    alpha = img.getchannel("A")
    return Image.merge("RGBA", (*rgb.split(), alpha))


def _harden_alpha(img: Image.Image, threshold: int = 110) -> Image.Image:
    """Make pixel edges crisp: no semi-transparent fringe."""
    alpha = img.getchannel("A").point(lambda v: 255 if v >= threshold else 0)
    img.putalpha(alpha)
    return img


def _to_low_res(img: Image.Image, n: int, colors: int = 0) -> Image.Image:
    """Collapse the image to a true n x n pixel-art tile."""
    small = img.resize((n, n), Image.Resampling.BOX)
    small = _harden_alpha(small)
    small = _quantize_rgb(small, colors)
    return small


def to_ico(
    png_path: Path,
    ico_path: Path | None = None,
    theme: dict | None = None,
    pixelate: bool | None = None,
    remove_bg: bool = True,
) -> Path:
    """Build a multi-size .ico from a PNG.

    pixelate: None -> follow the theme's pixel_art.enabled flag (default);
              True/False -> force pixel-art on/off (used for custom uploads).
    remove_bg: True (default) -> chroma-key the solid background to transparent;
               False -> keep the generated background as-is.
    """
    png_path = Path(png_path)
    if ico_path is None:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        ico_path = OUTPUT_DIR / (png_path.stem + ".ico")
    Path(ico_path).parent.mkdir(parents=True, exist_ok=True)
    with Image.open(png_path) as source:
        img = _trim_and_square(source, remove_bg=remove_bg)

    pixel_art = (theme or {}).get("pixel_art") or {}
    do_pixel = pixel_art.get("enabled") if pixelate is None else pixelate
    if do_pixel:
        n = int(pixel_art.get("source_size", 32))
        colors = int(pixel_art.get("colors", 0))
        low = _to_low_res(img, n, colors)
        # Upscale each icon size as a clean NEAREST multiple so the grid stays crisp.
        largest = max(ICO_SIZES)
        base = low.resize((largest, largest), Image.Resampling.NEAREST)
        frames = {s: low.resize((s, s), Image.Resampling.NEAREST) for s in ICO_SIZES}
        base.save(
            ico_path, format="ICO", sizes=[(s, s) for s in ICO_SIZES],
            append_images=[frames[s] for s in ICO_SIZES if s != largest],
        )
        # Also drop a crisp 256 PNG preview alongside the .ico.
        base.save(ico_path.with_name(ico_path.stem + "_preview.png"))
        print(f"[postprocess] saved {ico_path} (pixel grid={n}, colors={colors or 'full'})")
        return ico_path

    largest = max(ICO_SIZES)
    img = img.resize((largest, largest), Image.Resampling.LANCZOS)
    img.save(ico_path, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    print(f"[postprocess] saved {ico_path} (sizes={ICO_SIZES})")
    return ico_path


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("png", help="path to restyled PNG")
    args = ap.parse_args()
    to_ico(Path(args.png))
