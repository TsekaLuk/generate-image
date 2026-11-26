"""Animated GIF output (`--gif`, GPT Image 2.6 on the OpenAI Image API)."""

from __future__ import annotations

import base64
import json
import struct
import sys

import httpx
import pytest

from generate_image import cli as generate
from generate_image import probe
from generate_image.providers import PROVIDERS, route_provider

_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _gif(delays_cs: list[int], w: int = 4, h: int = 3) -> bytes:
    """A minimal valid GIF89a with one 1x1 frame per entry (delay in 1/100 s)."""
    out = bytearray(b"GIF89a" + struct.pack("<HH", w, h) + bytes([0x80, 0, 0]))
    out += bytes([0, 0, 0, 255, 255, 255])                       # 2-colour global table
    for d in delays_cs:
        out += bytes([0x21, 0xF9, 4, 0]) + struct.pack("<H", d) + bytes([0, 0])
        out += bytes([0x2C]) + struct.pack("<HHHH", 0, 0, 1, 1) + bytes([0])
        out += bytes([2, 2, 0x44, 0x01, 0])                      # LZW min 2, one sub-block
    out += b"\x3B"
    return bytes(out)


_GIF = _gif([20, 20, 20])  # 3 frames x 200 ms


@pytest.fixture(autouse=True)
def _openai_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")


def _install(monkeypatch, handler):
    monkeypatch.setattr(generate, "_TEST_TRANSPORT", httpx.MockTransport(handler))


def _run(monkeypatch, argv) -> int:
    monkeypatch.setattr(sys, "argv", ["g", *argv])
    try:
        generate.main()
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)


def _ok(payload: bytes):
    return httpx.Response(200, json={"output_format": "gif",
                                     "data": [{"b64_json": base64.b64encode(payload).decode()}]})


def _no_network(req):
    raise AssertionError(f"no request may be sent, got {req.method} {req.url}")


def test_gif_frames_and_dims():
    assert probe.gif_frames(_gif([10, 25, 200])) == [100, 250, 2000]
    assert probe.image_dims(_gif([10], w=640, h=360)) == (640, 360, "GIF")
    assert probe.gif_frames(_TINY_PNG) == []
    three = _gif([10, 10, 10])
    assert probe.gif_frames(three[:41]) == []
    assert probe.gif_frames(three[:42]) == [100]
    assert probe.gif_frames(three[:50]) == [100]
    assert probe.gif_frames(three[:-1]) == [100, 100, 100]


def test_gif_generation_uses_images_endpoint_with_pinned_frames(tmp_path, monkeypatch, capsys):
    seen = []

    def handler(req):
        seen.append((req.url.path, json.loads(req.content)))
        return _ok(_GIF)

    _install(monkeypatch, handler)
    rc = _run(monkeypatch, ["弹跳的小球，无缝循环", "--gif", "--frames", "12",
                            "--frame-ms", "120", "-o", str(tmp_path), "-n", "ball", "--json"])
    assert rc == 0
    assert len(seen) == 1
    path, body = seen[0]
    assert path == "/v1/images/generations"
    assert body["model"] == "gpt-image-2.6-flare"
    assert body["output_format"] == "gif"
    assert body["frame_count"] == 12
    assert body["frame_duration_ms"] == 120
    assert "size" not in body

    out = json.loads(capsys.readouterr().out)
    assert out["path"] == str(tmp_path / "ball.gif")
    assert out["format"] == "gif" and out["frames"] == 3
    assert (out["width"], out["height"]) == (4, 3)
    assert (tmp_path / "ball.gif").read_bytes() == _GIF
    meta = json.loads((tmp_path / "ball.json").read_text())
    assert meta["format"] == "gif"
    assert meta["frames"] == 3 and meta["frame_ms"] == [200, 200, 200]
    assert meta["model"] == "gpt-image-2.6-flare"


def test_gif_without_frame_flags_sends_only_the_format(tmp_path, monkeypatch):
    bodies = []

    def handler(req):
        bodies.append(json.loads(req.content))
        return _ok(_GIF)

    _install(monkeypatch, handler)
    assert _run(monkeypatch, ["转圈的风车", "--gif", "-m", "gpt-image-2.6-sunburst",
                              "-o", str(tmp_path), "-n", "w"]) == 0
    body = bodies[0]
    assert body["output_format"] == "gif"
    assert body["model"] == "gpt-image-2.6-sunburst"
    assert "frame_count" not in body and "frame_duration_ms" not in body


def test_gif_with_ref_goes_multipart_to_edits(tmp_path, monkeypatch):
    ref = tmp_path / "pose.png"
    ref.write_bytes(_TINY_PNG)
    seen = {}

    def handler(req):
        seen["path"] = req.url.path
        seen["ctype"] = req.headers["content-type"]
        seen["raw"] = req.content
        return _ok(_GIF)

    _install(monkeypatch, handler)
    assert _run(monkeypatch, ["让参考图里的角色挥手，循环", "--gif", "--frames", "4",
                              "--ref", str(ref), "-o", str(tmp_path), "-n", "wave"]) == 0
    assert seen["path"] == "/v1/images/edits"
    assert seen["ctype"].startswith("multipart/form-data")
    raw = seen["raw"]
    for name, value in (("model", "gpt-image-2.6-flare"), ("output_format", "gif"),
                        ("frame_count", "4")):
        assert f'name="{name}"\r\n\r\n{value}\r\n'.encode() in raw, name
    assert b"frame_duration_ms" not in raw
    assert (tmp_path / "wave.gif").exists()


