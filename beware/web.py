"""A tiny flask webapp for editing reader-beware narratives.

Serves an in-browser editor that:
  * lists and opens ``*.yaml``/``*.yml`` story files under a root folder,
  * edits a story as named sections (name + jinja/markdown body) with
    tools for building ``explore``/``choice`` links, live preview and
    autosave validation (the "studio" editor at ``/<story>``),
  * keeps a raw yaml editor at ``/raw/<story>`` for power editing,
  * validates the narrative against the actual builder semantics
    (entrypoint present, all linked sections defined),
  * reloads yaml files on save so external changes are picked up.

Run it with::

    beware serve --root stories_folder --port 8181
"""

import json
import os
import re
import tempfile

import markdown2
import yaml
from flask import Flask, abort, jsonify, redirect, render_template, request, url_for
from jinja2 import ChainableUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment

from beware.sections import parse_links, parse_sections, serialize_sections

#: matches a jinja filter call in narrative bodies, e.g. ``'go'|choice(x=1)``
#: capturing (filter_name, first_argument).  The target section is the value
#: of the *first* positional argument; with `explore`/`choice` it may also be
#: written as a bare string before the pipe.
FILTER_RE = re.compile(r"'([^']*)'\s*\|\s*(?:(explore)|(choice))\b")
YAML_EXTENSIONS = (".yaml", ".yml")


def list_stories(root):
    """Return story file paths (relative to root) under ``root``."""
    stories = []
    for dirpath, _dirs, files in os.walk(root):
        for name in sorted(files):
            if os.path.splitext(name)[1] in YAML_EXTENSIONS:
                rel = os.path.relpath(os.path.join(dirpath, name), root)
                stories.append(rel.replace(os.sep, "/"))
    return sorted(stories)


def validate_narrative(text):
    """Validate narrative yaml text; return a list of error strings.

    Mirrors builder rules: valid YAML mapping, an ``entrypoint`` section,
    every section linked via explore/choice exists, and each body parses as
    jinja2 (a full render needs world state so only parse errors are shown).
    """
    errors = []
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return ["invalid yaml: %s" % str(exc)]
    if not isinstance(data, dict):
        return ["narrative must be a mapping of section names"]
    if "entrypoint" not in data:
        errors.append("missing entrypoint section")
    from jinja2 import Environment

    env = Environment()
    for name, section in sorted(data.items()):
        body = ""
        if isinstance(section, dict):
            body = str((section or {}).get("body", "") or "")
        else:
            body = str(section)
        try:
            env.parse(body)
        except Exception as exc:
            errors.append("%s: jinja error: %s" % (name, exc))
        for target, explore, choice in FILTER_RE.findall(body):
            kind = "explore" if explore else "choice"
            if not isinstance(data.get(target), dict) or "body" not in data[target]:
                errors.append(
                    "%s links to undefined section %r (%s)" % (name, target, kind)
                )
    return errors


def validate_payload(sections):
    """Validate studio payload sections; return a list of error strings.

    Covers editor-only problems the raw text validator cannot see (empty or
    duplicated section names) before the payload is serialized.
    """
    errors = []
    seen = set()
    for section in sections:
        name = str(section.get("name", "")).strip()
        if not name:
            errors.append("section name is empty")
        elif name in seen:
            errors.append("duplicate section name: %s" % name)
        seen.add(name)
    return errors


def load_payload(form):
    """Decode a studio payload (json in the ``payload`` field) to sections.

    Returns ``(sections, errors)``; either may be empty lists.
    """
    raw = form.get("payload", "")
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as exc:
        return [], ["invalid payload: %s" % exc]
    sections = data.get("sections") if isinstance(data, dict) else None
    if not isinstance(sections, list):
        return [], ["payload must contain a list of sections"]
    clean = []
    for item in sections:
        if not isinstance(item, dict):
            return [], ["payload section entries must be objects"]
        extra = {}
        source = item.get("extra", "")
        if isinstance(source, dict):
            extra = source
        elif isinstance(source, str) and source.strip():
            try:
                loaded = yaml.safe_load(source)
            except yaml.YAMLError as exc:
                return [], ["invalid section extras: %s" % exc]
            if not isinstance(loaded, dict):
                return [], ["section extras must be a mapping"]
            extra = loaded
        clean.append(
            {
                "name": str(item.get("name", "")),
                "body": str(item.get("body", "") or ""),
                "extra": extra,
            }
        )
    return clean, []


