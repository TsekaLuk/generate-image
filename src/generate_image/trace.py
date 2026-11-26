"""High-fidelity raster-to-SVG vectorization for flat marks and custom logotypes.

Converts crisp AI-generated flat logos, handcrafted CJK/Latin logotypes, and
graphic emblems into clean, scalable multi-color Bezier `.svg` vector masters.

Backend priority:
  1. `vtracer` (optional Python package — smooth spline multi-color tracing)
  2. `potrace` (system binary, e.g. `brew install potrace` / `apt install potrace`)
     paired with Pillow foreground isolation + perceptual color-layer clustering
     so multi-color brand marks export cleanly with zero extra Python packages.
"""

from __future__ import annotations

import argparse
import math
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from PIL import Image, ImageFilter

_PATH_D_RE = re.compile(r'<path\b[^>]*\bd="([^"]+)"', flags=re.IGNORECASE | re.DOTALL)
_G_TRANSFORM_RE = re.compile(r'<g\b[^>]*\btransform="([^"]+)"', flags=re.IGNORECASE)


class TraceError(RuntimeError):
    """Raised when raster-to-SVG vectorization cannot complete."""


def _rgb_dist(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def _detect_bg_color(rgba: Image.Image) -> tuple[int, int, int] | None:
    """Detect whether the border is transparent or a solid opaque background."""
    w, h = rgba.size
    corners = [
        rgba.getpixel((0, 0)),
        rgba.getpixel((w - 1, 0)),
        rgba.getpixel((0, h - 1)),
        rgba.getpixel((w - 1, h - 1)),
        rgba.getpixel((w // 2, 0)),
        rgba.getpixel((w // 2, h - 1)),
    ]
    if sum(1 for c in corners if c[3] < 128) >= 3:
        return None  # already alpha-transparent background
    rgbs = [(c[0], c[1], c[2]) for c in corners]
    med = tuple(sorted(c[i] for c in rgbs)[len(rgbs) // 2] for i in range(3))
    if sum(1 for c in rgbs if _rgb_dist(c, med) < 28) >= 4:
        return med  # type: ignore[return-value]
    return (255, 255, 255)


def _quantize_foreground_layers(
    im: Image.Image, *, max_colors: int = 4, bg_tol: int = 34, min_area_ratio: float = 0.0012
) -> list[tuple[tuple[int, int, int], Image.Image]]:
    """Segment foreground into clean flat brand-color masks (sorted largest first)."""
    rgba = im.convert("RGBA")
    w, h = rgba.size
    bg = _detect_bg_color(rgba)
    px = list(rgba.getdata())

    fg_mask = [False] * (w * h)
    fg_rgb: list[tuple[int, int, int]] = []
    for idx, (r, g, b, a) in enumerate(px):
        if a < 140:
            continue
        if bg is not None and _rgb_dist((r, g, b), bg) <= bg_tol:
            continue
        fg_mask[idx] = True
        fg_rgb.append((r, g, b))

    if not fg_rgb:
        raise TraceError("no foreground pixels found to vectorize")

    # Erode the foreground mask by 2px strictly for palette discovery so 1-2px
    # anti-aliasing edge halos (gray transition pixels between dark ink and
    # white backdrop) never pollute the discovered flat brand colors.
    fg_img = Image.frombytes("L", (w, h), bytes(255 if f else 0 for f in fg_mask))
    interior = list(fg_img.filter(ImageFilter.MinFilter(size=5)).getdata())
    interior_rgb = [
        (px[i][0], px[i][1], px[i][2])
        for i, v in enumerate(interior)
        if v > 0
    ]
    palette_src = interior_rgb if len(interior_rgb) >= 64 else fg_rgb

    # Quantize foreground samples via Pillow MEDIANCUT on a compact strip image
    sample = palette_src if len(palette_src) <= 60000 else palette_src[:: max(1, len(palette_src) // 60000)]
    strip = Image.new("RGB", (len(sample), 1))
    strip.putdata(sample)
    k = max(4, min(max_colors * 3, 16))
    q = strip.quantize(colors=k, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette() or []
    counts = Counter(q.getdata())

    # Extract candidate palette colors sorted by frequency, then merge near-duplicates
    # (which are usually anti-aliased edge transition pixels).
    raw_colors: list[tuple[tuple[int, int, int], int]] = []
    for pidx, cnt in counts.most_common():
        rgb = (pal[pidx * 3], pal[pidx * 3 + 1], pal[pidx * 3 + 2])
        raw_colors.append((rgb, cnt))

    merged: list[tuple[tuple[int, int, int], int]] = []
    for rgb, cnt in raw_colors:
        placed = False
        for mi, (mrgb, mcnt) in enumerate(merged):
            if _rgb_dist(rgb, mrgb) < 62:
                merged[mi] = (mrgb, mcnt + cnt)
                placed = True
                break
        if not placed:
            merged.append((rgb, cnt))
        if len(merged) >= max_colors:
            break

    palette = [rgb for rgb, _ in merged]
    # Assign each foreground pixel to its nearest palette color
    layer_buffers = [bytearray(w * h) for _ in palette]
    layer_counts = [0] * len(palette)
    for idx, is_fg in enumerate(fg_mask):
        if not is_fg:
            continue
        r, g, b, _ = px[idx]
        best_i = 0
        best_d = 1e9
        for ci, crgb in enumerate(palette):
            d = (r - crgb[0]) ** 2 + (g - crgb[1]) ** 2 + (b - crgb[2]) ** 2
            if d < best_d:
                best_d = d
                best_i = ci
        layer_buffers[best_i][idx] = 255
        layer_counts[best_i] += 1

    min_px = max(24, int(w * h * min_area_ratio))
    layers: list[tuple[tuple[int, int, int], Image.Image]] = []
    for rgb, buf, cnt in zip(palette, layer_buffers, layer_counts):
        if cnt < min_px:
            continue
        mask = Image.frombytes("L", (w, h), bytes(buf))
        # Mild median smoothing eliminates 1px anti-aliasing speckles before Bezier fitting
        mask = mask.filter(ImageFilter.MedianFilter(size=3))
        layers.append((rgb, mask))
    if not layers:
        raise TraceError("foreground layers were all below noise threshold")
    return layers


def _trace_mask_potrace(mask: Image.Image, potrace_bin: str, *, upscale: int = 2) -> tuple[str, list[str]]:
    """Run potrace on a single binary foreground mask (255=ink) and return (transform, path_ds)."""
    w, h = mask.size
    if upscale > 1:
        work = mask.resize((w * upscale, h * upscale), Image.Resampling.BILINEAR)
    else:
        work = mask
    # potrace treats BLACK (0) in PBM as foreground ink and WHITE (255) as background
    bw = work.point(lambda v: 0 if v >= 128 else 255, mode="1")

    with tempfile.TemporaryDirectory(prefix="genimg_trace_") as td:
        pbm = Path(td) / "mask.pbm"
        svg = Path(td) / "mask.svg"
        bw.save(pbm, format="PPM")
        cmd = [
            potrace_bin,
            str(pbm),
            "--svg",
            "--flat",
            "--turdsize", "16",
            "--alphamax", "0.95",
            "--opttolerance", "0.35",
            "-o", str(svg),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode != 0 or not svg.is_file():
            raise TraceError(f"potrace failed (rc={proc.returncode}): {proc.stderr.strip()[:300]}")
        text = svg.read_text(encoding="utf-8")

    tm = _G_TRANSFORM_RE.search(text)
    transform = tm.group(1) if tm else ""
    paths = _PATH_D_RE.findall(text)
    return transform, paths


def trace_image_to_svg(
    image_path: str | Path,
    out_svg: str | Path | None = None,
    *,
    max_colors: int = 4,
    backend: str = "auto",
) -> str:
    """Vectorize a flat logo/logotype raster image into a smooth multi-color SVG string."""
    src = Path(image_path).expanduser().resolve()
    if not src.is_file():
        raise TraceError(f"input image not found: {src}")

    if backend in ("auto", "vtracer"):
        try:
            import vtracer  # type: ignore[import-not-found]
            with tempfile.TemporaryDirectory(prefix="genimg_vt_") as td:
                tmp_svg = Path(td) / "traced.svg"
                vtracer.convert_image_to_svg_py(
                    str(src), str(tmp_svg),
                    colormode="color",
                    hierarchical="stacked",
                    mode="spline",
                    filter_speckle=10,
                    color_precision=6,
                    corner_threshold=60,
                )
                svg_text = tmp_svg.read_text(encoding="utf-8")
                if out_svg is not None:
                    Path(out_svg).write_text(svg_text, encoding="utf-8")
                return svg_text
        except ImportError:
            if backend == "vtracer":
                raise TraceError("vtracer is not installed; install `vtracer` or use `potrace`.")

    potrace_bin = shutil.which("potrace")
    if not potrace_bin:
        raise TraceError(
            "Vector tracing requires `potrace` (`brew install potrace` / `apt install potrace`) "
            "or Python package `vtracer`."
        )

    with Image.open(src) as im:
        w, h = im.size
        layers = _quantize_foreground_layers(im, max_colors=max_colors)

    upscale = 2 if max(w, h) <= 1600 else 1
    groups: list[str] = []
    for (r, g, b), mask in layers:
        hex_color = f"#{r:02X}{g:02X}{b:02X}"
        transform, paths = _trace_mask_potrace(mask, potrace_bin, upscale=upscale)
        if not paths:
            continue
        # Potrace outputs coordinates in upscaled pt space; wrap scale cleanly back to original viewBox
        inv = 1.0 / upscale
        path_elems = "\n".join(f'      <path d="{d}"/>' for d in paths)
        inner = (
            f'    <g transform="{transform}" fill="{hex_color}" stroke="none">\n'
            f"{path_elems}\n"
            f"    </g>"
        )
        if upscale > 1:
            groups.append(f'  <g transform="scale({inv:g})">\n{inner}\n  </g>')
        else:
            groups.append(inner)

    if not groups:
        raise TraceError("vectorization produced no SVG paths")

    svg_text = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        f'width="{w}" height="{h}">\n'
        + "\n".join(groups)
        + "\n</svg>\n"
    )
    if out_svg is not None:
        out_p = Path(out_svg).expanduser().resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(svg_text, encoding="utf-8")
    return svg_text


def main_trace(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        prog="generate-image-trace",
        description="Vectorize a flat logo, handcrafted logotype, or emblem PNG into a smooth multi-color SVG.",
    )
    ap.add_argument("image", help="path to input raster image (PNG/JPG/WEBP)")
    ap.add_argument("-o", "--output", default=None, help="output .svg path (default: <image_stem>.svg)")
    ap.add_argument("--colors", type=int, default=4, help="maximum flat brand color layers (default: 4)")
    ap.add_argument("--backend", choices=("auto", "potrace", "vtracer"), default="auto")
    args = ap.parse_args(argv)
    src = Path(args.image).expanduser()
    out = Path(args.output).expanduser() if args.output else src.with_suffix(".svg")
    try:
        trace_image_to_svg(src, out, max_colors=args.colors, backend=args.backend)
    except TraceError as exc:
        sys.exit(f"error: {exc}")
    print(f"→ traced: {out}", file=sys.stderr)
