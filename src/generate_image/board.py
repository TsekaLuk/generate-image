"""Board grid slicing and composite contact-sheet rendering.

Two primitives that make multi-image workflows and N-in-1 concept/storyboard boards
first-class inside a harness-native agent loop:

  1. `slice_grid` — deterministically crops a generated multi-panel board (e.g. a
     2x3 concept exploration board or 3x3 short-drama storyboard) into standalone
     panel PNGs, shaving off border/gutter hairlines via `trim_pct`. Downstream DAG
     tasks can reference individual panels via `@board:C` or `@board[2]`.
  2. `build_contact_sheet` — tiles up to 16 generated images into a crisp labeled
     PNG grid (`contact_sheet.png`) so a multimodal host agent can visually inspect
     an entire batch in ONE image read instead of N separate reads.
"""

from __future__ import annotations

import argparse
import math
import string
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

_CJK_FONT_CANDIDATES = (
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "C:/Windows/Fonts/msyh.ttc",
)


def _load_ui_font(size: int = 13):
    """Load a crisp CJK-capable system font for contact-sheet labels, with safe fallback."""
    for path in _CJK_FONT_CANDIDATES:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


@dataclass(frozen=True)
class GridSpec:
    """Geometry and labeling of a regular rows x cols panel board."""

    rows: int
    cols: int
    trim_pct: float = 1.5
    labels: tuple[str, ...] = ()

    @property
    def count(self) -> int:
        return self.rows * self.cols

    def resolved_labels(self) -> tuple[str, ...]:
        n = self.count
        if self.labels:
            if len(self.labels) != n:
                raise ValueError(
                    f"grid labels count ({len(self.labels)}) must equal rows*cols ({n})"
                )
            return self.labels
        if n <= 26:
            return tuple(string.ascii_uppercase[:n])
        return tuple(str(i) for i in range(1, n + 1))

    def to_fingerprint(self) -> dict:
        return {
            "rows": self.rows,
            "cols": self.cols,
            "trim_pct": self.trim_pct,
            "labels": list(self.resolved_labels()),
        }


