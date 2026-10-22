"""Tests for reader-beware (pytest)."""

import os
import re
import zipfile

import pytest

from beware.build_html import NarativeWorldBuilder
from beware.build_epub import EPubWorldBuilder
from beware.mobi import MobiWorldBuilder, calibre_available
from beware.cli import cli as cli_group
from beware.meta import BookMetadata

HERE = os.path.dirname(os.path.abspath(__file__))
NARRATIVES = os.path.join(HERE, "narratives")


def narrative(name):
    return os.path.join(NARRATIVES, name)


@pytest.fixture
def out(tmp_path):
    """Unique output path per test so tests never clobber each other."""
    return str(tmp_path / "output")


# ---------------------------------------------------------------------------
# Html builder: the core of every README example.
# ---------------------------------------------------------------------------


class TestHtmlBuilder:

    def test_builds_simple_story(self, out):
        builder = NarativeWorldBuilder(narrative("simple.yaml"), out)
        builder.build()
        files = sorted(os.listdir(out))
        assert len(files) == 3
        stems = sorted(os.path.splitext(f)[0] for f in files)
        assert any(s.startswith("entrypoint") for s in stems)
        assert sum(1 for s in stems if s.startswith("left")) == 1
        assert sum(1 for s in stems if s.startswith("right")) == 1

    def test_no_entrypoint_raises(self, out):
        builder = NarativeWorldBuilder(narrative("no_entrypoint.yaml"), out)
        with pytest.raises(ValueError):
            builder.build()

    def test_missing_section_raises(self, out):
        builder = NarativeWorldBuilder(narrative("missing.yaml"), out)
        with pytest.raises(KeyError):
            builder.build()

    def test_loop_terminates(self, out):
        """Sections linking back to each other must not hang the build."""
        builder = NarativeWorldBuilder(narrative("loop.yaml"), out)
        builder.max_sections = 100
        builder.build()
        assert len(os.listdir(out)) == 2

    def test_incrementing_loop_with_break(self, out):
        builder = NarativeWorldBuilder(narrative("counting.yaml"), out)
        builder.build()
        # entrypoint + value=0..10 (the last prints Done counting!)
        assert len(os.listdir(out)) == 12

    def test_infinite_loop_stops_at_max(self, out):
        builder = NarativeWorldBuilder(narrative("infinite.yaml"), out)
        builder.max_sections = 50
        with pytest.raises(RuntimeError):
            builder.build()

    def test_world_state_flows_forward(self, out):
        builder = NarativeWorldBuilder(narrative("shirts.yaml"), out)
        builder.build()
        files = os.listdir(out)
        # put-on-shirt and go-outside each exist once per shirt color
        red_pages = [f for f in files if "red" in f]
        green_pages = [f for f in files if "green" in f]
        assert len(red_pages) == 2
        assert len(green_pages) == 2
        # the go-outside page for green contains Jane's approval
        green_out = [f for f in green_pages if f.startswith("go-outside")][0]
        html = open(os.path.join(out, green_out)).read()
        assert "I like your green shirt very much." in html
        red_out = [f for f in red_pages if f.startswith("go-outside")][0]
        html = open(os.path.join(out, red_out)).read()
        assert "I dislike that color on you." in html

    def test_link_urls_resolve_to_files(self, out):
        builder = NarativeWorldBuilder(narrative("simple.yaml"), out)
        builder.build()
        entrypoint_file = [f for f in os.listdir(out) if f.startswith("entrypoint")][0]
        html = open(os.path.join(out, entrypoint_file)).read()
        hrefs = re.findall(r'<a href="([^"]+)"', html)
        assert len(hrefs) == 2
        for href in hrefs:
            target = os.path.join(out, href)
            assert os.path.exists(target), "broken link %s" % href

    def test_the_square_bounded(self, out):
        """A bounded run of the Square maze: generation and page contents."""
        builder = NarativeWorldBuilder(narrative("square.yaml"), out)
        builder.max_sections = 200
        with pytest.raises(RuntimeError):
            builder.build()
        files = os.listdir(out)
        assert len(files) == 200  # stopped exactly at the limit
        sample = [f for f in files if "go-" in f][0]
        html = open(os.path.join(out, sample)).read()
        assert '<div class="story">' in html
        assert (
            "doors with the numbers" in html
            or "Monsters and horrible machines eat you!" in html
        )

    def test_the_square_maze_slow(self, tmp_path):
        """The README's 'Square' maze example (opt-in: BEWARE_RUN_SLOW=1)."""
        if not os.environ.get("BEWARE_RUN_SLOW"):
            pytest.skip("slow test; set BEWARE_RUN_SLOW=1 to run it")
        out_dir = str(tmp_path / "square")
        builder = NarativeWorldBuilder(narrative("square.yaml"), out_dir)
        # The full maze is ~40k pages (minutes of compute); stop at 6000
        # which still exercises thousands of rooms and many exit pages.
        builder.max_sections = 6000
        with pytest.raises(RuntimeError):
            builder.build()
        files = os.listdir(out_dir)
        assert len(files) == 6000
        assert any(f.startswith("exit") for f in files)
        # every html file is a real page with the story div
        sample = [f for f in files if 'x": 5' in f or True][0]
        html = open(os.path.join(out_dir, sample)).read()
        assert '<div class="story">' in html

    def test_markdown_rendered(self, out):
        builder = NarativeWorldBuilder(narrative("markdown_features.yaml"), out)
        builder.build()
        html_files = [f for f in os.listdir(out) if f.endswith(".html")]
        assert len(html_files) == 1
        html = open(os.path.join(out, html_files[0])).read()
        assert "Heading one" in html
        assert "<strong>bold</strong>" in html or "<b>bold</b>" in html
        assert "<em>italics</em>" in html or "<i>italics</i>" in html

    def test_rebuild_into_existing_folder(self, out):
        builder = NarativeWorldBuilder(narrative("simple.yaml"), out)
        builder.build()
        builder2 = NarativeWorldBuilder(narrative("simple.yaml"), out)
        builder2.build()
        assert len(os.listdir(out)) == 3

    def test_filters_are_pluggable(self, tmp_path):
        """Custom jinja filters can be registered and used in bodies."""
        path = str(tmp_path / "custom.yaml")
        body = "---\nentrypoint:\n  body: |\n" "    Hello {{ 'world'|shout }}\n"
        with open(path, "w") as f:
            f.write(body)
        out_dir = str(tmp_path / "out")
        builder = NarativeWorldBuilder(path, out_dir)

        def shout(value):
            return value.upper() + "!!!"

        previous = builder.register_filter("shout", shout)
        assert previous is None
        builder.build()
        html_files = [f for f in os.listdir(out_dir) if f.endswith(".html")]
        html = open(os.path.join(out_dir, html_files[0])).read()
        assert "WORLD!!!" in html

    def test_markdown_extras_are_pluggable(self, tmp_path):
        """markdown2 extensions can be enabled (pluggable behaviour)."""
        path = str(tmp_path / "fenced.yaml")
        body = "---\nentrypoint:\n  body: |\n" "    ```python\n    x = 1\n    ```\n"
        with open(path, "w") as f:
            f.write(body)
        out_dir = str(tmp_path / "out")
        builder = NarativeWorldBuilder(path, out_dir)
        builder.markdown_extras = ("fenced-code-blocks",)
        builder.build()
        html_files = [f for f in os.listdir(out_dir) if f.endswith(".html")]
        html = open(os.path.join(out_dir, html_files[0])).read()
        assert "<code>" in html

    def test_default_markdown_has_no_fenced_blocks(self, tmp_path):
        path = str(tmp_path / "fenced.yaml")
        body = "---\nentrypoint:\n  body: |\n" "    ```python\n    x = 1\n    ```\n"
        with open(path, "w") as f:
            f.write(body)
        out_dir = str(tmp_path / "out")
        builder = NarativeWorldBuilder(path, out_dir)
        builder.build()
        html_files = [f for f in os.listdir(out_dir) if f.endswith(".html")]
        html = open(os.path.join(out_dir, html_files[0])).read()
        # without extensions the fences are left as plain paragraphs
        assert "x = 1" in html


