"""Tests for multi-color raster-to-SVG tracing (`trace_svg`) and long-scroll `kind: stitch`."""

from __future__ import annotations

import io
import json
import shutil
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from generate_image import board, cli as generate, dag, trace


def _make_two_color_logo_png(path: Path) -> Path:
    im = Image.new("RGB", (240, 240), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle((40, 40, 140, 200), fill=(20, 22, 26))
    d.ellipse((150, 40, 210, 100), fill=(190, 50, 40))
    im.save(path, format="PNG")
    return path


@pytest.mark.skipif(shutil.which("potrace") is None, reason="potrace binary not installed")
def test_trace_image_to_svg_exports_two_color_bezier_paths(tmp_path):
    src = _make_two_color_logo_png(tmp_path / "logo.png")
    out_svg = tmp_path / "logo.svg"
    svg_text = trace.trace_image_to_svg(src, out_svg, max_colors=3, backend="potrace")
    assert out_svg.is_file()
    assert svg_text.startswith("<svg ")
    assert 'viewBox="0 0 240 240"' in svg_text
    # Expect 2 distinct color layers (dark ink + vermilion accent)
    assert svg_text.count("<path d=") >= 2
    assert svg_text.count("fill=\"#") == 2


def test_board_stitch_images_vertical_normalizes_width(tmp_path):
    p1 = tmp_path / "s1.png"
    p2 = tmp_path / "s2.png"
    Image.new("RGB", (200, 100), (20, 20, 20)).save(p1)
    Image.new("RGB", (100, 100), (220, 50, 40)).save(p2)
    out = tmp_path / "scroll.png"
    raw = board.stitch_images([p1, p2], out, direction="vertical", target_width=200, gap=10)
    assert out.is_file() and len(raw) > 100
    with Image.open(out) as res:
        assert res.size == (200, 100 + 10 + 200)


def test_parse_dag_and_cli_stitch_costs_zero(tmp_path, monkeypatch):
    p1 = tmp_path / "a.png"
    p2 = tmp_path / "b.png"
    Image.new("RGB", (120, 80), (10, 10, 10)).save(p1)
    Image.new("RGB", (120, 60), (200, 40, 40)).save(p2)

    spec = tmp_path / "stitch.json"
    spec.write_text(json.dumps({
        "tasks": [
            {"id": "long_scroll", "kind": "stitch", "refs": [str(p1), str(p2)], "width": 120}
        ]
    }), encoding="utf-8")
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "g", "--dag-file", str(spec), "-o", str(out_dir), "--max-cost", "0", "--no-gallery",
    ])
    generate.main()
    stitched = out_dir / "long_scroll.png"
    assert stitched.is_file()
    with Image.open(stitched) as im:
        assert im.size == (120, 140)
