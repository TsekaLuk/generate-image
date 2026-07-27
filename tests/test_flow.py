from __future__ import annotations

import json

import pytest

from generate_image.flow import (
    FlowError,
    NodeOutcome,
    parse_flow,
    render_template,
    run_flow,
)


def _loop_spec(**limit_overrides):
    limits = {"max_steps": 10, "max_billed_calls": 6, **limit_overrides}
    return {
        "version": 1,
        "entry": "generate",
        "limits": limits,
        "state": {"prompt": "draft"},
        "nodes": {
            "generate": {"type": "image.generate", "prompt": "${state.prompt}"},
            "review": {"type": "image.review", "image": "@generate"},
            "refine": {"type": "prompt.refine", "prompt": "${nodes.review.revised_prompt}"},
        },
        "edges": [
            {"from": "generate", "route": "success", "to": "review"},
            {"from": "generate", "route": "error", "to": "failed"},
            {"from": "review", "route": "accepted", "to": "done"},
            {"from": "review", "route": "rejected", "to": "refine"},
            {"from": "refine", "route": "success", "to": "generate"},
        ],
    }


def test_cycle_requires_explicit_max_steps():
    data = _loop_spec()
    del data["limits"]["max_steps"]
    with pytest.raises(FlowError, match="cyclic flows"):
        parse_flow(data)


def test_duplicate_route_is_rejected():
    data = _loop_spec()
    data["edges"].append({"from": "review", "route": "accepted", "to": "failed"})
    with pytest.raises(FlowError, match="duplicate route"):
        parse_flow(data)


def test_rejected_image_refines_then_accepts_with_immutable_attempts(tmp_path):
    calls = {"generate": 0, "review": 0}

    def generate(node, context, attempt_dir):
        calls["generate"] += 1
        image = attempt_dir / "image.png"
        image.write_bytes(f"image-{calls['generate']}".encode())
        return NodeOutcome("success", artifacts=[str(image)],
                           data={"prompt": render_template(node.config["prompt"], context)},
                           billed_calls=1)

    def review(node, context, attempt_dir):
        calls["review"] += 1
        accepted = calls["review"] == 2
        return NodeOutcome(
            "accepted" if accepted else "rejected",
            data={"accepted": accepted, "score": 0.9 if accepted else 0.4,
                  "feedback": "fix composition", "revised_prompt": "revised"},
            billed_calls=1,
        )

    def refine(node, context, attempt_dir):
        prompt = render_template(node.config["prompt"], context)
        return NodeOutcome("success", state_patch={"prompt": prompt}, data={"prompt": prompt})

    result = run_flow(
        parse_flow(_loop_spec()),
        {"image.generate": generate, "image.review": review, "prompt.refine": refine},
        run_dir=tmp_path / "run",
        billed_calls_by_type={"image.generate": 1, "image.review": 1},
    )

    assert result.status == "succeeded"
    assert result.terminal == "done"
    assert result.state["prompt"] == "revised"
    assert result.billed_calls == 4
    assert [event["node"] for event in result.history] == [
        "generate", "review", "refine", "generate", "review",
    ]
    assert (tmp_path / "run/generate/attempt-001/image.png").read_bytes() == b"image-1"
    assert (tmp_path / "run/generate/attempt-002/image.png").read_bytes() == b"image-2"
    journal = (tmp_path / "run/journal.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(journal) == 5 and all(json.loads(line)["step"] for line in journal)
    persisted = json.loads((tmp_path / "run/state.json").read_text(encoding="utf-8"))
    assert persisted["status"] == "succeeded" and persisted["billed_calls"] == 4


def test_billed_budget_stops_before_next_handler_call(tmp_path):
    calls = 0

    def always_reject(node, context, attempt_dir):
        nonlocal calls
        calls += 1
        route = "success" if node.type == "image.generate" else "rejected"
        data = {"revised_prompt": "again"} if node.type == "image.review" else {}
        return NodeOutcome(route, data=data, artifacts=["x"] if node.type == "image.generate" else [],
                           billed_calls=1)

    def refine(node, context, attempt_dir):
        return NodeOutcome("success", state_patch={"prompt": "again"})

    spec = parse_flow(_loop_spec(max_billed_calls=2))
    result = run_flow(
        spec,
        {"image.generate": always_reject, "image.review": always_reject,
         "prompt.refine": refine},
        run_dir=tmp_path / "run",
        billed_calls_by_type={"image.generate": 1, "image.review": 1},
    )
    assert result.status == "limit_exceeded"
    assert result.billed_calls == 2
    assert calls == 2


def test_handler_exception_follows_error_route(tmp_path):
    spec = parse_flow({
        "entry": "a",
        "nodes": {"a": {"type": "boom"}},
        "edges": [{"from": "a", "route": "error", "to": "done"}],
    })

    def boom(node, context, attempt_dir):
        raise RuntimeError("expected")

    result = run_flow(spec, {"boom": boom}, run_dir=tmp_path / "run")
    assert result.status == "succeeded"
    assert result.history[0]["status"] == "error"
    assert result.history[0]["error"] == "expected"


def test_missing_route_fails_closed(tmp_path):
    spec = parse_flow({
        "entry": "a",
        "nodes": {"a": {"type": "route"}},
        "edges": [{"from": "a", "route": "yes", "to": "done"}],
    })
    result = run_flow(
        spec, {"route": lambda node, context, path: NodeOutcome("no")},
        run_dir=tmp_path / "run",
    )
    assert result.status == "failed"
    assert "no 'no' route" in result.error
