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
import re
import shutil
import sys
import tempfile

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

#: story page embeds: (book, built filename, embed name)
STORY_EMBEDS = [
    ("shirts", "entrypoint-{}.html", "story-entry"),
    ("shirts", 'go-outside-{"shirt_color": "green"}.html', "story-state"),
    ("maze", "entrypoint-{}.html", "story-maze"),
    ("belair", "prince-of-belair-{}.html", "story-belair"),
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
    for entry in os.listdir(html_dir):
        if entry.endswith(".html") or entry == "template.css":
            shutil.copyfile(os.path.join(html_dir, entry), os.path.join(dest, entry))
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
    e-reader screen would show) using lxml; ids are dropped so nothing
    clashes when two pages share a document."""
    from lxml import etree

    parser = etree.HTMLParser(remove_comments=True)
    tree = etree.fromstring(page_html.encode("utf-8"), parser)
    parts = []
    for selector in ("breadcrumbs", "story"):
        found = tree.xpath('//div[contains(@class, "%s")]' % selector)
        for node in found:
            strip_ids(node)
            parts.append(etree.tostring(node, encoding="unicode", method="html"))
    return "\n".join(parts) if parts else page_html


def strip_ids(node):
    """Remove id attributes from a subtree (xml-safe unique ids would clash
    inside the shared frame document)."""
    for element in node.iter():
        if "id" in element.attrib:
            del element.attrib["id"]


def story_pages():
    """Render each built story page into site/embeds/; the stylesheet is
    inlined so every embed is fully self-contained (srcdoc pages load
    their own resources poorly, and self-contained renders anywhere)."""
    css = template_css_source()
    for book, filename, embed in STORY_EMBEDS:
        folder = build_story(book)
        target = os.path.join(folder, filename)
        if not os.path.exists(target):
            raise FileNotFoundError(target)
        with open(target, "r", encoding="utf-8") as f:
            page_html = f.read()
        page_html = re.sub(
            r"<link[^>]*template\.css[^>]*>",
            "<style>\n%s\n</style>" % inline_css(css),
            page_html,
            count=1,
        )
        write_embed(embed, page_html)


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
        'value="%s"><input class="vvalue" placeholder="red" value="%s">'
        '<button class="danger ghost rm" type="button">&times;</button></div>'
        % (name, value)
        for name, value in VARIABLES
    )
    segment = replace_once(
        segment, '<div class="lt-vars"></div>', '<div class="lt-vars">%s</div>' % rows
    )
    snippet = html_module.escape(build_snippet(), quote=False)
    segment = replace_once(
        segment,
        '<code class="snippet"></code>',
        '<code class="snippet">%s</code>' % snippet,
    )
    return html[:start] + segment + html[end:]


def editor_pages():
    """Render the flask editor pages through the test client and embed them:
    story index, section studio with the live preview open on the entrypoint
    card, the explore/choice link tool mid-build, raw yaml editor."""
    app = create_app(EXAMPLE_SRC)
    app.config["TESTING"] = True
    client = app.test_client()

    write_embed("editor-index", client.get("/").get_data(as_text=True))

    studio = client.get("/" + DEMO_STORY).get_data(as_text=True)
    previewed = inject_preview(studio, client, "entrypoint")
    write_embed("editor-studio-preview", previewed)

    studio = client.get("/" + DEMO_STORY).get_data(as_text=True)
    write_embed("editor-studio-link", open_link_tool(studio))

    raw = client.get("/raw/" + DEMO_STORY).get_data(as_text=True)
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
    it survives as an attribute; the browser parses it as real html)."""
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
    if not args.books_only:
        copy_template_css()
        story_pages()
        device_pages()
        editor_pages()
        inject_index()
    for name in BOOKS_TO_BUILD:
        build_book(name)


if __name__ == "__main__":
    main()
