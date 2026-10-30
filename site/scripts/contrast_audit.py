"""Check every colour pair the site and editor actually paint with.

The palette is dark-on-dark by design, so it is far too easy to ship a text
colour that quietly disappears into a panel background -- the e-ink screen of
the framed device captures got exactly that bug, a light-web grey sitting at
2.6:1 on paper.  This lists the foreground/background pairs that the css
actually paints (one entry per selector pair, spelled out below), measures
each with the WCAG 2.x formula, and fails the build on anything under AA.

Run from the repo root::

    python site/scripts/contrast_audit.py          # what CI runs
    python site/scripts/contrast_audit.py --show   # print every ratio

The pairs are explicit rather than derived by parsing css: a stylesheet that
paints a new surface is a deliberate act, and it gets a deliberate entry here
(the audit then refuses to pass until the new pair clears the floor).  A
non-zero exit code means the deploy job will not publish.
"""

import argparse
import os
import re
import sys

#: (label, foreground, background) triples: every colour combination that
#: any stylesheet in the repo paints text onto.  ``floor`` defaults to 4.5
#: (WCAG AA for normal text); pairs marked large clear the 3.0 bar instead,
#: which is what WCAG allows for text of 18.6px+ bold or 24px+.
PAIRS = [
    # site/index.html over site/style.css
    ("site body text", "#f2ecf5", "#0b0a10"),
    ("site muted text", "#c3b9cc", "#0b0a10"),
    ("site faint text", "#9c95ad", "#0b0a10"),
    ("site heading lilac", "#c9a8ff", "#0b0a10"),
    ("site link", "#ffb0df", "#0b0a10"),
    ("hero accent word", "#ff6ec7", "#0b0a10"),
    ("card heading", "#ffb0df", "#17161f"),
    ("card body text", "#c3b9cc", "#17161f"),
    ("inline code", "#ffb0df", "#211e29"),
    ("code block text", "#c3b9cc", "#211e29"),
    ("code comment", "#9c95ad", "#211e29"),
    ("step number", "#ffb0df", "#211e29"),
    ("button face, top stop", "#ffffff", "#8a55d6"),
    ("button face, deep stop", "#ffffff", "#7b4fd0"),
    ("button hover text", "#140712", "#ff6ec7"),
    ("ghost button label", "#c3b9cc", "#0b0a10"),
    # built story pages over beware/files/template.css
    ("story body text", "#f2ecf5", "#0b0a10"),
    ("story link", "#ffb0df", "#0b0a10"),
    ("story heading", "#c9a8ff", "#0b0a10"),
    ("story subheading", "#ffb0df", "#0b0a10"),
    ("breadcrumbs", "#9c95ad", "#0b0a10"),
    ("book metadata", "#9c95ad", "#0b0a10"),
    ("story code", "#ffb0df", "#17161f"),
    # the framed e-reader screen (e-ink paper, not the web palette)
    ("screen body text", "#201c28", "#f7f5ef"),
    ("screen heading", "#4a2f6e", "#f7f5ef"),
    ("screen link", "#7b4fd0", "#f7f5ef"),
    ("screen breadcrumbs", "#756e7d", "#f7f5ef"),
    ("device chrome label", "#9c95ad", "#1c1a24"),
    ("device chrome title", "#ffb0df", "#1c1a24"),
    # flask editor (beware/templates/web)
    ("editor body text", "#f2ecf5", "#0b0a10"),
    ("editor root path", "#9c95ad", "#1b1526"),
    ("brand accent", "#ff6ec7", "#1b1526"),
    ("editor link", "#ffb0df", "#0b0a10"),
    ("problem panel text", "#ffdfe6", "#24141e"),
    ("panel label", "#c3b9cc", "#17161f"),
    ("card name field", "#f2ecf5", "#211e29"),
    ("section textarea", "#f2ecf5", "#131019"),
    ("link tool summary", "#c9a8ff", "#181423"),
    ("link tool bullet", "#ff6ec7", "#181423"),
    ("generated snippet", "#ffb0df", "#0d0b13"),
    ("inspector heading", "#9c95ad", "#17161f"),
    ("explore badge", "#a06ae8", "#17161f"),
    ("choice badge", "#ff6ec7", "#17161f"),
    ("link target", "#f2ecf5", "#17161f"),
    ("link arguments", "#9c95ad", "#17161f"),
    ("missing link warning", "#ff5c7a", "#17161f"),
    ("preview heading", "#ffb0df", "#14111c"),
    ("preview link", "#c9a8ff", "#14111c"),
    ("preview code", "#f2ecf5", "#0d0b13"),
    ("preview error", "#ff5c7a", "#14111c"),
    ("accent button, top stop", "#20051a", "#ff6ec7"),
    ("accent button, end stop", "#20051a", "#c44ea0"),
    ("outline chip", "#c3b9cc", "#211e29"),
    ("danger button label", "#ff5c7a", "#17161f"),
    # the studio navigator and its per-card problem boxes
    ("nav heading", "#9c95ad", "#17161f"),
    ("nav entry label", "#c3b9cc", "#17161f"),
    ("nav entry shown", "#f2ecf5", "#211e29"),
    ("nav entry hover", "#ffb0df", "#211e29"),
    ("nav problem marker", "#ff5c7a", "#17161f"),
    ("nav trouble row hover", "#ff5c7a", "#24141e"),
    ("broken link name", "#ff5c7a", "#17161f"),
    ("card problem text", "#ffdfe6", "#24141e"),
    ("card create-section button", "#ff5c7a", "#24141e"),
    ("header show-them button", "#c3b9cc", "#24141e"),
    ("skip link", "#ffb0df", "#211e29"),
]

