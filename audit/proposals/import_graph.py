"""S2: the import graph of ``src`` (imports inside functions included).

Finds package-level cycles (``src.ml`` <-> ``src.eval``) and what the serving path
(``src.ml.predict``) pulls in. ``rewire`` simulates the proposed moves before anyone
touches ``src``: ``src.eval.metrics`` -> ``src.ml.metrics``, and the quantile helpers
of ``src.ml.train`` -> a small ``src.ml.quantiles``.
"""

import ast
from pathlib import Path

Graph = dict[str, set[str]]


def _module_name(root: Path, path: Path) -> str:
    parts = list(path.relative_to(root.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def module_graph(root="src") -> Graph:
    root = Path(root).resolve()
    graph: Graph = {}
    for path in sorted(root.rglob("*.py")):
        name = _module_name(root, path)
        package = name if path.name == "__init__.py" else name.rsplit(".", 1)[0]
        deps = set()
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                deps |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = package.split(".")
                    base = base[: len(base) - node.level + 1]
                    mod = ".".join(base + ([node.module] if node.module else []))
                else:
                    mod = node.module or ""
                deps.add(mod)
                deps |= {f"{mod}.{a.name}" for a in node.names}  # "from src.ml import train"
        graph[name] = deps
    known = set(graph)
    return {m: {d for d in deps if d in known and d != m} for m, deps in graph.items()}


def package_graph(graph: Graph, depth: int = 2) -> Graph:
    def pkg(m):
        return ".".join(m.split(".")[:depth])

    out: Graph = {}
    for m, deps in graph.items():
        out.setdefault(pkg(m), set()).update(pkg(d) for d in deps if pkg(d) != pkg(m))
    return out


def cycles(graph: Graph) -> list[set[str]]:
    """Strongly connected components with more than one node (Tarjan)."""
    index, low, stack, on, out, counter = {}, {}, [], set(), [], [0]

    def visit(v):
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        for w in graph.get(v, ()):
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = set()
            while True:
                w = stack.pop()
                on.discard(w)
                comp.add(w)
                if w == v:
                    break
            if len(comp) > 1:
                out.append(comp)

    for v in list(graph):
        if v not in index:
            visit(v)
    return out


def closure(graph: Graph, start: str) -> set[str]:
    seen, todo = set(), [start]
    while todo:
        m = todo.pop()
        for d in graph.get(m, ()):
            if d not in seen:
                seen.add(d)
                todo.append(d)
    return seen


def rewire(graph: Graph, moves: dict[str, str], redirect: dict[tuple[str, str], str]) -> Graph:
    """Rename modules (``moves``) and point single imports elsewhere (``redirect``)."""
    out: Graph = {}
    for m, deps in graph.items():
        new_deps = {redirect.get((m, d), d) for d in deps}
        out.setdefault(moves.get(m, m), set()).update(moves.get(d, d) for d in new_deps)
    for target in redirect.values():
        out.setdefault(target, set())
    return {m: {d for d in deps if d != m} for m, deps in out.items()}


PROPOSED_MOVES = {"src.eval.metrics": "src.ml.metrics"}
PROPOSED_REDIRECT = {
    ("src.ml.predict", "src.ml.train"): "src.ml.quantiles",
    ("src.ml.explain", "src.ml.train"): "src.ml.quantiles",
    ("src.ml.forecast_pv_load", "src.ml.train"): "src.ml.quantiles",
}