@pytest.mark.parametrize("payload, ext, frames, what", [
    (_TINY_PNG, "png", 0, "a PNG still"),
    (_gif([20]), "gif", 1, "a 1-frame GIF"),
])
def test_non_animated_answer_fails_but_keeps_the_billed_file(payload, ext, frames, what,
                                                             tmp_path, monkeypatch, capsys):
    _install(monkeypatch, lambda req: _ok(payload))
    assert _run(monkeypatch, ["跳动的心", "--gif", "-o", str(tmp_path), "-n", "heart",
                              "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and what in out["error"]
    assert out["path"] == str(tmp_path / f"heart.{ext}")
    assert out["format"] == ext and out["frames"] == frames
    assert (tmp_path / f"heart.{ext}").read_bytes() == payload


def test_gif_gate_is_not_retried_and_explains_itself(tmp_path, monkeypatch, capsys):
    calls = []

    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(400, json={"error": {
            "message": "GIF output is not enabled for this request.",
            "type": "invalid_request_error"}})

    _install(monkeypatch, handler)
    rc = _run(monkeypatch, ["弹跳的小球", "--gif", "-o", str(tmp_path), "--json"])
    assert rc == 1
    assert calls == ["/v1/images/generations"]
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert "GIF output is not enabled" in out["error"]
    assert "not entitled to GIF output" in out["error"]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("argv, needle", [
    (["--frames", "8"], "add --gif"),
    (["--frame-ms", "100"], "add --gif"),
    (["--gif", "--frames", "1"], "--frames must be between 2 and 16"),
    (["--gif", "--frames", "17"], "--frames must be between 2 and 16"),
    (["--gif", "--frame-ms", "19"], "--frame-ms must be between 20 and 2000"),
    (["--gif", "--frame-ms", "2001"], "--frame-ms must be between 20 and 2000"),
    (["--gif", "-p", "openai", "-m", "gpt-image-2.5-flare"], "makes stills only"),
    (["--gif", "-m", "gpt-image-2.5-flare"], "GIF output (providers with GIF: 302ai, openai)"),
    (["--gif", "-p", "volcengine"], "cannot produce GIF output"),
    (["--gif", "--count", "2"], "one animation per run"),
])
def test_gif_refusals_send_nothing(argv, needle, tmp_path, monkeypatch):
    monkeypatch.setenv("ARK_API_KEY", "test-key-not-real")
    _install(monkeypatch, _no_network)
    with pytest.raises(SystemExit) as exc:
        monkeypatch.setattr(sys, "argv", ["g", "一个循环动画", "-o", str(tmp_path), *argv])
        generate.main()
    assert needle in str(exc.value.code)


def test_auto_routes_gif_only_to_gif_capable_providers(monkeypatch):
    for p in PROVIDERS.values():
        monkeypatch.setenv(p.key_env, "k")
    assert route_provider(gif=True).name == "openai"
    assert route_provider(gif=True, ref_count=2).name == "openai"
    with pytest.raises(ValueError, match="GIF output"):
        route_provider(gif=True, model="gpt-image-2.5-flare")


def test_auto_gif_excludes_still_only_providers(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.setenv("ARK_API_KEY", "k")
    assert route_provider().name == "volcengine"
    with pytest.raises(ValueError, match="GIF output"):
        route_provider(gif=True)


def test_302ai_gif_omits_size_and_succeeds(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("AI302_API_KEY", "k")
    seen = []

    def handler(req):
        seen.append((req.url.host, req.url.path, json.loads(req.content)))
        return _ok(_GIF)

    _install(monkeypatch, handler)
    rc = _run(monkeypatch, ["弹跳的小球", "--gif", "--frames", "6", "--frame-ms", "150",
                            "-o", str(tmp_path), "-n", "b302", "--json"])
    assert rc == 0
    host, path, body = seen[0]
    assert host == "api.302.ai" and path == "/v1/images/generations"
    assert body["model"] == "gpt-image-2.6-flare"
    assert body["output_format"] == "gif"
    assert body["frame_count"] == 6 and body["frame_duration_ms"] == 150
    assert "size" not in body
    out = json.loads(capsys.readouterr().out)
    assert out["provider"] == "302ai" and out["path"].endswith("b302.gif")


def test_dry_run_gif_plan(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _install(monkeypatch, _no_network)
    assert _run(monkeypatch, ["弹跳的小球", "--gif", "--frames", "6", "--dry-run",
                              "--json"]) == 0
    cap = capsys.readouterr()
    plan = json.loads(cap.out)
    assert plan["provider"] == "openai" and plan["model"] == "gpt-image-2.6-flare"
    assert plan["output_format"] == "gif"
    assert plan["frame_count"] == 6 and plan["frame_duration_ms"] is None
    assert plan["estimated_cost_cny"] is None
    assert "/v1/images/generations" in cap.err
    assert "not measured for GIF" in cap.err
