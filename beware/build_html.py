"""Build html pages from a reader-beware narrative (also the base class)."""

import json
import os
import shutil
import urllib.parse
import yaml

from markdown2 import Markdown
from jinja2 import Environment, FileSystemLoader


class NarativeWorldBuilder(object):

    #: When True section filenames are percent-encoded so they are always
    #: valid urls/uris (needed for epub/xhtml; html builds keep them raw).
    encode_filenames = False

    #: Maximum number of sections to render (None means no limit).  Guards
    #: against accidentally generating a book that never terminates.
    max_sections = None

    def __init__(self, yaml_path, output_path):
        self.yaml_path = os.path.realpath(yaml_path)
        with open(self.yaml_path, "r") as f:
            self.naratives = yaml.safe_load(f)
        if not isinstance(self.naratives, dict):
            raise ValueError("%s does not contain a narrative mapping" % yaml_path)
        self.base_dir = os.path.dirname(os.path.realpath(__file__))
        template_dir = os.path.join(self.base_dir, "templates")
        self.env = Environment(loader=FileSystemLoader(template_dir))
        # markdown2's default behaviour: plain markdown only.  Override
        # `markdown_extras` to enable markdown2 extensions (pluggable).
        self.markdown_extras = ()
        self._markdowner = None
        self.output_path = output_path
        self.section_names = []
        self.render_next = []
        # Register the default jinja2 filters.  These are pluggable: any
        # code (including user extensions) can call `register_filter` to
        # add or replace a filter before building.
        self.register_default_filters()

    def register_default_filters(self):
        """Register the built-in jinja2 filters used by narrative bodies."""
        self.register_filter("explore", self.explore)
        self.register_filter("choice", self.choice)

    def register_filter(self, name, function=None):
        """Plug a jinja2 filter into the build environment.

        Passing ``None`` as ``function`` removes the named filter.  Returns
        the previously registered function (or ``None``) so callers can
        save/restore filters around their own builds.
        """
        previous = self.env.filters.get(name)
        if function is None:
            self.env.filters.pop(name, None)
        else:
            self.env.filters[name] = function
        return previous

    @property
    def markdown_to_html(self):
        if self._markdowner is None:
            self._markdowner = Markdown(extras=list(self.markdown_extras))
        return self._markdowner.convert

    # Holds the world state of the section currently being rendered.  It is
    # a class attribute because jinja2 globals are shared between all
    # templates, so every filter invocation must read the live value.
    _current_world = {}

    @classmethod
    def push_current_world(cls, world):
        cls._current_world = dict(world)

    def _world_snapshot(self):
        """A copy of the world state of the section being rendered."""
        return dict(type(self)._current_world)

    # -- building ------------------------------------------------------
    def build(self):
        try:
            shutil.rmtree(self.output_path)
        except FileNotFoundError:
            pass
        os.makedirs(self.output_path, exist_ok=True)
        if "entrypoint" not in self.naratives:
            raise ValueError(
                "narrative %r is missing an entrypoint section" % self.yaml_path
            )
        self.render_body("entrypoint", {})
        while self.render_next:
            narative = self.render_next.pop()
            if (
                self.max_sections is not None
                and len(self.section_names) >= self.max_sections
            ):
                raise RuntimeError(
                    "narrative generated more than %s sections; it may be "
                    "unbounded" % self.max_sections
                )
            self.render_body(*narative)
        print("%s sections written" % len(self.section_names))

    def body(self, narative_name):
        try:
            return self.naratives[narative_name]["body"]
        except KeyError:
            raise KeyError(
                "section %r is linked to but not defined in the narrative "
                "file" % narative_name
            )

    # -- paths ---------------------------------------------------------
    def section_id(self, narative, world):
        """Unique id for a section+world combination."""
        return narative + "-" + json.dumps(world, sort_keys=True)

    def narative_path(self, narative, world):
        """Filename (html by default) for a section+world combination."""
        return self.section_file(self.section_id(narative, world))

    def section_file(self, base_name):
        """Encode a raw stem into a filename according to `encode_filenames`."""
        if not self.encode_filenames:
            return base_name + ".html"
        encoded = urllib.parse.quote(base_name, safe="")
        return encoded + ".html"

    # -- filters -------------------------------------------------------
    def explore(self, value):
        return self.choice(value)

    def choice(self, next_narative, **update_vars):
        world = self._world_snapshot()
        world.update(update_vars)
        self.render_next.append([next_narative, world])
        return self.narative_path(next_narative, world)

    # -- rendering -----------------------------------------------------
    def render_body(self, narative_name, world):
        """Render one section to its final html file in the output folder."""
        path = self.narative_path(narative_name, world)
        if path in self.section_names:
            return
        self.section_names.append(path)
        body = self.body(narative_name)
        type(self).push_current_world(world)
        markdown = self.env.from_string(body, globals=dict(world)).render()
        html_body = self.markdown_to_html(markdown)
        template = self.env.get_template("html/narative.html.j2")
        raw_id = self.section_id(narative_name, world)
        html = template.render(
            narative_name=narative_name,
            section_id=self.anchor_id(raw_id),
            path=self.anchor_id(raw_id),
            body=html_body,
        )
        output_file = os.path.join(self.output_path, path)
        with open(output_file, "w", encoding="utf-8") as output:
            output.write(html)

    def anchor_id(self, raw):
        """An xml-safe id derived from a section id (letter start required)."""
        import hashlib

        digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]
        return "sid-" + digest
