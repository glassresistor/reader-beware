#!/usr/bin/env python3
"""Capture screenshots of reader-beware for the github.io advertisement site.

Everything here runs in CI (the deploy workflow installs playwright and
downloads a chromium into ``.pptr`` so the browser cache survives between
steps).  The script drives real artifacts built by the repo itself:

* ``beware build-html`` output for the example books (story pages), plus a
  hand-written CSS-driven "reader" wrapper used to photograph whole spreads,
* the flask editor from ``create_app`` (story index, section studio with the
  live preview and link tool open, raw yaml editor).

Screenshots land in ``site/images/``.  Fixed viewport sizes and selector
waits keep the captures deterministic.

Usage::

    python site/scripts/capture_screenshots.py [--width 1280] [--height 900]
"""

import argparse
import os
import shutil
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
SITE_DIR = os.path.abspath(os.path.join(HERE, os.pardir))
REPO_ROOT = os.path.abspath(os.path.join(SITE_DIR, os.pardir))
sys.path.insert(0, REPO_ROOT)

from beware.build_html import NarativeWorldBuilder  # noqa: E402
from beware.web import create_app  # noqa: E402

IMAGES = os.path.join(SITE_DIR, "images")
BOOKS = os.path.join(SITE_DIR, "books")
BUILD_ROOT = os.path.join(tempfile.gettempdir(), "reader-beware-shots")

#: (book, built filename, png name) for the story page captures
STORY_SHOTS = [
    ("shirts", "entrypoint-{}.html", "story-entry.png"),
    ("shirts", 'go-outside-{"shirt_color": "green"}.html', "story-state.png"),
    ("maze", "entrypoint-{}.html", "story-maze.png"),
    ("belair", "prince-of-belair-{}.html", "story-belair.png"),
]

#: device-framed captures of epub-rendered pages: (book, filename, png,
#: title, chrome text shown under the screen)
DEVICE_SHOTS = [
    (
        "shirts",
        "entrypoint-%7B%22shirt_color%22%3A%20%22red%22%7D.html",
        "device-red-shirt.png",
        "Red or Green?",
        "chapter 2 of 9 &#183; beware build-epub",
    ),
    (
        "shirts",
        "go-outside-%7B%22shirt_color%22%3A%20%22green%22%7D.html",
        "device-green-shirt.png",
        "Red or Green?",
        "chapter 6 of 9 &#183; world: shirt_color=green",
    ),
]


def build_story(name):
    """Build one example narrative into BUILD_ROOT/<name>, return its folder."""
    src = os.path.join(SITE_DIR, "examples-src", name + ".yaml")
    out = os.path.join(BUILD_ROOT, name)
    builder = NarativeWorldBuilder(src, out)
    builder.build()
    return out


def build_book(name):
    """Build html pages + a real epub for a narrative into site/books/<name>."""
    from beware.build_epub import EPubWorldBuilder
    from beware.meta import BookMetadata

    src = os.path.join(SITE_DIR, "examples-src", name + ".yaml")
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


def file_url(path):
    """A file:// url that tolerates braces/quotes in filenames.

    Percent-encodes with the public ``urllib.parse.quote`` (keeping ``/``
    safe) so characters like ``{}"`` in built section filenames survive;
    no private stdlib helpers are used so this works on python 3.8+.
    """
    from pathlib import Path
    from urllib.parse import quote

    absolute = str(Path(path).absolute())
    return "file://" + quote(absolute, "/")


def shot(page, path, full_page=True):
    page.wait_for_timeout(500)  # let webfonts/paint settle
    page.screenshot(path=path, full_page=full_page)
    print("captured", os.path.basename(path))


def serve_app(app, port=0):
    from werkzeug.serving import make_server

    srv = make_server("127.0.0.1", port, app)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def story_pages(browser, width, height):
    for book, filename, png in STORY_SHOTS:
        out = build_story(book)
        target = os.path.join(out, filename)
        if not os.path.exists(target):
            print("WARN missing", target)
            continue
        page = browser.new_page(viewport={"width": width, "height": height})
        page.goto(file_url(target))
        shot(page, os.path.join(IMAGES, png))
        page.close()