def parse_grid_spec(raw: object) -> GridSpec:
    """Parse a GridSpec from `"RxC"` (e.g. `"3x3"`, `"2x3"`) or a dict mapping.

    String shorthand uses `rows x cols` (matching matrix notation). For clarity on
    non-square boards, prefer `{rows: 2, cols: 3, trim_pct: 2, labels: [...]}`.
    """
    if isinstance(raw, GridSpec):
        return raw
    if isinstance(raw, str):
        s = raw.strip().lower().replace("×", "x")
        parts = s.split("x")
        if len(parts) != 2 or not all(p.strip().isdigit() for p in parts):
            raise ValueError(f"invalid grid spec {raw!r}; expected 'RxC' (e.g. '3x3', '2x3')")
        rows, cols = int(parts[0]), int(parts[1])
        trim_pct = 1.5
        labels: tuple[str, ...] = ()
    elif isinstance(raw, dict):
        try:
            rows = int(raw["rows"])
            cols = int(raw["cols"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("grid mapping must provide integer 'rows' and 'cols'") from exc
        trim_pct = float(raw.get("trim_pct", 1.5))
        raw_labels = raw.get("labels")
        if raw_labels is None:
            labels = ()
        elif isinstance(raw_labels, (list, tuple)) and all(isinstance(x, (str, int)) for x in raw_labels):
            labels = tuple(str(x) for x in raw_labels)
        else:
            raise ValueError("grid 'labels' must be a list of strings/integers")
    else:
        raise ValueError(f"grid spec must be 'RxC' string or mapping, got {type(raw).__name__}")

    if rows < 1 or cols < 1 or rows * cols < 2:
        raise ValueError(f"grid must have at least 2 cells (got {rows}x{cols})")
    if not 0.0 <= trim_pct < 25.0:
        raise ValueError(f"grid trim_pct must be in [0, 25), got {trim_pct}")
    spec = GridSpec(rows=rows, cols=cols, trim_pct=trim_pct, labels=labels)
    spec.resolved_labels()  # validate label count upfront
    return spec


def slice_grid(image_path: Path, grid: GridSpec, out_dir: Path, stem: str) -> dict[str, Path]:
    """Slice `image_path` into `rows * cols` standalone panel PNGs.

    Returns an ordered `{label: path}` mapping. Each panel is written to
    `out_dir / f"{stem}_{label}.png"`.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    labels = grid.resolved_labels()
    result: dict[str, Path] = {}

    with Image.open(image_path) as im:
        im.load()
        width, height = im.size
        cell_w = width / grid.cols
        cell_h = height / grid.rows
        pad_x = cell_w * (grid.trim_pct / 100.0)
        pad_y = cell_h * (grid.trim_pct / 100.0)

        idx = 0
        for r in range(grid.rows):
            for c in range(grid.cols):
                x0 = int(round(c * cell_w + pad_x))
                y0 = int(round(r * cell_h + pad_y))
                x1 = int(round((c + 1) * cell_w - pad_x))
                y1 = int(round((r + 1) * cell_h - pad_y))
                # Clamp safely inside image bounds
                x0 = max(0, min(x0, width - 1))
                y0 = max(0, min(y0, height - 1))
                x1 = max(x0 + 1, min(x1, width))
                y1 = max(y0 + 1, min(y1, height))
                label = labels[idx]
                target = out_dir / f"{stem}_{label}.png"
                im.crop((x0, y0, x1, y1)).save(target, format="PNG")
                result[label] = target
                idx += 1
    return result


def _render_single_sheet(items: list[dict], out_path: Path, *, cols: int,
                         thumb_size: int, title: str) -> Path:
    n = len(items)
    actual_cols = max(1, min(cols, n))
    rows = math.ceil(n / actual_cols)
    pad = 16
    label_h = 34
    header_h = 44 if title else 12
    cell_w = thumb_size
    cell_h = thumb_size + label_h

    canvas_w = pad + actual_cols * (cell_w + pad)
    canvas_h = header_h + rows * (cell_h + pad) + pad
    canvas = Image.new("RGB", (canvas_w, canvas_h), (20, 22, 27))
    draw = ImageDraw.Draw(canvas)
    title_font = _load_ui_font(16)
    label_font = _load_ui_font(12)

    if title:
        draw.text((pad, 13), title, fill=(235, 238, 245), font=title_font)

    # Subtle checkerboard tile for visualising transparent RGBA thumbnails
    checker = Image.new("RGB", (cell_w, thumb_size), (38, 41, 49))
    cdraw = ImageDraw.Draw(checker)
    sq = 16
    for y in range(0, thumb_size, sq):
        for x in range(0, cell_w, sq):
            if ((x // sq) + (y // sq)) % 2 == 0:
                cdraw.rectangle((x, y, x + sq - 1, y + sq - 1), fill=(52, 56, 66))

    for idx, item in enumerate(items):
        r, c = divmod(idx, actual_cols)
        x0 = pad + c * (cell_w + pad)
        y0 = header_h + r * (cell_h + pad)
        # Card backdrop
        draw.rectangle((x0 - 1, y0 - 1, x0 + cell_w + 1, y0 + cell_h + 1),
                       fill=(30, 33, 40), outline=(60, 65, 78))

        img_path = item.get("path")
        rendered = False
        if img_path and Path(img_path).is_file():
            try:
                with Image.open(img_path) as raw_im:
                    frame = raw_im.convert("RGBA")
                    thumb = ImageOps.contain(frame, (cell_w, thumb_size))
                    bg = checker.copy()
                    ox = (cell_w - thumb.width) // 2
                    oy = (thumb_size - thumb.height) // 2
                    bg.paste(thumb, (ox, oy), thumb)
                    canvas.paste(bg, (x0, y0))
                    rendered = True
            except Exception:  # noqa: BLE001 - tolerate synthetic/corrupt files
                rendered = False

        if not rendered:
            status = item.get("status") or ("ok" if item.get("ok") else "failed")
            draw.rectangle((x0, y0, x0 + cell_w, y0 + thumb_size), fill=(42, 32, 36))
            draw.text((x0 + 12, y0 + thumb_size // 2 - 6), f"[{status}]", fill=(230, 140, 140), font=label_font)

        # Label bar underneath
        label = str(item.get("id") or Path(str(img_path or idx)).stem)
        dims = ""
        if item.get("width") and item.get("height"):
            dims = f" {item['width']}x{item['height']}"
        tag_str = ""
        tags = item.get("tags")
        if isinstance(tags, dict) and tags:
            tag_str = " [" + "/".join(str(v) for v in tags.values()) + "]"
        caption = f"{label}{dims}{tag_str}"
        if len(caption) > 48:
            caption = caption[:45] + "..."
        draw.text((x0 + 8, y0 + thumb_size + 10), caption, fill=(225, 229, 238), font=label_font)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, format="PNG")
    return out_path


def build_contact_sheet(items: list[dict], out_path: Path, *, cols: int = 4,
                        thumb_size: int = 384, max_per_sheet: int = 16,
                        title: str = "") -> list[Path]:
    """Render one or more composite contact-sheet PNGs for rapid visual review.

    Splits automatically into `<stem>_1.png`, `<stem>_2.png`, ... when `len(items)`
    exceeds `max_per_sheet` so each cell remains crisp for multimodal inspection.
    """
    if not items:
        return []
    out_path = Path(out_path)
    if len(items) <= max_per_sheet:
        return [_render_single_sheet(items, out_path, cols=cols,
                                     thumb_size=thumb_size, title=title)]
    sheets: list[Path] = []
    total_pages = math.ceil(len(items) / max_per_sheet)
    for page in range(total_pages):
        chunk = items[page * max_per_sheet:(page + 1) * max_per_sheet]
        page_path = out_path.with_name(f"{out_path.stem}_{page + 1}{out_path.suffix}")
        page_title = f"{title} (page {page + 1}/{total_pages})" if title else f"Page {page + 1}/{total_pages}"
        sheets.append(_render_single_sheet(chunk, page_path, cols=cols,
                                           thumb_size=thumb_size, title=page_title))
    return sheets


def stitch_images(
    image_paths: list[str | Path],
    out_path: Path | None = None,
    *,
    direction: str = "vertical",
    target_width: int | None = None,
    gap: int = 0,
    bg: tuple[int, int, int] = (20, 21, 24),
) -> bytes:
    """Seamlessly stitch modular sections into one Behance/Zcool long-scroll PNG.

    Supports `direction='vertical'` (normalizes all sections to `target_width`
    or the max section width, preserving aspect ratio) and `direction='horizontal'`.
    Returns PNG bytes and writes to `out_path` if provided.
    """
    if not image_paths:
        raise ValueError("stitch_images requires at least one image path")
    if direction not in ("vertical", "horizontal"):
        raise ValueError(f"direction must be 'vertical' or 'horizontal', got {direction!r}")

    import io
    opened: list[Image.Image] = []
    try:
        for p in image_paths:
            with Image.open(Path(p).expanduser()) as raw:
                if raw.mode == "RGBA":
                    flat = Image.new("RGB", raw.size, bg)
                    flat.paste(raw, mask=raw.getchannel("A"))
                    opened.append(flat)
                else:
                    opened.append(raw.convert("RGB"))

        if direction == "vertical":
            w = target_width or max(im.width for im in opened)
            scaled: list[Image.Image] = []
            for im in opened:
                if im.width != w:
                    nh = max(1, round(im.height * (w / im.width)))
                    scaled.append(im.resize((w, nh), Image.Resampling.LANCZOS))
                else:
                    scaled.append(im)
            total_h = sum(im.height for im in scaled) + gap * max(0, len(scaled) - 1)
            canvas = Image.new("RGB", (w, total_h), bg)
            y = 0
            for im in scaled:
                canvas.paste(im, (0, y))
                y += im.height + gap
        else:
            h = max(im.height for im in opened)
            scaled = []
            for im in opened:
                if im.height != h:
                    nw = max(1, round(im.width * (h / im.height)))
                    scaled.append(im.resize((nw, h), Image.Resampling.LANCZOS))
                else:
                    scaled.append(im)
            total_w = sum(im.width for im in scaled) + gap * max(0, len(scaled) - 1)
            canvas = Image.new("RGB", (total_w, h), bg)
            x = 0
            for im in scaled:
                canvas.paste(im, (x, 0))
                x += im.width + gap

        buf = io.BytesIO()
        canvas.save(buf, format="PNG")
        data = buf.getvalue()
        if out_path is not None:
            op = Path(out_path)
            op.parent.mkdir(parents=True, exist_ok=True)
            op.write_bytes(data)
        return data
    finally:
        for im in opened:
            im.close()


def main_slice(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        prog="generate-image-slice",
        description="Slice a multi-panel board image (e.g. 2x3 or 3x3 grid) into standalone PNG panels.",
    )
    ap.add_argument("image", help="path to the board image to slice")
    ap.add_argument("-g", "--grid", required=True,
                    help="grid layout as ROWSxCOLS (e.g. 3x3, 2x3)")
    ap.add_argument("--trim", type=float, default=1.5,
                    help="percentage to trim from each cell edge to remove dividers (default: 1.5)")
    ap.add_argument("--labels", default=None,
                    help="comma-separated panel labels (default: A,B,C... or 1,2,3...)")
    ap.add_argument("-o", "--output-dir", default=None,
                    help="output directory (default: same directory as input image)")
    ap.add_argument("-n", "--name", default=None,
                    help="output filename stem (default: input image stem)")
    args = ap.parse_args(argv)

    src = Path(args.image).expanduser()
    if not src.is_file():
        sys.exit(f"error: image not found: {args.image}")

    base = parse_grid_spec(args.grid)
    labels = tuple(s.strip() for s in args.labels.split(",") if s.strip()) if args.labels else ()
    try:
        spec = GridSpec(rows=base.rows, cols=base.cols, trim_pct=args.trim, labels=labels)
        spec.resolved_labels()
    except ValueError as exc:
        sys.exit(f"error: {exc}")

    out_dir = Path(args.output_dir).expanduser() if args.output_dir else src.parent
    stem = args.name or src.stem
    written = slice_grid(src, spec, out_dir, stem)
    for label, path in written.items():
        print(f"{label}\t{path}")


if __name__ == "__main__":
    main_slice()