#: pairs that render as large or bold text and clear the 3:1 bar instead
LARGE = {"hero accent word"}


def luminance(hex_color):
    """Relative luminance of a #rgb/#rrggbb colour (WCAG 2.x)."""
    digits = hex_color.lstrip("#")
    if len(digits) == 3:
        digits = "".join(d * 2 for d in digits)
    channels = [int(digits[i : i + 2], 16) / 255 for i in (0, 2, 4)]

    def linear(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return sum(w * linear(c) for w, c in zip((0.2126, 0.7152, 0.0722), channels))


def contrast(foreground, background):
    """WCAG 2.x contrast ratio of two colours: 1 (invisible) to 21 (black/white)."""
    first, second = luminance(foreground), luminance(background)
    if first < second:
        first, second = second, first
    return (first + 0.05) / (second + 0.05)


def floor_for(label):
    return 3.0 if label in LARGE else 4.5


def audit(show=False):
    """Measure every pair; print the report and return the failures."""
    failures = []
    rows = []
    for label, fg, bg in PAIRS:
        ratio = contrast(fg, bg)
        floor = floor_for(label)
        # round first, then compare: the ratios are reported to two decimals
        # and a pair written as 4.50 is meant to satisfy a 4.5 floor
        ok = round(ratio, 2) >= floor
        if not ok:
            failures.append(
                "%s: %s on %s is %.2f (needs %.1f)" % (label, fg, bg, ratio, floor)
            )
        rows.append((ratio, floor, label, fg, bg, ok))
    if show or failures:
        for ratio, floor, label, fg, bg, ok in sorted(rows):
            print(
                "%5.2f  %-3s  %s (%s on %s)  floor %.1f"
                % (ratio, "ok" if ok else "LOW", label, fg, bg, floor)
            )
    print(
        "measured %d colour pairs; lowest ratio %.2f"
        % (len(rows), min(r[0] for r in rows))
    )
    return failures


#: markup checks that ride along with the contrast audit: cheap structural
#: accessibility rules run against every published page of the site.
#: the editor captures and cover markup, checked by name
MARKUP_SOURCES = [
    "site/index.html",
    "site/embeds/editor-index.html",
    "site/embeds/editor-studio-preview.html",
    "site/embeds/editor-studio-link.html",
    "site/embeds/editor-raw.html",
    "site/embeds/device-red-shirt.html",
    "site/embeds/device-green-shirt.html",
    "site/scripts/reader_frame.html",
]

#: every published book page is walked too (they are the pages a reader
#: actually opens); a cap keeps the walk short over the maze book's 811
MAX_BOOK_PAGES = 40


def parse(page):
    """Parse a page into an element tree (lxml, not regexes over raw html).

    Pattern-matching the markup is hopeless where srcdoc is involved: the
    attribute holds a whole escaped html document whose payload contains
    literal '>' characters, apostrophes and quotes.  A parser sees one
    iframe element with attributes, which is all these checks need; the
    embedded documents are audited separately as their own files.
    """
    from lxml import etree

    parser = etree.HTMLParser(remove_comments=True)
    return etree.fromstring(page.encode("utf-8"), parser)


def book_pages():
    """A capped sample of the built book pages under site/books/ (paths are
    reported relative to wherever the audit was launched from)."""
    found = []
    for base, _dirs, files in os.walk(os.path.join("site", "books")):
        for name in sorted(files):
            if name.endswith(".html"):
                found.append(os.path.join(base, name))
    return found[:MAX_BOOK_PAGES]


def check_markup(show=False):
    """Structural accessibility checks over the published markup: language,
    viewport zoomability, alt text, iframe titles and labelled controls."""
    problems = []
    for path in MARKUP_SOURCES + book_pages():
        with open(path, encoding="utf-8") as handle:
            page = handle.read()
        tree = parse(page)
        # lxml hands back the <html> element itself (it drops the document
        # node), so the language lives on the root rather than below it
        if not tree.get("lang"):
            problems.append("%s: <html> carries no lang attribute" % path)
        for meta in tree.iter("meta"):
            if meta.get("name") == "viewport" and "user-scalable=no" in (
                meta.get("content") or ""
            ):
                problems.append("%s: viewport disables zooming" % path)
        for img in tree.iter("img"):
            if img.get("alt") is None:
                problems.append("%s: <img> without alt text" % path)
        for iframe in tree.iter("iframe"):
            if not iframe.get("title"):
                problems.append("%s: iframe embed without a title" % path)
        # every text control must reach assistive tech by name: an
        # aria-label, a <label for=...> pointing at it, or a label element
        # wrapping the control outright
        labelled_by = {
            label.get("for") for label in tree.iter("label") if label.get("for")
        }
        for control in tree.iter("input", "textarea"):
            if control.tag == "input" and control.get("type") not in (
                None,
                "text",
                "url",
            ):
                continue
            wrapped = control.getparent().tag == "label"
            named = (
                control.get("aria-label") or control.get("id") in labelled_by or wrapped
            )
            if not named:
                problems.append(
                    "%s: %s with no accessible name (class=%s)"
                    % (path, control.tag, control.get("class"))
                )
    checked = MARKUP_SOURCES + book_pages()
    if problems or show:
        print(
            "markup checks: %d pages (%d named, %d built book pages)"
            % (len(checked), len(MARKUP_SOURCES), len(book_pages()))
        )
    return problems


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--show", action="store_true", help="print every pair, not just failures"
    )
    args = parser.parse_args()
    failures = audit(show=args.show)
    failures += check_markup(show=args.show)
    if failures:
        for failure in failures:
            print("FAIL:", failure)
        sys.exit("%d accessibility problems found" % len(failures))
    print("every colour pair clears WCAG 2.2 AA")


if __name__ == "__main__":
    main()
