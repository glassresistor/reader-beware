"""Render the story tree of a narrative as Graphviz DOT and scalable SVG.

This module turns a narrative's structure into two kinds of picture:

* a **DOT** file (via :func:`beware.check.to_dot`), for people who have
  Graphviz installed and want to tweak it further, and
* an **SVG** file rendered by a small self-contained layered graph layout.

The SVG is produced with *no external dependencies* (Graphviz's ``dot``
binary is not required).  It lays the story out top-to-bottom (or
left-to-right) in layers -- the entrypoint at the top, each branch one row
further down -- using a Sugiyama-style pipeline:

1. **rank** nodes into layers with a longest-path layering over a DAG that is
   made acyclic by dropping back edges found with a depth-first search (so
   cycles and self-loops in the story are handled, not crashed on);
2. **order** nodes within each layer with a few barycenter sweeps to reduce
   edge crossings;
3. **assign coordinates** that pull children toward their parents while
   guaranteeing no two boxes overlap.

The output is vector-only and carries a ``viewBox`` (no raster, no fixed
pixel grid), so it stays crisp at any zoom level or when embedded at any
size -- a thumbnail in a README or full-bleed on screen.
"""

import re
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
import xml.sax.saxutils as _xml

from beware.check import CheckResult, check_narrative, to_dot
from beware.sections import parse_sections

__all__ = [
    "StoryGraph",
    "GNode",
    "GEdge",
    "build_story_graph",
    "to_svg",
    "to_dot",
]


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

#: node categories, each with its own colour treatment (see :data:`PALETTES`)
NODE_NORMAL = "normal"
NODE_ENTRYPOINT = "entrypoint"
NODE_DEAD_END = "dead_end"
NODE_UNREACHABLE = "unreachable"
NODE_MISSING = "missing"

#: edge kinds
EDGE_NORMAL = "normal"
EDGE_BROKEN = "broken"  # points at a section that does not exist
EDGE_BACK = "back"      # part of a cycle (drawn dashed so loops are visible)


@dataclass
class GNode:
    """One box in the story graph."""

    name: str
    category: str = NODE_NORMAL
    label: str = ""  # wrapped text lines, set by the layout
    lines: List[str] = field(default_factory=list)
    layer: int = 0
    order: int = 0
    x: float = 0.0  # centre x (pixels in the layout coordinate space)
    y: float = 0.0  # centre y
    w: float = 0.0
    h: float = 0.0


@dataclass
class GEdge:
    """One directed connection between two boxes."""

    src: str
    dst: str
    kind: str = EDGE_NORMAL


@dataclass
class StoryGraph:
    """A laid-out story graph ready for SVG (or DOT) emission."""

    nodes: List[GNode]
    edges: List[GEdge]
    node_by_name: Dict[str, GNode] = field(default_factory=dict)
    orientation: str = "TB"  # TB (top->bottom) or LR (left->right)
    title: Optional[str] = None

    def __post_init__(self):
        self.node_by_name = {n.name: n for n in self.nodes}


# ---------------------------------------------------------------------------
# Build the model from a narrative
# ---------------------------------------------------------------------------

_JINJA_RE = re.compile(r"{[{%].*?[%}]}", re.DOTALL)
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_WS_RE = re.compile(r"\s+")


def plain_preview(body: str, limit: int) -> str:
    """Reduce a markdown/jinja body to a short single-line plain-text preview.

    Jinja blocks/tags are dropped, ``[text](url)`` links keep their text and
    all runs of whitespace collapse to single spaces.  The result is trimmed
    to ``limit`` characters with an ellipsis when it had to be cut.
    """
    text = _JINJA_RE.sub(" ", str(body or ""))
    text = _MD_LINK_RE.sub(r"\1", text)
    # strip the common markdown emphasis/heading markers
    text = re.sub(r"[*_`>#]+", " ", text)
    text = _WS_RE.sub(" ", text).strip()
    if len(text) > limit:
        cut = text[: limit - 1].rstrip()
        return cut + "\u2026"
    return text


