"""Developer-experience features driven end-to-end through generate.main(), with
HTTP mocked via the generate._TEST_TRANSPORT seam (httpx.MockTransport) — no real
network is ever hit:

  (1) --dry-run     plan only, NO API call and NO key required (all 3 paths)
  (2) metadata      <name>.json sidecar next to each PNG, --no-metadata to opt out
  (3) --json        machine-readable JSON to stdout, human banner stays on stderr
"""

from __future__ import annotations

import base64
import json
import sys

import httpx
import pytest

import generate_image
from generate_image import cli as generate

# A real 1x1 PNG so probe.image_dims() decodes width/height = 1/1.
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _success_response() -> httpx.Response:
    return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(_TINY_PNG).decode("ascii")}]})


def _install(monkeypatch, handler):
    monkeypatch.setattr(generate, "_TEST_TRANSPORT", httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _default_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")


def _write_batch(tmp_path, lines):
    p = tmp_path / "prompts.txt"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _write_spec(tmp_path, spec) -> str:
    f = tmp_path / "dag.json"
    f.write_text(json.dumps(spec), encoding="utf-8")
    return str(f)


def _run_main() -> int:
    try:
        generate.main()
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)


# --- (1) --dry-run ------------------------------------------------------------

def test_dry_run_single_no_call_no_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)  # a missing key must NOT error under --dry-run

    def handler(req):
        raise AssertionError("no network must happen under --dry-run")

    _install(monkeypatch, handler)
    monkeypatch.setattr(sys, "argv", ["g", "一只猫", "--dry-run", "-r", "9:16"])
    assert _run_main() == 0
    err = capsys.readouterr().err
    assert "openai" in err
    assert "9:16" in err
    assert "billed call" in err
    assert "cost varies for openai" in err  # openai is not in the fixed cost map
    assert "→ spent:" not in err  # dry-run spends nothing (plan shows '→ cost:' only)


def test_dry_run_batch_counts_usable_prompts(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)  # dry-run must short-circuit before require_key
    bf = _write_batch(tmp_path, ["a", "", "# comment", "b", "c"])  # 3 usable

    def handler(req):
        raise AssertionError("no network under --dry-run")

    _install(monkeypatch, handler)
    monkeypatch.setattr(sys, "argv", ["g", "--batch-file", str(bf), "--dry-run"])
    assert _run_main() == 0
    err = capsys.readouterr().err
    assert "3" in err
    assert "billed call" in err
    assert "→ spent:" not in err  # nothing billed under --dry-run


def test_dry_run_dag_counts_tasks(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)  # dry-run must short-circuit before require_key
    spec = {"tasks": [{"id": "A", "prompt": "p"}, {"id": "B", "prompt": "q", "refs": ["@A"]}]}
    sp = _write_spec(tmp_path, spec)

    def handler(req):
        raise AssertionError("no network under --dry-run")

    _install(monkeypatch, handler)
    monkeypatch.setattr(sys, "argv", ["g", "--dag-file", sp, "--dry-run", "-o", str(tmp_path / "out")])
    assert _run_main() == 0
    err = capsys.readouterr().err
    assert "2" in err
    assert "billed call" in err
    assert "→ spent:" not in err  # nothing billed under --dry-run
    # dry-run short-circuits before any output dir is created
    assert not (tmp_path / "out").exists()


# --- (2) metadata sidecars ----------------------------------------------------

def test_metadata_single(tmp_path, monkeypatch):
    out = tmp_path / "out"
    _install(monkeypatch, lambda req: _success_response())
    monkeypatch.setattr(sys, "argv", [
        "g", "日落", "-o", str(out), "-n", "pic", "--no-preview", "-r", "9:16",
    ])
    assert _run_main() == 0
    meta = json.loads((out / "pic.json").read_text(encoding="utf-8"))
    assert meta["prompt"] == "日落"          # original prompt, not the ratio-hinted one
    assert meta["provider"] == "openai"
    assert meta["model"] == "gpt-image-2"
    assert meta["ratio"] == "9:16"
    assert meta["width"] == 1 and meta["height"] == 1
    assert meta["refs"] == []
    assert meta["background"] is None            # default: no background override
    assert meta["version"] == generate_image.__version__
    assert "created" in meta and meta["created"]


def test_no_metadata_opt_out(tmp_path, monkeypatch):
    out = tmp_path / "out"
    _install(monkeypatch, lambda req: _success_response())
    monkeypatch.setattr(sys, "argv", [
        "g", "x", "-o", str(out), "-n", "pic", "--no-preview", "--no-metadata",
    ])
    assert _run_main() == 0
    assert (out / "pic.png").exists()
    assert not (out / "pic.json").exists()


