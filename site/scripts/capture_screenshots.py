#!/usr/bin/env python3
"""Render reader-beware artifacts for the github.io advertisement site.

No headless browser is involved: no playwright, no screenshots.  The script
uses reader beware's own builders plus the flask editor from ``create_app``
to render real html, which lands in ``site/embeds/`` and gets embedded into
``site/index.html`` as <iframe srcdoc="..."> examples -- static html and css
that renders identically on github pages and locally.

Artifacts produced (all from the repo's own build code):

* ``site/books/<name>/`` -- built html pages plus a real epub per example
  narrative (the same output as ``beware build-epub``),
* ``site/embeds/*.html`` -- rendered story pages, epub pages framed inside
  a mock e-reader device, and editor captures (story index, section studio
  with the live preview open, the explore/choice link tool mid-build, raw
  yaml editor),
* ``site/index.html`` -- rewritten in place: every placeholder comment is
  replaced by its embed (see PLACEHOLDERS).

The editor captures are rendered server-side through flask's test client
(no server socket, no browser): the studio page is fetched, then demo state
is injected into the returned html (the preview panel filled with the real
``/preview`` endpoint output, link tool fields set to typed values with the
built snippet baked in) so the static markup shows exactly what a running
editor would show.

Usage::

    python site/scripts/capture_screenshots.py
"""

import argparse
import html as html_module
import os
import posixpath
import re
import shutil
import sys
import tempfile
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
SITE_DIR = os.path.abspath(os.path.join(HERE, os.pardir))
REPO_ROOT = os.path.abspath(os.path.join(SITE_DIR, os.pardir))
sys.path.insert(0, REPO_ROOT)

import yaml  # noqa: E402  (demo bodies; beware depends on it anyway)

from beware.build_html import NarativeWorldBuilder  # noqa: E402
from beware.web import create_app  # noqa: E402

EMBEDS = os.path.join(SITE_DIR, "embeds")
BOOKS = os.path.join(SITE_DIR, "books")
INDEX = os.path.join(SITE_DIR, "index.html")
EXAMPLE_SRC = os.path.join(SITE_DIR, "examples-src")
BUILD_ROOT = os.path.join(tempfile.gettempdir(), "reader-beware-embeds")

#: example narratives compiled into site/books/ (epub + html pages); the
#: demo story only powers the editor captures, it is not a buildable book
BOOKS_TO_BUILD = ("shirts", "maze", "belair")


#: story page embeds: (book, built filename, embed name).  The pages must
#: carry links (the demos invite the reader to click through them), so a
#: terminal section like prince-of-belair is not what this shows.
STORY_EMBEDS = [
    ("shirts", "entrypoint-{}.html", "story-entry"),
    ("shirts", 'go-outside-{"shirt_color": "green"}.html', "story-state"),
    ("maze", "entrypoint-{}.html", "story-maze"),
    ("belair", "take-a-minute-{}.html", "story-belair"),
]

#: device-framed captures of epub-rendered pages: (book, filename in the
#: unzipped build folder, embed name, title, chrome text under the screen)
DEVICE_EMBEDS = [
    (
        "shirts",
        'entrypoint-{"shirt_color": "red"}.html',
        "device-red-shirt",
        "Red or Green?",
        "chapter 2 of 9 &#183; world: shirt_color=red",
    ),
    (
        "shirts",
        'go-outside-{"shirt_color": "green"}.html',
        "device-green-shirt",
        "Red or Green?",
        "chapter 6 of 9 &#183; world: shirt_color=green",
    ),
]

#: the editor story used for the studio/raw captures
DEMO_STORY = "demo.yaml"

#: demo values typed into the link tool for the capture
LINK_TEXT = "visit the hacker"
LINK_TARGET = "hacker"
LINK_KIND = "choice"
VARIABLES = [("credits", "10")]


def build_story(name):
    """Build one example narrative into BUILD_ROOT/<name>, return its folder."""
    src = os.path.join(EXAMPLE_SRC, name + ".yaml")
    out = os.path.join(BUILD_ROOT, name)
    builder = NarativeWorldBuilder(src, out)
    builder.build()
    return out


