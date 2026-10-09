"""A tiny flask webapp for editing reader-beware narratives.

Serves an in-browser editor that:
  * lists and opens ``*.yaml``/``*.yml`` story files under a root folder,
  * edits raw YAML text with autosave (writes on save) to disk,
  * validates the narrative against the actual builder semantics
    (entrypoint present, all linked sections defined),
  * reloads yaml files on save so external changes are picked up.

Run it with::

    beware serve --root stories_folder --port 8181
"""

import os
import re
import tempfile

import yaml
from flask import (Flask, abort, jsonify, redirect, render_template,
                   request, url_for)

#: matches a jinja filter call in narrative bodies, e.g. ``'go'|choice(x=1)``
#: capturing (filter_name, first_argument).  The target section is the value
#: of the *first* positional argument; with `explore`/`choice` it may also be
#: written as a bare string before the pipe.
FILTER_RE = re.compile(
    r"'([^']*)'\s*\|\s*(?:(explore)|(choice))\b")
YAML_EXTENSIONS = ('.yaml', '.yml')


def list_stories(root):
    """Return story file paths (relative to root) under ``root``."""
    stories = []
    for dirpath, _dirs, files in os.walk(root):
        for name in sorted(files):
            if os.path.splitext(name)[1] in YAML_EXTENSIONS:
                rel = os.path.relpath(os.path.join(dirpath, name), root)
                stories.append(rel.replace(os.sep, '/'))
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
        return ['invalid yaml: %s' % str(exc)]
    if not isinstance(data, dict):
        return ['narrative must be a mapping of section names']
    if 'entrypoint' not in data:
        errors.append('missing entrypoint section')
    from jinja2 import Environment
    env = Environment()
    for name, section in sorted(data.items()):
        body = ''
        if isinstance(section, dict):
            body = str((section or {}).get('body', '') or '')
        else:
            body = str(section)
        try:
            env.parse(body)
        except Exception as exc:
            errors.append('%s: jinja error: %s' % (name, exc))
        for target, explore, choice in FILTER_RE.findall(body):
            kind = 'explore' if explore else 'choice'
            if not isinstance(data.get(target), dict) or 'body' not in \
                    data[target]:
                errors.append(
                    '%s links to undefined section %r (%s)' % (
                        name, target, kind))
    return errors


def create_app(root=None):
    """Build the flask app for editing stories under ``root``.

    If ``root`` is None a temporary directory is used (useful for tests and
    zero-config demos).
    """
    if root is None:
        root = tempfile.mkdtemp(prefix='reader-beware-web-')
    root = os.path.realpath(root)

    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), 'templates',
                                      'web'),
    )
    # narrative bodies contain raw html/template syntax; the jinja env used
    # for web pages must escape everything by default (except .j2 templates
    # are rendered with autoescape on via Flask's own env, which we enable)
    app.jinja_env.autoescape = True

    def story_path(rel):
        """Absolute path for a relative story name (rejects traversal)."""
        target = os.path.realpath(os.path.join(root, rel))
        # containment check: realpath must stay under root
        if target != root and \
                not target.startswith(root + os.sep):
            abort(404)
        ext = os.path.splitext(target)[1]
        if ext not in YAML_EXTENSIONS:
            abort(404)
        return target

    @app.route('/')
    def index():
        stories = list_stories(root)
        return render_template('index.html.j2', root=root, stories=stories)

    @app.route('/new', methods=['GET'])
    def new_story_form():
        return render_template(
            'edit.html.j2', story=None, text='', errors=[], root=root,
            created=True)

    @app.route('/save/<path:rel>', methods=['POST'])
    def save(rel):
        target = story_path(rel)
        data = request.form.get('body', '')
        errors = validate_narrative(data) if data.strip() else []
        if not data.strip():
            errors = ['story text is empty']
        if errors:
            return render_template(
                'edit.html.j2', story=rel, text=data, errors=errors,
                root=root, created=False)
        # atomic-ish write: temp file then rename so reloads are consistent
        tmp = target + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(data)
        os.replace(tmp, target)
        return redirect(url_for('edit', rel=rel))

    @app.route('/<path:rel>', methods=['GET'])
    def edit(rel):
        target = story_path(rel)
        if not os.path.exists(target):
            abort(404)
        with open(target, 'r', encoding='utf-8') as f:
            text = f.read()
        errors = validate_narrative(text)
        return render_template(
            'edit.html.j2', story=rel, text=text, errors=errors,
            root=root, created=False)

    @app.route('/create/<path:rel>', methods=['POST'])
    def create(rel):
        target = story_path(rel)
        data = request.form.get('body', '')
        errors = validate_narrative(data) if data.strip() else []
        if not data.strip():
            errors = ['story text is empty']
        if os.path.exists(target):
            errors.append('file already exists: %s' % rel)
        if errors:
            return render_template(
                'edit.html.j2', story=rel, text=data, errors=errors,
                root=root, created=True)
        parent = os.path.dirname(target)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)
        tmp = target + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(data)
        os.replace(tmp, target)
        return redirect(url_for('edit', rel=rel))

    @app.route('/validate/<path:rel>', methods=['POST'])
    def validate(rel):
        """API endpoint used by autosave; returns json errors."""
        story_path(rel)  # security check only
        data = request.form.get('body', '')
        return jsonify({'errors': validate_narrative(data)})

    @app.route('/delete/<path:rel>', methods=['POST'])
    def delete(rel):
        target = story_path(rel)
        if not os.path.exists(target):
            abort(404)
        os.unlink(target)
        return redirect(url_for('index'))

    app.root_folder = root  # exposed for tests / introspection
    return app
