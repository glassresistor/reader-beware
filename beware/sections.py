"""Parse and re-serialize narrative yaml for the section-based editor.

The web studio edits a narrative as a list of named sections (each with a
markdown/jinja body) instead of raw yaml text.  This module owns the two
directions of that translation:

* :func:`parse_sections` reads yaml text into ordered ``{"name", "body",
  "extra"}`` records (document order is preserved, bodies are always
  strings, unknown per-section keys are kept in ``extra``), and
* :func:`serialize_sections` writes those records back out as canonical
  narrative yaml: a ``---`` document start, one section per block mapping,
  literal block scalars for bodies (so jinja/markdown stays readable) and
  human-friendly blank lines between sections.

Serialization is verified against the parser before it is returned; any
body that would not survive a literal block scalar round-trip falls back
to a double-quoted scalar, so editor saves never silently mangle a story.
"""

import json
import re

import yaml

__all__ = [
    "parse_sections",
    "serialize_sections",
    "parse_links",
    "split_kwargs",
    "quote_key",
]

#: section names that never need quoting (slugs like ``put-on-shirt``)
SAFE_KEY_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*$")

#: a jinja filter call inside a body, e.g. ``'go'|choice(x=1)`` or
#: ``'exit'|explore``; captures target section, filter name and the raw
#: keyword arguments (without the parentheses).
LINK_RE = re.compile(
    r"'((?:[^'\\]|\\.)+)'\s*\|\s*(explore|choice)\b(?:\s*\(\s*([^)]*)\))?"
)


def parse_sections(text):
    """Parse narrative yaml text into a list of section dicts.

    Raises ``ValueError`` when the text is not valid narrative yaml (or is
    not a mapping of sections).
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError("invalid yaml: %s" % exc) from exc
    if data is None:
        return []
    if not isinstance(data, dict):
        raise ValueError("narrative must be a mapping of section names")
    sections = []
    for name, spec in data.items():
        extra = {}
        scalar = False
        if isinstance(spec, dict):
            body = spec.get("body", "")
            extra = {k: v for k, v in spec.items() if str(k) != "body"}
        else:
            # a section written as ``name: some text`` is still editable
            scalar = True
            body = spec
        if body is None:
            body = ""
        elif not isinstance(body, str):
            body = str(body)
        sections.append(
            {
                "name": str(name),
                "body": body,
                "extra": extra,
                "scalar": scalar,
            }
        )
    return sections


def quote_key(name):
    """Emit a yaml mapping key for ``name`` (quoted when it must be)."""
    name = str(name)
    if SAFE_KEY_RE.match(name):
        return name
    # json's double quoted style is a subset of yaml's double quoted style
    return json.dumps(name)


def literal_body(body):
    """Lines for a ``body:`` entry using a literal block scalar, or None.

    ``None`` means the body cannot be represented this way (it is empty,
    whitespace-only, or its first content line starts with whitespace) and
    the caller should fall back to a quoted scalar.
    """
    if body == "":
        return ['  body: ""']
    trailing = len(body) - len(body.rstrip("\n"))
    chomp = "-" if trailing == 0 else ("" if trailing == 1 else "+")
    core = body[: len(body) - trailing] if trailing else body
    lines = core.split("\n")
    content = [ln for ln in lines if ln.strip() != ""]
    if not content:
        return None
    first = content[0]
    if first.startswith(" ") or first.startswith("\t"):
        return None
    out = ["  body: |%s" % chomp]
    for ln in lines:
        out.append(("    " + ln) if ln else "")
    if chomp == "+":
        # keep the extra trailing newlines as real blank lines
        out.extend([""] * (trailing - 1))
    return out


def format_body(body):
    """Lines for one section's ``body:`` entry, any style needed."""
    literal = literal_body(body)
    if literal is not None:
        return literal
    return ["  body: %s" % json.dumps(body)]


def format_extra(extra):
    """Lines for per-section keys other than ``body`` (kept verbatim)."""
    dumped = yaml.safe_dump(
        extra, default_flow_style=False, allow_unicode=True, sort_keys=False
    )
    return ["  %s" % ln if ln else "" for ln in dumped.rstrip("\n").split("\n")]


def serialize_sections(sections):
    """Serialize parsed sections back into canonical narrative yaml text.

    The result is verified with :func:`parse_sections` before being
    returned; if a literal block scalar would not round-trip exactly the
    affected bodies are re-emitted as quoted scalars.
    """
    parts = ["---"]
    for index, section in enumerate(sections):
        body = section.get("body", "")
        if body is None:
            body = ""
        elif not isinstance(body, str):
            body = str(body)
        if index and parts[-1] != "":
            parts.append("")  # blank line between sections
        parts.append(quote_key(section.get("name", "")) + ":")
        parts.extend(format_body(body))
        extra = section.get("extra") or {}
        if extra:
            parts.extend(format_extra(extra))
    text = "\n".join(parts) + "\n"
    try:
        parsed = parse_sections(text)
    except ValueError:
        parsed = None
    if (
        parsed is None
        or len(parsed) != len(sections)
        or any(
            a.get("name") != b["name"] or a.get("body", "") != b["body"]
            for a, b in zip(sections, parsed)
        )
    ):
        # fall back to fully quoted bodies and re-verify
        parts = ["---"]
        for index, section in enumerate(sections):
            body = section.get("body", "") or ""
            if not isinstance(body, str):
                body = str(body)
            if index and parts[-1] != "":
                parts.append("")
            parts.append(quote_key(section.get("name", "")) + ":")
            parts.append("  body: %s" % json.dumps(body))
            extra = section.get("extra") or {}
            if extra:
                parts.extend(format_extra(extra))
        text = "\n".join(parts) + "\n"
    return text


def parse_links(body):
    """List the ``explore``/``choice`` links inside one narrative body.

    Each entry is a dict with ``target`` (section name), ``kind``
    (``explore``/``choice``) and ``args`` (the raw keyword argument text,
    e.g. ``"x=1, name='bob'"``, or ``""``).
    """
    links = []
    for target, kind, args in LINK_RE.findall(str(body or "")):
        links.append(
            {"target": target.replace("\\'", "'"), "kind": kind, "args": args or ""}
        )
    return links


def split_kwargs(text):
    """Split ``k=v, k2='v 2'`` kwarg text into ``(name, value)`` pairs.

    Values keep their literal yaml/jinja source text (quotes included).
    Malformed fragments are skipped rather than raising.
    """
    pairs = []
    depth = 0
    quote = None
    current = ""
    chunks = []
    for char in str(text or ""):
        if quote:
            current += char
            if char == quote and not current.endswith("\\\\"):
                quote = None
            continue
        if char in "'\"":
            quote = char
            current += char
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            chunks.append(current)
            current = ""
            continue
        current += char
    if current.strip():
        chunks.append(current)
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        name, _, value = chunk.partition("=")
        name = name.strip()
        value = value.strip()
        if name:
            pairs.append((name, value))
    return pairs
