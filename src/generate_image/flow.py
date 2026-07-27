"""Bounded directed-graph workflow runtime.

Unlike :mod:`generate_image.dag`, a flow is a control graph: each node returns a
named route and exactly one matching edge is followed. Cycles are allowed, but a
cyclic spec must declare ``limits.max_steps`` so a malformed acceptance loop can
never run or bill forever. Runtime history is unrolled into immutable attempts.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

TERMINALS = frozenset({"done", "failed"})
_TEMPLATE = re.compile(r"\$\{([^{}]+)\}")


class FlowError(Exception):
    """Invalid flow spec or runtime transition."""


@dataclass(frozen=True)
class FlowNode:
    id: str
    type: str
    config: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FlowEdge:
    source: str
    route: str
    target: str


@dataclass(frozen=True)
class FlowLimits:
    max_steps: int | None = None
    max_billed_calls: int | None = None
    max_visits: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class FlowSpec:
    entry: str
    nodes: Mapping[str, FlowNode]
    edges: tuple[FlowEdge, ...]
    state: Mapping[str, Any] = field(default_factory=dict)
    services: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    limits: FlowLimits = field(default_factory=FlowLimits)


@dataclass
class NodeOutcome:
    route: str
    state_patch: dict[str, Any] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    billed_calls: int = 0


@dataclass
class FlowContext:
    state: dict[str, Any]
    node_data: dict[str, dict[str, Any]]
    latest_artifacts: dict[str, list[str]]
    services: Mapping[str, Mapping[str, Any]]
    step: int
    billed_calls: int


@dataclass
class FlowResult:
    status: str
    terminal: str | None
    current_node: str | None
    state: dict[str, Any]
    node_data: dict[str, dict[str, Any]]
    latest_artifacts: dict[str, list[str]]
    history: list[dict[str, Any]]
    billed_calls: int
    error: str | None = None


NodeHandler = Callable[[FlowNode, FlowContext, Path], NodeOutcome]


def _positive_int(value: object, label: str, *, optional: bool = False) -> int | None:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise FlowError(f"{label} must be a positive integer")
    return value


def _strongly_connected_components(graph: Mapping[str, set[str]]) -> list[set[str]]:
    """Tarjan SCC, kept local to avoid a graph dependency for one validation."""
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[set[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in graph[node]:
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] == indices[node]:
            component: set[str] = set()
            while True:
                member = stack.pop()
                on_stack.remove(member)
                component.add(member)
                if member == node:
                    break
            components.append(component)

    for node in graph:
        if node not in indices:
            visit(node)
    return components


def _validate(spec: FlowSpec) -> None:
    if spec.entry not in spec.nodes:
        raise FlowError(f"entry node {spec.entry!r} does not exist")
    transitions: set[tuple[str, str]] = set()
    graph = {node_id: set() for node_id in spec.nodes}
    for edge in spec.edges:
        if edge.source not in spec.nodes:
            raise FlowError(f"edge source {edge.source!r} does not exist")
        if edge.target not in spec.nodes and edge.target not in TERMINALS:
            raise FlowError(f"edge target {edge.target!r} does not exist")
        key = (edge.source, edge.route)
        if key in transitions:
            raise FlowError(f"duplicate route {edge.route!r} from node {edge.source!r}")
        transitions.add(key)
        if edge.target in spec.nodes:
            graph[edge.source].add(edge.target)
    unknown_limits = set(spec.limits.max_visits) - set(spec.nodes)
    if unknown_limits:
        raise FlowError(f"max_visits references unknown nodes: {sorted(unknown_limits)}")
    cyclic = any(
        len(component) > 1 or any(node in graph[node] for node in component)
        for component in _strongly_connected_components(graph)
    )
    if cyclic and spec.limits.max_steps is None:
        raise FlowError("cyclic flows must declare limits.max_steps")


def parse_flow(data: object) -> FlowSpec:
    if not isinstance(data, dict):
        raise FlowError("flow spec must be a mapping")
    if data.get("version", 1) != 1:
        raise FlowError("unsupported flow spec version; expected 1")
    raw_nodes = data.get("nodes")
    if not isinstance(raw_nodes, dict) or not raw_nodes:
        raise FlowError("'nodes' must be a non-empty mapping")
    nodes: dict[str, FlowNode] = {}
    for node_id, raw_node in raw_nodes.items():
        if not isinstance(node_id, str) or not node_id:
            raise FlowError("node ids must be non-empty strings")
        if not isinstance(raw_node, dict):
            raise FlowError(f"node {node_id!r} must be a mapping")
        node_type = raw_node.get("type")
        if not isinstance(node_type, str) or not node_type:
            raise FlowError(f"node {node_id!r} is missing a string 'type'")
        nodes[node_id] = FlowNode(node_id, node_type, {
            key: value for key, value in raw_node.items() if key != "type"
        })

    raw_edges = data.get("edges")
    if not isinstance(raw_edges, list) or not raw_edges:
        raise FlowError("'edges' must be a non-empty list")
    edges: list[FlowEdge] = []
    for index, raw_edge in enumerate(raw_edges):
        if not isinstance(raw_edge, dict):
            raise FlowError(f"edge #{index} must be a mapping")
        source, route, target = (
            raw_edge.get("from"), raw_edge.get("route"), raw_edge.get("to")
        )
        if not all(isinstance(item, str) and item for item in (source, route, target)):
            raise FlowError(f"edge #{index} requires string from/route/to")
        edges.append(FlowEdge(source, route, target))

    raw_limits = data.get("limits") or {}
    if not isinstance(raw_limits, dict):
        raise FlowError("'limits' must be a mapping")
    raw_visits = raw_limits.get("max_visits") or {}
    if not isinstance(raw_visits, dict):
        raise FlowError("limits.max_visits must be a mapping")
    max_visits = {
        node_id: _positive_int(value, f"limits.max_visits.{node_id}")
        for node_id, value in raw_visits.items()
    }
    limits = FlowLimits(
        max_steps=_positive_int(raw_limits.get("max_steps"), "limits.max_steps", optional=True),
        max_billed_calls=_positive_int(
            raw_limits.get("max_billed_calls"), "limits.max_billed_calls", optional=True
        ),
        max_visits=max_visits,
    )
    state = data.get("state") or {}
    services = data.get("services") or {}
    if not isinstance(state, dict):
        raise FlowError("'state' must be a mapping")
    if not isinstance(services, dict) or any(not isinstance(v, dict) for v in services.values()):
        raise FlowError("'services' must be a mapping of mappings")
    entry = data.get("entry")
    if not isinstance(entry, str) or not entry:
        raise FlowError("flow spec is missing a string 'entry'")
    spec = FlowSpec(entry, nodes, tuple(edges), state, services, limits)
    _validate(spec)
    return spec


def load_flow(path: str) -> FlowSpec:
    source = Path(path).expanduser()
    if not source.is_file():
        raise FlowError(f"flow file not found: {path}")
    text = source.read_text(encoding="utf-8")
    try:
        if source.suffix.lower() == ".json":
            data = json.loads(text)
        elif source.suffix.lower() in (".yaml", ".yml"):
            import yaml
            data = yaml.safe_load(text)
        else:
            raise FlowError("flow files must use .json, .yaml, or .yml")
    except (json.JSONDecodeError, ValueError) as exc:
        raise FlowError(f"invalid flow file {path}: {exc}") from exc
    return parse_flow(data)


def _lookup(path: str, context: FlowContext) -> Any:
    parts = path.split(".")
    if parts[0] == "state":
        value: Any = context.state
    elif parts[0] == "nodes":
        value = context.node_data
    else:
        raise FlowError(f"template path must start with state or nodes: {path!r}")
    for part in parts[1:]:
        if not isinstance(value, Mapping) or part not in value:
            raise FlowError(f"template path not found: {path!r}")
        value = value[part]
    return value


def render_template(value: Any, context: FlowContext) -> Any:
    """Resolve safe ``${state.x}`` / ``${nodes.id.x}`` references recursively."""
    if isinstance(value, list):
        return [render_template(item, context) for item in value]
    if isinstance(value, dict):
        return {key: render_template(item, context) for key, item in value.items()}
    if not isinstance(value, str):
        return value
    match = _TEMPLATE.fullmatch(value)
    if match:
        return _lookup(match.group(1), context)
    return _TEMPLATE.sub(lambda found: str(_lookup(found.group(1), context)), value)


def resolve_artifact(ref: str, context: FlowContext) -> str:
    if not isinstance(ref, str) or not ref.startswith("@"):
        return ref
    node_id = ref[1:]
    artifacts = context.latest_artifacts.get(node_id) or []
    if not artifacts:
        raise FlowError(f"artifact ref {ref!r} has no completed output")
    return artifacts[-1]


def _write_state(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def run_flow(spec: FlowSpec, handlers: Mapping[str, NodeHandler], *, run_dir: Path,
             billed_calls_by_type: Mapping[str, int] | None = None) -> FlowResult:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    journal_path = run_dir / "journal.jsonl"
    state = dict(spec.state)
    node_data: dict[str, dict[str, Any]] = {}
    artifacts: dict[str, list[str]] = {}
    history: list[dict[str, Any]] = []
    visits = {node_id: 0 for node_id in spec.nodes}
    billed_calls = 0
    current = spec.entry
    transitions = {(edge.source, edge.route): edge.target for edge in spec.edges}
    costs = dict(billed_calls_by_type or {})

    def finish(status: str, terminal: str | None, error: str | None = None) -> FlowResult:
        result = FlowResult(status, terminal, current, state, node_data, artifacts,
                            history, billed_calls, error)
        _write_state(run_dir / "state.json", {
            "status": status, "terminal": terminal, "current_node": current,
            "state": state, "node_data": node_data, "latest_artifacts": artifacts,
            "visits": visits, "steps": len(history), "billed_calls": billed_calls,
            "error": error,
        })
        return result

    while current not in TERMINALS:
        if spec.limits.max_steps is not None and len(history) >= spec.limits.max_steps:
            return finish("limit_exceeded", None, "limits.max_steps exceeded")
        node = spec.nodes[current]
        visits[current] += 1
        visit_limit = spec.limits.max_visits.get(current)
        if visit_limit is not None and visits[current] > visit_limit:
            return finish("limit_exceeded", None, f"max visits exceeded for {current!r}")
        estimated = costs.get(node.type, 0)
        if (spec.limits.max_billed_calls is not None
                and billed_calls + estimated > spec.limits.max_billed_calls):
            return finish("limit_exceeded", None, "limits.max_billed_calls exceeded")
        handler = handlers.get(node.type)
        if handler is None:
            return finish("failed", "failed", f"no handler registered for {node.type!r}")

        attempt_dir = run_dir / current / f"attempt-{visits[current]:03d}"
        attempt_dir.mkdir(parents=True, exist_ok=False)
        context = FlowContext(state, node_data, artifacts, spec.services,
                              len(history) + 1, billed_calls)
        event: dict[str, Any] = {
            "step": len(history) + 1, "node": current, "type": node.type,
            "attempt": visits[current],
        }
        try:
            outcome = handler(node, context, attempt_dir)
            if not isinstance(outcome, NodeOutcome) or not outcome.route:
                raise FlowError(f"handler {node.type!r} returned an invalid outcome")
            if outcome.billed_calls < 0:
                raise FlowError("billed_calls cannot be negative")
            billed_calls += outcome.billed_calls
            if (spec.limits.max_billed_calls is not None
                    and billed_calls > spec.limits.max_billed_calls):
                raise FlowError("handler exceeded limits.max_billed_calls")
            state.update(outcome.state_patch)
            node_data[current] = dict(outcome.data)
            artifacts[current] = list(outcome.artifacts)
            route = outcome.route
            event.update({
                "status": "success", "route": route,
                "state_patch": outcome.state_patch, "data": outcome.data,
                "artifacts": outcome.artifacts, "billed_calls": outcome.billed_calls,
            })
        except Exception as exc:  # noqa: BLE001 - handler failures become control outcomes
            route = "error"
            event.update({"status": "error", "route": route, "error": str(exc)})

        target = transitions.get((current, route))
        if target is None:
            event["transition_error"] = f"no {route!r} route from {current!r}"
        history.append(event)
        with journal_path.open("a", encoding="utf-8") as journal:
            journal.write(json.dumps(event, ensure_ascii=False) + "\n")
        _write_state(run_dir / "state.json", {
            "status": "running", "current_node": current, "next_node": target,
            "state": state, "node_data": node_data, "latest_artifacts": artifacts,
            "visits": visits, "steps": len(history), "billed_calls": billed_calls,
        })
        if target is None:
            return finish("failed", "failed", event["transition_error"])
        current = target

    return finish("succeeded" if current == "done" else "failed", current)
