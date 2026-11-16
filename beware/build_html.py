"""Build html pages from a reader-beware narrative (also the base class)."""

import json
import os
import shutil
import urllib.parse
import yaml

from markdown2 import Markdown
from jinja2 import Environment, FileSystemLoader
from beware.meta import BookMetadata

#: language stamped onto every rendered page, so assistive tech voices the
#: prose correctly instead of falling back to whatever the reader's system
#: happens to speak (an xml:lang alone is not read by html user agents)
DEFAULT_LANGUAGE = "en-US"


class NarrativeWorldBuilder(object):

    #: When True section filenames are percent-encoded so they are always
    #: valid urls/uris (needed for epub/xhtml; html builds keep them raw).
    encode_filenames = False

    #: Maximum number of sections to render (None means no limit).  Guards
    #: against accidentally generating a book that never terminates.
    max_sections = None

    #: If True, filenames in a folder are used as section names. 
    #: If False, section names are extracted from filename__section_name.
    folder_mode_filename_as_section = True

    def __init__(self, narrative_path, output_path, meta=None):
        self.narrative_path = os.path.realpath(narrative_path)
        self.output_path = output_path
        self.meta = meta
        self.base_dir = os.path.dirname(os.path.realpath(__file__))
        template_dir = os.path.join(self.base_dir, "templates")
        self.env = Environment(loader=FileSystemLoader(template_dir))
        # markdown2's default behaviour: plain markdown only.  Override
        # `markdown_extras` to enable markdown2 extensions (pluggable).
        self.markdown_extras = ()
        self._markdowner = None
        self.section_names = []
        self.render_next = []
        # Register the default jinja2 filters.  These are pluggable: any
        # code (including user extensions) can call `register_filter` to
        # add or replace a filter before building.
        self.register_default_filters()

        if os.path.isfile(self.narrative_path):
            self._load_single_file()
        elif os.path.isdir(self.narrative_path):
            self._load_folder()
        else:
            raise FileNotFoundError("Narrative path %r is not a file or directory" % self.narrative_path)

    def _load_single_file(self):
        with open(self.narrative_path, "r") as f:
            self.narratives = yaml.safe_load(f)
        if not isinstance(self.narratives, dict):
            raise ValueError("%s does not contain a narrative mapping" % self.narrative_path)

    def _load_folder(self):
        """Loads narratives from a folder of either bare markdown/jinja or YAML sections."""
        self.narratives = {}
        files = sorted([f for f in os.listdir(self.narrative_path) if os.path.isfile(os.path.join(self.narrative_path, f))])
        
        if not files:
            raise ValueError("Narrative folder %r is empty" % self.narrative_path)

        # Detect mode based on first file
        first_file = os.path.join(self.narrative_path, files[0])
        is_yaml_mode = False
        try:
            with open(first_file, "r") as f:
                # Try to see if it starts with something that looks like YAML
                content = f.read(512)
                if content.strip().startswith(("---", "{", "[")):
                    is_yaml_mode = True
        except Exception:
            is_yaml_mode = False

        for filename in files:
            file_path = os.path.join(self.narrative_path, filename)
            stem = os.path.splitext(filename)[0]
            
            if is_yaml_mode:
                # YAML mode: files contain sections (or are themselves sections if parsed as dict)
                with open(file_path, "r") as f:
                    import yaml
                    data = yaml.safe_load(f)
                if isinstance(data, dict):
                    # If the file itself is a mapping of sections
                    self.narratives.update(data)
                elif data is not None:
                    # A single scalar value in a YAML file might be intended as a section body?
                    # But user said "files with yaml sections", implying dicts.
                    raise ValueError("YAML mode requires files to contain section mappings")
            else:
                # Bare Markdown/Jinja mode
                section_name = stem
                if self.folder_mode_filename_as_section and "__" in stem:
                    # filename__section_name -> extract section_name
                    parts = stem.split("__", 1)
                    if len(parts) == 2:
                        section_name = parts[1]
                
                with open(file_path, "r") as f:
                    body = f.read()
                
                # In bare mode, we need to wrap it in the expected structure
                self.narratives[section_name] = {"body": body}

        if "entrypoint" not in self.narratives:
            raise ValueError("Narrative is missing an entrypoint section")

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
        if "entrypoint" not in self.narratives:
            raise ValueError(
                "narrative %r is missing an entrypoint section" % self.narrative_path
            )
        self.render_body("entrypoint", {})
        
        # Interstitial dead pages for HTML build
        if self.meta and self.meta.dead_pages:
            for idx, text in enumerate(self.meta.dead_page_texts()):
                path = "dead-page-%d-%d.html" % (0, idx)
                output_file = os.path.join(self.output_path, path)
                template = self.env.get_template("html/dead_page.html.j2")
                html = template.render(message=text, language=getattr(self.meta, 'language', 'en-US'))
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(html)

        while self.render_next:
            narrative = self.render_next.pop()
            if (
                self.max_sections is not None
                and len(self.section_names) >= self.max_sections
            ):
                raise RuntimeError(
                    "narrative generated more than %s sections; it may be "
                    "unbounded" % self.max_sections
                )
            self.render_body(*narrative)
        print("%s sections written" % len(self.section_names))

    def body(self, narrative_name):
        try:
            return self.narratives[narrative_name]["body"]
        except KeyError:
            raise KeyError(
                "section %r is linked to but not defined in the narrative "
                "file" % narrative_name
            )

    # -- paths ---------------------------------------------------------
    def section_id(self, narrative, world):
        """Unique id for a section+world combination."""
        return narrative + "-" + json.dumps(world, sort_keys=True)

    def narrative_path(self, narrative, world):
        """Filename (html by default) for a section+world combination."""
        return self.section_file(self.section_id(narrative, world))

    def section_file(self, base_name):
        """Encode a raw stem into a filename according to encode_filenames."""
        if not self.encode_filenames:
            return base_name + ".html"
        encoded = urllib.parse.quote(base_name, safe="")
        return encoded + ".html"

    # -- filters -------------------------------------------------------
    def explore(self, value):
        return self.choice(value)

    def choice(self, next_narrative, **update_vars):
        world = self._world_snapshot()
        world.update(update_vars)
        self.render_next.append([next_narrative, world])
        return self.narrative_path(next_narrative, world)

    # -- rendering -----------------------------------------------------
    def render_body(self, narrative_name, world):
        """Render one section to its final html file in the output folder."""
        path = self.narrative_path(narrative_name, world)
        if path in self.section_names:
            return
        self.section_names.append(path)
        body = self.body(narrative_name)
        type(self).push_current_world(world)
        markdown = self.env.from_string(body, globals=dict(world)).render()
        html_body = self.markdown_to_html(markdown)
        template = self.env.get_template("html/narrative.html.j2")
        raw_id = self.section_id(narrative_name, world)
        html = template.render(
            narrative_name=narrative_name,
            section_id=self.anchor_id(raw_id),
            path=self.anchor_id(raw_id),
            body=html_body,
            breadcrumb=self.breadcrumb(narrative_name, world),
            language=getattr(self, "language", DEFAULT_LANGUAGE),
        )
        output_file = os.path.join(self.output_path, path)
        with open(output_file, "w", encoding="utf-8") as output:
            output.write(html)

    def anchor_id(self, raw):
        """An xml-safe id derived from a section id (letter start required)."""
        import hashlib

        digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]
        return "sid-" + digest

    def hash_filename(self, raw):
        """Filesystem stem for a section whose raw name needs hashing.

        The same sid-<md5> digest the anchor id uses, without the
        .html suffix; the epub builder writes these as its section
        filenames (see EPubWorldBuilder.hash_filename), and site scripts
        need to find those pages again from a raw name.
        """
        return self.anchor_id(raw)

    def breadcrumb(self, narrative_name, world):
        """Human-readable page label: section name plus current world state."""
        if not world:
            return narrative_name
        parts = ", ".join(
            "%s=%s" % (key, value) for key, value in sorted(world.items())
        )
        return "%s (%s)" % (narrative_name, parts)
