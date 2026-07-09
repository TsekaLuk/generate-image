"""Image-generation DAG scheduler.

Runs image tasks over an ARBITRARY directed acyclic graph at maximum
parallelism, using the stdlib `graphlib.TopologicalSorter` — the native
primitive designed to "process nodes as they become ready". Any acyclic
dependency shape works; the common ones are just special cases:

  * serial              B after A
  * independent         no edges → everything runs in parallel
  * serial-then-parallel   A, then B/C/D fan out from A
  * diamond             A → {B, C} → D  (D joins both branches)
  * multi-parent join   D depends on B AND C, compositing @B + @C into one image
  * arbitrary mesh      any mix of the above

A node may have ANY number of parents (via multiple depends_on and/or multiple
"@id" refs) and ANY number of children. Dependencies are the UNION of:
  * explicit   Task.depends_on
  * implicit   each ref "@other_id" ("use other_id's output image as input") adds
               an edge other_id -> this task. Multiple @refs on one node = a join
               that feeds several upstream outputs into one (multi-image) call.

This module is pure orchestration — topological scheduling, @ref resolution to
the upstream's written output path, failure/skip propagation, result collection.
The per-node work (provider selection + reliability + HTTP) is injected as
`execute(task, resolved_refs) -> bytes`, so the engine is fully testable offline.
"""

from __future__ import annotations

import graphlib
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REF_PREFIX = "@"

# TaskResult.status values
SUCCESS = "success"
FAILED = "failed"
SKIPPED = "skipped"

# on_failure policies
ON_FAILURE_SKIP = "skip"
ON_FAILURE_FAIL_FAST = "fail-fast"
ON_FAILURE_CHOICES = (ON_FAILURE_SKIP, ON_FAILURE_FAIL_FAST)


@dataclass(frozen=True)
class Task:
    """One image-generation node in the DAG."""
    id: str
    prompt: str
    provider: str | None = None
    model: str | None = None
    ratio: str | None = None
    refs: tuple[str, ...] = ()          # static path/URL, or "@id" (upstream output)
    background: str | None = None
    depends_on: tuple[str, ...] = ()
    name: str | None = None             # output filename stem (defaults to id)


@dataclass
class TaskResult:
    status: str                          # SUCCESS | FAILED | SKIPPED
    output_path: str | None = None
    error: str | None = None


class DagError(Exception):
    """Malformed DAG: unknown/duplicate id, self-loop, cycle, or bad ref."""


def _ref_dep(ref: str) -> str | None:
    """'@id' -> 'id'; anything else -> None (a literal path/URL)."""
    if ref.startswith(REF_PREFIX):
        return ref[len(REF_PREFIX):]
    return None


def build_graph(tasks: list[Task]) -> dict[str, set[str]]:
    """Map each task id to its predecessor ids (depends_on ∪ @ref-implied).

    Validates: unique ids, deps point at real tasks, no self-loop. (Cycle
    detection happens at prepare() time via graphlib.)
    """
    ids = [t.id for t in tasks]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise DagError(f"duplicate task id(s): {dupes}")
    idset = set(ids)
    graph: dict[str, set[str]] = {}
    for t in tasks:
        deps: set[str] = set(t.depends_on)
        for r in t.refs:
            d = _ref_dep(r)
            if d is not None:
                deps.add(d)
        unknown = deps - idset
        if unknown:
            raise DagError(f"task {t.id!r} depends on unknown task(s): {sorted(unknown)}")
        if t.id in deps:
            raise DagError(f"task {t.id!r} depends on itself")
        graph[t.id] = deps
    return graph


def _check_acyclic(graph: dict[str, set[str]]) -> None:
    try:
        graphlib.TopologicalSorter(graph).prepare()
    except graphlib.CycleError as e:
        cycle = e.args[1] if len(e.args) > 1 else ["?"]
        raise DagError(f"DAG has a cycle: {' -> '.join(map(str, cycle))}") from e


def resolve_refs(task: Task, results: dict[str, TaskResult]) -> list[str]:
    """Replace each '@id' ref with that upstream's written output path; keep literals."""
    out: list[str] = []
    for r in task.refs:
        d = _ref_dep(r)
        if d is None:
            out.append(r)
            continue
        res = results.get(d)
        if res is None or res.output_path is None:
            raise DagError(f"task {task.id!r} ref {r!r}: upstream {d!r} produced no output")
        out.append(res.output_path)
    return out


