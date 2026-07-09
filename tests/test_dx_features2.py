"""DX features round 2, end-to-end through generate.main() with HTTP mocked via
the generate._TEST_TRANSPORT seam (httpx.MockTransport) — no real network:

  (A) --seed N          seed in body only where supported (siliconflow); else warn
  (B) --count N         N single-prompt images -> <stem>_1..N.png; N=1 unchanged
  (C) live progress      _progress: carriage-return elapsed on tty only, then cleared
  (D) --open            reveal outputs via OS opener, best-effort, skipped on dry-run
  (E) env defaults      GENIMAGE_PROVIDER / _RATIO / _OUTPUT_DIR (+ invalid => warn)
  (F) cost summary      "→ spent: ..." after a real run, sharing the cost map
"""

from __future__ import annotations

import base64
import json
import sys
import time

import httpx
import pytest

from generate_image import cli as generate

_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _success_response() -> httpx.Response:
    return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(_TINY_PNG).decode("ascii")}]})


def _install(monkeypatch, handler):
    monkeypatch.setattr(generate, "_TEST_TRANSPORT", httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    # A pristine env so GENIMAGE_* from the developer shell never leaks into a test.
    for k in ("GENIMAGE_PROVIDER", "GENIMAGE_RATIO", "GENIMAGE_OUTPUT_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("AI302_API_KEY", "test-key-not-real")


def _run_main() -> int:
    try:
        generate.main()
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)


def _write_batch(tmp_path, lines):
    p = tmp_path / "prompts.txt"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _capture_body(store):
    def handler(req):
        store.append(req.content.decode("utf-8") if req.content else "")
        return _success_response()
    return handler


# --- (A) --seed ---------------------------------------------------------------

def test_seed_included_for_siliconflow(tmp_path, monkeypatch):
    monkeypatch.setenv("SILICONFLOW_API_KEY", "k")
    bodies: list[str] = []
    _install(monkeypatch, _capture_body(bodies))
    monkeypatch.setattr(sys, "argv", [
        "g", "一只猫", "-p", "siliconflow", "-m", "Qwen/Qwen-Image",
        "--seed", "42", "-o", str(tmp_path / "out"), "-n", "s", "--no-preview",
    ])
    assert _run_main() == 0
    body = json.loads(bodies[0])
    assert body.get("seed") == 42


def test_seed_ignored_and_warns_on_openai(tmp_path, monkeypatch, capsys):
    bodies: list[str] = []
    _install(monkeypatch, _capture_body(bodies))
    monkeypatch.setattr(sys, "argv", [
        "g", "一只猫", "--seed", "7", "-o", str(tmp_path / "out"), "-n", "m", "--no-preview",
    ])
    assert _run_main() == 0
    body = json.loads(bodies[0])
    assert "seed" not in body
    err = capsys.readouterr().err
    assert "--seed ignored on openai" in err
    assert "unsupported" in err


@pytest.mark.parametrize("provider,key_env", [
    ("openai", "OPENAI_API_KEY"),
    ("302ai", "AI302_API_KEY"),
    ("openrouter", "OPENROUTER_API_KEY"),
])
def test_seed_ignored_and_warns_per_unsupported_provider(
        provider, key_env, tmp_path, monkeypatch, capsys):
    # All three lack supports_seed: seed must NOT reach the body and a warning fires
    # once. Guards against a provider being flipped to supports_seed=True by mistake.
    monkeypatch.setenv(key_env, "k")
    bodies: list[str] = []
    _install(monkeypatch, _capture_body(bodies))
    monkeypatch.setattr(sys, "argv", [
        "g", "一只猫", "-p", provider, "--seed", "9",
        "-o", str(tmp_path / "out"), "-n", "s", "--no-preview",
    ])
    assert _run_main() == 0
    assert "seed" not in json.loads(bodies[0])
    err = capsys.readouterr().err
    assert err.count(f"--seed ignored on {provider}") == 1  # once, not per request


def test_seed_in_batch_bodies_for_siliconflow(tmp_path, monkeypatch):
    monkeypatch.setenv("SILICONFLOW_API_KEY", "k")
    bodies: list[str] = []
    _install(monkeypatch, _capture_body(bodies))
    bf = _write_batch(tmp_path, ["a", "b"])
    monkeypatch.setattr(sys, "argv", [
        "g", "--batch-file", str(bf), "-p", "siliconflow", "-m", "Qwen/Qwen-Image",
        "--seed", "42", "-o", str(tmp_path / "out"), "-n", "b",
        "--no-preview", "--concurrency", "1",
    ])
    assert _run_main() == 0
    assert len(bodies) == 2
    assert all(json.loads(b).get("seed") == 42 for b in bodies)


def test_seed_warns_once_in_batch_on_openai(tmp_path, monkeypatch, capsys):
    bodies: list[str] = []
    _install(monkeypatch, _capture_body(bodies))
    bf = _write_batch(tmp_path, ["a", "b", "c"])
    monkeypatch.setattr(sys, "argv", [
        "g", "--batch-file", str(bf), "--seed", "5",
        "-o", str(tmp_path / "out"), "-n", "b", "--no-preview", "--concurrency", "1",
    ])
    assert _run_main() == 0
    err = capsys.readouterr().err
    assert err.count("--seed ignored on openai") == 1  # one warning for the whole batch
    assert all("seed" not in json.loads(b) for b in bodies)


# --- (B) --count --------------------------------------------------------------

def test_count_writes_n_images_and_sidecars(tmp_path, monkeypatch):
    out = tmp_path / "out"
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return _success_response()

    _install(monkeypatch, handler)
    monkeypatch.setattr(sys, "argv", [
        "g", "日落", "-o", str(out), "-n", "pic", "--no-preview", "--count", "3",
    ])
    assert _run_main() == 0
    assert calls["n"] == 3
    for i in (1, 2, 3):
        assert (out / f"pic_{i}.png").exists()
        assert (out / f"pic_{i}.json").exists()
    # count>1 does NOT also write the unsuffixed <stem>.png
    assert not (out / "pic.png").exists()


def test_count_json_is_array(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    _install(monkeypatch, lambda req: _success_response())
    monkeypatch.setattr(sys, "argv", [
        "g", "x", "-o", str(out), "-n", "pic", "--no-preview", "--count", "2", "--json",
    ])
    assert _run_main() == 0
    arr = json.loads(capsys.readouterr().out.strip())
    assert isinstance(arr, list) and len(arr) == 2
    assert arr[0]["ok"] is True and arr[0]["path"].endswith("pic_1.png")
    assert arr[1]["path"].endswith("pic_2.png")


def test_count_one_keeps_single_object_and_unsuffixed_name(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    _install(monkeypatch, lambda req: _success_response())
    monkeypatch.setattr(sys, "argv", [
        "g", "x", "-o", str(out), "-n", "pic", "--no-preview", "--count", "1", "--json",
    ])
    assert _run_main() == 0
    obj = json.loads(capsys.readouterr().out.strip())
    assert isinstance(obj, dict)              # single object, NOT an array
    assert obj["ok"] is True and obj["path"].endswith("pic.png")
    assert (out / "pic.png").exists()
    assert not (out / "pic_1.png").exists()


def test_count_rejected_with_batch_file(tmp_path, monkeypatch):
    bf = _write_batch(tmp_path, ["a", "b"])
    _install(monkeypatch, lambda req: _success_response())
    monkeypatch.setattr(sys, "argv", [
        "g", "--batch-file", str(bf), "--count", "2", "-o", str(tmp_path / "out"),
    ])
    assert _run_main() != 0


def test_count_rejected_with_dag_file(tmp_path, monkeypatch):
    spec = tmp_path / "dag.json"
    spec.write_text(json.dumps({"tasks": [{"id": "A", "prompt": "p"}]}), encoding="utf-8")
    _install(monkeypatch, lambda req: _success_response())
    monkeypatch.setattr(sys, "argv", [
        "g", "--dag-file", str(spec), "--count", "2", "-o", str(tmp_path / "out"),
    ])
    assert _run_main() != 0


def test_count_below_one_rejected(tmp_path, monkeypatch):
    _install(monkeypatch, lambda req: _success_response())
    monkeypatch.setattr(sys, "argv", [
        "g", "x", "--count", "0", "-o", str(tmp_path / "out"), "-n", "p", "--no-preview",
    ])
    assert _run_main() != 0  # count>=1 is validated up front, no silent coercion to 1


def test_count_mid_sequence_failure_json_array(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 2:
            return httpx.Response(400, text="bad")  # non-retryable => aborts the sequence
        return _success_response()

    _install(monkeypatch, handler)
    monkeypatch.setattr(sys, "argv", [
        "g", "x", "-o", str(out), "-n", "pic", "--no-preview", "--count", "2", "--json",
    ])
    assert _run_main() == 1
    arr = json.loads(capsys.readouterr().out.strip())
    assert isinstance(arr, list) and len(arr) == 2
    assert arr[0]["ok"] is True and arr[0]["path"].endswith("pic_1.png")
    assert arr[-1]["ok"] is False and arr[-1]["path"] is None and arr[-1]["error"]
    assert (out / "pic_1.png").exists()  # the first image was still written before the abort


def test_count_mid_sequence_failure_reports_spent(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 2:
            return httpx.Response(400, text="bad")
        return _success_response()

    _install(monkeypatch, handler)
    monkeypatch.setattr(sys, "argv", [
        "g", "x", "-p", "302ai", "-o", str(out), "-n", "pic", "--no-preview", "--count", "3",
    ])
    assert _run_main() != 0
    err = capsys.readouterr().err
    # 302ai bills success AND failure -> 1 written + 1 failed = 2 billed calls surfaced
    # (the '→ spent:' line prints BEFORE the abort, so already-billed cost isn't hidden)
    assert "→ spent:" in err and "¥0.20" in err and "2 billed call" in err
    assert (out / "pic_1.png").exists()


def test_count_dry_run_reflects_n(tmp_path, monkeypatch, capsys):
    _install(monkeypatch, lambda req: (_ for _ in ()).throw(AssertionError("no net")))
    monkeypatch.setattr(sys, "argv", ["g", "cat", "-p", "302ai", "--dry-run", "--count", "4", "--json"])
    assert _run_main() == 0
    cap = capsys.readouterr()
    assert "4" in cap.err and "billed call" in cap.err
    obj = json.loads(cap.out.strip())
    assert obj["images"] == 4
    assert obj["estimated_cost_cny"] == 0.4


# --- (C) progress -------------------------------------------------------------

class _FakeErr:
    def __init__(self, tty: bool):
        self._tty = tty
        self.buf: list[str] = []

    def isatty(self) -> bool:
        return self._tty

    def write(self, s: str) -> int:
        self.buf.append(s)
        return len(s)

    def flush(self) -> None:
        pass


def test_progress_writes_and_clears_on_tty(monkeypatch, capsys):
    fake = _FakeErr(tty=True)
    monkeypatch.setattr(generate.sys, "stderr", fake)
    with generate._progress("generating", interval=0.01):
        time.sleep(0.05)
    text = "".join(fake.buf)
    assert "generating" in text
    assert "\r" in text  # carriage-return in-place update + clear
    # progress is stderr-only: nothing must ever leak to stdout
    assert capsys.readouterr().out == ""


def test_progress_silent_on_non_tty(monkeypatch):
    fake = _FakeErr(tty=False)
    monkeypatch.setattr(generate.sys, "stderr", fake)
    with generate._progress("generating", interval=0.01):
        time.sleep(0.03)
    assert fake.buf == []  # nothing written when not a tty


# --- (D) --open ---------------------------------------------------------------

def test_open_invokes_os_opener(tmp_path, monkeypatch):
    out = tmp_path / "out"
    _install(monkeypatch, lambda req: _success_response())
    recorded: list[list[str]] = []
    monkeypatch.setattr(generate.subprocess, "run",
                        lambda cmd, *a, **k: recorded.append([str(x) for x in cmd]))
    monkeypatch.setattr(sys, "argv", [
        "g", "x", "-o", str(out), "-n", "pic", "--no-preview", "--open",
    ])
    assert _run_main() == 0
    assert recorded, "expected an OS opener invocation"
    cmd = recorded[-1]
    assert cmd[0] in ("open", "xdg-open")
    assert any(c.endswith("pic.png") for c in cmd)


def test_open_count_reveals_all_images(tmp_path, monkeypatch):
    out = tmp_path / "out"
    _install(monkeypatch, lambda req: _success_response())
    recorded: list[list[str]] = []
    monkeypatch.setattr(generate.subprocess, "run",
                        lambda cmd, *a, **k: recorded.append([str(x) for x in cmd]))
    monkeypatch.setattr(sys, "argv", [
        "g", "x", "-o", str(out), "-n", "pic", "--no-preview", "--count", "2", "--open",
    ])
    assert _run_main() == 0
    flat = [c for cmd in recorded for c in cmd]
    assert any(c.endswith("pic_1.png") for c in flat)
    assert any(c.endswith("pic_2.png") for c in flat)


def test_open_warns_and_noops_with_batch_file(tmp_path, monkeypatch, capsys):
    bf = _write_batch(tmp_path, ["a", "b"])
    _install(monkeypatch, lambda req: _success_response())
    recorded: list[list[str]] = []
    monkeypatch.setattr(generate.subprocess, "run",
                        lambda cmd, *a, **k: recorded.append([str(x) for x in cmd]))
    monkeypatch.setattr(sys, "argv", [
        "g", "--batch-file", str(bf), "-o", str(tmp_path / "out"), "-n", "b",
        "--no-preview", "--open",
    ])
    assert _run_main() == 0
    err = capsys.readouterr().err
    assert "--open ignored with --batch-file/--dag-file" in err  # warned, not silent
    assert recorded == []  # and genuinely a no-op (no OS opener invoked)


def test_open_skipped_under_dry_run(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _install(monkeypatch, lambda req: (_ for _ in ()).throw(AssertionError("no net")))
    recorded: list[list[str]] = []
    monkeypatch.setattr(generate.subprocess, "run",
                        lambda cmd, *a, **k: recorded.append(list(cmd)))
    monkeypatch.setattr(sys, "argv", ["g", "x", "--dry-run", "--open"])
    assert _run_main() == 0
    assert recorded == []  # nothing revealed under --dry-run


# --- (E) env defaults ---------------------------------------------------------

def test_env_default_provider(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GENIMAGE_PROVIDER", "302ai")
    monkeypatch.setenv("AI302_API_KEY", "k")
    _install(monkeypatch, lambda req: _success_response())
    monkeypatch.setattr(sys, "argv", ["g", "x", "-o", str(tmp_path / "o"), "-n", "p", "--no-preview"])
    assert _run_main() == 0
    assert "→ provider: 302ai" in capsys.readouterr().err


def test_cli_provider_flag_beats_env_default(tmp_path, monkeypatch, capsys):
    # An explicit -p must override GENIMAGE_PROVIDER (the env is only a default).
    monkeypatch.setenv("GENIMAGE_PROVIDER", "302ai")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    _install(monkeypatch, lambda req: _success_response())
    monkeypatch.setattr(sys, "argv", [
        "g", "x", "-p", "openrouter", "-o", str(tmp_path / "o"), "-n", "p", "--no-preview",
    ])
    assert _run_main() == 0
    assert "→ provider: openrouter" in capsys.readouterr().err


def test_cli_ratio_flag_beats_env_default(tmp_path, monkeypatch, capsys):
    # An explicit -r must override GENIMAGE_RATIO, with no invalid-env warning.
    monkeypatch.setenv("GENIMAGE_RATIO", "not-a-ratio")
    _install(monkeypatch, lambda req: _success_response())
    monkeypatch.setattr(sys, "argv", [
        "g", "x", "-r", "9:16", "-o", str(tmp_path / "o"), "-n", "p", "--no-preview",
    ])
    assert _run_main() == 0
    err = capsys.readouterr().err
    assert "→ ratio:    9:16" in err
    assert "GENIMAGE_RATIO" not in err  # env ignored (and not warned) when -r is explicit


def test_env_invalid_provider_warns_and_falls_back(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GENIMAGE_PROVIDER", "not-real")
    _install(monkeypatch, lambda req: _success_response())
    monkeypatch.setattr(sys, "argv", ["g", "x", "-o", str(tmp_path / "o"), "-n", "p", "--no-preview"])
    assert _run_main() == 0
    err = capsys.readouterr().err
    assert "GENIMAGE_PROVIDER" in err          # one-line warning
    assert "→ provider: openai" in err         # built-in default used


def test_env_default_ratio(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GENIMAGE_RATIO", "9:16")
    _install(monkeypatch, lambda req: _success_response())
    monkeypatch.setattr(sys, "argv", ["g", "x", "-o", str(tmp_path / "o"), "-n", "p", "--no-preview"])
    assert _run_main() == 0
    assert "→ ratio:    9:16" in capsys.readouterr().err


def test_env_invalid_ratio_warns_and_falls_back(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GENIMAGE_RATIO", "not-a-ratio")
    _install(monkeypatch, lambda req: _success_response())
    monkeypatch.setattr(sys, "argv", ["g", "x", "-o", str(tmp_path / "o"), "-n", "p", "--no-preview"])
    assert _run_main() == 0
    err = capsys.readouterr().err
    assert "GENIMAGE_RATIO" in err
    assert "→ ratio:    16:9" in err            # default ratio used


def test_env_output_dir(tmp_path, monkeypatch):
    dest = tmp_path / "env-out"
    monkeypatch.setenv("GENIMAGE_OUTPUT_DIR", str(dest))
    _install(monkeypatch, lambda req: _success_response())
    monkeypatch.setattr(sys, "argv", ["g", "x", "-n", "p", "--no-preview"])
    assert _run_main() == 0
    assert (dest / "p.png").exists()


# --- (F) cost summary ---------------------------------------------------------

def test_cost_summary_single_302ai(tmp_path, monkeypatch, capsys):
    _install(monkeypatch, lambda req: _success_response())
    monkeypatch.setattr(sys, "argv", ["g", "x", "-p", "302ai", "-o", str(tmp_path / "o"), "-n", "p", "--no-preview"])
    assert _run_main() == 0
    err = capsys.readouterr().err
    assert "→ spent:" in err
    assert "¥0.10" in err and "1 billed call" in err


def test_cost_summary_count(tmp_path, monkeypatch, capsys):
    _install(monkeypatch, lambda req: _success_response())
    monkeypatch.setattr(sys, "argv", [
        "g", "x", "-p", "302ai", "-o", str(tmp_path / "o"), "-n", "p", "--no-preview", "--count", "3",
    ])
    assert _run_main() == 0
    err = capsys.readouterr().err
    assert "→ spent:" in err and "¥0.30" in err and "3 billed call" in err


def test_cost_summary_varies_for_openrouter(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    _install(monkeypatch, lambda req: _success_response())
    monkeypatch.setattr(sys, "argv", [
        "g", "x", "-p", "openrouter", "-o", str(tmp_path / "o"), "-n", "p", "--no-preview",
    ])
    assert _run_main() == 0
    err = capsys.readouterr().err
    assert "→ spent:" in err
    assert "cost varies for openrouter" in err


def test_cost_summary_batch_302ai(tmp_path, monkeypatch, capsys):
    bf = _write_batch(tmp_path, ["one", "two"])
    _install(monkeypatch, lambda req: _success_response())
    monkeypatch.setattr(sys, "argv", [
        "g", "-p", "302ai", "--batch-file", str(bf), "-o", str(tmp_path / "o"), "-n", "b", "--no-preview",
    ])
    assert _run_main() == 0
    err = capsys.readouterr().err
    assert "→ spent:" in err and "¥0.20" in err and "2 billed call" in err


def test_dry_run_cost_uses_shared_map_for_varies(tmp_path, monkeypatch, capsys):
    # The dry-run cost line must reuse the same cost map: a provider without a
    # known per-image price reports "cost varies", not a bogus ¥0.1.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _install(monkeypatch, lambda req: (_ for _ in ()).throw(AssertionError("no net")))
    monkeypatch.setattr(sys, "argv", ["g", "cat", "-p", "openrouter", "--dry-run"])
    assert _run_main() == 0
    err = capsys.readouterr().err
    assert "cost varies for openrouter" in err


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
