"""Tests for beware.meta."""

import os

import pytest

from beware.meta import BookMetadata

HERE = os.path.dirname(os.path.abspath(__file__))
NARRATIVES = os.path.join(HERE, "narratives")


def narrative(name):
    return os.path.join(NARRATIVES, name)


def test_defaults():
    meta = BookMetadata()
    assert meta.title == "Reader Beware Story"
    assert meta.language == "en-US"
    assert not meta.has_cover
    assert meta.cover_mime == ""


def test_from_yaml_config():
    meta = BookMetadata.from_config(narrative("book.yaml"))
    assert meta.title == "The Adventures of Sam"
    assert meta.author == "Margaret Killjoy"
    assert meta.description.strip().endswith("sam.")
    assert meta.publisher == "Test Publisher"
    assert meta.date == "2018-08-03"
    assert meta.cover == "Images/cover.png"
    assert meta.has_cover
    assert meta.cover_mime == "image/png"


def test_from_json_config():
    meta = BookMetadata.from_config(narrative("book.json"))
    assert meta.title == "Json Book"
    assert meta.author == "Someone"
    assert meta.description == "json description"


def test_no_config_returns_defaults():
    meta = BookMetadata.from_config(None)
    assert meta.title == "Reader Beware Story"


def test_unknown_keys_go_to_extras(tmp_path):
    cfg = str(tmp_path / "cfg.yaml")
    with open(cfg, "w") as f:
        f.write("title: X\nsome_extra: 42\n")
    meta = BookMetadata.from_config(cfg)
    assert meta.title == "X"
    assert meta.extras.get("some_extra") == 42


def test_bad_config_raises(tmp_path):
    cfg = str(tmp_path / "cfg.yaml")
    with open(cfg, "w") as f:
        f.write("{{{ not valid yaml or json")
    with pytest.raises(ValueError):
        BookMetadata.from_config(cfg)


def test_as_dict_roundtrip():
    meta = BookMetadata(title="A", author="B")
    data = meta.as_dict()
    assert data["title"] == "A"
    restored = BookMetadata.from_dict(data)
    assert restored.title == "A"
    assert restored.author == "B"


def test_css_files_tuple():
    import tempfile, json as _json

    with tempfile.TemporaryDirectory() as d:
        cfg = os.path.join(d, "cfg.json")
        with open(cfg, "w") as f:
            _json.dump({"title": "T", "css_files": ["a.css"]}, f)
        meta = BookMetadata.from_config(cfg)
        assert meta.css_files == ("a.css",) or meta.css_files == ["a.css"]
