"""Deterministic local SVG / HTML rendering engine for hybrid vector + AI DAGs.

Uses a locally installed Chromium-family browser (Google Chrome, Chromium,
Microsoft Edge, or Brave) in headless mode with an isolated temp profile per
call so concurrent DAG threads never collide. Zero extra Python dependencies.

Supports:
  * Razor-sharp 2x/3x Retina PNG rendering of exact SVG vector marks, custom
    CJK/Latin typography lockups, print-ready VI manuals, posters, cards & UIs
  * True 8-bit RGBA transparent PNGs (`transparent=True`) OR guaranteed opaque
    RGB PNGs (`transparent=False`)
  * Multi-page print-ready PDF export (`render_html_to_pdf`)
  * Template injection of upstream AI outputs (`{{ref.0}}`, `{{refs.<id>}}`,
    and base64 `{{ref_data.0}}` / `{{refs_data.<id>}}`)
"""

from __future__ import annotations

import base64
import io
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

_BROWSER_ENV = "GENERATE_IMAGE_BROWSER"

_MACOS_BROWSERS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
)

_PATH_BROWSERS = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "microsoft-edge",
    "brave-browser",
)

_REF_IDX_RE = re.compile(r"\{\{\s*ref\.([0-9]+)\s*\}\}")
_REF_DATA_IDX_RE = re.compile(r"\{\{\s*ref_data\.([0-9]+)\s*\}\}")
_REF_ID_RE = re.compile(r"\{\{\s*refs\.([A-Za-z0-9_:-]+)\s*\}\}")
_REF_DATA_ID_RE = re.compile(r"\{\{\s*refs_data\.([A-Za-z0-9_:-]+)\s*\}\}")
_VIEWBOX_RE = re.compile(r'viewBox\s*=\s*["\']\s*[-0-9.]+\s+[-0-9.]+\s+([0-9.]+)\s+([0-9.]+)\s*["\']')
_ATTR_W_RE = re.compile(r'\bwidth\s*=\s*["\']([0-9.]+)(?:px)?["\']')
_ATTR_H_RE = re.compile(r'\bheight\s*=\s*["\']([0-9.]+)(?:px)?["\']')


class RenderError(RuntimeError):
    """Raised when local browser discovery or headless rendering fails."""


def find_browser() -> str:
    """Locate a headless-capable Chromium-family binary."""
    env = os.environ.get(_BROWSER_ENV, "").strip()
    if env:
        if Path(env).is_file() and os.access(env, os.X_OK):
            return env
        found = shutil.which(env)
        if found:
            return found
        raise RenderError(f"{_BROWSER_ENV}={env!r} is not an executable browser binary")

    for p in _MACOS_BROWSERS:
        if Path(p).is_file() and os.access(p, os.X_OK):
            return p
    for name in _PATH_BROWSERS:
        found = shutil.which(name)
        if found:
            return found
    raise RenderError(
        "No Chromium-family browser found for `kind: render` tasks. "
        "Install Google Chrome / Chromium or set GENERATE_IMAGE_BROWSER=/path/to/chrome."
    )


def _to_file_uri(path_str: str) -> str:
    if path_str.startswith(("http://", "https://", "data:", "file://")):
        return path_str
    return Path(path_str).expanduser().resolve().as_uri()


def _to_data_uri(path_str: str) -> str:
    if path_str.startswith("data:"):
        return path_str
    p = Path(path_str).expanduser().resolve()
    raw = p.read_bytes()
    mime, _ = mimetypes.guess_type(p.name)
    mime = mime or "image/png"
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