def test_metadata_batch(tmp_path, monkeypatch):
    bf = _write_batch(tmp_path, ["p one", "p two"])
    out = tmp_path / "out"
    _install(monkeypatch, lambda req: _success_response())
    monkeypatch.setattr(sys, "argv", [
        "g", "--batch-file", str(bf), "-o", str(out), "-n", "b", "--no-preview",
    ])
    assert _run_main() == 0
    m1 = json.loads((out / "b_001.json").read_text(encoding="utf-8"))
    m2 = json.loads((out / "b_002.json").read_text(encoding="utf-8"))
    assert m1["prompt"] == "p one" and m2["prompt"] == "p two"
    assert m1["provider"] == "openai" and m1["width"] == 1


def test_metadata_dag(tmp_path, monkeypatch):
    out = tmp_path / "out"
    _install(monkeypatch, lambda req: _success_response())
    spec = {"tasks": [{"id": "A", "prompt": "root", "ratio": "1:1"}]}
    sp = _write_spec(tmp_path, spec)
    monkeypatch.setattr(sys, "argv", ["g", "--dag-file", sp, "-o", str(out)])
    assert _run_main() == 0
    m = json.loads((out / "A.json").read_text(encoding="utf-8"))
    assert m["prompt"] == "root"
    assert m["ratio"] == "1:1"
    assert m["provider"] == "openai"
    assert m["model"] == "gpt-image-2"
    assert m["width"] == 1 and m["height"] == 1


# --- (3) --json ---------------------------------------------------------------