def write_embed(name, source):
    """Write rendered html to site/embeds/<name>.html; return its basename."""
    os.makedirs(EMBEDS, exist_ok=True)
    filename = name + ".html"
    with open(os.path.join(EMBEDS, filename), "w", encoding="utf-8") as f:
        f.write(source)
    print("embedded", filename)
    return filename


def template_css_source():
    """The stylesheet shipped with built story pages (beware/files/)."""
    import beware

    source = os.path.join(
        os.path.dirname(os.path.abspath(beware.__file__)), "files", "template.css"
    )
    with open(source, "r", encoding="utf-8") as f:
        return f.read()


def copy_template_css():
    """Publish beware/files/template.css into site/embeds/ (kept alongside
    the embeds for reference; pages inline their own copy)."""
    os.makedirs(EMBEDS, exist_ok=True)
    with open(os.path.join(EMBEDS, "template.css"), "w", encoding="utf-8") as f:
        f.write(template_css_source())
    print("embedded template.css")


def publish_filename(filename):
    """Filesystem name a built section page is published under in site/books/.

    The epub builder writes its unzipped debug pages with percent-encoded
    names already (encode_filenames), and the story embed targets are
    written raw (``entrypoint-{}.html``); publish both spellings as the
    *decoded* name, because github pages decodes a request path exactly
    once before looking it up on the artifact tree.  A file stored as
    ``entrypoint-%7B%7D.html`` is therefore only reachable by a request
    that decodes to that literal string (``%257B...``, twice-encoded),
    while every real link in the site is written once-encoded and decodes
    to ``entrypoint-{}.html`` -- which is exactly the name stored here,
    so those links hit.  Storing encoded names instead was what made
    every choice link on the deployed site 404."""
    stem = os.path.splitext(filename)[0]
    if "%" in stem:
        stem = urllib.parse.unquote(stem)
    return stem + ".html"


def breadcrumb_of(stem):
    """Human page label for a section filename stem (entrypoint-{a: 1}).

    Mirrors the breadcrumb strip the plain html builder puts on its pages:
    section name plus the world state baked into the filename.
    """
    import json

    name, _, world = stem.rpartition("-")
    try:
        loaded = json.loads(world)
    except (ValueError, TypeError):
        return None
    if not isinstance(loaded, dict):
        return None
    if not loaded:
        return name
    parts = ", ".join("%s=%s" % (k, loaded[k]) for k in sorted(loaded))
    return "%s (%s)" % (name, parts)


#: story pages published next to each book in site/books/.  The epub builder
#: writes its unzipped html debug pages with xhtml package targets (hrefs
#: pointing at ../xhtml/<name>.xhtml inside the .epub file); those files
#: cannot be served on a static host, so before publishing them they are
#: rewritten back to plain sibling pages: percent-encoded filenames (the
#: raw ones carry braces, quotes and spaces which github pages does not
#: serve), a real stylesheet link, breadcrumbs, and hrefs that resolve to
#: the other published .html files.  That makes every choice link in every
#: demo page a clickable link on the site.
PAGE_CSS_LINK = '<link href="template.css" rel="stylesheet" type="text/css"/>'

#: language of the example narratives, published onto every book page so
#: screen readers voice them correctly instead of guessing
BOOK_LANGUAGE = "en-US"


