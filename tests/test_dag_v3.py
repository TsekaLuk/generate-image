"""Tests for v3 scalable DAG engine, board grid slicing, contact sheets, and HTML gallery."""

from __future__ import annotations

import base64
import io
import json
import sys

import httpx
import pytest
from PIL import Image

from generate_image import board, cli as generate, dag, gallery


def _make_png(w: int = 60, h: int = 40, color=(200, 50, 50, 255), mode: str = "RGBA") -> bytes:
    im = Image.new(mode, (w, h), color)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _make_colored_grid_png(rows: int = 2, cols: int = 3, cell: int = 40) -> bytes:
    im = Image.new("RGB", (cols * cell, rows * cell))
    palette = [
        (255, 0, 0), (0, 255, 0), (0, 0, 255),
        (255, 255, 0), (255, 0, 255), (0, 255, 255),
    ]
    idx = 0
    for r in range(rows):
        for c in range(cols):
            color = palette[idx % len(palette)]
            for y in range(r * cell, (r + 1) * cell):
                for x in range(c * cell, (c + 1) * cell):
                    im.putpixel((x, y), color)
            idx += 1
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _ok_b64(raw: bytes) -> httpx.Response:
    return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(raw).decode()}]})


def test_parse_dag_matrix_blocks_spec_and_exclude():
    spec = {
        "vars": {"brand": "Nova"},
        "defaults": {"ratio": "1:1", "stage": "fanout"},
        "blocks": {
            "style": "Swiss flat editorial vector for {{vars.brand}}",
            "negatives": "no text clutter, no watermark",
        },
        "tasks": [
            {
                "id": "anchor",
                "stage": "anchors",
                "prompt": "Master hero of {{vars.brand}}, {{blocks.style}}",
            },
            {
                "id": "var_{{angle.key}}_{{mood}}",
                "refs": ["@anchor"],
                "matrix": {
                    "angle": [
                        {"key": "front", "desc": "straight-on front view"},
                        {"key": "iso", "desc": "isometric 3/4 view"},
                    ],
                    "mood": ["day", "night"],
                },
                "exclude": [{"angle": "iso", "mood": "night"}],
                "spec": {
                    "deliverable": "Product angle card",
                    "subject": "{{angle.desc}} of {{vars.brand}} device",
                    "info_points": ["Feature A: fast", "Feature B: silent"],
                    "style": "{{blocks.style}}",
                    "lighting": "{{mood}} studio lighting",
                    "negatives": "{{blocks.negatives}}",
                },
            },
        ],
    }
    tasks = dag.parse_dag(spec, cli_vars={"brand": "Orion"})
    assert [t.id for t in tasks] == ["anchor", "var_front_day", "var_front_night", "var_iso_day"]
    assert "Orion" in tasks[0].prompt
    t1 = tasks[1]
    assert t1.ratio == "1:1" and t1.stage == "fanout" and t1.refs == ("@anchor",)
    assert t1.tags == {"angle": "front", "mood": "day"}
    assert "Feature A: fast; Feature B: silent" in t1.prompt


def test_parse_dag_foreach_and_provider_pool_sharding():
    spec = {
        "defaults": {"provider_pool": ["openai", "302ai"]},
        "tasks": [
            {
                "id": "shot_{{item}}",
                "foreach": ["01", "02", "03", "04"],
                "prompt": "Shot {{item}}",
            }
        ],
    }
    tasks = dag.parse_dag(spec)
    assert [t.id for t in tasks] == ["shot_01", "shot_02", "shot_03", "shot_04"]
    assert [t.provider for t in tasks] == ["openai", "302ai", "openai", "302ai"]