def build_story_graph(
    text: str,
    labels: str = "name",
    preview_chars: int = 48,
    result: Optional[CheckResult] = None,
) -> StoryGraph:
    """Build a :class:`StoryGraph` from narrative yaml ``text``.

    ``labels`` selects what is written inside each box:

    * ``"name"`` -- the section name (default, compact);
    * ``"preview"`` -- the section name plus a one-line preview of its body;
    * ``"off"`` -- no text at all (just boxes and arrows).

    ``preview_chars`` caps the length of a ``"preview"`` label.  Pass an
    already-computed :class:`~beware.check.CheckResult` as ``result`` to avoid
    re-running the structural check.
    """
    if result is None:
        result = check_narrative(text)
    bodies = {s["name"]: s.get("body", "") for s in parse_sections(text)}

    real = list(result.sections)
    missing = sorted(result.broken_links.keys())
    all_names = real + [m for m in missing if m not in set(real)]
    name_set = set(all_names)

    dead_ends = set(result.dead_ends)
    unreachable = set(result.unreachable)

    nodes: List[GNode] = []
    for name in all_names:
        if name == result.entrypoint:
            cat = NODE_ENTRYPOINT
        elif name in missing:
            cat = NODE_MISSING
        elif name in unreachable:
            cat = NODE_UNREACHABLE
        elif name in dead_ends:
            cat = NODE_DEAD_END
        else:
            cat = NODE_NORMAL
        label = _node_label(name, bodies.get(name, ""), labels, preview_chars)
        nodes.append(GNode(name=name, category=cat, label=label))

    # edges: real section -> target.  Targets that are missing become broken
    # edges; back edges (cycles) are detected during layering and re-tagged.
    adjacency = result.adjacency
    edges: List[GEdge] = []
    for name in real:
        for target in sorted(adjacency.get(name, ())):
            if target not in name_set:
                continue  # defensive; broken targets are already in name_set
            kind = EDGE_BROKEN if target in missing else EDGE_NORMAL
            edges.append(GEdge(src=name, dst=target, kind=kind))

    return StoryGraph(nodes=nodes, edges=edges)


def _node_label(name: str, body: str, mode: str, limit: int) -> str:
    if mode == "off":
        return ""
    if mode == "preview":
        preview = plain_preview(body, limit)
        if preview:
            return "%s\n%s" % (name, preview)
        return name
    return name


# ---------------------------------------------------------------------------
# Layout: rank -> order -> coordinates
# ---------------------------------------------------------------------------