def publishable_page(page_html, breadcrumb=None):
    """Rewrite an unzipped epub debug page into a standalone html page."""
    from lxml import etree

    parser = etree.HTMLParser(remove_comments=False)
    root = etree.fromstring(page_html.encode("utf-8"), parser)
    # the head stylesheet link is dropped and re-added below so it runs
    # after the href rewriting, otherwise the fresh css link would get
    # rewritten with itself (template.css -> template.css.html)
    for head_link in root.xpath("/html/head/link"):
        head_link.getparent().remove(head_link)
    for elem in root.iter():
        href = elem.get("href")
        if not href or href.startswith(("http:", "https:", "#")):
            continue
        # the unzipped package pages link with percent-encoded xhtml
        # targets (xhtml/<name>.xhtml); decode before re-encoding so
        # nothing escapes twice, and never trust splitext here: the stem
        # may legitimately end in %7B ({), which .html would eat whole.
        base = os.path.basename(urllib.parse.unquote(href))
        if base == "template.xhtml":
            # the package stylesheet is published beside the pages as
            # template.css (the plain html builder's filename)
            elem.set("href", "template.css")
            continue
        for suffix in (".xhtml", ".html"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        encoded = urllib.parse.quote(base, safe="") + ".html"
        elem.set("href", encoded)
    # the language travels with the page: assistive tech needs it to pick a
    # voice, and an xml:lang on an html document is not read by browsers
    root.xpath("/html")[0].set("lang", BOOK_LANGUAGE)
    head = root.xpath("/html/head")[0]
    style = etree.SubElement(head, "link")
    style.set("href", "template.css")
    style.set("rel", "stylesheet")
    style.set("type", "text/css")
    if breadcrumb:
        body = root.xpath("/html/body")[0]
        story_div = body.xpath('div[contains(@class, "story")]')
        index = body.index(story_div[0]) if story_div else 0
        strip = etree.Element("div")
        strip.set("class", "breadcrumbs")
        brand = etree.SubElement(strip, "b")
        brand.text = "Reader Beware"
        brand.tail = " \u00b7 " + breadcrumb
        body.insert(index, strip)
    rendered = etree.tostring(root, encoding="unicode", method="html")
    return "<!DOCTYPE html>\n" + rendered


def build_book(name):
    """Build html pages + a real epub for a narrative into site/books/<name>."""
    from beware.build_epub import EPubWorldBuilder
    from beware.meta import BookMetadata

    src = os.path.join(EXAMPLE_SRC, name + ".yaml")
    shutil.rmtree(os.path.join(BOOKS, name), ignore_errors=True)
    html_dir = os.path.join(BUILD_ROOT, name + "_site_html")
    builder = EPubWorldBuilder(src, html_dir, meta=BookMetadata(title=name))
    builder.build()
    epub_file = builder.build_epub()
    dest = os.path.join(BOOKS, name)
    os.makedirs(dest, exist_ok=True)
    for entry in sorted(os.listdir(html_dir)):
        if entry == "template.css":
            shutil.copyfile(os.path.join(html_dir, entry), os.path.join(dest, entry))
        elif entry.endswith(".html"):
            # unzip-style filename: publish under the decoded name so a
            # once-encoded request (what every href on the site writes)
            # decodes to exactly this file on the pages artifact tree
            stem = os.path.splitext(urllib.parse.unquote(entry))[0]
            safe = stem + ".html"
            with open(os.path.join(html_dir, entry), "r", encoding="utf-8") as f:
                page_html = f.read()
            page_html = publishable_page(page_html, breadcrumb_of(stem))
            with open(os.path.join(dest, safe), "w", encoding="utf-8") as f:
                f.write(page_html)
    shutil.move(epub_file, os.path.join(dest, name + ".epub"))
    print("book built into", dest)


def device_pages():
    """Render built story pages framed inside a mock e-reader device: the
    page's breadcrumb + story markup is inlined into the screen (jinja
    template in this script's folder) so nothing needs to load over http."""
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(HERE))
    frame = env.get_template("reader_frame.html")
    for book, filename, embed, title, chrome in DEVICE_EMBEDS:
        pages = build_story(book)
        target = os.path.join(pages, filename)
        if not os.path.exists(target):
            raise FileNotFoundError(target)
        with open(target, "r", encoding="utf-8") as f:
            page_html = f.read()
        screen = screen_markup(page_html)
        rendered = frame.render(title=title, chrome=chrome, page_html=screen)
        write_embed(embed, rendered)