def decorate_sections(sections):
    """Add editor-only fields (parsed links, extras source) in place."""
    for section in sections:
        body = section.get("body", "") or ""
        section["links"] = parse_links(body)
        extra = section.get("extra") or {}
        if isinstance(extra, dict) and extra:
            section["extra_yaml"] = yaml.safe_dump(
                extra,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            ).strip()
        else:
            section["extra_yaml"] = ""
    return sections


#: maximum rendered preview length returned to the browser
PREVIEW_LIMIT = 200_000

_TAG_RE = re.compile(r"<(?=[/!A-Za-z])")


def render_preview(body):
    """Render one narrative body (jinja + markdown) for editor preview.

    Uses a sandboxed jinja environment with ``explore``/``choice`` mapped
    to inert anchors, and escapes raw html tags before running markdown so
    story text can never inject scripts into the editor page.
    """
    env = SandboxedEnvironment(undefined=ChainableUndefined)

    def anchor(value, **kwargs):
        return "#%s" % str(value).strip().lower().replace(" ", "-")

    env.filters["explore"] = anchor
    env.filters["choice"] = anchor
    try:
        text = env.from_string(str(body)).render()
    except TemplateError as exc:
        return {"error": "jinja error: %s" % exc}
    except Exception as exc:  # sandboxed stories can raise SecurityError etc.
        return {"error": "preview failed: %s" % exc}
    text = _TAG_RE.sub("&lt;", text)
    if len(text) > PREVIEW_LIMIT:
        text = text[:PREVIEW_LIMIT] + "\n\n… (preview truncated)"
    html = markdown2.Markdown().convert(text)
    return {"html": html}