def interpolate_refs(source: str, refs: list[str],
                     ref_map: dict[str, str] | None = None) -> str:
    """Resolve `{{ref.0}}`, `{{refs.<id>}}`, and `{{ref_data.*}}` inside HTML/SVG."""
    rmap = ref_map or {}

    def _sub_idx(m: re.Match, as_data: bool) -> str:
        idx = int(m.group(1))
        if not 0 <= idx < len(refs):
            raise RenderError(f"template placeholder {m.group(0)!r} out of range (have {len(refs)} ref(s))")
        return _to_data_uri(refs[idx]) if as_data else _to_file_uri(refs[idx])

    def _sub_id(m: re.Match, as_data: bool) -> str:
        key = m.group(1)
        if key not in rmap:
            raise RenderError(f"template placeholder {m.group(0)!r} not found in refs {sorted(rmap)}")
        return _to_data_uri(rmap[key]) if as_data else _to_file_uri(rmap[key])

    out = _REF_IDX_RE.sub(lambda m: _sub_idx(m, False), source)
    out = _REF_DATA_IDX_RE.sub(lambda m: _sub_idx(m, True), out)
    out = _REF_ID_RE.sub(lambda m: _sub_id(m, False), out)
    out = _REF_DATA_ID_RE.sub(lambda m: _sub_id(m, True), out)
    return out


def infer_svg_dimensions(svg_text: str, default: tuple[int, int] = (1024, 1024)) -> tuple[int, int]:
    """Infer logical (width, height) pixels from an SVG root tag."""
    head = svg_text[:1000]
    vb = _VIEWBOX_RE.search(head)
    if vb:
        return max(1, round(float(vb.group(1)))), max(1, round(float(vb.group(2))))
    mw, mh = _ATTR_W_RE.search(head), _ATTR_H_RE.search(head)
    if mw and mh:
        return max(1, round(float(mw.group(1)))), max(1, round(float(mh.group(1))))
    return default


def wrap_svg_as_html(svg_text: str, *, width: int, height: int,
                     transparent: bool = False, background: str = "#FFFFFF") -> str:
    """Wrap raw SVG markup into an exact-viewport, zero-margin HTML document."""
    bg = "transparent" if transparent else background
    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        f"html,body{{margin:0;padding:0;width:{width}px;height:{height}px;"
        f"overflow:hidden;background:{bg};display:flex;align-items:center;justify-content:center;}}"
        f"svg{{display:block;width:{width}px;height:{height}px;}}"
        "</style></head><body>"
        f"{svg_text}"
        "</body></html>"
    )


def _inject_base_href(html_text: str, base_dir: Path | None) -> str:
    if base_dir is None or "<base " in html_text.lower():
        return html_text
    base_tag = f'<base href="{base_dir.resolve().as_uri()}/">'
    m = re.search(r"<head\b[^>]*>", html_text, flags=re.IGNORECASE)
    if m:
        return html_text[:m.end()] + base_tag + html_text[m.end():]
    return base_tag + html_text


def render_html_to_png(html_text: str, *, width: int, height: int,
                       scale: float = 2.0, transparent: bool = False,
                       base_dir: Path | None = None, timeout: int = 45,
                       browser: str | None = None) -> bytes:
    """Render an HTML document to crisp PNG bytes via headless Chromium."""
    exe = browser or find_browser()
    if width <= 0 or height <= 0:
        raise RenderError(f"invalid render dimensions {width}x{height}")
    if scale <= 0:
        raise RenderError(f"invalid render scale {scale}")

    prepared = _inject_base_href(html_text, base_dir)
    with tempfile.TemporaryDirectory(prefix="genimg_render_") as td:
        tdir = Path(td)
        profile_dir = tdir / "profile"
        html_path = tdir / "page.html"
        out_png = tdir / "out.png"
        html_path.write_text(prepared, encoding="utf-8")

        cmd = [
            exe,
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--hide-scrollbars",
            "--allow-file-access-from-files",
            f"--user-data-dir={profile_dir}",
            f"--force-device-scale-factor={scale:g}",
            f"--window-size={width},{height}",
            f"--screenshot={out_png}",
        ]
        if transparent:
            cmd.append("--default-background-color=00000000")
        cmd.append(html_path.as_uri())

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise RenderError(f"headless browser timed out after {timeout}s") from exc

        if proc.returncode != 0 or not out_png.is_file():
            snippet = (proc.stderr or proc.stdout or "").strip()[-400:]
            raise RenderError(f"headless render failed (rc={proc.returncode}): {snippet}")

        raw = out_png.read_bytes()

    if not transparent:
        # Ensure opaque renders are saved as true RGB (no stray alpha channel).
        with Image.open(io.BytesIO(raw)) as im:
            if im.mode != "RGB":
                rgb = Image.new("RGB", im.size, (255, 255, 255))
                if im.mode == "RGBA":
                    rgb.paste(im, mask=im.getchannel("A"))
                else:
                    rgb = im.convert("RGB")
                buf = io.BytesIO()
                rgb.save(buf, format="PNG")
                return buf.getvalue()
    return raw


