"""Turn a restyled PNG into a multi-resolution Windows .ico."""
import struct
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


def _save_windows_ico(frames: dict[int, Image.Image], ico_path: Path) -> None:
    """Write an Explorer-friendly ICO using BMP/DIB frames for every size.

    Pillow's default ICO writer stores PNG-compressed frames for every size, and
    Explorer can render those as black blocks while rebuilding the icon cache.
    `bitmap_format="bmp"` keeps the file larger but follows the older shell
    paths reliably, including when shortcut overlays are changed.
    """
    sizes = sorted(frames)
    largest = max(sizes)
    base = frames[largest].convert("RGBA")
    append = [frames[s].convert("RGBA") for s in sizes if s != largest]
    base.save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=append,
        bitmap_format="bmp",
    )


def build_blank_overlay_ico(dest_path: Path) -> Path:
    """Write the shortcut-arrow overlay icon (#29): transparent except ONE pixel.

    A *fully* transparent overlay icon triggers a long-standing Windows bug. When
    Explorer rebuilds its overlay image list cold — at every session start (so every
    reboot) and when compositing the overlay onto a freshly-created shortcut not yet
    in the icon cache — an all-transparent overlay corrupts to an opaque BLACK square
    in the icon corner, then "self-heals" on a later repaint. Icon format (DIB vs
    PNG), file path and AND-mask correctness do NOT fix it; the trigger is the full
    transparency itself (a fully-transparent shell32,-50 overlay fails the same way).

    Fix: make the icon *not* fully transparent. One corner pixel gets a minimal
    non-zero alpha (1/255 — imperceptible on screen) and a cleared AND-mask bit, so
    Windows treats the icon as a genuine bitmap and honours its alpha channel; every
    other pixel stays transparent and no black square is ever baked in.

    Written by hand as classic 32bpp DIB/BMP frames — Pillow's current ICO writer
    emits a malformed AND mask once any alpha is present — at the small sizes the
    overlay compositor actually requests (16-48px, picked by DPI).
    """
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(_overlay_ico_bytes([16, 20, 24, 32, 40, 48]))
    return dest_path


def _overlay_ico_bytes(sizes: list[int]) -> bytes:
    """Build a near-transparent multi-size .ico (one alpha=1 corner pixel per frame).

    See build_blank_overlay_ico for why that single non-transparent pixel matters."""
    frames = []
    for s in sizes:
        # BITMAPINFOHEADER: 32bpp BGRA, height doubled for the XOR + AND bitmaps.
        header = struct.pack("<IiiHHIIiiII", 40, s, s * 2, 1, 32, 0, 0, 0, 0, 0, 0)
        # XOR pixels: all (0,0,0,0) except the bottom-right pixel's alpha = 1. DIB
        # rows are stored bottom-up, so file row 0 is the bottom display row.
        xor = bytearray(s * s * 4)
        xor[(s - 1) * 4 + 3] = 1
        # AND mask: 0xFF (transparent) everywhere except that same pixel, whose bit
        # we clear (0 = opaque) so legacy GDI paths also see the icon carrying content.
        row_bytes = ((s + 31) // 32) * 4
        and_mask = bytearray(b"\xff" * (row_bytes * s))
        col = s - 1
        and_mask[col // 8] &= (~(0x80 >> (col % 8))) & 0xFF
        frames.append(header + bytes(xor) + bytes(and_mask))
    out = bytearray(struct.pack("<HHH", 0, 1, len(sizes)))  # ICONDIR
    offset = 6 + 16 * len(sizes)                            # entries follow the dir
    for s, frame in zip(sizes, frames):
        dim = 0 if s >= 256 else s  # 0 encodes 256 in an ICONDIRENTRY width/height
        out += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(frame), offset)
        offset += len(frame)
    for frame in frames:
        out += frame
    return bytes(out)


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
        _save_windows_ico(frames, ico_path)
        # Also drop a crisp 256 PNG preview alongside the .ico.
        base.save(ico_path.with_name(ico_path.stem + "_preview.png"))
        print(
            f"[postprocess] saved {ico_path} "
            f"(pixel grid={n}, colors={colors or 'full'}, format=DIB)"
        )
        return ico_path

    largest = max(ICO_SIZES)
    frames = {s: img.resize((s, s), Image.Resampling.LANCZOS) for s in ICO_SIZES}
    _save_windows_ico(frames, ico_path)
    print(f"[postprocess] saved {ico_path} (sizes={ICO_SIZES}, format=DIB)")
    return ico_path


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("png", help="path to restyled PNG")
    args = ap.parse_args()
    to_ico(Path(args.png))