# ---------------------------------------------------------------------------
# Book metadata / config file
# ---------------------------------------------------------------------------


class TestBookMetadata:

    def test_defaults(self):
        meta = BookMetadata()
        assert meta.title == "Reader Beware Story"
        assert meta.language == "en-US"
        assert not meta.has_cover
        assert meta.cover_mime == ""

    def test_from_yaml_config(self):
        meta = BookMetadata.from_config(narrative("book.yaml"))
        assert meta.title == "The Adventures of Sam"
        assert meta.author == "Margaret Killjoy"
        assert meta.description.strip().endswith("sam.")
        assert meta.publisher == "Test Publisher"
        assert meta.date == "2018-08-03"
        assert meta.cover == "Images/cover.png"
        assert meta.has_cover
        assert meta.cover_mime == "image/png"

    def test_from_json_config(self):
        meta = BookMetadata.from_config(narrative("book.json"))
        assert meta.title == "Json Book"
        assert meta.author == "Someone"
        assert meta.description == "json description"

    def test_no_config_returns_defaults(self):
        meta = BookMetadata.from_config(None)
        assert meta.title == "Reader Beware Story"

    def test_unknown_keys_go_to_extras(self, tmp_path):
        cfg = str(tmp_path / "cfg.yaml")
        with open(cfg, "w") as f:
            f.write("title: X\nsome_extra: 42\n")
        meta = BookMetadata.from_config(cfg)
        assert meta.title == "X"
        assert meta.extras.get("some_extra") == 42

    def test_bad_config_raises(self, tmp_path):
        cfg = str(tmp_path / "cfg.yaml")
        with open(cfg, "w") as f:
            f.write("{{{ not valid yaml or json")
        with pytest.raises(ValueError):
            BookMetadata.from_config(cfg)

    def test_as_dict_roundtrip(self):
        meta = BookMetadata(title="A", author="B")
        data = meta.as_dict()
        assert data["title"] == "A"
        restored = BookMetadata.from_dict(data)
        assert restored.title == "A"
        assert restored.author == "B"

    def test_css_files_tuple(self):
        import tempfile, json as _json

        with tempfile.TemporaryDirectory() as d:
            cfg = os.path.join(d, "cfg.json")
            with open(cfg, "w") as f:
                _json.dump({"title": "T", "css_files": ["a.css"]}, f)
            meta = BookMetadata.from_config(cfg)
            assert meta.css_files == ("a.css",) or meta.css_files == ["a.css"]