def test_slice_grid_crops_exact_cells(tmp_path):
    src = tmp_path / "board.png"
    src.write_bytes(_make_colored_grid_png(rows=2, cols=3, cell=40))
    gs = board.parse_grid_spec("2x3")
    slices = board.slice_grid(src, gs, tmp_path / "out", "board")
    assert list(slices.keys()) == ["A", "B", "C", "D", "E", "F"]
    with Image.open(slices["A"]) as im_a:
        assert im_a.getpixel((im_a.width // 2, im_a.height // 2)) == (255, 0, 0)
    with Image.open(slices["C"]) as im_c:
        assert im_c.getpixel((im_c.width // 2, im_c.height // 2)) == (0, 0, 255)


def test_dag_board_slice_wires_panel_refs_downstream(tmp_path):
    grid_bytes = _make_colored_grid_png(rows=2, cols=3, cell=40)
    single_bytes = _make_png(32, 32, (10, 200, 10, 255))
    received_refs: dict[str, list[str]] = {}

    def execute(task: dag.Task, refs: list[str]) -> bytes:
        received_refs[task.id] = list(refs)
        return grid_bytes if task.id == "board" else single_bytes

    tasks = dag.parse_dag({
        "tasks": [
            {"id": "board", "prompt": "2x3 exploration board", "grid": {"rows": 2, "cols": 3}},
            {"id": "hero_c", "prompt": "expand panel C", "refs": ["@board:C"]},
            {"id": "hero_idx", "prompt": "expand panel 0", "refs": ["@board[0]"]},
        ]
    })
    results = dag.run_dag(tasks, execute, out_dir=tmp_path, concurrency=2)
    assert results["board"].status == dag.SUCCESS
    assert received_refs["hero_c"] == [str(tmp_path / "board_C.png")]
    assert received_refs["hero_idx"] == [str(tmp_path / "board_A.png")]


def test_dag_resume_caches_unchanged_and_invalidates_descendants_on_anchor_change(tmp_path):
    calls: list[str] = []
    anchor_version = [1]

    def execute(task: dag.Task, refs: list[str]) -> bytes:
        calls.append(task.id)
        if task.id == "anchor":
            return _make_png(20, 20, (anchor_version[0] * 50, 0, 0, 255))
        return _make_png(20, 20, (0, 128, 0, 255))

    tasks = dag.parse_dag({
        "tasks": [
            {"id": "anchor", "prompt": "master v1"},
            {"id": "child", "prompt": "derived from master", "refs": ["@anchor"]},
            {"id": "indep", "prompt": "independent asset"},
        ]
    })
    r1 = dag.run_dag(tasks, execute, out_dir=tmp_path, resume=True)
    assert all(r.status == dag.SUCCESS for r in r1.values())

    calls.clear()
    r2 = dag.run_dag(tasks, execute, out_dir=tmp_path, resume=True)
    assert all(r.status == dag.CACHED for r in r2.values())
    assert calls == []

    anchor_version[0] = 2
    tasks_v2 = dag.parse_dag({
        "tasks": [
            {"id": "anchor", "prompt": "master v2"},
            {"id": "child", "prompt": "derived from master", "refs": ["@anchor"]},
            {"id": "indep", "prompt": "independent asset"},
        ]
    })
    calls.clear()
    r3 = dag.run_dag(tasks_v2, execute, out_dir=tmp_path, resume=True)
    assert r3["anchor"].status == dag.SUCCESS
    assert r3["child"].status == dag.SUCCESS
    assert r3["indep"].status == dag.CACHED
    assert set(calls) == {"anchor", "child"}


def test_filter_tasks_only_roots_stage_and_until():
    tasks = dag.parse_dag({
        "tasks": [
            {"id": "char", "stage": "anchors", "prompt": "character sheet"},
            {"id": "board", "stage": "board", "prompt": "3x3 storyboard", "refs": ["@char"]},
            {"id": "kf1", "stage": "fanout", "prompt": "keyframe 1", "refs": ["@board"]},
            {"id": "kf2", "stage": "fanout", "prompt": "keyframe 2", "refs": ["@board"]},
        ]
    })
    assert [t.id for t in dag.filter_tasks(tasks, only_roots=True)] == ["char"]
    assert [t.id for t in dag.filter_tasks(tasks, stages={"board"})] == ["char", "board"]
    assert [t.id for t in dag.filter_tasks(tasks, only_ids={"kf1"})] == ["char", "board", "kf1"]
    assert [t.id for t in dag.filter_tasks(tasks, until_id="board")] == ["char", "board"]


def test_contact_sheet_pagination_and_gallery_html(tmp_path):
    items = []
    for i in range(18):
        p = tmp_path / f"img_{i:02d}.png"
        p.write_bytes(_make_png(48, 48, (i * 12 % 255, 100, 180, 200)))
        items.append({
            "id": f"img_{i:02d}", "status": "success", "ok": True,
            "path": str(p), "provider": "openai", "model": "gpt-image-2.6-flare",
            "ratio": "1:1", "width": 48, "height": 48,
            "stage": "fanout", "tags": {"idx": str(i)}, "prompt": f"Prompt {i}",
        })

    sheets = board.build_contact_sheet(items, tmp_path / "contact_sheet.png",
                                       cols=4, thumb_size=96, max_per_sheet=16, title="Batch")
    assert len(sheets) == 2
    assert all(s.is_file() for s in sheets)

    gal = gallery.build_gallery(items, tmp_path, title="Test Gallery")
    html_text = gal.read_text(encoding="utf-8")
    assert "Test Gallery" in html_text
    assert "bg-checker" in html_text
    assert "img_17.png" in html_text
    assert "https://" not in html_text


def test_cli_dag_end_to_end_with_resume_and_gallery(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    calls = []
    grid_png = _make_colored_grid_png(rows=1, cols=2, cell=32)
    single_png = _make_png(32, 32, (30, 160, 220, 255))

    def handler(req):
        calls.append(req.url.path)
        if req.url.path.endswith("/edits"):
            return _ok_b64(single_png)
        return _ok_b64(grid_png)

    monkeypatch.setattr(generate, "_TEST_TRANSPORT", httpx.MockTransport(handler))
    spec_path = tmp_path / "dag.json"
    spec_path.write_text(json.dumps({
        "vars": {"hero": "cat"},
        "tasks": [
            {"id": "board", "stage": "board", "prompt": "1x2 board of {{vars.hero}}", "grid": "1x2"},
            {"id": "kf_a", "stage": "fanout", "prompt": "expand A", "refs": ["@board:A"]},
            {"id": "kf_b", "stage": "fanout", "prompt": "expand B", "refs": ["@board:B"]},
        ],
    }), encoding="utf-8")
    out_dir = tmp_path / "out"

    monkeypatch.setattr(sys, "argv", [
        "g", "--dag-file", str(spec_path), "-o", str(out_dir),
        "--var", "hero=fox", "--stage", "board", "--resume",
    ])
    generate.main()
    assert calls == ["/v1/images/generations"]
    assert (out_dir / "board_A.png").is_file()
    assert (out_dir / "board_B.png").is_file()

    calls.clear()
    monkeypatch.setattr(sys, "argv", [
        "g", "--dag-file", str(spec_path), "-o", str(out_dir),
        "--var", "hero=fox", "--resume",
    ])
    generate.main()
    assert calls == ["/v1/images/edits", "/v1/images/edits"]
    assert (out_dir / "gallery.html").is_file()
    assert (out_dir / "contact_sheet.png").is_file()


def test_cli_dag_max_cost_aborts_before_network(tmp_path, monkeypatch):
    # Per CONTRIBUTING.md, 302ai is the public provider with known per-image ¥ pricing.
    monkeypatch.setenv("AI302_API_KEY", "test-key")

    def handler(req):
        raise AssertionError("network must not be called when --max-cost is exceeded")

    monkeypatch.setattr(generate, "_TEST_TRANSPORT", httpx.MockTransport(handler))
    spec_path = tmp_path / "big.json"
    spec_path.write_text(json.dumps({
        "defaults": {"provider": "302ai"},
        "tasks": [{"id": "n_{{item}}", "foreach": list(range(10)), "prompt": "p {{item}}"}]
    }), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "g", "--dag-file", str(spec_path), "-o", str(tmp_path / "out"), "--max-cost", "0.5",
    ])
    with pytest.raises(SystemExit) as ei:
        generate.main()
    assert "--max-cost" in str(ei.value)