def test_json_single_success(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    _install(monkeypatch, lambda req: _success_response())
    monkeypatch.setattr(sys, "argv", [
        "g", "cat", "-o", str(out), "-n", "pic", "--no-preview", "--json", "-r", "1:1",
    ])
    assert _run_main() == 0
    cap = capsys.readouterr()
    obj = json.loads(cap.out.strip())
    assert obj["ok"] is True
    assert obj["path"].endswith("pic.png")
    assert obj["provider"] == "openai"
    assert obj["model"] == "gpt-image-2"
    assert obj["ratio"] == "1:1"
    assert obj["width"] == 1 and obj["height"] == 1
    # human banner stays on stderr; stdout is ONLY the json (plain path suppressed)
    assert "provider" in cap.err
    assert cap.out.strip().startswith("{")


def test_json_single_failure(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    _install(monkeypatch, lambda req: httpx.Response(400, text="bad prompt"))
    monkeypatch.setattr(sys, "argv", [
        "g", "cat", "-o", str(out), "-n", "pic", "--no-preview", "--json",
    ])
    assert _run_main() != 0
    obj = json.loads(capsys.readouterr().out.strip())
    assert obj["ok"] is False
    assert obj["error"]


def test_no_json_prints_plain_path(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    _install(monkeypatch, lambda req: _success_response())
    monkeypatch.setattr(sys, "argv", ["g", "cat", "-o", str(out), "-n", "pic", "--no-preview"])
    assert _run_main() == 0
    o = capsys.readouterr().out.strip()
    assert o.endswith("pic.png")
    assert not o.startswith("{")


def test_json_batch_array(tmp_path, monkeypatch, capsys):
    bf = _write_batch(tmp_path, ["p one", "p two (fails)", "p three"])
    out = tmp_path / "out"

    def handler(req):
        body = req.content.decode("utf-8") if req.content else ""
        prompt = json.loads(body).get("prompt", "") if body else ""
        if "fails" in prompt:
            return httpx.Response(400, text="bad")  # non-retryable
        return _success_response()

    _install(monkeypatch, handler)
    monkeypatch.setattr(sys, "argv", [
        "g", "--batch-file", str(bf), "-o", str(out), "-n", "b",
        "--no-preview", "--json", "--concurrency", "1",
    ])
    assert _run_main() == 0
    arr = json.loads(capsys.readouterr().out.strip())
    assert isinstance(arr, list) and len(arr) == 3
    by_index = {d["index"]: d for d in arr}
    assert by_index[1]["ok"] is True and by_index[1]["path"].endswith("b_001.png")
    assert by_index[2]["ok"] is False and by_index[2]["error"]
    assert by_index[3]["ok"] is True


def test_json_dag_array(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    _install(monkeypatch, lambda req: _success_response())
    spec = {"tasks": [{"id": "A", "prompt": "p"}]}
    sp = _write_spec(tmp_path, spec)
    monkeypatch.setattr(sys, "argv", ["g", "--dag-file", sp, "-o", str(out), "--json"])
    assert _run_main() == 0
    arr = json.loads(capsys.readouterr().out.strip())
    assert isinstance(arr, list) and len(arr) == 1
    assert arr[0]["id"] == "A"
    assert arr[0]["ok"] is True
    assert arr[0]["path"].endswith("A.png")


def test_dry_run_json_emits_plan_to_stdout(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)  # dry-run needs no key even with --json

    def handler(req):
        raise AssertionError("no network under --dry-run")

    _install(monkeypatch, handler)
    monkeypatch.setattr(sys, "argv", ["g", "cat", "--dry-run", "--json", "-r", "1:1"])
    assert _run_main() == 0
    cap = capsys.readouterr()
    obj = json.loads(cap.out.strip())            # machine-readable plan on stdout
    assert obj["mode"] == "single"
    assert obj["provider"] == "openai"
    assert obj["ratio"] == "1:1"
    assert obj["images"] == 1
    assert obj["estimated_cost_cny"] is None  # openai has no fixed per-image price
    assert cap.out.strip().startswith("{")       # clean JSON, banner stays on stderr


# --- (4) sidecars are SKIPPED for failed/skipped jobs -------------------------

def test_batch_failed_job_writes_no_sidecar(tmp_path, monkeypatch):
    bf = _write_batch(tmp_path, ["p one", "p two (fails)", "p three"])
    out = tmp_path / "out"

    def handler(req):
        body = req.content.decode("utf-8") if req.content else ""
        prompt = json.loads(body).get("prompt", "") if body else ""
        if "fails" in prompt:
            return httpx.Response(400, text="bad")  # non-retryable
        return _success_response()

    _install(monkeypatch, handler)
    monkeypatch.setattr(sys, "argv", [
        "g", "--batch-file", str(bf), "-o", str(out), "-n", "b",
        "--no-preview", "--concurrency", "1",
    ])
    assert _run_main() == 0
    # failed job (index 2) produces NEITHER a .png NOR a .json sidecar
    assert not (out / "b_002.png").exists()
    assert not (out / "b_002.json").exists()
    # succeeded siblings get both
    assert (out / "b_001.png").exists() and (out / "b_001.json").exists()
    assert (out / "b_003.png").exists() and (out / "b_003.json").exists()


def test_dag_failed_task_writes_no_sidecar(tmp_path, monkeypatch):
    out = tmp_path / "out"

    def handler(req):
        body = req.content.decode("utf-8") if req.content else ""
        prompt = json.loads(body).get("prompt", "") if body else ""
        if "fail" in prompt:
            return httpx.Response(400, text="bad")  # non-retryable
        return _success_response()

    _install(monkeypatch, handler)
    # two independent tasks: one succeeds, one fails (skip policy leaves siblings alone)
    spec = {"tasks": [{"id": "good", "prompt": "a nice scene"},
                      {"id": "bad", "prompt": "will fail"}]}
    sp = _write_spec(tmp_path, spec)
    monkeypatch.setattr(sys, "argv", ["g", "--dag-file", sp, "-o", str(out)])
    assert _run_main() != 0  # partial completion -> nonzero
    # failed task: no image and no sidecar
    assert not (out / "bad.png").exists()
    assert not (out / "bad.json").exists()
    # succeeded task: image + sidecar
    assert (out / "good.png").exists() and (out / "good.json").exists()


# --- (5) --json failure arrays ------------------------------------------------

def test_json_dag_array_with_failure(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"

    def handler(req):
        body = req.content.decode("utf-8") if req.content else ""
        prompt = json.loads(body).get("prompt", "") if body else ""
        if "fail" in prompt:
            return httpx.Response(400, text="bad")  # non-retryable
        return _success_response()

    _install(monkeypatch, handler)
    spec = {"tasks": [{"id": "good", "prompt": "a nice scene"},
                      {"id": "bad", "prompt": "will fail"}]}
    sp = _write_spec(tmp_path, spec)
    monkeypatch.setattr(sys, "argv", ["g", "--dag-file", sp, "-o", str(out), "--json"])
    assert _run_main() != 0
    cap = capsys.readouterr()
    arr = json.loads(cap.out.strip())            # pure JSON, no banner leak on stdout
    assert cap.out.strip().startswith("[")
    by_id = {d["id"]: d for d in arr}
    assert by_id["good"]["ok"] is True
    assert by_id["bad"]["ok"] is False and by_id["bad"]["error"]


def test_json_batch_all_fail_still_emits_array(tmp_path, monkeypatch, capsys):
    bf = _write_batch(tmp_path, ["one", "two"])
    out = tmp_path / "out"
    _install(monkeypatch, lambda req: httpx.Response(400, text="nope"))  # every job fails
    monkeypatch.setattr(sys, "argv", [
        "g", "--batch-file", str(bf), "-o", str(out), "-n", "b",
        "--no-preview", "--json", "--concurrency", "1",
    ])
    assert _run_main() != 0  # all failed -> nonzero
    arr = json.loads(capsys.readouterr().out.strip())  # array still emitted before exit
    assert isinstance(arr, list) and len(arr) == 2
    assert all(d["ok"] is False and d["error"] for d in arr)


# --- (6) background sidecar field ---------------------------------------------

def test_metadata_background_transparent(tmp_path, monkeypatch):
    out = tmp_path / "out"
    # 302ai's gpt-image-2 allows --background; give it a key.
    monkeypatch.setenv("AI302_API_KEY", "test-key-not-real")
    _install(monkeypatch, lambda req: _success_response())
    monkeypatch.setattr(sys, "argv", [
        "g", "a logo", "-p", "302ai", "--background", "transparent",
        "-o", str(out), "-n", "pic", "--no-preview",
    ])
    assert _run_main() == 0
    meta = json.loads((out / "pic.json").read_text(encoding="utf-8"))
    assert meta["background"] == "transparent"
    assert meta["provider"] == "302ai"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