def render_svg_to_png(svg_text: str, *, width: int | None = None,
                      height: int | None = None, scale: float = 2.0,
                      transparent: bool = False, background: str = "#FFFFFF",
                      timeout: int = 45, browser: str | None = None) -> bytes:
    """Render an SVG document to crisp PNG bytes via headless Chromium."""
    inf_w, inf_h = infer_svg_dimensions(svg_text)
    w = width or inf_w
    h = height or inf_h
    wrapped = wrap_svg_as_html(svg_text, width=w, height=h,
                               transparent=transparent, background=background)
    return render_html_to_png(wrapped, width=w, height=h, scale=scale,
                              transparent=transparent, timeout=timeout,
                              browser=browser)


def render_html_to_pdf(html_text: str, out_pdf: Path, *,
                       base_dir: Path | None = None, timeout: int = 45,
                       browser: str | None = None) -> Path:
    """Render a multi-page CSS @page HTML document to a print-ready PDF."""
    exe = browser or find_browser()
    out_pdf = Path(out_pdf).expanduser().resolve()
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    prepared = _inject_base_href(html_text, base_dir)
    with tempfile.TemporaryDirectory(prefix="genimg_pdf_") as td:
        tdir = Path(td)
        profile_dir = tdir / "profile"
        html_path = tdir / "page.html"
        html_path.write_text(prepared, encoding="utf-8")
        cmd = [
            exe,
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--allow-file-access-from-files",
            "--print-to-pdf-no-header",
            f"--user-data-dir={profile_dir}",
            f"--print-to-pdf={out_pdf}",
            html_path.as_uri(),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise RenderError(f"headless PDF render timed out after {timeout}s") from exc
        if proc.returncode != 0 or not out_pdf.is_file():
            snippet = (proc.stderr or proc.stdout or "").strip()[-400:]
            raise RenderError(f"headless PDF render failed (rc={proc.returncode}): {snippet}")
    return out_pdf


def execute_render_task(task, refs: list[str], *,
                        ref_map: dict[str, str] | None = None,
                        out_dir: Path | None = None) -> tuple[bytes, str | None]:
    """Execute one `kind='render'` DAG Task.

    Returns `(png_bytes, svg_text_or_None)`. When `svg_text` is non-None, the
    DAG runner writes `<stem>.svg` right next to `<stem>.png` as a true vector
    deliverable.
    """
    transparent = (task.background == "transparent")
    scale = float(task.scale or 2.0)

    if task.svg is not None or task.svg_file is not None:
        base_dir = Path(task.svg_file).parent if task.svg_file else None
        raw_svg = Path(task.svg_file).read_text(encoding="utf-8") if task.svg_file else str(task.svg)
        resolved_svg = interpolate_refs(raw_svg, refs, ref_map)
        png = render_svg_to_png(
            resolved_svg,
            width=task.width,
            height=task.height,
            scale=scale,
            transparent=transparent,
        )
        return png, resolved_svg

    if task.html is not None or task.html_file is not None:
        base_dir = Path(task.html_file).parent if task.html_file else out_dir
        raw_html = Path(task.html_file).read_text(encoding="utf-8") if task.html_file else str(task.html)
        resolved_html = interpolate_refs(raw_html, refs, ref_map)
        w = task.width or 1440
        h = task.height or 900
        png = render_html_to_png(
            resolved_html,
            width=w,
            height=h,
            scale=scale,
            transparent=transparent,
            base_dir=base_dir,
        )
        return png, None

    raise RenderError(f"render task {task.id!r} must specify html, html_file, svg, or svg_file")