def create_app(root=None):
    """Build the flask app for editing stories under ``root``.

    If ``root`` is None a temporary directory is used (useful for tests and
    zero-config demos).
    """
    if root is None:
        root = tempfile.mkdtemp(prefix="reader-beware-web-")
    root = os.path.realpath(root)

    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "templates", "web"),
    )
    # narrative bodies contain raw html/template syntax; the jinja env used
    # for web pages must escape everything by default (except .j2 templates
    # are rendered with autoescape on via Flask's own env, which we enable)
    app.jinja_env.autoescape = True

    def story_path(rel):
        """Absolute path for a relative story name (rejects traversal)."""
        target = os.path.realpath(os.path.join(root, rel))
        # containment check: realpath must stay under root
        if target != root and not target.startswith(root + os.sep):
            abort(404)
        ext = os.path.splitext(target)[1]
        if ext not in YAML_EXTENSIONS:
            abort(404)
        return target

    @app.route("/")
    def index():
        stories = list_stories(root)
        return render_template("index.html.j2", root=root, stories=stories)

    @app.route("/new", methods=["GET"])
    def new_story_form():
        sections = decorate_sections([{"name": "entrypoint", "body": "", "extra": {}}])
        names = [section["name"] for section in sections]
        return render_template(
            "sections.html.j2",
            story=None,
            sections=sections,
            names=names,
            errors=[],
            root=root,
            created=True,
            parse_error=None,
        )

    @app.route("/new/raw", methods=["GET"])
    def new_story_raw_form():
        return render_template(
            "edit.html.j2", story=None, text="", errors=[], root=root, created=True
        )

    @app.route("/save/<path:rel>", methods=["POST"])
    def save(rel):
        target = story_path(rel)
        data = request.form.get("body", "")
        errors = validate_narrative(data) if data.strip() else []
        if not data.strip():
            errors = ["story text is empty"]
        if errors:
            return render_template(
                "edit.html.j2",
                story=rel,
                text=data,
                errors=errors,
                root=root,
                created=False,
            )
        # atomic-ish write: temp file then rename so reloads are consistent
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, target)
        return redirect(url_for("edit", rel=rel))

    @app.route("/raw/<path:rel>", methods=["GET"])
    def edit_raw(rel):
        target = story_path(rel)
        if not os.path.exists(target):
            abort(404)
        with open(target, "r", encoding="utf-8") as f:
            text = f.read()
        errors = validate_narrative(text)
        return render_template(
            "edit.html.j2",
            story=rel,
            text=text,
            errors=errors,
            root=root,
            created=False,
        )

    @app.route("/<path:rel>", methods=["GET"])
    def edit(rel):
        target = story_path(rel)
        if not os.path.exists(target):
            abort(404)
        with open(target, "r", encoding="utf-8") as f:
            text = f.read()
        errors = validate_narrative(text)
        parse_error = None
        try:
            sections = decorate_sections(parse_sections(text))
        except ValueError as exc:
            parse_error = str(exc)
            sections = []
        names = [section["name"] for section in sections]
        return render_template(
            "sections.html.j2",
            story=rel,
            sections=sections,
            names=names,
            errors=errors,
            root=root,
            created=False,
            parse_error=parse_error,
            text=text,
        )

    @app.route("/write/<path:rel>", methods=["POST"])
    def write(rel):
        """Studio save endpoint; takes a payload and answers with json."""
        target = story_path(rel)
        sections, errors = load_payload(request.form)
        if not errors:
            errors = validate_payload(sections)
        if not errors:
            text = serialize_sections(sections)
            errors = validate_narrative(text)
        if errors:
            return jsonify({"ok": False, "errors": errors}), 400
        parent = os.path.dirname(target)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, target)
        return jsonify({"ok": True, "errors": []})

    @app.route("/preview/<path:rel>", methods=["POST"])
    def preview(rel):
        """Render one section body (jinja + markdown) for the editor."""
        story_path(rel)  # security check only
        body = request.form.get("body", "")
        return jsonify(render_preview(body))

    @app.route("/create/<path:rel>", methods=["POST"])
    def create(rel):
        target = story_path(rel)
        payload = request.form.get("payload")
        if payload:
            # studio flow: answer with json so the editor can redirect or
            # show the problems without a full page reload
            sections, errors = load_payload(request.form)
            if not errors:
                errors = validate_payload(sections)
            data = serialize_sections(sections) if not errors else ""
            if not errors and not data.strip():
                errors = ["story text is empty"]
            if os.path.exists(target):
                errors.append("file already exists: %s" % rel)
            if not errors:
                errors = validate_narrative(data)
            if errors:
                return jsonify({"ok": False, "errors": errors}), 400
        else:
            data = request.form.get("body", "")
            errors = validate_narrative(data) if data.strip() else []
            if not data.strip():
                errors = ["story text is empty"]
            if os.path.exists(target):
                errors.append("file already exists: %s" % rel)
            if errors:
                return render_template(
                    "edit.html.j2",
                    story=rel,
                    text=data,
                    errors=errors,
                    root=root,
                    created=True,
                )
        parent = os.path.dirname(target)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, target)
        if payload:
            return jsonify({"ok": True, "errors": []})
        return redirect(url_for("edit", rel=rel))

    @app.route("/validate/<path:rel>", methods=["POST"])
    def validate(rel):
        """API endpoint used by autosave; returns json errors.

        Accepts either raw yaml text in ``body`` or a studio ``payload``.
        """
        story_path(rel)  # security check only
        if request.form.get("payload"):
            sections, errors = load_payload(request.form)
            if not errors:
                errors = validate_payload(sections)
            if not errors:
                errors = validate_narrative(serialize_sections(sections))
            return jsonify({"errors": errors})
        data = request.form.get("body", "")
        return jsonify({"errors": validate_narrative(data)})

    @app.route("/delete/<path:rel>", methods=["POST"])
    def delete(rel):
        target = story_path(rel)
        if not os.path.exists(target):
            abort(404)
        os.unlink(target)
        return redirect(url_for("index"))

    app.root_folder = root  # exposed for tests / introspection
    return app