def run_dag(tasks: list[Task],
            execute: Callable[[Task, list[str]], bytes],
            *,
            out_dir: Path,
            concurrency: int = 4,
            on_failure: str = ON_FAILURE_SKIP,
            write: Callable[[Path, bytes], None] | None = None) -> dict[str, TaskResult]:
    """Execute the task DAG at maximum parallelism. Returns id -> TaskResult.

    `execute(task, resolved_refs)` runs ONE node and returns image bytes; it owns
    provider selection + retry/reliability. The engine schedules nodes as their
    predecessors complete (graphlib), resolves @refs to upstream output paths,
    writes bytes to out_dir/{name or id}.png, and propagates failure/skip:
      * on_failure="skip"      — a node with any failed/skipped upstream is skipped
                                 (no execute call, no billed request); the rest run.
      * on_failure="fail-fast" — the first failure aborts every not-yet-started node
                                 (in-flight nodes finish; threads can't be killed).
    """
    if on_failure not in ON_FAILURE_CHOICES:
        raise DagError(f"on_failure must be one of {ON_FAILURE_CHOICES}, got {on_failure!r}")

    by_id = {t.id: t for t in tasks}
    graph = build_graph(tasks)

    ts = graphlib.TopologicalSorter(graph)
    try:
        ts.prepare()
    except graphlib.CycleError as e:
        cycle = e.args[1] if len(e.args) > 1 else ["?"]
        raise DagError(f"DAG has a cycle: {' -> '.join(map(str, cycle))}") from e

    results: dict[str, TaskResult] = {}
    lock = threading.Lock()
    abort = threading.Event()
    writer = write or (lambda p, b: p.write_bytes(b))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def _upstream_ok(task: Task) -> bool:
        with lock:
            return all(
                (results[dep].status == SUCCESS)
                for dep in graph[task.id]
                if dep in results
            )

    def run_node(node_id: str) -> None:
        task = by_id[node_id]
        if on_failure == ON_FAILURE_FAIL_FAST and abort.is_set():
            with lock:
                results[node_id] = TaskResult(SKIPPED, error="aborted (fail-fast)")
            return
        if not _upstream_ok(task):
            with lock:
                results[node_id] = TaskResult(SKIPPED, error="upstream failed or skipped")
            return
        try:
            with lock:
                refs = resolve_refs(task, results)
            raw = execute(task, refs)
            path = out_dir / f"{task.name or task.id}.png"
            writer(path, raw)
            with lock:
                results[node_id] = TaskResult(SUCCESS, output_path=str(path))
        except Exception as e:  # noqa: BLE001 - isolate per node
            with lock:
                results[node_id] = TaskResult(FAILED, error=str(e))
            if on_failure == ON_FAILURE_FAIL_FAST:
                abort.set()

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
        fut2node: dict = {}
        while ts.is_active():
            for node in ts.get_ready():
                fut2node[ex.submit(run_node, node)] = node
            if not fut2node:
                break  # no ready nodes and nothing in flight (shouldn't happen post-prepare)
            done, _ = wait(fut2node, return_when=FIRST_COMPLETED)
            for fut in done:
                node = fut2node.pop(fut)
                fut.result()          # run_node isolates; this only surfaces engine bugs
                ts.done(node)          # unblock successors for the next get_ready()

    return results


# --- spec loading (YAML / JSON) -----------------------------------------------

def parse_dag(data: object) -> list[Task]:
    """Turn a parsed spec mapping ({"tasks": [ {...}, ... ]}) into validated Tasks.

    Validates required fields, unique ids, that deps/@refs point at real tasks,
    and that the graph is acyclic — so errors surface at load time, not mid-run.
    """
    if not isinstance(data, dict) or "tasks" not in data:
        raise DagError("dag spec must be a mapping with a 'tasks' list")
    raw = data["tasks"]
    if not isinstance(raw, list) or not raw:
        raise DagError("'tasks' must be a non-empty list")

    tasks: list[Task] = []
    for i, rt in enumerate(raw):
        if not isinstance(rt, dict):
            raise DagError(f"task #{i} must be a mapping")
        tid, prompt = rt.get("id"), rt.get("prompt")
        if not isinstance(tid, str) or not tid:
            raise DagError(f"task #{i} is missing a string 'id'")
        if not isinstance(prompt, str) or not prompt:
            raise DagError(f"task {tid!r} is missing a string 'prompt'")
        tasks.append(Task(
            id=tid,
            prompt=prompt,
            provider=rt.get("provider"),
            model=rt.get("model"),
            ratio=rt.get("ratio"),
            refs=tuple(rt.get("refs") or ()),
            background=rt.get("background"),
            depends_on=tuple(rt.get("depends_on") or ()),
            name=rt.get("name"),
        ))

    _check_acyclic(build_graph(tasks))  # validates ids + acyclicity up front
    return tasks


def load_dag(path: str) -> list[Task]:
    """Load a DAG spec from a .json (stdlib) or .yaml/.yml (pyyaml) file."""
    p = Path(path).expanduser()
    if not p.is_file():
        raise DagError(f"dag file not found: {path}")
    text = p.read_text(encoding="utf-8")
    suffix = p.suffix.lower()
    if suffix == ".json":
        import json
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise DagError(f"invalid JSON dag spec {path}: {e}") from e
    elif suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ModuleNotFoundError as e:
            raise DagError(
                "YAML dag specs need pyyaml — `pip install pyyaml`, or use a .json spec."
            ) from e
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as e:  # type: ignore[attr-defined]
            raise DagError(f"invalid YAML dag spec {path}: {e}") from e
    else:
        raise DagError(f"unsupported dag spec extension {suffix!r}; use .json / .yaml / .yml")
    return parse_dag(data)
