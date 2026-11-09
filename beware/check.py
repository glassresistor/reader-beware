"""Validate narrative structure: broken links, unreachable sections, dead ends.

Produces a Graphviz DOT graph and a human-readable report of structural
problems in a narrative yaml file.
"""

import re
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import yaml

from beware.sections import parse_links, parse_sections


@dataclass
class CheckResult:
    """Aggregated results of a narrative structure check."""

    total_sections: int = 0
    entrypoint: Optional[str] = None
    broken_links: Dict[str, List[str]] = field(default_factory=dict)
    dead_ends: List[str] = field(default_factory=list)
    unreachable: List[str] = field(default_factory=list)
    adjacency: Dict[str, Set[str]] = field(default_factory=dict)
    sections: List[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return bool(self.entrypoint is None or self.broken_links or self.unreachable)

    def report(self) -> str:
        """Human-readable summary of all findings."""
        lines = []
        lines.append(f"Sections: {self.total_sections}")
        lines.append(f"Entrypoint: {'OK' if self.entrypoint else 'MISSING'}")
        lines.append("")

        if self.broken_links:
            lines.append("Broken links (target section does not exist):")
            for target, sources in sorted(self.broken_links.items()):
                for src in sources:
                    lines.append(f"  {src} -> {target}")
            lines.append("")

        if self.dead_ends:
            lines.append(
                f"Dead ends (no outgoing links; verify these are intentional endings):"
            )
            for name in sorted(self.dead_ends):
                lines.append(f"  {name}")
            lines.append("")

        if self.unreachable:
            lines.append("Unreachable sections (not reachable from entrypoint):")
            for name in sorted(self.unreachable):
                lines.append(f"  {name}")
            lines.append("")

        if not self.has_errors and not self.dead_ends:
            lines.append("No structural issues found.")

        return "\n".join(lines)


def check_narrative(text: str) -> CheckResult:
    """Run all structural checks on narrative yaml text."""
    sections_data = parse_sections(text)
    section_names = [s["name"] for s in sections_data]
    section_set = set(section_names)

    result = CheckResult(
        total_sections=len(section_names),
        sections=section_names,
    )

    # entrypoint check
    if "entrypoint" in section_set:
        result.entrypoint = "entrypoint"

    # build adjacency from links
    for sec in sections_data:
        name = sec["name"]
        links = parse_links(sec["body"])
        targets = {link["target"] for link in links}
        result.adjacency[name] = targets

    # broken links
    for name, targets in result.adjacency.items():
        for target in targets:
            if target not in section_set:
                result.broken_links.setdefault(target, []).append(name)

    # dead ends (no outgoing links)
    for name in section_names:
        if not result.adjacency.get(name):
            result.dead_ends.append(name)

    # reachability from entrypoint
    if result.entrypoint:
        seen: Set[str] = set()
        queue = deque([result.entrypoint])
        while queue:
            node = queue.popleft()
            if node in seen:
                continue
            seen.add(node)
            for neighbor in result.adjacency.get(node, ()):  # type: ignore[arg-type]
                if neighbor not in seen and neighbor in section_set:
                    queue.append(neighbor)
        result.unreachable = [s for s in section_names if s not in seen]

    return result


def to_dot(result: CheckResult) -> str:
    """Render a Graphviz DOT digraph of the narrative structure."""
    lines = []
    lines.append("digraph narrative {")
    lines.append("    rankdir=TB;")
    lines.append('    node [shape=box, style="rounded,filled", fillcolor="#f8f9fa"];')
    lines.append('    edge [color="#6c757d"];')
    lines.append("")

    # --- nodes ---
    for name in result.sections:
        attrs = []
        if name == result.entrypoint:
            attrs.append('fillcolor="#d4edda"')
            attrs.append("penwidth=2")
            attrs.append('label="%s\n(entrypoint)"' % name)
        elif name in result.unreachable:
            attrs.append('style="rounded,filled,dashed"')
            attrs.append('fillcolor="#f8d7da"')
            attrs.append('label="%s\n(unreachable)"' % name)
        elif name in result.dead_ends:
            attrs.append('fillcolor="#fff3cd"')
            attrs.append('label="%s\n(dead end)"' % name)
        else:
            attrs.append('label="%s"' % name)

        attr_str = ", ".join(attrs) if attrs else ""
        if attr_str:
            lines.append(f'    "{name}" [{attr_str}];')
        else:
            lines.append(f'    "{name}";')

    # phantom nodes for broken link targets
    for target in sorted(result.broken_links):
        lines.append(
            f'    "{target}" [shape=box, style="dashed,dotted", '
            f'fillcolor="white", color="#dc3545", label="{target}\n(missing)"];'
        )

    lines.append("")

    # --- edges ---
    for name in result.sections:
        for target in sorted(result.adjacency.get(name, ())):
            if target in result.broken_links:
                lines.append(
                    f'    "{name}" -> "{target}" [style=dashed, color="#dc3545"];'
                )
            else:
                lines.append(f'    "{name}" -> "{target}";')

    lines.append("}")
    return "\n".join(lines) + "\n"
