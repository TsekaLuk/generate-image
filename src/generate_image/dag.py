"""Scalable parametric image-generation DAG scheduler.

Runs image tasks over an ARBITRARY directed acyclic graph at maximum
parallelism, using stdlib `graphlib.TopologicalSorter`. Supports both classic
flat task lists and v3 scale primitives (100% backward compatible):

  * `vars` + CLI `--var k=v`   — bind winning anchors or campaign variables cleanly
  * `defaults`                 — shared provider/model/ratio/quality/background/stage
  * `blocks`                   — reusable prompt DNA (`invariant`, `style`, `negatives`)
  * structured `spec`          — compiles 6-layer structured fields into rich prompts
  * `matrix` / `foreach`       — Cartesian-product / list expansion (30 lines -> 100+ nodes)
  * `grid` board slicing       — auto-slices multi-panel boards (`3x3`, `2x3`) and
                                 resolves `@board:C` / `@board[2]` refs downstream
  * `--resume` content hashing — skips unchanged nodes via `.dag-manifest.json`;
                                 automatically invalidates descendants if an anchor changes
  * staged execution           — filter by `stages`, `only_ids`, `only_roots`, `until_id`
"""

from __future__ import annotations

import graphlib
import hashlib
import itertools
import json
import re
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import board

REF_PREFIX = "@"
MANIFEST_FILENAME = ".dag-manifest.json"

# Task.kind values
KIND_GENERATE = "generate"
KIND_RENDER = "render"
KIND_STITCH = "stitch"
KIND_CHOICES = (KIND_GENERATE, KIND_RENDER, KIND_STITCH)

# TaskResult.status values
SUCCESS = "success"
CACHED = "cached"
FAILED = "failed"
SKIPPED = "skipped"

# on_failure policies
ON_FAILURE_SKIP = "skip"
ON_FAILURE_FAIL_FAST = "fail-fast"
ON_FAILURE_CHOICES = (ON_FAILURE_SKIP, ON_FAILURE_FAIL_FAST)

_TEMPLATE_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")
_SLICE_COLON_RE = re.compile(r"^([^:\[\]]+):([^:\[\]]+)$")
_SLICE_BRACKET_RE = re.compile(r"^([^:\[\]]+)\[([0-9]+)\]$")


@dataclass(frozen=True)
class Task:
    """One image-generation or deterministic local render node in the DAG."""
    id: str
    prompt: str = ""
    provider: str | None = None
    model: str | None = None
    ratio: str | None = None
    refs: tuple[str, ...] = ()          # static path/URL, "@id", "@board:C", or "@board[0]"
    background: str | None = None
    depends_on: tuple[str, ...] = ()
    name: str | None = None             # output filename stem (defaults to id)
    quality: str | None = None
    gif: bool = False
    frames: int | None = None
    frame_ms: int | None = None
    stage: str | None = None
    tags: dict[str, str] = field(default_factory=dict)
    grid: board.GridSpec | None = None
    provider_pool: tuple[str, ...] = ()
    # Deterministic local vector/HTML rendering fields (kind="render", zero API cost)
    kind: str = KIND_GENERATE
    html: str | None = None
    html_file: str | None = None
    svg: str | None = None
    svg_file: str | None = None
    width: int | None = None
    height: int | None = None
    scale: float = 2.0
    pdf: bool = False
    # Automatic raster-to-SVG vectorization & long-scroll stitching fields
    trace_svg: bool = False
    trace_colors: int = 4
    stitch_direction: str = "vertical"
    stitch_gap: int = 0


@dataclass
class TaskResult:
    status: str                          # SUCCESS | CACHED | FAILED | SKIPPED
    output_path: str | None = None
    error: str | None = None
    slices: dict[str, str] = field(default_factory=dict)
    content_hash: str | None = None


class DagError(Exception):
    """Malformed DAG: unknown/duplicate id, self-loop, cycle, or bad ref."""


def _parse_ref(ref: str) -> tuple[str | None, str | None]:
    """Parse an `@` reference into `(upstream_task_id, slice_selector_or_None)`.

    Examples:
      * `'@A'`         -> `('A', None)`
      * `'@board:C'`   -> `('board', 'C')`
      * `'@board[2]'`  -> `('board', '[2]')`
      * `'/tmp/a.png'` -> `(None, None)`
    """
    if not ref.startswith(REF_PREFIX):
        return None, None
    body = ref[len(REF_PREFIX):]
    m = _SLICE_COLON_RE.match(body)
    if m:
        return m.group(1), m.group(2)
    m = _SLICE_BRACKET_RE.match(body)
    if m:
        return m.group(1), f"[{m.group(2)}]"
    return body, None