class _Layout(object):
    """Holds the mutable state of a single layout pass."""

    def __init__(self, graph: StoryGraph, orientation: str = "TB"):
        self.graph = graph
        self.orientation = orientation
        self.nodes = {n.name: n for n in graph.nodes}
        self.names = [n.name for n in graph.nodes]
        self.name_set = set(self.names)
        # outgoing / incoming edges restricted to nodes that exist
        self.out: Dict[str, List[str]] = {}
        self.in_: Dict[str, List[str]] = {}
        for name in self.names:
            self.out[name] = []
            self.in_[name] = []
        for e in graph.edges:
            if e.src in self.name_set and e.dst in self.name_set:
                self.out[e.src].append(e.dst)
                self.in_[e.dst].append(e.src)

    # -- step 1: rank -----------------------------------------------------
    def assign_layers(self) -> Set[Tuple[str, str]]:
        """Assign each node a layer (rank).  Returns the set of back edges."""
        state: Dict[str, int] = {}  # 0 white, 1 gray(on stack), 2 black
        back_edges: Set[Tuple[str, str]] = set()

        # Start from the entrypoint first so the main story is ranked from the
        # top; then visit anything left over (unreachable islands).  The DFS is
        # iterative so a very long linear story cannot hit the recursion limit.
        order = []
        if self.graph.node_by_name:
            for n in self.graph.nodes:
                if n.category == NODE_ENTRYPOINT:
                    order.append(n.name)
        order += [n for n in self.names if n not in set(order)]

        for start in order:
            if state.get(start, 0) != 0:
                continue
            state[start] = 1
            stack = [(start, iter(self.out.get(start, ())))]
            while stack:
                node, it = stack[-1]
                descended = False
                for v in it:
                    st = state.get(v, 0)
                    if st == 0:
                        state[v] = 1
                        stack.append((v, iter(self.out.get(v, ()))))
                        descended = True
                        break
                    elif st == 1:
                        back_edges.add((node, v))
                if not descended:
                    state[node] = 2
                    stack.pop()

        # longest-path layering over the DAG left after dropping back edges.
        dag_out: Dict[str, List[str]] = {n: [] for n in self.names}
        indeg = {n: 0 for n in self.names}
        for u in self.names:
            for v in self.out.get(u, ()):
                if (u, v) in back_edges:
                    continue
                dag_out[u].append(v)
                indeg[v] += 1

        layer = {n: 0 for n in self.names}
        queue = deque(n for n in self.names if indeg[n] == 0)
        while queue:
            u = queue.popleft()
            for v in dag_out[u]:
                if layer[v] < layer[u] + 1:
                    layer[v] = layer[u] + 1
                indeg[v] -= 1
                if indeg[v] == 0:
                    queue.append(v)

        for n in self.names:
            self.nodes[n].layer = layer[n]
        return back_edges

    # -- step 2: order within layers -------------------------------------
    def order_nodes(self):
        """Order nodes inside each layer with barycenter sweeps."""
        by_layer: Dict[int, List[str]] = {}
        for n in self.names:
            by_layer.setdefault(self.nodes[n].layer, []).append(n)
        # deterministic initial order
        for L in by_layer:
            by_layer[L].sort()
        max_layer = max(by_layer) if by_layer else 0

        def position(name):
            return by_layer[self.nodes[name].layer].index(name)

        def barycenter(name, neighbours):
            vals = [position(nb) for nb in neighbours if nb in self.name_set]
            if not vals:
                return None
            return sum(vals) / float(len(vals))

        def sort_layer(L, direction):
            nodes_l = by_layer[L]
            keys = {}
            for name in nodes_l:
                neigh = self.in_[name] if direction == "down" else self.out[name]
                b = barycenter(name, neigh)
                keys[name] = (b if b is not None else 1e9, name)
            nodes_l.sort(key=lambda nm: keys[nm])

        for _ in range(4):
            for L in range(1, max_layer + 1):
                if L in by_layer:
                    sort_layer(L, "down")
            for L in range(max_layer - 1, -1, -1):
                if L in by_layer:
                    sort_layer(L, "up")

        for L, nodes_l in by_layer.items():
            for i, name in enumerate(nodes_l):
                self.nodes[name].order = i

    # -- step 3: coordinates ---------------------------------------------
    def assign_coordinates(self, metrics, flow_gap, across_gap):
        """Give every node an (x, y) centre and a (w, h) size.

        ``metrics`` supplies the per-node width/height already computed from
        its wrapped label.  Coordinates are assigned in the *flow* direction
        first (layer -> one axis) then across the layer (order -> other).
        """
        by_layer: Dict[int, List[str]] = {}
        for n in self.names:
            by_layer.setdefault(self.nodes[n].layer, []).append(n)

        # y (flow axis): stack layers with a running cursor so that layers of
        # different heights never collide.
        cursor = 0.0
        for L in sorted(by_layer):
            height_at_layer = max(metrics[name][1] for name in by_layer[L])
            for name in by_layer[L]:
                self.nodes[name].y = cursor + height_at_layer / 2.0
            cursor += height_at_layer + flow_gap

        # x (across axis): start from order, then pull toward parents/children.
        for L, nodes_l in by_layer.items():
            nodes_l.sort(key=lambda nm: self.nodes[nm].order)
            cursor = 0.0
            for name in nodes_l:
                w = metrics[name][0]
                self.nodes[name].x = cursor + w / 2.0
                cursor += w + across_gap

        # alignment passes: pull each node toward the mean of its neighbours in
        # the adjacent layer, then resolve overlaps so boxes never collide.
        for _ in range(3):
            self._align(by_layer, metrics, "down", across_gap)
            self._align(by_layer, metrics, "up", across_gap)

        self._center_layers(by_layer, metrics)

    def _align(self, by_layer, metrics, direction, across_gap):
        if direction == "down":
            layers = sorted(by_layer)[1:]
            neigh = self.in_
        else:
            layers = sorted(by_layer)[-2::-1] if len(by_layer) > 1 else []
            neigh = self.out
        for L in layers:
            nodes_l = [nm for nm in by_layer[L] if nm in self.name_set]
            desired = {}
            for name in nodes_l:
                ns = [nb for nb in neigh[name] if nb in self.name_set]
                if ns:
                    desired[name] = sum(self.nodes[nb].x for nb in ns) / float(len(ns))
                else:
                    desired[name] = self.nodes[name].x
            self._resolve_layer(by_layer[L], metrics, desired, across_gap)

    def _resolve_layer(self, nodes_l, metrics, desired, across_gap):
        """Set non-overlapping x for a layer, preserving left-to-right order.

        Each node is pulled toward ``desired`` but never allowed to cross its
        neighbour; the result is then re-centred so the layer does not drift.
        """
        nodes_l.sort(key=lambda nm: self.nodes[nm].order)
        n = len(nodes_l)
        if n == 0:
            return
        widths = [metrics[nm][0] for nm in nodes_l]
        min_gap = across_gap

        # left-to-right pass: keep order, enforce minimum separation
        x = [0.0] * n
        x[0] = desired[nodes_l[0]]
        for i in range(1, n):
            prev_right = x[i - 1] + widths[i - 1] / 2.0
            need = prev_right + min_gap + widths[i] / 2.0
            x[i] = max(desired[nodes_l[i]], need)
        # right-to-left pass: push back anything that overflowed to the right
        for i in range(n - 2, -1, -1):
            next_left = x[i + 1] - widths[i + 1] / 2.0
            limit = next_left - min_gap - widths[i] / 2.0
            if x[i] > limit:
                x[i] = limit
        # re-centre the layer around its original centroid to avoid drift
        orig_centroid = sum(self.nodes[nm].x for nm in nodes_l) / float(n)
        new_centroid = (x[0] + x[-1]) / 2.0
        shift = orig_centroid - new_centroid
        for i, name in enumerate(nodes_l):
            self.nodes[name].x = x[i] + shift

    def _center_layers(self, by_layer, metrics):
        """Centre every layer on the same vertical axis so the graph is balanced."""
        centroids = []
        for L, nodes_l in by_layer.items():
            c = sum(self.nodes[nm].x for nm in nodes_l) / float(len(nodes_l))
            centroids.append(c)
        if not centroids:
            return
        target = sum(centroids) / float(len(centroids))
        for L, nodes_l in by_layer.items():
            c = sum(self.nodes[nm].x for nm in nodes_l) / float(len(nodes_l))
            shift = target - c
            for name in nodes_l:
                self.nodes[name].x += shift


