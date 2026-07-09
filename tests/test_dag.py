"""Tests for the DAG engine + spec loader (dag.py).

The engine is exercised with an injected fake `execute` (records call order and
the resolved refs it receives, can be told to fail specific ids) and a tmp
out_dir — no network, no providers.
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from generate_image import dag
from generate_image.dag import (
    Task,
    TaskResult,
    DagError,
    run_dag,
    parse_dag,
    load_dag,
    build_graph,
    SUCCESS,
    FAILED,
    SKIPPED,
    ON_FAILURE_SKIP,
    ON_FAILURE_FAIL_FAST,
)


class _Recorder:
    """Thread-safe fake execute: records (id, refs) call order; fails given ids."""

    def __init__(self, fail_ids: set[str] | None = None):
        self.fail_ids = fail_ids or set()
        self.calls: list[tuple[str, list[str]]] = []
        self.lock = threading.Lock()

    def __call__(self, task: Task, refs: list[str]) -> bytes:
        with self.lock:
            self.calls.append((task.id, list(refs)))
        if task.id in self.fail_ids:
            raise RuntimeError(f"boom-{task.id}")
        return f"img-{task.id}".encode()

    @property
    def order(self) -> list[str]:
        with self.lock:
            return [c[0] for c in self.calls]

    def refs_for(self, tid: str) -> list[str]:
        with self.lock:
            return next(r for (i, r) in self.calls if i == tid)


# --- graph validation ---------------------------------------------------------

def test_duplicate_id_raises():
    tasks = [Task("A", "p"), Task("A", "q")]
    with pytest.raises(DagError):
        build_graph(tasks)


def test_unknown_dependency_raises():
    with pytest.raises(DagError):
        build_graph([Task("B", "p", depends_on=("A",))])


def test_self_loop_raises():
    with pytest.raises(DagError):
        build_graph([Task("A", "p", depends_on=("A",))])


def test_cycle_detected(tmp_path):
    tasks = [Task("A", "p", depends_on=("B",)), Task("B", "q", depends_on=("A",))]
    with pytest.raises(DagError) as ei:
        run_dag(tasks, _Recorder(), out_dir=tmp_path)
    assert "cycle" in str(ei.value).lower()


# --- serial + @ref wiring -----------------------------------------------------

def test_linear_chain_order_and_ref_resolution(tmp_path):
    # A -> B -> C, B and C pull the upstream output via @ref
    tasks = [
        Task("A", "first"),
        Task("B", "second", refs=("@A",)),
        Task("C", "third", refs=("@B",)),
    ]
    rec = _Recorder()
    results = run_dag(tasks, rec, out_dir=tmp_path, concurrency=4)

    assert [r.status for r in results.values()] == [SUCCESS, SUCCESS, SUCCESS]
    # topological order: A before B before C
    assert rec.order == ["A", "B", "C"]
    # B received A's written output path; C received B's
    assert rec.refs_for("B") == [str(tmp_path / "A.png")]
    assert rec.refs_for("C") == [str(tmp_path / "B.png")]
    # outputs written
    assert (tmp_path / "A.png").read_bytes() == b"img-A"
    assert (tmp_path / "C.png").read_bytes() == b"img-C"


def test_static_refs_are_passed_through(tmp_path):
    tasks = [Task("A", "p", refs=("/tmp/literal.png", "https://x.test/y.png"))]
    rec = _Recorder()
    run_dag(tasks, rec, out_dir=tmp_path)
    assert rec.refs_for("A") == ["/tmp/literal.png", "https://x.test/y.png"]


# --- serial-then-parallel + independent ---------------------------------------

def test_serial_then_parallel_A_before_BCD(tmp_path):
    tasks = [
        Task("A", "root"),
        Task("B", "b", depends_on=("A",)),
        Task("C", "c", depends_on=("A",)),
        Task("D", "d", depends_on=("A",)),
    ]
    rec = _Recorder()
    results = run_dag(tasks, rec, out_dir=tmp_path, concurrency=4)

    assert all(r.status == SUCCESS for r in results.values())
    assert rec.order[0] == "A"                      # A runs first
    assert set(rec.order[1:]) == {"B", "C", "D"}    # then B/C/D fan out


def test_independent_nodes_all_run_in_parallel(tmp_path):
    tasks = [Task(x, x) for x in ("A", "B", "C", "D")]

    def slow_execute(task, refs):
        time.sleep(0.15)
        return b"x"

    start = time.monotonic()
    results = run_dag(tasks, slow_execute, out_dir=tmp_path, concurrency=4)
    elapsed = time.monotonic() - start

    assert all(r.status == SUCCESS for r in results.values())
    # 4 x 0.15s in parallel should be well under the 0.6s serial time
    assert elapsed < 0.45, f"expected parallel execution, took {elapsed:.2f}s"


# --- arbitrary DAG: diamond + multi-parent join -------------------------------

def test_diamond_multi_parent_join(tmp_path):
    # A -> {B, C} -> D ; D joins BOTH branches by compositing @B + @C.
    tasks = [
        Task("A", "root"),
        Task("B", "left", refs=("@A",)),
        Task("C", "right", refs=("@A",)),
        Task("D", "join", refs=("@B", "@C")),
    ]
    rec = _Recorder()
    results = run_dag(tasks, rec, out_dir=tmp_path, concurrency=4)

    assert all(r.status == SUCCESS for r in results.values())
    order = rec.order
    # topological guarantees: A first; B and C before D; D last
    assert order[0] == "A"
    assert order.index("B") < order.index("D")
    assert order.index("C") < order.index("D")
    assert order[-1] == "D"
    # D is a real join: it received BOTH upstream outputs as reference images
    assert rec.refs_for("D") == [str(tmp_path / "B.png"), str(tmp_path / "C.png")]
    # D depends on both B and C (implicit edges from @B, @C)
    assert build_graph(tasks)["D"] == {"B", "C"}


def test_multi_parent_via_depends_on_and_refs_mixed(tmp_path):
    # A node can mix explicit depends_on with @ref parents (union of both).
    tasks = [
        Task("A", "a"),
        Task("B", "b"),
        Task("C", "c", depends_on=("A",), refs=("@B",)),
    ]
    assert build_graph(tasks)["C"] == {"A", "B"}
    rec = _Recorder()
    results = run_dag(tasks, rec, out_dir=tmp_path, concurrency=4)
    assert all(r.status == SUCCESS for r in results.values())
    assert rec.order.index("A") < rec.order.index("C")
    assert rec.order.index("B") < rec.order.index("C")
    assert rec.refs_for("C") == [str(tmp_path / "B.png")]  # only @B is a ref; A is a pure dep


# --- failure propagation ------------------------------------------------------

def test_skip_policy_skips_only_descendants(tmp_path):
    # A fails; B depends on A (skip); C is independent (still runs)
    tasks = [
        Task("A", "a"),
        Task("B", "b", depends_on=("A",)),
        Task("C", "c"),
    ]
    rec = _Recorder(fail_ids={"A"})
    results = run_dag(tasks, rec, out_dir=tmp_path, on_failure=ON_FAILURE_SKIP)

    assert results["A"].status == FAILED
    assert results["B"].status == SKIPPED
    assert results["C"].status == SUCCESS
    assert "B" not in rec.order  # skipped node never calls execute (no billed request)


def test_skip_propagates_transitively(tmp_path):
    # A fails -> B (dep A) skipped -> C (dep B) skipped
    tasks = [
        Task("A", "a"),
        Task("B", "b", depends_on=("A",)),
        Task("C", "c", depends_on=("B",)),
    ]
    rec = _Recorder(fail_ids={"A"})
    results = run_dag(tasks, rec, out_dir=tmp_path, on_failure=ON_FAILURE_SKIP)
    assert results["A"].status == FAILED
    assert results["B"].status == SKIPPED
    assert results["C"].status == SKIPPED


def test_fail_fast_vs_skip_on_independent_nodes(tmp_path):
    tasks = [Task("A", "a"), Task("B", "b"), Task("C", "c")]

    # skip policy: independent B, C still run to completion
    rec_skip = _Recorder(fail_ids={"A"})
    res_skip = run_dag(tasks, rec_skip, out_dir=tmp_path, concurrency=1,
                       on_failure=ON_FAILURE_SKIP)
    assert sum(1 for r in res_skip.values() if r.status == SKIPPED) == 0
    assert res_skip["A"].status == FAILED

    # fail-fast: once A fails, at least one not-yet-started node is skipped
    rec_ff = _Recorder(fail_ids={"A"})
    res_ff = run_dag(tasks, rec_ff, out_dir=tmp_path, concurrency=1,
                     on_failure=ON_FAILURE_FAIL_FAST)
    assert res_ff["A"].status == FAILED
    assert sum(1 for r in res_ff.values() if r.status == SKIPPED) >= 1


# --- spec loading -------------------------------------------------------------

_SPEC = {
    "tasks": [
        {"id": "A", "prompt": "root"},
        {"id": "B", "prompt": "leaf", "refs": ["@A"], "provider": "openai", "ratio": "9:16"},
    ]
}


def test_parse_dag_builds_tasks_and_implicit_edge():
    tasks = parse_dag(_SPEC)
    assert [t.id for t in tasks] == ["A", "B"]
    b = next(t for t in tasks if t.id == "B")
    assert b.refs == ("@A",) and b.provider == "openai" and b.ratio == "9:16"
    # @A implies an edge A -> B
    assert build_graph(tasks)["B"] == {"A"}


def test_parse_dag_missing_prompt_raises():
    with pytest.raises(DagError):
        parse_dag({"tasks": [{"id": "A"}]})


def test_parse_dag_duplicate_id_raises():
    with pytest.raises(DagError):
        parse_dag({"tasks": [{"id": "A", "prompt": "p"}, {"id": "A", "prompt": "q"}]})


def test_parse_dag_cycle_raises():
    spec = {"tasks": [
        {"id": "A", "prompt": "p", "depends_on": ["B"]},
        {"id": "B", "prompt": "q", "depends_on": ["A"]},
    ]}
    with pytest.raises(DagError):
        parse_dag(spec)


def test_load_dag_json(tmp_path):
    f = tmp_path / "spec.json"
    f.write_text(json.dumps(_SPEC), encoding="utf-8")
    tasks = load_dag(str(f))
    assert [t.id for t in tasks] == ["A", "B"]


def test_load_dag_yaml(tmp_path):
    yaml = pytest.importorskip("yaml")
    f = tmp_path / "spec.yaml"
    f.write_text(yaml.safe_dump(_SPEC), encoding="utf-8")
    tasks = load_dag(str(f))
    assert [t.id for t in tasks] == ["A", "B"]


def test_load_dag_unknown_extension_raises(tmp_path):
    f = tmp_path / "spec.txt"
    f.write_text("nope", encoding="utf-8")
    with pytest.raises(DagError):
        load_dag(str(f))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