def _ref_dep(ref: str) -> str | None:
    """'@id' / '@id:label' / '@id[i]' -> 'id'; anything else -> None."""
    dep, _ = _parse_ref(ref)
    return dep


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


def filter_tasks(tasks: list[Task], *,
                 stages: set[str] | None = None,
                 only_ids: set[str] | None = None,
                 only_roots: bool = False,
                 until_id: str | None = None) -> list[Task]:
    """Return a topologically closed subset of `tasks` matching the given selectors.

    Any upstream ancestor required by a selected task is automatically included
    so the subgraph remains self-contained (with `--resume`, already-finished
    ancestors execute as zero-cost cache hits).
    """
    graph = build_graph(tasks)
    by_id = {t.id: t for t in tasks}
    selected: set[str] = set(by_id)

    if only_roots:
        selected &= {tid for tid, deps in graph.items() if not deps}
    if stages:
        stage_hits = {t.id for t in tasks if t.stage in stages}
        if not stage_hits:
            known = sorted({t.stage for t in tasks if t.stage})
            raise DagError(f"no tasks match stage(s) {sorted(stages)}; available: {known}")
        selected &= stage_hits
    if only_ids:
        unknown = only_ids - set(by_id)
        if unknown:
            raise DagError(f"unknown task id(s) in --only: {sorted(unknown)}")
        selected &= only_ids
    if until_id is not None:
        if until_id not in by_id:
            raise DagError(f"unknown task id in --until: {until_id!r}")
        selected &= {until_id}

    # Include transitive ancestors of selected tasks (except when only_roots was exclusive)
    closed: set[str] = set()
    stack = list(selected)
    while stack:
        nid = stack.pop()
        if nid in closed:
            continue
        closed.add(nid)
        for dep in graph[nid]:
            if dep not in closed:
                stack.append(dep)

    return [t for t in tasks if t.id in closed]


def resolve_refs(task: Task, results: dict[str, TaskResult]) -> list[str]:
    """Replace each '@id' / '@id:label' / '@id[i]' ref with the upstream path."""
    out: list[str] = []
    for r in task.refs:
        dep, sel = _parse_ref(r)
        if dep is None:
            out.append(r)
            continue
        res = results.get(dep)
        if res is None or res.output_path is None:
            raise DagError(f"task {task.id!r} ref {r!r}: upstream {dep!r} produced no output")
        if sel is None:
            out.append(res.output_path)
            continue
        if not res.slices:
            raise DagError(
                f"task {task.id!r} ref {r!r}: upstream {dep!r} has no grid slices "
                f"(add `grid: RxC` to task {dep!r})"
            )
        if sel.startswith("[") and sel.endswith("]"):
            idx = int(sel[1:-1])
            ordered = list(res.slices.values())
            if not 0 <= idx < len(ordered):
                raise DagError(
                    f"task {task.id!r} ref {r!r}: slice index {idx} out of range "
                    f"(0..{len(ordered) - 1})"
                )
            out.append(ordered[idx])
        else:
            if sel not in res.slices:
                raise DagError(
                    f"task {task.id!r} ref {r!r}: unknown slice label {sel!r}; "
                    f"available: {list(res.slices)}"
                )
            out.append(res.slices[sel])
    return out


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_task_hash(task: Task, resolved_refs: list[str]) -> str:
    """Deterministic fingerprint of a task + its exact resolved input image bytes.

    Hashing the bytes of local resolved refs means changing an upstream anchor
    automatically invalidates every descendant node on `--resume`.
    """
    ref_digests: list[str] = []
    for r in resolved_refs:
        p = Path(r).expanduser()
        if p.is_file():
            ref_digests.append(f"file:{_sha256_file(p)}")
        else:
            ref_digests.append(f"lit:{r}")
    payload = {
        "kind": task.kind,
        "prompt": task.prompt,
        "provider": task.provider,
        "model": task.model,
        "ratio": task.ratio,
        "background": task.background,
        "quality": task.quality,
        "gif": task.gif,
        "frames": task.frames,
        "frame_ms": task.frame_ms,
        "grid": task.grid.to_fingerprint() if task.grid else None,
        "trace_svg": task.trace_svg,
        "trace_colors": task.trace_colors if task.trace_svg else None,
        "refs": ref_digests,
    }
    if task.kind == KIND_STITCH:
        payload.update({
            "width": task.width,
            "stitch_direction": task.stitch_direction,
            "stitch_gap": task.stitch_gap,
        })
    if task.kind == KIND_RENDER:
        payload.update({
            "html": task.html,
            "html_file": f"file:{_sha256_file(Path(task.html_file))}" if task.html_file and Path(task.html_file).is_file() else task.html_file,
            "svg": task.svg,
            "svg_file": f"file:{_sha256_file(Path(task.svg_file))}" if task.svg_file and Path(task.svg_file).is_file() else task.svg_file,
            "width": task.width,
            "height": task.height,
            "scale": task.scale,
            "pdf": task.pdf,
        })
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _load_manifest(out_dir: Path) -> dict[str, dict]:
    p = out_dir / MANIFEST_FILENAME
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_manifest(out_dir: Path, manifest: dict[str, dict]) -> None:
    p = out_dir / MANIFEST_FILENAME
    p.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _output_ext_for(task: Task, raw: bytes) -> str:
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if task.gif:
        return "gif"
    return "png"


