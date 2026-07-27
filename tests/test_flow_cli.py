from __future__ import annotations

import base64
import json
import sys

import httpx
import pytest

from generate_image import cli

_PNG_1 = b"first-image"
_PNG_2 = b"second-image"


def _spec():
    return {
        "version": 1,
        "entry": "generate",
        "limits": {"max_steps": 8, "max_billed_calls": 4},
        "state": {"prompt": "draft poster"},
        "services": {
            "judge": {
                "provider": "openai",
                "model": "vision-test",
            },
        },
        "nodes": {
            "generate": {
                "type": "image.generate", "provider": "openai",
                "ratio": "1:1", "prompt": "${state.prompt}",
            },
            "review": {
                "type": "image.review", "service": "judge", "image": "@generate",
                "prompt": "${state.prompt}", "criteria": ["clear subject"],
                "threshold": 0.8,
            },
            "refine": {
                "type": "prompt.refine", "prompt": "${nodes.review.revised_prompt}",
            },
        },
        "edges": [
            {"from": "generate", "route": "success", "to": "review"},
            {"from": "generate", "route": "error", "to": "failed"},
            {"from": "review", "route": "accepted", "to": "done"},
            {"from": "review", "route": "rejected", "to": "refine"},
            {"from": "review", "route": "error", "to": "failed"},
            {"from": "refine", "route": "success", "to": "generate"},
        ],
    }


def _run_main() -> int:
    try:
        cli.main()
        return 0
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "image-key")


def test_flow_cli_rejects_refines_then_accepts(tmp_path, monkeypatch, capsys):
    generations = 0
    reviews = 0
    review_bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal generations, reviews
        if request.url.path == "/v1/images/generations":
            generations += 1
            image = _PNG_1 if generations == 1 else _PNG_2
            return httpx.Response(200, json={
                "data": [{"b64_json": base64.b64encode(image).decode("ascii")}],
            })
        if request.url.path == "/v1/chat/completions":
            assert request.url.host == "api.openai.com"
            assert request.headers["authorization"] == "Bearer image-key"
            reviews += 1
            body = json.loads(request.content)
            review_bodies.append(body)
            verdict = {
                "accepted": reviews == 2,
                "score": 0.95 if reviews == 2 else 0.4,
                "feedback": "good" if reviews == 2 else "make the subject larger",
                "revised_prompt": "poster with a large centered subject",
            }
            return httpx.Response(200, json={
                "choices": [{"message": {"content": json.dumps(verdict)}}],
            })
        raise AssertionError(f"unexpected request {request.url}")

    monkeypatch.setattr(cli, "_TEST_TRANSPORT", httpx.MockTransport(handler))
    reference = tmp_path / "target.png"
    reference.write_bytes(b"target-reference")
    data = _spec()
    data["nodes"]["review"]["reference"] = str(reference)
    spec_path = tmp_path / "flow.yaml"
    import yaml
    spec_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "generate-image", "--flow-file", str(spec_path), "-o", str(out),
        "-n", "acceptance", "--json",
    ])

    assert _run_main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True and payload["status"] == "succeeded"
    assert payload["steps"] == 5 and payload["billed_calls"] == 4
    assert payload["state"]["prompt"] == "poster with a large centered subject"
    run = out / "runs/acceptance"
    assert (run / "generate/attempt-001/image.png").read_bytes() == _PNG_1
    assert (run / "generate/attempt-002/image.png").read_bytes() == _PNG_2
    assert json.loads((run / "review/attempt-002/verdict.json").read_text())["accepted"] is True
    assert (run / "review/attempt-001/reference.png").read_bytes() == b"target-reference"
    assert generations == 2 and reviews == 2
    review_content = review_bodies[0]["messages"][0]["content"]
    assert review_content[1]["text"] == "TARGET REFERENCE IMAGE:"
    assert base64.b64decode(review_content[2]["image_url"]["url"].split(",", 1)[1]) \
        == b"target-reference"
    assert review_content[3]["text"] == "CANDIDATE GENERATED IMAGE:"
    first_image_url = review_content[4]["image_url"]["url"]
    assert first_image_url.startswith("data:image/png;base64,")
    assert base64.b64decode(first_image_url.split(",", 1)[1]) == _PNG_1


def test_describe_node_sniffs_jpeg_and_sets_initial_prompt(tmp_path, monkeypatch, capsys):
    source = tmp_path / "misnamed.png"
    source.write_bytes(b"\xff\xd8jpeg-content")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps({
                "prompt": "cinematic city portrait",
            })}}],
        })

    monkeypatch.setattr(cli, "_TEST_TRANSPORT", httpx.MockTransport(handler))
    spec = {
        "entry": "describe",
        "limits": {"max_billed_calls": 1},
        "services": {"judge": {"provider": "openai", "model": "vision-test"}},
        "nodes": {"describe": {
            "type": "image.describe", "service": "judge", "image": str(source),
        }},
        "edges": [
            {"from": "describe", "route": "success", "to": "done"},
            {"from": "describe", "route": "error", "to": "failed"},
        ],
    }
    spec_path = tmp_path / "describe.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "generate-image", "--flow-file", str(spec_path), "-o", str(tmp_path / "out"),
        "-n", "describe", "--json",
    ])
    assert _run_main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["state"]["prompt"] == "cinematic city portrait"
    assert (tmp_path / "out/runs/describe/describe/attempt-001/reference.jpg").read_bytes() \
        == b"\xff\xd8jpeg-content"
    image_url = seen["messages"][0]["content"][1]["image_url"]["url"]
    assert image_url.startswith("data:image/jpeg;base64,")


def test_flow_dry_run_needs_no_keys_or_network(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(cli, "_TEST_TRANSPORT", httpx.MockTransport(
        lambda request: (_ for _ in ()).throw(AssertionError("no network in dry-run"))
    ))
    spec_path = tmp_path / "flow.json"
    spec_path.write_text(json.dumps(_spec()), encoding="utf-8")
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "generate-image", "--flow-file", str(spec_path), "-o", str(out), "--dry-run",
    ])
    assert _run_main() == 0
    assert "max_billed_calls=4" in capsys.readouterr().err
    assert not out.exists()


def test_flow_modes_are_mutually_exclusive(tmp_path, monkeypatch, capsys):
    spec_path = tmp_path / "flow.json"
    spec_path.write_text(json.dumps(_spec()), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "generate-image", "--flow-file", str(spec_path), "--batch-file", "prompts.txt",
    ])
    assert _run_main() != 0


def test_flow_dry_run_performs_cli_level_validation(tmp_path, monkeypatch, capsys):
    data = _spec()
    data["nodes"]["review"]["service"] = "missing"
    spec_path = tmp_path / "flow.json"
    spec_path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "generate-image", "--flow-file", str(spec_path), "--dry-run",
    ])
    assert _run_main() != 0


def test_flow_run_name_cannot_escape_output_directory(tmp_path, monkeypatch):
    spec_path = tmp_path / "flow.json"
    spec_path.write_text(json.dumps(_spec()), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "generate-image", "--flow-file", str(spec_path), "-o", str(tmp_path / "out"),
        "-n", "../escape",
    ])
    assert _run_main() != 0
    assert not (tmp_path / "escape").exists()