def _wrap_text(text: str, max_chars: int) -> List[str]:
    """Word-wrap ``text`` into lines of at most ``max_chars`` characters."""
    if not text:
        return [""]
    words = text.split()
    lines: List[str] = []
    current = ""
    for word in words:
        candidate = word if not current else current + " " + word
        if len(candidate) <= max_chars or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _compute_metrics(graph: StoryGraph, font_size: float, pad_x: float,
                      pad_y: float, min_w: float, max_w: float) -> Dict[str, Tuple[float, float]]:
    """Compute (width, height) for every node from its wrapped label.

    For name/off labels all boxes share one uniform width (the widest label)
    so columns line up; preview labels keep per-node widths but are capped.
    """
    char_w = font_size * 0.62
    line_h = font_size * 1.35

    raw: Dict[str, List[str]] = {}
    for node in graph.nodes:
        parts = node.label.split("\n") if node.label else [node.name]
        # wrap each logical line (a preview label has name + body lines)
        wrapped: List[str] = []
        for part in parts:
            wrapped.extend(_wrap_text(part, 60))
        raw[node.name] = wrapped

    def width_for(lines):
        longest = max((len(ln) for ln in lines), default=1)
        return min(max_w, max(min_w, longest * char_w + 2 * pad_x))

    # name/off labels are a single line each -> share one uniform width so the
    # columns line up; preview labels vary in length -> per-node widths.
    uniform = all(len(raw[n.name]) <= 1 for n in graph.nodes)
    metrics: Dict[str, Tuple[float, float]] = {}
    if uniform:
        common = max(width_for(raw[n.name]) for n in graph.nodes) if graph.nodes else min_w
        for node in graph.nodes:
            w = common
            h = 2 * pad_y + len(raw[node.name]) * line_h
            metrics[node.name] = (w, h)
    else:
        for node in graph.nodes:
            metrics[node.name] = (width_for(raw[node.name]),
                                  2 * pad_y + len(raw[node.name]) * line_h)
    # stash the wrapped lines on each node for rendering
    for node in graph.nodes:
        node.lines = raw[node.name]
    return metrics


# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------

#: (fill, stroke) per node category.  The palette is muted and high-contrast
#: so the diagram reads well at a glance and stays legible when scaled down.
PALETTES = {
    NODE_NORMAL: ("#f8f9fa", "#495057"),
    NODE_ENTRYPOINT: ("#d1e7dd", "#146c43"),  # green
    NODE_DEAD_END: ("#fff3cd", "#997404"),  # amber
    NODE_UNREACHABLE: ("#f8d7da", "#a71d2a"),  # red
    NODE_MISSING: ("#ffffff", "#dc3545"),  # white w/ red dashed border
}

#: edge stroke colours
EDGE_COLORS = {
    EDGE_NORMAL: "#6c757d",
    EDGE_BROKEN: "#dc3545",
    EDGE_BACK: "#8b5cf6",  # violet, to set loops apart from normal flow
}


# ---------------------------------------------------------------------------
# Edge geometry
# ---------------------------------------------------------------------------


def _edge_path(graph: StoryGraph, e: GEdge) -> Tuple[str, str]:
    """Return (d_attribute, marker_end) for one edge.

    Edges leave the bottom of their source box and enter the top of their
    target box (for TB), or the sides for LR.  A cubic bezier is used so the
    line bows smoothly when a target sits to the side of its source; back
    edges (cycles) are routed around the outside so they do not overlap the
    forward flow.
    """
    s = graph.node_by_name[e.src]
    t = graph.node_by_name[e.dst]
    marker = "url(#arrow-" + e.kind + ")"

    if graph.orientation == "LR":
        sx = s.x + s.w / 2.0
        sy = s.y
        tx = t.x - t.w / 2.0
        ty = t.y
        if e.kind == EDGE_BACK:
            # route the loop around below both boxes
            bend = max(s.y, t.y) + 40
            return (
                "M %.1f %.1f C %.1f %.1f, %.1f %.1f, %.1f %.1f" % (sx, sy, sx + 30, bend, tx - 30, bend, tx, ty),
                marker,
            )
        dx = max(20.0, abs(tx - sx) * 0.5)
        return (
            "M %.1f %.1f C %.1f %.1f, %.1f %.1f, %.1f %.1f" % (sx, sy, sx + dx, sy, tx - dx, ty, tx, ty),
            marker,
        )

    # TB (default): flow is top -> bottom
    if e.kind == EDGE_BACK:
        # loop around the right side of both boxes
        bend = max(s.x, t.x) + 40
        return (
            "M %.1f %.1f C %.1f %.1f, %.1f %.1f, %.1f %.1f" % (s.x, s.y + s.h / 2.0, bend, s.y + 30, bend, t.y - 30, t.x, t.y - t.h / 2.0),
            marker,
        )
    sx = s.x
    sy = s.y + s.h / 2.0
    tx = t.x
    ty = t.y - t.h / 2.0
    dy = max(20.0, abs(ty - sy) * 0.5)
    return (
        "M %.1f %.1f C %.1f %.1f, %.1f %.1f, %.1f %.1f" % (sx, sy, sx, sy + dy, tx, ty - dy, tx, ty),
        marker,
    )