def build_epub_pages(name):
    """Build the epub (unzipped pages) for a narrative; return the folder."""
    from beware.build_epub import EPubWorldBuilder
    from beware.meta import BookMetadata

    src = os.path.join(SITE_DIR, "examples-src", name + ".yaml")
    out = os.path.join(BUILD_ROOT, name + "_epub")
    builder = EPubWorldBuilder(src, out, meta=BookMetadata(title="Red or Green?"))
    builder.build()
    return out


def device_pages(browser):
    """Screenshot epub pages framed inside a mock e-reader device."""
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(HERE))
    frame = env.get_template("reader_frame.html")
    for book, filename, png, title, chrome in DEVICE_SHOTS:
        pages = build_epub_pages(book)
        target = os.path.join(pages, filename)
        if not os.path.exists(target):
            print("WARN missing", target)
            continue
        rendered = frame.render(title=title, chrome=chrome, page=file_url(target))
        wrapper = os.path.join(BUILD_ROOT, "frame-" + png)
        with open(wrapper, "w", encoding="utf-8") as f:
            f.write(rendered)
        page = browser.new_page(viewport={"width": 500, "height": 860})
        page.goto(file_url(wrapper))
        shot(page, os.path.join(IMAGES, png), full_page=False)
        page.close()


def editor_pages(browser, width, height):
    root = os.path.join(SITE_DIR, "examples-src")
    app = create_app(root)
    srv = serve_app(app)
    base = "http://127.0.0.1:%s" % srv.server_port

    def visit(path):
        page = browser.new_page(viewport={"width": width, "height": height})
        page.goto(base + path, wait_until="networkidle")
        return page

    page = visit("/")
    shot(page, os.path.join(IMAGES, "editor-index.png"))
    page.close()

    # section studio with the live preview open on the first card
    page = visit("/demo.yaml")
    buttons = page.locator('article.card button[data-open="preview"]')
    if buttons.count():
        buttons.nth(0).click()
        page.wait_for_selector("article.card .preview:not([hidden])")
        # wait until the fetch fills the preview (anything but the
        # "rendering..." placeholder)
        page.wait_for_function(
            "() => { const out = document.querySelector('article.card .preview-out');"
            " return out && !out.textContent.includes('rendering') }"
        )
    shot(page, os.path.join(IMAGES, "editor-studio-preview.png"))
    page.close()

    # studio with the explore/choice link tool open on the first card
    page = visit("/demo.yaml")
    page.locator('article.card button[data-open="link"]').nth(0).click()
    page.wait_for_selector("article.card details.linktool:not([hidden])")
    card = page.locator("article.card").nth(0)
    card.locator(".lt-text").fill("visit the hacker")
    card.locator(".lt-target").fill("hacker")
    # show the link tool with a state-carrying variable so the screenshot
    # demonstrates choice args, not just a plain jump
    card.locator("select.lt-kind").select_option("choice")
    card.locator("button.lt-addvar").click()
    card.locator(".lt-vars .vname").fill("credits")
    card.locator(".lt-vars .vvalue").fill("10")
    # trigger the snippet refresh (change events fire on select clicks)
    card.locator(".lt-vars .vvalue").dispatch_event("input")
    page.wait_for_selector("article.card code.snippet:not(:empty)")
    shot(page, os.path.join(IMAGES, "editor-studio-link.png"))
    page.close()

    # raw yaml editor (viewport only: it is a long textarea)
    page = visit("/raw/demo.yaml")
    shot(page, os.path.join(IMAGES, "editor-raw.png"), full_page=False)
    page.close()

    srv.shutdown()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument(
        "--books-only",
        action="store_true",
        help="build site/books/ without capturing screenshots",
    )
    args = parser.parse_args()
    if not args.books_only:
        # playwright is only needed for the screenshot capture itself
        from playwright.sync_api import sync_playwright

        os.makedirs(IMAGES, exist_ok=True)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--font-render-hinting=none"])
            story_pages(browser, args.width, args.height)
            device_pages(browser)
            editor_pages(browser, args.width, args.height)
            browser.close()
    for name in ("shirts", "maze", "belair"):
        build_book(name)


if __name__ == "__main__":
    main()
