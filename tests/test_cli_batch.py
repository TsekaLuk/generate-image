"""CLI batch mode (--batch-file) end-to-end via main(), with HTTP mocked through
the generate._TEST_TRANSPORT seam (httpx.MockTransport) — no real network.

Batch runs on the default provider (openai). Simulated failures use HTTP 400
(non-retryable) so per-prompt call counts stay deterministic (a retryable error
would be retried up to provider.max_retries, multiplying the counts).
"""

from __future__ import annotations

import base64
import json
import sys

import httpx
import pytest

from generate_image import cli as generate

_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _success_response() -> httpx.Response:
    return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(_TINY_PNG).decode("ascii")}]})


@pytest.fixture(autouse=True)
def _openai_key_env(monkeypatch):
    """Batch exercises the openai provider; ensure require_key never sys.exits."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")


def _install_transport(monkeypatch, handler):
    monkeypatch.setattr(generate, "_TEST_TRANSPORT", httpx.MockTransport(handler))


def _write_batch_file(tmp_path, lines):
    p = tmp_path / "prompts.txt"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


# --- parse_args: --batch-file makes positional prompt optional -----------------

def test_parse_args_accepts_batch_file_without_positional_prompt(tmp_path, monkeypatch):
    batch_file = _write_batch_file(tmp_path, ["一只猫", "", "# comment", "天际线"])
    monkeypatch.setattr(sys, "argv", ["generate.py", "--batch-file", str(batch_file)])
    args = generate.parse_args()
    assert args.batch_file == str(batch_file)
    assert getattr(args, "prompt", None) in (None, "")


def test_parse_args_concurrency_defaults_to_none(tmp_path, monkeypatch):
    # default is None so main() falls back to the provider's default_concurrency
    batch_file = _write_batch_file(tmp_path, ["a prompt"])
    monkeypatch.setattr(sys, "argv", ["generate.py", "--batch-file", str(batch_file)])
    assert generate.parse_args().concurrency is None


def test_parse_args_concurrency_override(tmp_path, monkeypatch):
    batch_file = _write_batch_file(tmp_path, ["a prompt"])
    monkeypatch.setattr(
        sys, "argv", ["generate.py", "--batch-file", str(batch_file), "--concurrency", "7"]
    )
    assert generate.parse_args().concurrency == 7


# --- main(): full batch success -----------------------------------------------

def test_main_batch_writes_all_png_on_full_success(tmp_path, monkeypatch):
    batch_file = _write_batch_file(tmp_path, ["prompt A", "prompt B", "prompt C"])
    out_dir = tmp_path / "out"
    calls = []

    def handler(req):
        calls.append(req)
        return _success_response()

    _install_transport(monkeypatch, handler)
    monkeypatch.setattr(sys, "argv", [
        "generate.py", "--batch-file", str(batch_file),
        "-o", str(out_dir), "-n", "mybatch", "--no-preview",
    ])

    try:
        generate.main()
        exit_code = 0
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)

    assert exit_code == 0
    assert len(calls) == 3
    written = sorted(p.name for p in out_dir.glob("*.png"))
    assert written == ["mybatch_001.png", "mybatch_002.png", "mybatch_003.png"]
    for fname in written:
        assert (out_dir / fname).read_bytes() == _TINY_PNG


def test_main_batch_skips_blank_and_comment_lines(tmp_path, monkeypatch):
    batch_file = _write_batch_file(tmp_path, [
        "# leading comment", "", "real one", "   ", "# another", "real two",
    ])
    out_dir = tmp_path / "out"
    calls = []

    def handler(req):
        calls.append(req)
        return _success_response()

    _install_transport(monkeypatch, handler)
    monkeypatch.setattr(sys, "argv", [
        "generate.py", "--batch-file", str(batch_file), "-o", str(out_dir), "--no-preview",
    ])

    try:
        generate.main()
    except SystemExit:
        pass

    assert len(calls) == 2
    assert len(list(out_dir.glob("*.png"))) == 2


# --- main(): partial failure continues ----------------------------------------

def test_main_batch_partial_failure_writes_survivors(tmp_path, monkeypatch, capsys):
    batch_file = _write_batch_file(tmp_path, ["prompt one", "prompt two (fails)", "prompt three"])
    out_dir = tmp_path / "out"
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        body = req.content.decode("utf-8") if req.content else ""
        prompt = json.loads(body).get("prompt", "") if body else ""
        if "fails" in prompt:
            return httpx.Response(400, text="bad prompt")  # non-retryable
        return _success_response()

    _install_transport(monkeypatch, handler)
    monkeypatch.setattr(sys, "argv", [
        "generate.py", "--batch-file", str(batch_file),
        "-o", str(out_dir), "-n", "partial", "--no-preview", "--concurrency", "1",
    ])

    try:
        generate.main()
        exit_code = 0
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except Exception as e:  # noqa: BLE001
        pytest.fail(f"main() must isolate a single job failure, not crash: {type(e).__name__}: {e}")

    assert calls["n"] == 3
    written = sorted(p.name for p in out_dir.glob("*.png"))
    assert len(written) == 2
    assert "partial_002.png" not in written
    assert exit_code == 0
    err = capsys.readouterr().err
    assert "2" in err and "3" in err


def test_main_batch_all_fail_exits_nonzero(tmp_path, monkeypatch):
    batch_file = _write_batch_file(tmp_path, ["prompt one", "prompt two"])
    out_dir = tmp_path / "out"

    def handler(req):
        return httpx.Response(400, text="nope")  # non-retryable

    _install_transport(monkeypatch, handler)
    monkeypatch.setattr(sys, "argv", [
        "generate.py", "--batch-file", str(batch_file), "-o", str(out_dir), "--no-preview",
    ])

    with pytest.raises(SystemExit) as ei:
        generate.main()
    assert ei.value.code not in (0, None)
    assert not out_dir.exists() or len(list(out_dir.glob("*.png"))) == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