# ---------------------------------------------------------------------------
# SVG rendering
# ---------------------------------------------------------------------------


def _fmt(value: float) -> str:
    """Format a coordinate for the SVG (drop a trailing .0)."""
    return ("%.1f" % value).rstrip("0").rstrip(".") if "." in ("%.1f" % value) else "%d" % int(value)


def _render_svg(graph: StoryGraph, font_size: float, margin: float,
                title: Optional[str]) -> str:
    """Render a laid-out :class:`StoryGraph` to an SVG string."""
    nodes = graph.nodes
    if not nodes:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>\n'

    # bounding box of the laid-out coordinates (centres + half extents)
    min_x = min(n.x - n.w / 2.0 for n in nodes)
    max_x = max(n.x + n.w / 2.0 for n in nodes)
    min_y = min(n.y - n.h / 2.0 for n in nodes)
    max_y = max(n.y + n.h / 2.0 for n in nodes)

    title_block_h = (font_size * 1.6) if title else 0.0
    # translate so the top-left of the content sits at (margin, margin+title)
    ox = -min_x + margin
    oy = -min_y + margin + title_block_h
    width = (max_x - min_x) + 2 * margin
    height = (max_y - min_y) + 2 * margin + title_block_h

    parts: List[str] = []
    # viewBox is the whole canvas in user units; width/height give a sensible
    # default raster size but any viewer can scale freely (vector output).
    parts.append(
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'viewBox="0 0 %s %s" width="%s" height="%s" '
        "font-family='-apple-system, \"Segoe UI\", Roboto, Helvetica, Arial, sans-serif'>"
        % (_fmt(width), _fmt(height), _fmt(width), _fmt(height))
    )

    # arrowhead markers, one per edge kind so colours match the line
    parts.append("<defs>")
    for kind in (EDGE_NORMAL, EDGE_BROKEN, EDGE_BACK):
        color = EDGE_COLORS[kind]
        parts.append(
            '<marker id="arrow-%s" viewBox="0 0 10 10" refX="9" refY="5" '
            'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            '<path d="M 0 0 L 10 5 L 0 10 z" fill="%s"/></marker>' % (kind, color)
        )
    parts.append("</defs>")

    if title:
        parts.append(
            '<text x="%s" y="%s" font-size="%s" font-weight="600" '
            'fill="#212529" text-anchor="start">%s</text>'
            % (margin, margin + font_size * 1.1, font_size * 1.4, _xml.escape(title))
        )

    # edges first so boxes paint over their endpoints
    parts.append('<g fill="none" stroke-width="1.5">')
    for e in graph.edges:
        d, marker = _edge_path(graph, e)
        style = 'stroke="%s"' % EDGE_COLORS[e.kind]
        if e.kind == EDGE_BROKEN:
            style += ' stroke-dasharray="6 4"'
        elif e.kind == EDGE_BACK:
            style += ' stroke-dasharray="2 3"'
        parts.append(
            '<path d="%s" %s marker-end="%s" transform="translate(%s %s)"/>'
            % (d, style, marker, _fmt(ox), _fmt(oy))
        )
    parts.append("</g>")

    # nodes: a rounded rect + its label lines
    line_h = font_size * 1.35
    parts.append('<g stroke-width="1.5">')
    for node in nodes:
        fill, stroke = PALETTES.get(node.category, PALETTES[NODE_NORMAL])
        x = node.x - node.w / 2.0 + ox
        y = node.y - node.h / 2.0 + oy
        dash = "" 
        if node.category == NODE_MISSING:
            dash = ' stroke-dasharray="5 3"'
        penw = "2" if node.category == NODE_ENTRYPOINT else "1.5"
        parts.append(
            '<rect x="%s" y="%s" width="%s" height="%s" rx="6" ry="6" '
            'fill="%s" stroke="%s" stroke-width="%s"%s/>'
            % (_fmt(x), _fmt(y), _fmt(node.w), _fmt(node.h), fill, stroke, penw, dash)
        )
        # label: name line(s) + optional preview lines.  The first line is the
        # section name (bold); any further lines are the body preview (muted).
        lines = node.lines
        if not lines:
            continue
        block_h = len(lines) * line_h
        top = node.y - block_h / 2.0 + oy
        for i, line in enumerate(lines):
            ty = top + (i + 0.5) * line_h
            cx = node.x + ox
            if i == 0:
                weight = "600"
                color = "#212529"
                size = font_size
            else:
                weight = "400"
                color = "#6c757d"
                size = font_size * 0.85
            parts.append(
                '<text x="%s" y="%s" font-size="%s" font-weight="%s" '
                'fill="%s" text-anchor="middle">%s</text>'
                % (_fmt(cx), _fmt(ty + size * 0.35), _fmt(size), weight, color, _xml.escape(line))
            )
    parts.append("</g>")

    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def to_svg(
    text: str,
    orientation: str = "TB",
    labels: str = "name",
    preview_chars: int = 48,
    title: Optional[str] = None,
    font_size: float = 13.0,
    result: Optional[CheckResult] = None,
) -> str:
    """Render the story tree of narrative yaml ``text`` to an SVG string.

    The SVG is vector-only and carries a ``viewBox`` (no fixed pixel grid),
    so it stays crisp at any zoom level or when embedded at any size.

    :param text: narrative yaml text.
    :param orientation: ``"TB"`` (top-to-bottom, default) or ``"LR"``.
    :param labels: ``"name"``, ``"preview"`` or ``"off"`` (see
        :func:`build_story_graph`).
    :param preview_chars: cap for ``"preview"`` label length.
    :param title: optional heading rendered above the diagram.
    :param font_size: base font size in user units.
    :param result: an already-computed :class:`~beware.check.CheckResult` to
        avoid re-running the structural check.
    """
    graph = build_story_graph(text, labels=labels, preview_chars=preview_chars,
                              result=result)
    graph.orientation = orientation
    graph.title = title

    layout = _Layout(graph, orientation)
    back_edges = layout.assign_layers()
    # tag cycle edges so they render dashed/violet instead of solid
    for e in graph.edges:
        if (e.src, e.dst) in back_edges and e.kind == EDGE_NORMAL:
            e.kind = EDGE_BACK
    layout.order_nodes()
    metrics = _compute_metrics(
        graph,
        font_size=font_size,
        pad_x=10.0,
        pad_y=7.0,
        min_w=48.0,
        max_w=260.0,
    )
    for node in graph.nodes:
        node.w, node.h = metrics[node.name]
    layout.assign_coordinates(metrics, flow_gap=36.0, across_gap=28.0)

    # orient LR by swapping x/y after a TB layout (keeps one code path)
    if orientation == "LR":
        for node in graph.nodes:
            node.x, node.y = node.y, node.x
            node.w, node.h = node.h, node.w

    return _render_svg(graph, font_size=font_size, margin=24.0, title=title)