def screen_markup(page_html):
    """Pull the breadcrumb and story divs out of a built page (the bits an
    e-reader screen would show) using lxml.

    The framed device is a still: its document lives at about:srcdoc with
    no base url, so every link inside it points nowhere.  Anchors are
    unwrapped to their text (and ids dropped, since unique xml ids would
    clash when two pages share a document) before serialising."""
    from lxml import etree

    parser = etree.HTMLParser(remove_comments=True)
    tree = etree.fromstring(page_html.encode("utf-8"), parser)
    parts = []
    for selector in ("breadcrumbs", "story"):
        found = tree.xpath('//div[contains(@class, "%s")]' % selector)
        for node in found:
            strip_ids(node)
            unwrap_links(node)
            parts.append(etree.tostring(node, encoding="unicode", method="html"))
    return "\n".join(parts) if parts else page_html


def unwrap_links(node):
    """Replace every anchor in a subtree with plain text (its children and
    its tail), keeping the surrounding markup intact."""
    from lxml import etree

    for anchor in node.xpath(".//a"):
        parent = anchor.getparent()
        if parent is None:
            continue
        index = parent.index(anchor)
        # text of the anchor merges into the preceding text node
        merged = anchor.text or ""
        for child in list(anchor):
            merged += etree.tostring(child, encoding="unicode", method="html")
            if child.tail:
                merged += child.tail
        previous = anchor.getprevious()
        if previous is not None:
            previous.tail = (previous.tail or "") + merged
        else:
            parent.text = (parent.text or "") + merged
        if anchor.tail:
            # the tail belongs after the removed element: append it onto
            # whatever we just merged, so nothing is lost
            if previous is not None:
                previous.tail = previous.tail + anchor.tail
            else:
                parent.text = (parent.text or "") + merged + anchor.tail
        parent.remove(anchor)


def strip_ids(node):
    """Remove id attributes from a subtree (xml-safe unique ids would clash
    inside the shared frame document)."""
    for element in node.iter():
        if "id" in element.attrib:
            del element.attrib["id"]


def story_pages():
    """Render each built story page into site/embeds/; the stylesheet is
    inlined so every embed is fully self-contained (srcdoc pages load
    their own resources poorly, and self-contained renders anywhere).  The
    pages are taken from site/books/ after build_book publishes them, which
    keeps what the demos show identical to what the site actually serves.

    A srcdoc document lives at about:srcdoc with no base url of its own, so
    relative targets in it resolve against nothing and never reach a real
    file; the demo pages therefore link absolute paths into the published
    books (/books/<name>/<page>.html), which is exactly where a reader who
    clicks a choice ends up."""
    css = template_css_source()
    for book, filename, embed in STORY_EMBEDS:
        target = os.path.join(BOOKS, book, publish_filename(filename))
        if not os.path.exists(target):
            raise FileNotFoundError(
                "%s missing; run the full script (build_book publishes it)" % target
            )
        with open(target, "r", encoding="utf-8") as f:
            page_html = f.read()
        page_html = re.sub(
            r"<link[^>]*template\.css[^>]*>",
            "<style>\n%s\n</style>" % inline_css(css),
            page_html,
            count=1,
        )
        page_html = link_into_published_books(page_html, book)
        write_embed(embed, page_html)


#: the unzipped epub pages never carry this breadcrumb suffix; a demo page
#: keeps its own breadcrumb strip but its links must aim at real files
BOOK_PATH_PREFIX = "/books/"


