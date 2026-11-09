"""Tests for interstitial "dead" pages (nuclear-waste-warning guardrails).

Dead pages are optional, configured in the book config, and dropped between
each section and the next in the epub spine so a reader flipping through
linearly cannot get lost.  Choice links jump straight over them.
"""

import os
import re
import zipfile

from lxml import etree

from beware.build_epub import EPubWorldBuilder
from beware.meta import BookMetadata, DeadPageConfig, DEFAULT_DEAD_PAGE_MESSAGES

HERE = os.path.dirname(os.path.abspath(__file__))
NARRATIVES = os.path.join(HERE, "narratives")


def narrative(name):
    return os.path.join(NARRATIVES, name)


def build_epub(out, meta):
    builder = EPubWorldBuilder(narrative("simple.yaml"), out)
    builder.build()
    return builder.build_epub(meta)


def dead_files(epub_file):
    with zipfile.ZipFile(epub_file) as z:
        return sorted(n for n in z.namelist() if "/dead-" in n)


def spine_hrefs(epub_file):
    """Ordered list of hrefs in the reading (spine) order."""
    with zipfile.ZipFile(epub_file) as z:
        opf = z.read("EPUB/content.opf").decode()
    uid_to_href = {i: h for h, i in re.findall(r'<item href="([^"]+)" id="([^"]+)"', opf)}
    spine_block = opf.split("<spine", 1)[1]
    idrefs = re.findall(r'idref="([^"]+)"', spine_block)
    return [uid_to_href[r] for r in idrefs]


def test_disabled_by_default(out):
    epub_file = build_epub(out, BookMetadata())
    assert dead_files(epub_file) == []
    with zipfile.ZipFile(epub_file) as z:
        # mimetype + container + opf + css + 3 pages, no dead pages
        assert len(z.namelist()) == 7


def test_enabled_inserts_dead_pages_between_sections(out):
    epub_file = build_epub(out, BookMetadata(dead_pages=DeadPageConfig(count=3)))
    # simple.yaml has 3 sections -> 2 gaps -> 6 dead pages
    assert len(dead_files(epub_file)) == 6
    order = spine_hrefs(epub_file)
    # real, dead x3, real, dead x3, real (last section gets no trailing dead)
    pattern = ["R", "D", "D", "D", "R", "D", "D", "D", "R"]
    got = ["D" if "/dead-" in h else "R" for h in order]
    assert got == pattern


def test_true_enables_defaults(out):
    epub_file = build_epub(out, BookMetadata(dead_pages=True))
    # default count is 3 -> 2 gaps x 3 = 6
    assert len(dead_files(epub_file)) == 6


def test_custom_messages_used(out):
    custom = ("STOP. Do not read further.", "This page is a trap.")
    meta = BookMetadata(
        dead_pages=DeadPageConfig(count=2, messages=custom)
    )
    epub_file = build_epub(out, meta)
    with zipfile.ZipFile(epub_file) as z:
        bodies = [z.read(n).decode() for n in dead_files(epub_file)]
    assert any("STOP. Do not read further." in b for b in bodies)
    assert any("This page is a trap." in b for b in bodies)
    # default copy must NOT leak in when custom messages are supplied
    assert not any(
        m in b for b in bodies for m in DEFAULT_DEAD_PAGE_MESSAGES
    )


def test_count_cycles_messages(out):
    meta = BookMetadata(
        dead_pages=DeadPageConfig(count=5, messages=("only one line",))
    )
    epub_file = build_epub(out, meta)
    # 2 gaps x 5 pages = 10 dead pages, all showing the single cycled message
    files = dead_files(epub_file)
    assert len(files) == 10
    with zipfile.ZipFile(epub_file) as z:
        bodies = [z.read(n).decode() for n in files]
    assert all("only one line" in b for b in bodies)


def test_include_after_last(out):
    meta = BookMetadata(
        dead_pages=DeadPageConfig(count=3, include_after_last=True)
    )
    epub_file = build_epub(out, meta)
    # now all 3 sections are followed by dead pages -> 3 gaps x 3 = 9
    assert len(dead_files(epub_file)) == 9
    got = ["D" if "/dead-" in h else "R" for h in spine_hrefs(epub_file)]
    assert got == ["R", "D", "D", "D"] * 3


def test_dead_pages_are_well_formed_xhtml(out):
    epub_file = build_epub(out, BookMetadata(dead_pages=DeadPageConfig(count=3)))
    with zipfile.ZipFile(epub_file) as z:
        for name in dead_files(epub_file):
            root = etree.fromstring(z.read(name))
            assert root is not None


def test_from_config_yaml_parses_dead_pages(out):
    cfg = os.path.join(os.path.dirname(out), "dead-cfg.yaml")
    with open(cfg, "w") as f:
        f.write(
            "title: Dead Book\n"
            "dead_pages:\n"
            "  count: 4\n"
            "  include_after_last: true\n"
            "  messages:\n"
            "    - First warning.\n"
            "    - Second warning.\n"
        )
    meta = BookMetadata.from_config(cfg)
    assert isinstance(meta.dead_pages, DeadPageConfig)
    assert meta.dead_pages.count == 4
    assert meta.dead_pages.include_after_last is True
    assert meta.dead_pages.messages == ("First warning.", "Second warning.")
    # 4 pages cycled over 2 messages -> [0,1,0,1]
    texts = meta.dead_page_texts()
    assert texts == [
        "First warning.",
        "Second warning.",
        "First warning.",
        "Second warning.",
    ]


def test_dead_page_texts_disabled(out):
    assert BookMetadata().dead_page_texts() == []