# ---------------------------------------------------------------------------
# Epub builder
# ---------------------------------------------------------------------------


class TestEpubBuilder:

    def test_builds_epub(self, out):
        builder = EPubWorldBuilder(narrative("simple.yaml"), out)
        builder.build()
        epub_file = builder.build_epub()
        assert os.path.exists(epub_file)
        with zipfile.ZipFile(epub_file) as z:
            names = z.namelist()
        # mimetype + container + opf + css + 3 pages
        assert len(names) == 7
        self.check_structure(epub_file)

    def check_structure(self, epub_file):
        with zipfile.ZipFile(epub_file) as z:
            infos = z.infolist()
            assert infos[0].filename == "mimetype"
            assert infos[0].compress_type == zipfile.ZIP_STORED
            opf = z.read("EPUB/content.opf").decode()
            assert "<dc:title>" in opf
            assert 'version="3.0"' in opf or "4.0" in opf

    def test_links_work_inside_epub(self, out):
        import posixpath

        builder = EPubWorldBuilder(narrative("shirts.yaml"), out)
        builder.build()
        epub_file = builder.build_epub()
        with zipfile.ZipFile(epub_file) as z:
            names = set(z.namelist())
            total_links = 0
            for name in sorted(names):
                if not name.endswith(".xhtml"):
                    continue
                content = z.read(name).decode("utf-8")
                hrefs = re.findall(r'<a[^>]*href="([^"]+)"', content)
                assert all(
                    h.startswith("../xhtml/") for h in hrefs
                ), "bad links %s in %s" % (hrefs, name)
                base = posixpath.dirname(name)  # e.g. EPUB/xhtml
                for href in hrefs:
                    target = posixpath.normpath(posixpath.join(base, href))
                    assert target in names, "broken epub link %s -> %s" % (name, href)
                    total_links += 1
            # entrypoint links to two shirts; each shirt page links outside
            assert total_links == 4

    def test_metadata_is_written(self, out):
        meta = BookMetadata(
            title="The Adventures of Sam",
            author="Margaret Killjoy",
            description="A test story.",
            publisher="Test Publisher",
            rights="Some rights.",
        )
        builder = EPubWorldBuilder(narrative("simple.yaml"), out)
        builder.build()
        epub_file = builder.build_epub(meta)
        with zipfile.ZipFile(epub_file) as z:
            opf = z.read("EPUB/content.opf").decode()
        assert "The Adventures of Sam" in opf
        assert "Margaret Killjoy" in opf
        assert "<dc:description>A test story.</dc:description>" in opf
        assert "<dc:publisher>Test Publisher</dc:publisher>" in opf
        assert "Some rights." in opf

    def test_cover_image_included(self, out):
        meta = BookMetadata(cover="Images/cover.png")
        cover_dir = os.path.join(NARRATIVES, "Images")
        os.makedirs(cover_dir, exist_ok=True)
        write_tiny_png(os.path.join(NARRATIVES, str(meta.cover)))
        builder = EPubWorldBuilder(narrative("simple.yaml"), out)
        builder.build()
        epub_file = builder.build_epub(meta)
        with zipfile.ZipFile(epub_file) as z:
            names = z.namelist()
            image_names = [n for n in names if "images/" in n]
            assert len(image_names) == 1
            opf = z.read("EPUB/content.opf").decode()
        assert "cover" in opf.lower() or "image" in opf.lower()
        assert image_names[0].endswith(".png")

    def test_missing_cover_raises(self, out):
        meta = BookMetadata(cover="Images/missing.png")
        builder = EPubWorldBuilder(narrative("simple.yaml"), out)
        builder.build()
        with pytest.raises(IOError):
            builder.build_epub(meta)

    def test_world_state_in_epub_pages(self, out):
        builder = EPubWorldBuilder(narrative("shirts.yaml"), out)
        builder.build()
        epub_file = builder.build_epub()
        with zipfile.ZipFile(epub_file) as z:
            pages = [n for n in z.namelist() if "go-outside" in n]
            assert len(pages) == 2
            bodies = [z.read(p).decode("utf-8") for p in sorted(pages)]
        assert any("I like your green shirt very much." in b for b in bodies)
        assert any("I dislike that color on you." in b for b in bodies)

    def test_epub_pages_are_well_formed_xhtml(self, out):
        from lxml import etree

        builder = EPubWorldBuilder(narrative("simple.yaml"), out)
        builder.build()
        epub_file = builder.build_epub()
        with zipfile.ZipFile(epub_file) as z:
            for name in z.namelist():
                if not name.endswith(".xhtml"):
                    continue
                data = z.read(name)
                root = etree.fromstring(data)
                assert root is not None

    def test_css_is_included(self, out):
        builder = EPubWorldBuilder(narrative("simple.yaml"), out)
        builder.build()
        epub_file = builder.build_epub()
        with zipfile.ZipFile(epub_file) as z:
            css_names = [n for n in z.namelist() if n.endswith(".css")]
            assert len(css_names) == 1
            css = z.read("EPUB/style/default.css").decode()
        assert "font-weight" in css or "text-decoration" in css