def link_into_published_books(page_html, book):
    """Rewrite relative story hrefs into /books/<book>/<file>.html paths.

    The embed renders inside an iframe whose document has no filesystem
    location, so the sibling files of the page it was built from only
    exist as served urls; make that url explicit in every link.  These
    pages are already html-escaped for their embed (the build writes them
    with &amp; entities), hence unescape first, escape back last.
    """
    import urllib.parse

    def rewrite(match):
        href = html_module.unescape(match.group(1))
        if href.startswith(("http:", "https:", "#", "/", "mailto:")):
            return match.group(0)
        base = os.path.basename(urllib.parse.unquote(href))
        for suffix in (".xhtml", ".html"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        safe = urllib.parse.quote(base, safe="") + ".html"
        target = html_module.escape(BOOK_PATH_PREFIX + book + "/" + safe, quote=True)
        # group(0) ends at the closing quote of the href attribute and
        # group(1) is the value between the quotes, so everything up to
        # start(1) plus the new target plus one quote is the whole
        # replacement; the old closing quote belongs to the untouched
        # tail after end(1)
        prefix = page_html[match.start() : match.start(1)]
        return prefix + target + '"'

    return re.sub(r'<a[^>]*?href="([^"]*)"', rewrite, page_html)


def inline_css(css):
    """Drop the remote font import (offline-safe embeds; local fallbacks
    in the stylesheet cover it) and neutralise url() tokens so nothing
    tries to load a file relative to an about:srcdoc base."""
    css = re.sub(r"@import url\([^)]*\)", "", css)
    return css


def demo_narratives():
    """The demo narrative mapping (the story the editor captures show)."""
    path = os.path.join(EXAMPLE_SRC, DEMO_STORY)
    with open(path, "r") as f:
        return yaml.safe_load(f)


def replace_once(text, old, new):
    """Replace the first occurrence of ``old`` with ``new`` (or do nothing)."""
    index = text.find(old)
    if index < 0:
        return text
    return text[:index] + new + text[index + len(old) :]


def card_spans(html):
    """(start, end) spans for each studio card article in a studio page."""
    marker = '<article class="card"'
    closing = "</article>"
    spans = []
    position = 0
    while True:
        start = html.find(marker, position)
        if start < 0:
            break
        end = html.find(closing, start) + len(closing)
        spans.append((start, end))
        position = start + 1
    return spans


def card_section(html, span):
    """The section name written into a studio card's name input."""
    match = re.search(
        r'<input class="sec-name" value="([^"]*)"', html[span[0] : span[1]]
    )
    return match.group(1) if match else None


def inject_preview(html, client, section):
    """Server-side mirror of the studio preview toggle: show the preview
    panel on the card for ``section``, mark it as the entrypoint tag and
    fill it with the real output of the editor's own /preview endpoint."""
    spans = card_spans(html)
    target = None
    for span in spans:
        if card_section(html, span) == section:
            target = span
            break
    if target is None:
        return html
    start, end = target
    segment = html[start:end]
    response = client.post(
        "/preview/" + DEMO_STORY, data={"body": demo_narratives()[section]["body"]}
    )
    rendered = response.json.get("html", "")
    if not rendered.strip():
        return html
    segment = replace_once(
        segment, '<div class="preview" hidden>', '<div class="preview">'
    )
    segment = replace_once(
        segment,
        '<div class="preview-out"></div>',
        '<div class="preview-out">%s</div>' % rendered,
    )
    segment = replace_once(
        segment,
        '<span class="tag" data-tag hidden>entrypoint</span>',
        '<span class="tag" data-tag>entrypoint</span>',
    )
    return html[:start] + segment + html[end:]


def format_value(value):
    """Mirror the studio's value formatting: bare numbers/bools, quoted else."""
    text = str(value)
    if re.match(r"^-?\d+(\.\d+)?$", text):
        return text
    if text.lower() in ("true", "false"):
        return text.lower()
    return "'" + text.replace("'", "\\'") + "'"


def build_snippet():
    """The markdown snippet the link tool would hand you, built server-side
    from the demo values (same shape as the studio's own buildSnippet)."""
    parts = ", ".join(
        "%s=%s" % (name, format_value(value)) for name, value in VARIABLES
    )
    args = "(%s)" % parts if parts else ""
    jinja = "{{ '%s'|%s%s }}" % (LINK_TARGET, LINK_KIND, args)
    return "[%s](%s)" % (LINK_TEXT, jinja)


def open_link_tool(html):
    """Server-side mirror of the studio link tool being used: show the tool
    on the first card, select "choice" as the kind, set text/target fields
    to typed values, add a filled variable row and bake the built snippet
    into the code element -- exactly what the page javascript would have
    produced after a user finished typing."""
    spans = card_spans(html)
    if not spans:
        return html
    start, end = spans[0]
    segment = html[start:end]
    segment = replace_once(
        segment, '<details class="linktool" hidden>', '<details class="linktool">'
    )
    segment = replace_once(
        segment,
        '<option value="choice">choice (sets variables)</option>',
        '<option value="choice" selected>choice (sets variables)</option>',
    )
    segment = replace_once(
        segment,
        '<input class="lt-text" placeholder="go left">',
        '<input class="lt-text" placeholder="go left" value="%s">' % LINK_TEXT,
    )
    segment = replace_once(
        segment,
        '<input class="lt-target" list="section-names" placeholder="section name">',
        '<input class="lt-target" list="section-names" placeholder="section name" value="%s">'
        % LINK_TARGET,
    )
    rows = "".join(
        '<div class="lt-row lt-var"><input class="vname" placeholder="shirt_color" '
        'aria-label="variable name" value="%s"><input class="vvalue" '
        'placeholder="red" aria-label="variable value" value="%s">'
        '<button class="danger ghost rm" type="button">&times;</button></div>'
        % (name, value)
        for name, value in VARIABLES
    )
    segment = replace_once(
        segment, '<div class="lt-vars"></div>', '<div class="lt-vars">%s</div>' % rows
    )
    # the snippet goes into a dom that will itself be html-escaped for
    # srcdoc injection, so it must carry plain text here; quote=False
    # would leave raw " characters that escape twice later on
    snippet = html_module.escape(build_snippet(), quote=True)
    segment = replace_once(
        segment,
        '<code class="snippet"></code>',
        '<code class="snippet">%s</code>' % snippet,
    )
    return html[:start] + segment + html[end:]


#: the demo editor pages show their story root as this label instead of
#: the render machine's absolute checkout path (which in CI reads
#: /home/runner/work/... and tells a reader nothing about their own box)
DEMO_ROOT_LABEL = "stories/"


def caption_editor_root(html_text):
    """Swap the absolute story root printed by the editor index for the
    demo label, both where it shows as the header path and in the page
    heading.  Parsed with lxml so text nodes are replaced whole."""
    from lxml import etree

    parser = etree.HTMLParser()
    root = etree.fromstring(html_text.encode("utf-8"), parser)
    changed = False
    for span in root.xpath(
        '//*[contains(concat(" ", normalize-space(@class), " "), " root ")]'
    ):
        if (span.text or "").strip():
            span.text = DEMO_ROOT_LABEL
            changed = True
    for code in root.xpath("//h1/code"):
        if (code.text or "").strip():
            code.text = DEMO_ROOT_LABEL
            changed = True
    if not changed:
        return html_text
    return etree.tostring(root, encoding="unicode", method="html")


def editor_pages():
    """Render the flask editor pages through the test client and embed them:
    story index, section studio with the live preview open on the entrypoint
    card, the explore/choice link tool mid-build, raw yaml editor."""
    app = create_app(EXAMPLE_SRC)
    app.config["TESTING"] = True
    client = app.test_client()

    index = caption_editor_root(client.get("/").get_data(as_text=True))
    write_embed("editor-index", index)

    studio = caption_editor_root(client.get("/" + DEMO_STORY).get_data(as_text=True))
    previewed = inject_preview(studio, client, "entrypoint")
    write_embed("editor-studio-preview", previewed)

    studio = caption_editor_root(client.get("/" + DEMO_STORY).get_data(as_text=True))
    write_embed("editor-studio-link", open_link_tool(studio))

    raw = caption_editor_root(client.get("/raw/" + DEMO_STORY).get_data(as_text=True))
    write_embed("editor-raw", raw)


#: device-framed embeds render at their own aspect ratio (mock e-reader)
#: rather than the 16:10 browser-frame ratio of editor/story embeds
FRAME_HEIGHTS = {
    "device-red-shirt": 760.0 / 420.0,
    "device-green-shirt": 760.0 / 420.0,
}
#: story pages render tall (a single article at reading width)
STORY_HEIGHTS = {
    "story-entry": 1.9,
    "story-state": 1.9,
    "story-maze": 1.9,
    "story-belair": 1.9,
}
#: the raw editor page is short (one textarea)
EDITOR_HEIGHTS = {
    "editor-index": 0.75,
    "editor-studio-preview": 2.4,
    "editor-studio-link": 2.6,
    "editor-raw": 1.3,
}


def embed_height(embed_name):
    """Aspect ratio (height/width) used for an embed's iframe."""
    for table in (FRAME_HEIGHTS, STORY_HEIGHTS, EDITOR_HEIGHTS):
        if embed_name in table:
            return table[embed_name]
    return 1.5  # browser-frame default


def srcdoc_embed(embed_name):
    """The iframe tag embedding a rendered page via srcdoc (html-escaped so
    it survives as an attribute; the browser parses it as real html).

    The demo pages live at about:srcdoc with no base url, so only the
    absolute targets (/books/...) written into them can ever resolve --
    nothing else breaks out to the network from a srcdoc document.
    """
    with open(os.path.join(EMBEDS, embed_name + ".html"), "r", encoding="utf-8") as f:
        source = f.read()
    escaped = html_module.escape(source, quote=True)
    ratio = embed_height(embed_name)
    return (
        '<iframe class="embed" srcdoc="%s" loading="lazy" '
        'style="aspect-ratio: %.3f;" title="reader-beware %s">'
        "</iframe>" % (escaped, ratio, embed_name.replace("-", " "))
    )


#: placeholders in site/index.html replaced by rendered embeds
PLACEHOLDERS = [
    "device-red-shirt",
    "device-green-shirt",
    "story-entry",
    "story-state",
    "story-maze",
    "story-belair",
    "editor-index",
    "editor-studio-preview",
    "editor-studio-link",
    "editor-raw",
]


def reset_placeholders(page):
    """Turn already-injected iframe tags back into placeholder comments so
    reruns (and local dev loops) always re-render fresh embeds."""
    pattern = re.compile(
        # srcdoc holds escaped html: it contains no literal quote but does
        # contain &amp;quot; entities, so a lazy dot-match (not [^"]*) is
        # the safe way to stop at the attribute's real closing quote
        r'<iframe class="embed" srcdoc=".+?" loading="lazy" '
        r'style="[^"]*" title="reader-beware ([a-z ]+)">'
        r"</iframe>",
        re.S,
    )

    def replace(match):
        name = match.group(1).strip().replace(" ", "-")
        return "<!-- reader-beware:screenshot:%s -->" % name

    return pattern.sub(replace, page)


def inject_index():
    """Rewrite site/index.html: every placeholder comment becomes the iframe
    embedding that rendered page (srcdoc, so the example is live markup but
    inert).  Previously injected iframes are first turned back into
    placeholders, which keeps reruns deterministic."""
    with open(INDEX, "r", encoding="utf-8") as f:
        page = f.read()
    page = reset_placeholders(page)
    original = page
    for embed_name in PLACEHOLDERS:
        marker = "<!-- reader-beware:screenshot:%s -->" % embed_name
        if marker not in page:
            continue
        page = page.replace(marker, srcdoc_embed(embed_name))
    if page != original:
        with open(INDEX, "w", encoding="utf-8") as f:
            f.write(page)
        print("injected index.html")
    else:
        print("index.html had no placeholders to inject")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--books-only",
        action="store_true",
        help="build site/books/ without rendering embeds",
    )
    args = parser.parse_args()
    # books first: the story/device embeds and the index link lists read
    # the pages build_book publishes into site/books/
    for name in BOOKS_TO_BUILD:
        build_book(name)
    if not args.books_only:
        copy_template_css()
        story_pages()
        device_pages()
        editor_pages()
        inject_index()


if __name__ == "__main__":
    main()