def run_dag(tasks: list[Task],
            execute: Callable[[Task, list[str]], bytes],
            *,
            out_dir: Path,
            concurrency: int = 4,
            on_failure: str = ON_FAILURE_SKIP,
            write: Callable[[Path, bytes], None] | None = None,
            resume: bool = False) -> dict[str, TaskResult]:
    """Execute the task DAG at maximum parallelism. Returns id -> TaskResult.

    `execute(task, resolved_refs)` runs ONE node and returns image bytes; it owns
    provider selection + retry/reliability. When `resume=True`, completed nodes
    whose content hash (including resolved ref file hashes) matches `.dag-manifest.json`
    and whose outputs exist on disk are skipped with `status=CACHED`.
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
    manifest = _load_manifest(out_dir) if resume else {}

    def _upstream_ok(task: Task) -> bool:
        with lock:
            return all(
                (results[dep].status in (SUCCESS, CACHED))
                for dep in graph[task.id]
                if dep in results
            )

    def _try_cache_hit(task: Task, digest: str) -> TaskResult | None:
        if not resume:
            return None
        entry = manifest.get(task.id)
        if not isinstance(entry, dict) or entry.get("hash") != digest:
            return None
        out_path = entry.get("output_path")
        if not out_path or not Path(out_path).is_file():
            return None
        if task.kind == KIND_RENDER:
            out_p = Path(out_path)
            if (task.svg is not None or task.svg_file is not None) and not out_p.with_suffix(".svg").is_file():
                return None
            if task.pdf and not out_p.with_suffix(".pdf").is_file():
                return None
        if task.trace_svg and not Path(out_path).with_suffix(".svg").is_file():
            return None
        slices = entry.get("slices") or {}
        if task.grid is not None:
            expected = set(task.grid.resolved_labels())
            if set(slices) != expected or not all(Path(p).is_file() for p in slices.values()):
                return None
        return TaskResult(CACHED, output_path=out_path, slices=dict(slices), content_hash=digest)

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
            digest = compute_task_hash(task, refs)
            with lock:
                hit = _try_cache_hit(task, digest)
            if hit is not None:
                with lock:
                    results[node_id] = hit
                return
            raw = execute(task, refs)
            ext = _output_ext_for(task, raw)
            stem = task.name or task.id
            path = out_dir / f"{stem}.{ext}"
            path.parent.mkdir(parents=True, exist_ok=True)
            writer(path, raw)
            slices_map: dict[str, str] = {}
            if task.grid is not None:
                sliced = board.slice_grid(path, task.grid, path.parent, path.stem)
                slices_map = {k: str(v) for k, v in sliced.items()}
            with lock:
                results[node_id] = TaskResult(
                    SUCCESS, output_path=str(path), slices=slices_map, content_hash=digest,
                )
                manifest[node_id] = {
                    "hash": digest,
                    "output_path": str(path),
                    "slices": slices_map,
                }
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
                break
            done, _ = wait(fut2node, return_when=FIRST_COMPLETED)
            for fut in done:
                node = fut2node.pop(fut)
                fut.result()
                ts.done(node)

    if manifest:
        _save_manifest(out_dir, manifest)

    return results


# --- declarative template & matrix expansion ----------------------------------

def _lookup_path(ctx: dict, path: str):
    parts = path.split(".")
    cur: object = ctx
    for p in parts:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return None
    return cur


def _render_str(text: str, ctx: dict) -> str:
    """Resolve `{{key}}` / `{{blocks.style}}` / `{{dim.field}}` placeholders.

    Performs up to 3 passes so a block referencing a variable (`{{vars.brand}}`)
    or matrix dimension resolves cleanly. Raises DagError on an unresolved token.
    """
    out = text
    for _ in range(3):
        if "{{" not in out:
            break

        def repl(m: re.Match) -> str:
            key = m.group(1)
            if key.startswith(("ref.", "refs.", "ref_data.", "refs_data.")):
                return m.group(0)
            val = _lookup_path(ctx, key)
            if val is None:
                # Also check blocks/vars shorthand without prefix
                for ns in ("blocks", "vars"):
                    sub = ctx.get(ns)
                    if isinstance(sub, dict) and key in sub:
                        val = sub[key]
                        break
            if val is None:
                raise DagError(f"unresolved template variable {{{{{key}}}}}")
            if isinstance(val, dict):
                # Allow {{dim}} when dim is an object with a `value` or `key` or `prompt`
                for fallback in ("prompt", "desc", "label", "value", "key", "id"):
                    if fallback in val:
                        return str(val[fallback])
                raise DagError(f"template variable {{{{{key}}}}} is a mapping; reference a field like {{{{{key}.key}}}}")
            return str(val)

        nxt = _TEMPLATE_RE.sub(repl, out)
        if nxt == out:
            break
        out = nxt
    return out


def _compile_structured_spec(spec: dict, ctx: dict) -> str:
    """Compile a structured 6-layer `spec:` mapping into a crisp natural-language prompt."""
    if not isinstance(spec, dict):
        raise DagError("task 'spec' must be a mapping")
    parts: list[str] = []
    ordered_labels = (
        ("deliverable", ""),
        ("subject", ""),
        ("info_points", "Key information points to depict clearly: "),
        ("composition", "Composition & layout: "),
        ("style", "Visual style & medium: "),
        ("lighting", "Lighting & color palette: "),
        ("context", "Environment & details: "),
        ("negatives", "Strict constraints & avoid: "),
    )
    for key, prefix in ordered_labels:
        val = spec.get(key)
        if not val:
            continue
        if isinstance(val, list):
            rendered_items = [_render_str(str(x), ctx).strip() for x in val if str(x).strip()]
            if rendered_items:
                parts.append(prefix + "; ".join(rendered_items))
        else:
            rendered = _render_str(str(val), ctx).strip()
            if rendered:
                parts.append(prefix + rendered)
    if not parts:
        raise DagError("task 'spec' produced an empty prompt")
    return ". ".join(p.rstrip(".。 ") for p in parts) + "."


def _dim_tag_value(val: object) -> str:
    if isinstance(val, dict):
        for k in ("key", "id", "label", "name", "value"):
            if k in val:
                return str(val[k])
        return json.dumps(val, sort_keys=True, ensure_ascii=False)
    return str(val)


def _matches_exclude(combo: dict[str, object], excludes: list[dict]) -> bool:
    for rule in excludes:
        if not isinstance(rule, dict):
            continue
        if all(_dim_tag_value(combo.get(k)) == str(v) for k, v in rule.items()):
            return True
    return False


def _resolve_template_file(raw_path: str | None, dag_dir: Path | None) -> str | None:
    if raw_path is None:
        return None
    p = Path(raw_path).expanduser()
    if not p.is_absolute() and dag_dir is not None:
        p = (dag_dir / p).resolve()
    return str(p)


def _expand_entry(rt: dict, *, defaults: dict, blocks: dict, base_vars: dict,
                  index: int, dag_dir: Path | None = None) -> list[Task]:
    if not isinstance(rt, dict):
        raise DagError(f"task #{index} must be a mapping")
    matrix = rt.get("matrix")
    foreach = rt.get("foreach")
    if matrix is not None and foreach is not None:
        raise DagError(f"task #{index} cannot specify both 'matrix' and 'foreach'")

    combos: list[dict[str, object]] = [{}]
    if matrix is not None:
        if not isinstance(matrix, dict) or not matrix:
            raise DagError(f"task #{index} 'matrix' must be a non-empty mapping of dimension -> list")
        dim_names = list(matrix.keys())
        dim_values = []
        for dn in dim_names:
            vals = matrix[dn]
            if not isinstance(vals, list) or not vals:
                raise DagError(f"task #{index} matrix dimension {dn!r} must be a non-empty list")
            dim_values.append(vals)
        excludes = rt.get("exclude") or []
        combos = []
        for prod in itertools.product(*dim_values):
            combo = dict(zip(dim_names, prod))
            if not _matches_exclude(combo, excludes):
                combos.append(combo)
    elif foreach is not None:
        if not isinstance(foreach, list) or not foreach:
            raise DagError(f"task #{index} 'foreach' must be a non-empty list")
        item_key = str(rt.get("as", "item"))
        combos = [{item_key: v} for v in foreach]

    merged_base = {**defaults, **{k: v for k, v in rt.items() if k not in ("matrix", "foreach", "exclude", "as")}}
    pool_raw = merged_base.get("provider_pool")
    pool: tuple[str, ...] = tuple(str(x) for x in pool_raw) if isinstance(pool_raw, (list, tuple)) else ()

    out: list[Task] = []
    for ci, combo in enumerate(combos):
        ctx = {
            "vars": base_vars,
            "blocks": blocks,
            "index": ci,
            **combo,
        }
        raw_id = merged_base.get("id")
        if not isinstance(raw_id, str) or not raw_id:
            raise DagError(f"task #{index} is missing a string 'id'")
        tid = _render_str(raw_id, ctx)

        raw_html = merged_base.get("html")
        raw_html_file = merged_base.get("html_file")
        raw_svg = merged_base.get("svg")
        raw_svg_file = merged_base.get("svg_file")
        has_render_src = any(x is not None for x in (raw_html, raw_html_file, raw_svg, raw_svg_file))
        default_kind = KIND_RENDER if has_render_src else KIND_GENERATE
        kind = str(merged_base.get("kind") or default_kind)
        if kind not in KIND_CHOICES:
            raise DagError(f"task {tid!r} invalid kind {kind!r}; choose from {KIND_CHOICES}")

        raw_prompt = merged_base.get("prompt")
        raw_spec = merged_base.get("spec")
        if raw_prompt and raw_spec:
            prompt = _render_str(str(raw_prompt), ctx).rstrip(". ") + ". " + _compile_structured_spec(raw_spec, ctx)
        elif raw_spec:
            prompt = _compile_structured_spec(raw_spec, ctx)
        elif isinstance(raw_prompt, str) and raw_prompt.strip():
            prompt = _render_str(raw_prompt, ctx)
        elif kind == KIND_RENDER:
            src_label = raw_svg_file or raw_html_file or ("inline svg" if raw_svg is not None else "inline html")
            prompt = f"[render] {src_label}"
        elif kind == KIND_STITCH:
            prompt = f"[stitch] {len(merged_base.get('refs') or ())} sections"
        else:
            raise DagError(f"task {tid!r} must specify 'prompt' or 'spec'")

        if kind == KIND_RENDER and not has_render_src:
            raise DagError(f"render task {tid!r} must specify one of html, html_file, svg, or svg_file")
        if kind == KIND_STITCH and not (merged_base.get("refs") or ()):
            raise DagError(f"stitch task {tid!r} must specify non-empty 'refs' to stitch")

        html_text = _render_str(str(raw_html), ctx) if raw_html is not None else None
        html_file = _resolve_template_file(_render_str(str(raw_html_file), ctx), dag_dir) if raw_html_file is not None else None
        svg_text = _render_str(str(raw_svg), ctx) if raw_svg is not None else None
        svg_file = _resolve_template_file(_render_str(str(raw_svg_file), ctx), dag_dir) if raw_svg_file is not None else None
        width = int(merged_base["width"]) if merged_base.get("width") is not None else None
        height = int(merged_base["height"]) if merged_base.get("height") is not None else None
        scale = float(merged_base["scale"]) if merged_base.get("scale") is not None else 2.0
        pdf = bool(merged_base.get("pdf", False))
        trace_svg = bool(merged_base.get("trace_svg", False))
        trace_colors = int(merged_base.get("trace_colors", 4))
        stitch_direction = str(merged_base.get("stitch_direction", "vertical"))
        stitch_gap = int(merged_base.get("stitch_gap", 0))

        raw_refs = merged_base.get("refs") or ()
        refs = tuple(_render_str(str(r), ctx) for r in raw_refs)
        raw_deps = merged_base.get("depends_on") or ()
        deps = tuple(_render_str(str(d), ctx) for d in raw_deps)

        raw_name = merged_base.get("name")
        name = _render_str(str(raw_name), ctx) if raw_name is not None else None
        raw_ratio = merged_base.get("ratio")
        ratio = _render_str(str(raw_ratio), ctx) if raw_ratio is not None else None
        raw_model = merged_base.get("model")
        model = _render_str(str(raw_model), ctx) if raw_model is not None else None
        raw_bg = merged_base.get("background")
        background = _render_str(str(raw_bg), ctx) if raw_bg is not None else None
        raw_quality = merged_base.get("quality")
        quality = _render_str(str(raw_quality), ctx) if raw_quality is not None else None
        raw_stage = merged_base.get("stage")
        stage = _render_str(str(raw_stage), ctx) if raw_stage is not None else None

        provider = merged_base.get("provider")
        if provider is not None:
            provider = _render_str(str(provider), ctx)
        elif pool:
            provider = pool[ci % len(pool)]

        grid_spec = None
        if merged_base.get("grid") is not None:
            try:
                grid_spec = board.parse_grid_spec(merged_base["grid"])
            except ValueError as exc:
                raise DagError(f"task {tid!r} invalid grid: {exc}") from exc

        tags = {k: _dim_tag_value(v) for k, v in combo.items()}
        if isinstance(merged_base.get("tags"), dict):
            for tk, tv in merged_base["tags"].items():
                tags[str(tk)] = _render_str(str(tv), ctx)

        out.append(Task(
            id=tid,
            prompt=prompt,
            provider=provider,
            model=model,
            ratio=ratio,
            refs=refs,
            background=background,
            depends_on=deps,
            name=name,
            quality=quality,
            gif=bool(merged_base.get("gif", False)),
            frames=int(merged_base["frames"]) if merged_base.get("frames") is not None else None,
            frame_ms=int(merged_base["frame_ms"]) if merged_base.get("frame_ms") is not None else None,
            stage=stage,
            tags=tags,
            grid=grid_spec,
            provider_pool=pool,
            kind=kind,
            html=html_text,
            html_file=html_file,
            svg=svg_text,
            svg_file=svg_file,
            width=width,
            height=height,
            scale=scale,
            pdf=pdf,
            trace_svg=trace_svg,
            trace_colors=trace_colors,
            stitch_direction=stitch_direction,
            stitch_gap=stitch_gap,
        ))
    return out


# --- spec loading (YAML / JSON) -----------------------------------------------

def parse_dag(data: object, *, cli_vars: dict[str, str] | None = None,
              dag_dir: Path | None = None) -> list[Task]:
    """Turn a parsed spec mapping (`{"tasks": [...], ...}`) into validated Tasks.

    Supports optional top-level `vars`, `defaults`, `blocks`, structured `spec`,
    `matrix`/`foreach` expansion, `grid` specs, and deterministic `kind: render`
    nodes while remaining 100% compatible with flat `{"tasks": [...]}` specs.
    """
    if not isinstance(data, dict) or "tasks" not in data:
        raise DagError("dag spec must be a mapping with a 'tasks' list")
    raw = data["tasks"]
    if not isinstance(raw, list) or not raw:
        raise DagError("'tasks' must be a non-empty list")

    defaults = data.get("defaults") or {}
    blocks = data.get("blocks") or {}
    spec_vars = dict(data.get("vars") or {})
    if cli_vars:
        spec_vars.update(cli_vars)
    if not isinstance(defaults, dict) or not isinstance(blocks, dict):
        raise DagError("'defaults' and 'blocks' must be mappings")

    tasks: list[Task] = []
    for i, rt in enumerate(raw):
        tasks.extend(_expand_entry(rt, defaults=defaults, blocks=blocks,
                                   base_vars=spec_vars, index=i, dag_dir=dag_dir))

    _check_acyclic(build_graph(tasks))
    return tasks


def load_dag(path: str, *, cli_vars: dict[str, str] | None = None) -> list[Task]:
    """Load a DAG spec from a .json (stdlib) or .yaml/.yml (pyyaml) file."""
    p = Path(path).expanduser()
    if not p.is_file():
        raise DagError(f"dag file not found: {path}")
    text = p.read_text(encoding="utf-8")
    suffix = p.suffix.lower()
    if suffix == ".json":
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
    return parse_dag(data, cli_vars=cli_vars, dag_dir=p.resolve().parent)
