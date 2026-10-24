"""Tests for the section-based studio editor (beware.sections + web routes)."""

import json
import os

import pytest

from beware.sections import (
    parse_links,
    parse_sections,
    serialize_sections,
    split_kwargs,
)

HERE = os.path.dirname(os.path.abspath(__file__))
NARRATIVES = os.path.join(HERE, "narratives")

ENTRYPOINT_BODY = (
    "This is your opening page.\n\n"
    "[go left]({{ 'left'|explore }})\n\n"
    "[go right]({{ 'right'|choice(where='right') }})\n"
)


def narrative(name):
    return os.path.join(NARRATIVES, name)


def make_app(tmp_path):
    from beware.web import create_app

    root = str(tmp_path / "stories")
    os.makedirs(root, exist_ok=True)
    return create_app(root), root


def payload_of(sections):
    return {"payload": json.dumps({"sections": sections})}


# ---------------------------------------------------------------- parsing


def test_roundtrip_is_semantically_exact():
    text = open(narrative("simple.yaml")).read()
    sections = parse_sections(text)
    out = serialize_sections(sections)
    again = parse_sections(out)
    assert [s["name"] for s in sections] == [s["name"] for s in again]
    assert [s["body"] for s in sections] == [s["body"] for s in again]


def test_roundtrip_preserves_tricky_bodies():
    bodies = [
        "no trailing newline",
        "two trailing\n\n",
        "  leading indent\nx\n",
        "blank\n\nlines\n\n",
        "jinja {{ x }} and markdown # head\n",
        "",
    ]
    sections = [{"name": "entrypoint", "body": bodies[0], "extra": {}}]
    for index, body in enumerate(bodies):
        sections.append({"name": "s%d" % index, "body": body, "extra": {}})
    out = serialize_sections(sections)
    again = parse_sections(out)
    assert [s["body"] for s in again] == [bodies[0]] + bodies


def test_serialize_is_byte_stable_for_canonical_files():
    text = open(narrative("simple.yaml")).read()
    assert serialize_sections(parse_sections(text)) == text


def test_extras_are_preserved():
    sections = parse_sections(open(narrative("simple.yaml")).read())
    sections[0]["extra"] = {"note": "keep me", "when": 3}
    out = serialize_sections(sections)
    again = parse_sections(out)
    assert again[0]["extra"] == {"note": "keep me", "when": 3}


def test_quoted_keys_roundtrip():
    text = serialize_sections([{"name": "has space", "body": "x\n", "extra": {}}])
    assert '"has space"' in text
    assert parse_sections(text)[0]["name"] == "has space"


def test_parse_rejects_non_mapping():
    with pytest.raises(ValueError):
        parse_sections("just a string\n")


def test_parse_links_and_kwargs():
    links = parse_links(ENTRYPOINT_BODY)
    assert [(l["target"], l["kind"]) for l in links] == [
        ("left", "explore"),
        ("right", "choice"),
    ]
    assert split_kwargs(links[1]["args"]) == [("where", "'right'")]


# ---------------------------------------------------------------- studio pages


def test_studio_page_renders_cards(tmp_path):
    app, root = make_app(tmp_path)
    client = app.test_client()
    with open(os.path.join(root, "seed.yaml"), "w") as f:
        f.write(open(narrative("simple.yaml")).read())
    r = client.get("/seed.yaml")
    assert r.status_code == 200
    text = r.get_data(as_text=True)
    assert text.count('class="card" data-card') == 3
    assert "This is your opening page." in text
    assert 'id="problems"' in text  # hidden box exists but no error content
    assert "&#39;left&#39;" in text  # quotes are escaped on the way out


def test_studio_page_escapes_story_markup(tmp_path):
    app, root = make_app(tmp_path)
    client = app.test_client()
    evil = (
        "entrypoint:\n  body: |\n" "    <script>alert(1)</script> {{ 'x'|explore }}\n"
    )
    with open(os.path.join(root, "e.yaml"), "w") as f:
        f.write(evil)
    text = client.get("/e.yaml").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;" in text


def test_studio_page_shows_parse_error_and_raw_link(tmp_path):
    app, root = make_app(tmp_path)
    client = app.test_client()
    with open(os.path.join(root, "bad.yaml"), "w") as f:
        f.write("entrypoint:\n  body: |\n    x\n other:\n  body: |\n   bad tab\t\n")
    text = client.get("/bad.yaml").get_data(as_text=True)
    assert "Cannot edit this story as sections" in text
    assert "/raw/bad.yaml" in text


def test_raw_editor_route(tmp_path):
    app, root = make_app(tmp_path)
    client = app.test_client()
    with open(os.path.join(root, "seed.yaml"), "w") as f:
        f.write(open(narrative("simple.yaml")).read())
    r = client.get("/raw/seed.yaml")
    assert r.status_code == 200
    text = r.get_data(as_text=True)
    assert 'id="editor"' in text
    assert "section studio" in text


# ---------------------------------------------------------------- saving


