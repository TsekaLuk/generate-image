"""Tests for deterministic local SVG/HTML rendering (`kind: render`) and CJK contact sheets."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import httpx
import pytest
from PIL import Image

from generate_image import board, cli as generate, dag, render


def _make_png(w: int = 40, h: int = 40, color=(184, 51, 42)) -> bytes:
    im = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def test_parse_dag_infers_render_kind_and_resolves_relative_files(tmp_path):
    svg_file = tmp_path / "mark.svg"
    svg_file.write_text('<svg viewBox="0 0 100 100"><rect width="100" height="100"/></svg>', encoding="utf-8")
    spec_path = tmp_path / "dag.json"
    spec_path.write_text(json.dumps({
        "tasks": [
            {"id": "logo", "svg_file": "mark.svg", "width": 500, "height": 500, "background": "transparent"},
            {"id": "sheet", "html": "<div>{{refs.logo}}</div>", "refs": ["@logo"], "width": 800, "height": 600, "pdf": True},
        ]
    }), encoding="utf-8")

    tasks = dag.load_dag(str(spec_path))
    assert len(tasks) == 2
    t0, t1 = tasks
    assert t0.kind == dag.KIND_RENDER
    assert t0.svg_file == str(svg_file.resolve())
    assert t0.width == 500 and t0.height == 500 and t0.background == "transparent"
    assert t1.kind == dag.KIND_RENDER
    assert t1.refs == ("@logo",)
    assert t1.pdf is True
    # Runtime ref placeholders must survive parse_dag untouched for render.interpolate_refs!
    assert "{{refs.logo}}" in (t1.html or "")


def test_compute_task_hash_invalidates_when_template_file_changes(tmp_path):
    tpl = tmp_path / "card.html"
    tpl.write_text("<div>v1</div>", encoding="utf-8")
    t = dag.Task(id="card", kind=dag.KIND_RENDER, html_file=str(tpl), width=600, height=400)
    h1 = dag.compute_task_hash(t, [])
    tpl.write_text("<div>v2</div>", encoding="utf-8")
    h2 = dag.compute_task_hash(t, [])
    assert h1 != h2


def test_interpolate_refs_supports_index_id_and_data_uri(tmp_path):
    img = tmp_path / "hero.png"
    img.write_bytes(_make_png())
    out = render.interpolate_refs(
        '<img src="{{ref.0}}"><img src="{{refs.hero}}"><img src="{{refs_data.hero}}">',
        [str(img)],
        {"hero": str(img)},
    )
    assert img.resolve().as_uri() in out
    assert "data:image/png;base64," in out


def test_infer_svg_dimensions():
    assert render.infer_svg_dimensions('<svg viewBox="0 0 1200 630"></svg>') == (1200, 630)
    assert render.infer_svg_dimensions('<svg width="400" height="300"></svg>') == (400, 300)


def test_render_only_dag_costs_zero_and_passes_max_cost_zero(tmp_path, monkeypatch):
    fake_png = _make_png(80, 60)
    monkeypatch.setattr(render, "render_svg_to_png", lambda *a, **kw: fake_png)

    spec_path = tmp_path / "render_only.json"
    spec_path.write_text(json.dumps({
        "tasks": [
            {"id": "emblem", "svg": '<svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="40"/></svg>'}
        ]
    }), encoding="utf-8")
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "g", "--dag-file", str(spec_path), "-o", str(out_dir), "--max-cost", "0", "--no-gallery",
    ])
    generate.main()
    assert (out_dir / "emblem.png").is_file()
    assert (out_dir / "emblem.svg").is_file()
    assert "<circle" in (out_dir / "emblem.svg").read_text(encoding="utf-8")


def test_contact_sheet_renders_cjk_title_cleanly(tmp_path):
    p = tmp_path / "a.png"
    p.write_bytes(_make_png(120, 90))
    sheets = board.build_contact_sheet(
        [{"id": "01_标志", "path": str(p), "width": 120, "height": 90, "tags": {"stage": "规范"}}],
        tmp_path / "sheet.png",
        title="颜子国际文化传媒 · VI 审核总览",
    )
    assert len(sheets) == 1 and sheets[0].is_file()
