"""Build real .epub books (EPUB 3) from reader-beware narratives."""

import base64
import hashlib
import mimetypes
import os
import posixpath
import shutil

from lxml import etree

from beware.build_html import NarativeWorldBuilder
from beware.meta import BookMetadata


def _xml_id(raw):
    """Turn an arbitrary string into a valid xml id (letter/underscore start)."""
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]
    return "sid-" + digest


def base64_safe(text):
    """url-safe ascii encoding, '=' padding stripped."""
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").strip("=")


#: map from mime type to a filename extension used inside the epub package
_MIME_SUFFIX = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
}

XHTML_MEDIA_TYPE = "application/xhtml+xml"


class EPubWorldBuilder(NarativeWorldBuilder):

    #: section filenames must be url-safe so they work as xhtml href targets
    encode_filenames = True

    def __init__(self, yaml_path, output_path, meta=None):
        super().__init__(yaml_path, output_path)
        self.meta = meta or BookMetadata()
        # spine order: list of (xml id, section filename) tuples
        self._spine_entries = []

    # -- filenames -----------------------------------------------------
    def xhtml_name(self, section_path):
        """Filename for a section inside the epub package."""
        stem = os.path.splitext(os.path.basename(section_path))[0]
        return posixpath.join("xhtml", stem + ".xhtml")

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
        xmlid = _xml_id(self.section_id(narative_name, world))
        self._spine_entries.append((xmlid, path))
        template = self.env.get_template("html/narative.html.j2")
        page = template.render(
            narative_name=narative_name, section_id=xmlid, path=xmlid, body=html_body
        )
        page = self.rewrite_links(page)
        output_file = os.path.join(self.output_path, path)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(page)

    def rewrite_links(self, page):
        """Rewrite hrefs from section .html files to epub xhtml targets.

        The explore/choice filters emit section filenames; inside the epub
        those point at nothing, so each one is mapped to its location in
        the package (xhtml/<name>.xhtml).
        """
        parser = etree.XMLParser(remove_blank_text=False)
        root = etree.fromstring(page.encode("utf-8"), parser)
        for elem in root.iter():
            href = elem.get("href")
            if not href or href.startswith(("http:", "https:", "#")):
                continue
            stem = os.path.splitext(os.path.basename(href))[0]
            target = posixpath.join("xhtml", stem + ".xhtml")
            elem.set("href", "../" + target)
        return etree.tostring(root, encoding="unicode", method="xml")

    # -- building ------------------------------------------------------
    def build(self):
        """Render every section into the output folder (unzipped view)."""
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
        shutil.copyfile(
            os.path.join(self.base_dir, "files", "template.css"),
            os.path.join(self.output_path, "template.css"),
        )

    def build_epub(self, meta=None):
        """Package the rendered pages into a real .epub file."""
        from ebooklib import epub

        if meta is not None:
            self.meta = meta

        book = epub.EpubBook()
        book.set_identifier(self.meta.identifier)
        book.set_title(self.meta.title)
        book.set_language(self.meta.language or "en-US")
        if self.meta.author:
            book.add_author(self.meta.author)

        # dc metadata that ebooklib does not expose via helpers.  The
        # expected shape is ``add_metadata(ns, tag, text_value, attrs)``.
        def add_dc(name, value):
            if value:
                book.add_metadata("DC", name, str(value))

        add_dc("subject", self.meta.subject)
        add_dc("description", self.meta.description)
        add_dc("publisher", self.meta.publisher)
        add_dc("rights", self.meta.rights)
        if self.meta.date:
            add_dc("date", self.meta.date)

        css_text_path = os.path.join(self.base_dir, "files", "template.css")
        with open(css_text_path, "r") as f:
            css_content = f.read().encode("utf-8")
        style_item = epub.EpubItem(
            uid="css",
            file_name="style/default.css",
            media_type="text/css",
            content=css_content,
        )
        book.add_item(style_item)

        spine_ids = []
        for xmlid, section_path in self._spine_entries:
            full = os.path.join(self.output_path, section_path)
            with open(full, "r", encoding="utf-8") as f:
                page_content = f.read().encode("utf-8")
            chapter = epub.EpubHtml(
                uid=xmlid,
                file_name=self.xhtml_name(section_path),
                media_type=XHTML_MEDIA_TYPE,
                lang=self.meta.language or "en-US",
            )
            # link the package stylesheet into every chapter so readers
            # apply the book theme (ebooklib drops <link> tags written
            # into the page head, so register them on the item instead)
            chapter.add_link(
                href="../style/default.css", rel="stylesheet", type="text/css"
            )
            chapter.content = page_content
            book.add_item(chapter)
            spine_ids.append(xmlid)

        if self.meta.has_cover:
            cover_data, mime = self._cover_bytes_and_mime()
            basename = posixpath.basename(str(self.meta.cover))
            stem = os.path.splitext(basename)[0] or "cover"
            image_uid = _xml_id("reader-beware-cover-" + str(stem))
            suffix = _MIME_SUFFIX.get(mime, "")
            safe_name = base64_safe(image_uid) + suffix
            image_item = epub.EpubImage(
                uid=image_uid,
                file_name="images/" + safe_name,
                media_type=mime,
                content=cover_data,
            )
            book.add_item(image_item)

        book.toc = []
        book.spine = spine_ids
        epub_file = "%s.epub" % self.output_path
        ok = epub.write_epub(epub_file, book, {"compresslevel": 6})
        if ok is False:
            raise IOError("failed to write epub file %s" % epub_file)
        return epub_file

    def _cover_bytes_and_mime(self):
        cover = str(self.meta.cover)
        candidates = [
            os.path.join(os.path.dirname(self.yaml_path), cover),
            os.path.join(os.getcwd(), cover),
            cover,
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                with open(candidate, "rb") as f:
                    data = f.read()
                mime = mimetypes.guess_type(candidate)[0] or "application/octet-stream"
                return data, mime
        raise IOError("cover image %r was not found" % cover)


class EPubBuilder(EPubWorldBuilder):
    """Alias kept for backwards compatibility with the old cli."""

    pass