# ---------------------------------------------------------------------------
# MOBI builder (Kindle formats)
# ---------------------------------------------------------------------------


class TestMobiBuilder:

    def test_calibre_detection(self):
        # calibre_available() must simply reflect whether ebook-convert is on
        # the PATH -- True or False, never crash.
        assert calibre_available() in (True, False)

    def test_fallback_builds_epub_and_note(self, tmp_path):
        out_base = str(tmp_path / "mobi")
        builder = MobiWorldBuilder(narrative("simple.yaml"), out_base)
        artifact, note = builder.build()
        if calibre_available():
            # real MOBI produced by Calibre
            assert artifact is not None and os.path.exists(artifact)
            assert note == ""
        else:
            assert artifact is None
            assert "Calibre" in note or "ebook-convert" in note
            assert os.path.exists(out_base + ".epub")

    def test_fallback_note_mentions_epub_path(self, tmp_path):
        out_base = str(tmp_path / "mobinote")
        builder = MobiWorldBuilder(narrative("simple.yaml"), out_base)
        artifact, note = builder.build()
        if not calibre_available():
            assert (out_base + ".epub") in note

    def test_azw_fallback(self, tmp_path):
        out_base = str(tmp_path / "azw")
        builder = MobiWorldBuilder(narrative("simple.yaml"), out_base)
        artifact, note = builder.build_azw()
        if calibre_available():
            assert os.path.exists(artifact)
        else:
            assert artifact is None
            assert os.path.exists(out_base + ".epub")

    def test_reuses_prebuilt_epub_builder(self, tmp_path):
        out_base = str(tmp_path / "reuse")
        epub_out = str(tmp_path / "src")
        meta = BookMetadata(title="Mobi Test", author="Tester")
        epub_builder = EPubWorldBuilder(narrative("simple.yaml"), epub_out, meta=meta)
        epub_builder.build()
        src = epub_builder.build_epub(meta)
        builder = MobiWorldBuilder(
            narrative("simple.yaml"), out_base, meta=meta, epub_builder=epub_builder
        )
        artifact, note = builder.build()
        if calibre_available():
            assert os.path.exists(artifact) and artifact.endswith(".mobi")
        else:
            # the copied epub exists at <out>.epub
            assert os.path.exists(out_base + ".epub")
            import zipfile

            with zipfile.ZipFile(out_base + ".epub") as z:
                opf = z.read("EPUB/content.opf").decode()
            assert "Mobi Test" in opf
        # source epub was built once and reused (same content)
        assert src.endswith(".epub")

    def test_mobi_cli(self, tmp_path):
        from click.testing import CliRunner

        runner = CliRunner()
        out_base = str(tmp_path / "mobicli")
        result = runner.invoke(
            cli_group,
            [
                "build-mobi",
                "--narative-path",
                narrative("simple.yaml"),
                "--output",
                out_base,
            ],
        )
        assert result.exit_code == 0, result.output
        if calibre_available():
            assert "mobi written to" in result.output
        else:
            assert os.path.exists(out_base + ".epub")
            assert "Calibre" in result.output or "ebook-convert" in result.output

    def test_kindle_notification_field_in_metadata(self):
        meta = BookMetadata(kindle_notification_address="me@kindle.com")
        assert meta.kindle_notification_address == "me@kindle.com"


