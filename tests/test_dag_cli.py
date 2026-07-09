"""End-to-end --dag-file through generate.main(), HTTP mocked via _TEST_TRANSPORT.

Proves the DAG wiring: an A -> B chain where B (refs: ["@A"]) is an img2img edit
whose request actually carries A's produced image bytes.
"""

from __future__ import annotations

import base64
import json
import sys

import httpx
import pytest

from generate_image import cli as generate

_PNG_A = b"AAAA-image-from-task-A"
_PNG_B = b"BBBB-image-from-task-B"


@pytest.fixture(autouse=True)
def _default_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")


def _install(monkeypatch, handler):
    monkeypatch.setattr(generate, "_TEST_TRANSPORT", httpx.MockTransport(handler))


def _write_spec(tmp_path, spec) -> str:
    f = tmp_path / "dag.json"
    f.write_text(json.dumps(spec), encoding="utf-8")
    return str(f)


def test_dag_chain_wires_A_output_into_B(tmp_path, monkeypatch):
    out_dir = tmp_path / "out"
    edit_bodies = []

    def handler(req):
        path = req.url.path
        if path == "/v1/images/generations":
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(_PNG_A).decode()}]})
        if path == "/v1/images/edits":
            edit_bodies.append(req.content)
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(_PNG_B).decode()}]})
        raise AssertionError(f"unexpected path {path}")

    _install(monkeypatch, handler)
    spec = {"tasks": [
        {"id": "A", "prompt": "root scene"},
        {"id": "B", "prompt": "restyle using A", "refs": ["@A"]},
    ]}
    spec_path = _write_spec(tmp_path, spec)
    monkeypatch.setattr(sys, "argv", ["generate.py", "--dag-file", spec_path, "-o", str(out_dir)])

    try:
        generate.main()
    except SystemExit as e:
        assert e.code in (0, None), f"unexpected non-zero exit: {e.code}"

    # both outputs written under their task ids
    assert (out_dir / "A.png").read_bytes() == _PNG_A
    assert (out_dir / "B.png").read_bytes() == _PNG_B
    # B's edit request carried A's produced image (the @A wiring)
    assert len(edit_bodies) == 1
    assert _PNG_A in edit_bodies[0]


def test_dag_skip_policy_skips_descendants_of_failure(tmp_path, monkeypatch):
    out_dir = tmp_path / "out"

    def handler(req):
        if req.url.path == "/v1/images/generations":
            return httpx.Response(400, text="bad prompt")  # A fails (non-retryable)
        raise AssertionError("B must be skipped, never reaching the edit endpoint")

    _install(monkeypatch, handler)
    spec = {"tasks": [
        {"id": "A", "prompt": "will fail"},
        {"id": "B", "prompt": "depends on A", "refs": ["@A"]},
    ]}
    spec_path = _write_spec(tmp_path, spec)
    monkeypatch.setattr(sys, "argv", [
        "generate.py", "--dag-file", spec_path, "-o", str(out_dir), "--on-failure", "skip",
    ])

    with pytest.raises(SystemExit) as ei:
        generate.main()
    assert ei.value.code not in (0, None)  # nothing produced -> nonzero
    assert not (out_dir / "A.png").exists()
    assert not (out_dir / "B.png").exists()


def test_dag_spent_counts_only_tasks_that_ran(tmp_path, monkeypatch, capsys):
    """A fails, B depends on A (skipped), C is independent (runs). The '→ spent:'
    summary must count only the tasks that actually issued a billed call (A + C),
    NOT the skipped descendant B. Pinned to 302ai, which has a fixed per-image
    price, so the exact ¥ amount can be asserted."""
    monkeypatch.setenv("AI302_API_KEY", "test-key")
    out_dir = tmp_path / "out"

    def handler(req):
        body = req.content.decode("utf-8") if req.content else ""
        prompt = json.loads(body).get("prompt", "") if body else ""
        if "fail" in prompt:
            return httpx.Response(400, text="bad")  # A fails (non-retryable)
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(_PNG_A).decode()}]})

    _install(monkeypatch, handler)
    spec = {"tasks": [
        {"id": "A", "prompt": "will fail", "provider": "302ai"},
        {"id": "B", "prompt": "styled from A", "refs": ["@A"], "provider": "302ai"},  # skipped
        {"id": "C", "prompt": "independent scene", "provider": "302ai"},              # runs
    ]}
    spec_path = _write_spec(tmp_path, spec)
    monkeypatch.setattr(sys, "argv", [
        "generate.py", "--dag-file", spec_path, "-o", str(out_dir), "--on-failure", "skip",
    ])

    with pytest.raises(SystemExit) as ei:
        generate.main()
    assert ei.value.code not in (0, None)  # partial completion -> nonzero
    err = capsys.readouterr().err
    # A (failed, billed) + C (ok, billed) = 2 billed calls; B skipped -> never billed.
    assert "→ spent:" in err and "¥0.20" in err and "2 billed call" in err


def test_dag_unknown_provider_fails_fast_before_network(tmp_path, monkeypatch):
    out_dir = tmp_path / "out"

    def handler(req):
        raise AssertionError("must not hit network on an invalid spec")

    _install(monkeypatch, handler)
    spec = {"tasks": [{"id": "A", "prompt": "p", "provider": "not-a-provider"}]}
    spec_path = _write_spec(tmp_path, spec)
    monkeypatch.setattr(sys, "argv", ["generate.py", "--dag-file", spec_path, "-o", str(out_dir)])

    with pytest.raises(SystemExit) as ei:
        generate.main()
    assert "unknown provider" in str(ei.value)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