def test_write_endpoint_saves_canonical_yaml(tmp_path):
    app, root = make_app(tmp_path)
    client = app.test_client()
    with open(os.path.join(root, "w.yaml"), "w") as f:
        f.write("entrypoint:\n  body: old\n")
    payload = payload_of(
        [
            {"name": "entrypoint", "body": ENTRYPOINT_BODY, "extra": ""},
            {"name": "left", "body": "done\n", "extra": ""},
            {
                "name": "right",
                "body": "where are we?\n",
                "extra": "note: kept\n",
            },
        ]
    )
    r = client.post("/write/w.yaml", data=payload)
    assert r.status_code == 200
    assert r.json["ok"] is True
    saved = open(os.path.join(root, "w.yaml")).read()
    assert saved.startswith("---\n")
    assert "note: kept" in saved
    sections = parse_sections(saved)
    assert [s["name"] for s in sections] == ["entrypoint", "left", "right"]
    assert sections[0]["body"] == ENTRYPOINT_BODY


def test_write_endpoint_rejects_duplicates_and_missing(tmp_path):
    app, root = make_app(tmp_path)
    client = app.test_client()
    open(os.path.join(root, "d.yaml"), "w").write("entrypoint:\n  body: x\n")
    dup = payload_of(
        [
            {"name": "a", "body": "", "extra": ""},
            {"name": "a", "body": "", "extra": ""},
        ]
    )
    r = client.post("/write/d.yaml", data=dup)
    assert r.status_code == 400
    assert any("duplicate" in e for e in r.json["errors"])
    missing = payload_of(
        [{"name": "entrypoint", "body": "[x]({{ 'gone'|explore }})\n", "extra": ""}]
    )
    r = client.post("/write/d.yaml", data=missing)
    assert r.status_code == 400
    assert any("undefined section" in e for e in r.json["errors"])


def test_validate_endpoint_accepts_payload(tmp_path):
    app, root = make_app(tmp_path)
    client = app.test_client()
    open(os.path.join(root, "v.yaml"), "w").write("entrypoint:\n  body: ok\n")
    payload = payload_of(
        [{"name": "nope", "body": "[x]({{ 'gone'|choice(a=1) }})\n", "extra": ""}]
    )
    r = client.post("/validate/v.yaml", data=payload)
    errors = r.json["errors"]
    assert any("missing entrypoint" in e for e in errors)
    assert any("undefined section" in e for e in errors)


def test_create_via_payload_answers_json(tmp_path):
    app, root = make_app(tmp_path)
    client = app.test_client()
    payload = payload_of(
        [
            {"name": "entrypoint", "body": ENTRYPOINT_BODY, "extra": ""},
            {"name": "left", "body": "a\n", "extra": ""},
            {"name": "right", "body": "b\n", "extra": ""},
        ]
    )
    r = client.post("/create/new%2Fbook.yaml", data=payload)
    assert r.status_code == 200
    assert r.json["ok"] is True
    target = os.path.join(root, "new" + os.sep, "book.yaml")
    assert os.path.exists(target)
    # second create conflicts
    r = client.post("/create/new%2Fbook.yaml", data=payload)
    assert r.status_code == 400
    assert any("already exists" in e for e in r.json["errors"])


def test_new_story_form_page(tmp_path):
    app, root = make_app(tmp_path)
    client = app.test_client()
    text = client.get("/new").get_data(as_text=True)
    assert "New story" in text
    assert 'id="rel-new"' in text
    assert text.count('class="card" data-card') == 1


# ---------------------------------------------------------------- preview


def test_preview_renders_markdown_and_jinja(tmp_path):
    app, root = make_app(tmp_path)
    client = app.test_client()
    open(os.path.join(root, "p.yaml"), "w").write("entrypoint:\n  body: x\n")
    r = client.post(
        "/preview/p.yaml",
        data={"body": "# Title\n\nA [link]({{ 'x'|choice(a=1) }}) and {{ nobody }}.\n"},
    )
    html = r.json["html"]
    assert "<h1>Title</h1>" in html
    assert 'href="#x"' in html
    # undefined variables render as nothing, not as an error page
    assert "Undefined" not in html


def test_preview_escapes_raw_html(tmp_path):
    app, root = make_app(tmp_path)
    client = app.test_client()
    open(os.path.join(root, "p.yaml"), "w").write("entrypoint:\n  body: x\n")
    r = client.post(
        "/preview/p.yaml",
        data={"body": "hello <script>alert(1)</script> world\n"},
    )
    html = r.json["html"]
    assert "<script>" not in html
    assert "&lt;script>" in html


def test_preview_reports_jinja_errors(tmp_path):
    app, root = make_app(tmp_path)
    client = app.test_client()
    open(os.path.join(root, "p.yaml"), "w").write("entrypoint:\n  body: x\n")
    r = client.post("/preview/p.yaml", data={"body": "{{ unclosed \n"})
    assert "error" in r.json


def test_preview_blocks_sandbox_escapes(tmp_path):
    app, root = make_app(tmp_path)
    client = app.test_client()
    open(os.path.join(root, "p.yaml"), "w").write("entrypoint:\n  body: x\n")
    r = client.post(
        "/preview/p.yaml",
        data={"body": "{{ ''.__class__.__mro__ }}\n"},
    )
    # sandbox refuses the attribute access; nothing dangerous is rendered
    assert "mro" not in str(r.json)