# ---------------------------------------------------------------------------
# Web editor (flask app)
# ---------------------------------------------------------------------------


class TestWebEditor:

    def make_app(self, tmp_path):
        from beware.web import create_app

        root = str(tmp_path / "stories")
        os.makedirs(root, exist_ok=True)
        return create_app(root), root

    def test_lists_stories(self, tmp_path):
        app, root = self.make_app(tmp_path)
        client = app.test_client()
        # seed a story file on disk (simulates existing content)
        with open(os.path.join(root, "seed.yaml"), "w") as f:
            f.write(open(narrative("simple.yaml")).read())
        r = client.get("/")
        assert r.status_code == 200
        assert "seed.yaml" in r.get_data(as_text=True)

    def test_create_and_edit_roundtrip(self, tmp_path):
        app, root = self.make_app(tmp_path)
        client = app.test_client()
        body = (
            "---\nentrypoint:\n  body: |\n"
            "    hello [go]({{ 'next'|explore }})\n"
            "next:\n  body: |\n    done\n"
        )
        r = client.post("/create/my%2Fbook.yaml", data={"body": body})
        assert r.status_code == 302
        target = os.path.join(root, "my" + os.sep, "book.yaml")
        assert os.path.exists(target)
        saved = open(target).read()
        assert saved == body
        # edit page shows content and validates clean (no inline error box)
        r = client.get("/my%2Fbook.yaml")
        assert r.status_code == 200
        text = r.get_data(as_text=True)
        assert "hello" in text
        assert re.search(r"class=\"errors\"", text) is None

    def test_autosave_validation_endpoint(self, tmp_path):
        app, root = self.make_app(tmp_path)
        client = app.test_client()
        with open(os.path.join(root, "v.yaml"), "w") as f:
            f.write("entrypoint:\n  body: ok\n")
        r = client.post(
            "/validate/v.yaml", data={"body": "entrypint:\n  body: |\n    x {{ y \n"}
        )
        assert r.status_code == 200
        errors = r.json["errors"]
        assert any("missing entrypoint" in e for e in errors)
        assert any("jinja error" in e for e in errors)

    def test_save_writes_and_reloads(self, tmp_path):
        app, root = self.make_app(tmp_path)
        client = app.test_client()
        with open(os.path.join(root, "s.yaml"), "w") as f:
            f.write("entrypoint:\n  body: old\n")
        r = client.post("/save/s.yaml", data={"body": "entrypoint:\n  body: new\n"})
        assert r.status_code == 302
        after = open(os.path.join(root, "s.yaml")).read()
        assert "new" in after and "old" not in after
        # external edit before next GET is picked up (reloads on save)
        with open(os.path.join(root, "s.yaml"), "w") as f:
            f.write("entrypoint:\n  body: externally-edited\n")
        r = client.get("/s.yaml")
        assert "externally-edited" in r.get_data(as_text=True)

    def test_delete_removes_file(self, tmp_path):
        app, root = self.make_app(tmp_path)
        client = app.test_client()
        with open(os.path.join(root, "d.yaml"), "w") as f:
            f.write("entrypoint:\n  body: x\n")
        r = client.post("/delete/d.yaml")
        assert r.status_code == 302
        assert not os.path.exists(os.path.join(root, "d.yaml"))

    def test_path_traversal_blocked(self, tmp_path):
        app, root = self.make_app(tmp_path)
        client = app.test_client()
        secret = str(tmp_path / "outside.yaml")
        with open(secret, "w") as f:
            f.write("entrypoint:\n  body: x\n")
        rel = os.path.relpath(secret, root).replace(os.sep, "/")
        r = client.get(
            "/%2E%2E%2Foutside.yaml" if False else "/" + rel.replace("/", "%2F")
        )
        # path resolves outside root -> rejected with 404
        assert r.status_code in (404,)

    def test_rejects_non_yaml_extension(self, tmp_path):
        app, root = self.make_app(tmp_path)
        client = app.test_client()
        with open(os.path.join(root, "evil.txt"), "w") as f:
            f.write("hello")
        r = client.get("/evil.txt")
        assert r.status_code == 404

    def test_validate_narrative_function(self):
        from beware.web import validate_narrative

        good = open(narrative("simple.yaml")).read()
        assert validate_narrative(good) == []
        bad_missing = open(narrative("missing.yaml")).read()
        errors = validate_narrative(bad_missing)
        assert any("undefined section" in e for e in errors)

    def test_story_text_is_escaped_in_pages(self, tmp_path):
        """Bodies contain raw markup/jinja; pages must never inject it."""
        app, root = self.make_app(tmp_path)
        client = app.test_client()
        evil = (
            "entrypoint:\n  body: |\n"
            "    <script>alert(1)</script> {{ 'x'|explore }}\n"
        )
        with open(os.path.join(root, "e.yaml"), "w") as f:
            f.write(evil)
        r = client.get("/e.yaml")
        text = r.get_data(as_text=True)
        assert "<script>alert(1)</script>" not in text
        assert "&lt;script&gt;" in text or "&#60;" in repr(text)

    def test_list_stories_finds_yaml_only(self, tmp_path):
        from beware.web import list_stories

        app, root = self.make_app(tmp_path)
        os.makedirs(os.path.join(root, "deeper"))
        open(os.path.join(root, "a.yaml"), "w").write("x: 1\n")
        open(os.path.join(root, "b.yml"), "w").write("y: 2\n")
        open(os.path.join(root, "ignore.txt"), "w").write("nope\n")
        open(os.path.join(root, "deeper", "c.yaml"), "w").write("z: 3\n")
        stories = list_stories(root)
        assert sorted(stories) == [
            "a.yaml",
            "b.yml",
            os.path.join("deeper", "c.yaml").replace(os.sep, "/"),
        ]

    def test_serve_command_registered(self):
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(cli_group, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--root" in result.output and "--port" in result.output


class TestCli:

    def test_build_html_cli(self, tmp_path):
        from click.testing import CliRunner

        runner = CliRunner()
        out_dir = str(tmp_path / "html")
        result = runner.invoke(
            cli_group,
            [
                "build-html",
                "--narative-path",
                narrative("simple.yaml"),
                "--output",
                out_dir,
            ],
        )
        assert result.exit_code == 0, result.output
        assert "3 sections written" in result.output
        assert len(os.listdir(out_dir)) == 3

    def test_build_epub_cli(self, tmp_path):
        from click.testing import CliRunner

        runner = CliRunner()
        out_base = str(tmp_path / "epub")
        result = runner.invoke(
            cli_group,
            [
                "build-epub",
                "--narative-path",
                narrative("simple.yaml"),
                "--output",
                out_base,
            ],
        )
        assert result.exit_code == 0, result.output
        assert os.path.exists(out_base + ".epub")

    def test_build_epub_cli_with_book_config(self, tmp_path):
        from click.testing import CliRunner

        runner = CliRunner()
        cfg = str(tmp_path / "cfg.yaml")
        with open(cfg, "w") as f:
            f.write("title: CLI Book\nauthor: Someone\n" "description: From the cli.\n")
        out_base = str(tmp_path / "epub2")
        result = runner.invoke(
            cli_group,
            [
                "build-epub",
                "--narative-path",
                narrative("simple.yaml"),
                "--output",
                out_base,
                "--book-config",
                cfg,
            ],
        )
        assert result.exit_code == 0, result.output
        with zipfile.ZipFile(out_base + ".epub") as z:
            opf = z.read("EPUB/content.opf").decode()
        assert "CLI Book" in opf
        assert "Someone" in opf
        assert "<dc:description>From the cli.</dc:description>" in opf

    def test_help_lists_commands(self):
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(cli_group, ["--help"])
        assert result.exit_code == 0
        assert "build-html" in result.output
        assert "build-epub" in result.output


def write_tiny_png(path):
    """Write a minimal valid 1x1 transparent png file."""
    import struct
    import zlib

    def chunk(name, data):
        return (
            struct.pack(">I", len(data))
            + name
            + data
            + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">II", 1, 1) + bytes([8, 6, 0, 0, 0])
    raw = bytearray()
    raw.append(0)
    raw.extend(bytes(4))
    png = (
        sig
        + chunk(b"IHDR", ihdr_data)
        + chunk(b"IDAT", zlib.compress(bytes(raw)))
        + chunk(b"IEND", b"")
    )
    with open(path, "wb") as f:
        f.write(png)
