"""Tests for beware.web."""

import os
import re

from beware.cli import cli as cli_group

HERE = os.path.dirname(os.path.abspath(__file__))
NARRATIVES = os.path.join(HERE, 'narratives')


def narrative(name):
    return os.path.join(NARRATIVES, name)


def make_app(tmp_path):
    from beware.web import create_app
    root = str(tmp_path / 'stories')
    os.makedirs(root, exist_ok=True)
    return create_app(root), root


def test_lists_stories(tmp_path):
    app, root = make_app(tmp_path)
    client = app.test_client()
    # seed a story file on disk (simulates existing content)
    with open(os.path.join(root, 'seed.yaml'), 'w') as f:
        f.write(open(narrative('simple.yaml')).read())
    r = client.get('/')
    assert r.status_code == 200
    assert 'seed.yaml' in r.get_data(as_text=True)


def test_create_and_edit_roundtrip(tmp_path):
    app, root = make_app(tmp_path)
    client = app.test_client()
    body = ("---\nentrypoint:\n  body: |\n"
            "    hello [go]({{ 'next'|explore }})\n"
            "next:\n  body: |\n    done\n")
    r = client.post('/create/my%2Fbook.yaml', data={'body': body})
    assert r.status_code == 302
    target = os.path.join(root, 'my' + os.sep, 'book.yaml')
    assert os.path.exists(target)
    saved = open(target).read()
    assert saved == body
    # edit page shows content and validates clean (no inline error box)
    r = client.get('/my%2Fbook.yaml')
    assert r.status_code == 200
    text = r.get_data(as_text=True)
    assert 'hello' in text
    assert re.search(r'class=\"errors\"', text) is None


def test_autosave_validation_endpoint(tmp_path):
    app, root = make_app(tmp_path)
    client = app.test_client()
    with open(os.path.join(root, 'v.yaml'), 'w') as f:
        f.write('entrypoint:\n  body: ok\n')
    r = client.post('/validate/v.yaml', data={
        'body': "entrypint:\n  body: |\n    x {{ y \n"})
    assert r.status_code == 200
    errors = r.json['errors']
    assert any('missing entrypoint' in e for e in errors)
    assert any('jinja error' in e for e in errors)


def test_save_writes_and_reloads(tmp_path):
    app, root = make_app(tmp_path)
    client = app.test_client()
    with open(os.path.join(root, 's.yaml'), 'w') as f:
        f.write('entrypoint:\n  body: old\n')
    r = client.post('/save/s.yaml', data={
        'body': 'entrypoint:\n  body: new\n'})
    assert r.status_code == 302
    after = open(os.path.join(root, 's.yaml')).read()
    assert 'new' in after and 'old' not in after
    # external edit before next GET is picked up (reloads on save)
    with open(os.path.join(root, 's.yaml'), 'w') as f:
        f.write('entrypoint:\n  body: externally-edited\n')
    r = client.get('/s.yaml')
    assert 'externally-edited' in r.get_data(as_text=True)


def test_delete_removes_file(tmp_path):
    app, root = make_app(tmp_path)
    client = app.test_client()
    with open(os.path.join(root, 'd.yaml'), 'w') as f:
        f.write('entrypoint:\n  body: x\n')
    r = client.post('/delete/d.yaml')
    assert r.status_code == 302
    assert not os.path.exists(os.path.join(root, 'd.yaml'))


def test_path_traversal_blocked(tmp_path):
    app, root = make_app(tmp_path)
    client = app.test_client()
    secret = str(tmp_path / 'outside.yaml')
    with open(secret, 'w') as f:
        f.write('entrypoint:\n  body: x\n')
    rel = os.path.relpath(secret, root).replace(os.sep, '/')
    r = client.get('/%2E%2E%2Foutside.yaml' if False else
                   '/' + rel.replace('/', '%2F'))
    # path resolves outside root -> rejected with 404
    assert r.status_code in (404,)


def test_rejects_non_yaml_extension(tmp_path):
    app, root = make_app(tmp_path)
    client = app.test_client()
    with open(os.path.join(root, 'evil.txt'), 'w') as f:
        f.write('hello')
    r = client.get('/evil.txt')
    assert r.status_code == 404


def test_validate_narrative_function():
    from beware.web import validate_narrative
    good = open(narrative('simple.yaml')).read()
    assert validate_narrative(good) == []
    bad_missing = open(narrative('missing.yaml')).read()
    errors = validate_narrative(bad_missing)
    assert any('undefined section' in e for e in errors)


def test_story_text_is_escaped_in_pages(tmp_path):
    """Bodies contain raw markup/jinja; pages must never inject it."""
    app, root = make_app(tmp_path)
    client = app.test_client()
    evil = ('entrypoint:\n  body: |\n'
            '    <script>alert(1)</script> {{ \'x\'|explore }}\n')
    with open(os.path.join(root, 'e.yaml'), 'w') as f:
        f.write(evil)
    r = client.get('/e.yaml')
    text = r.get_data(as_text=True)
    assert '<script>alert(1)</script>' not in text
    assert '&lt;script&gt;' in text or '&#60;' in repr(text)


def test_list_stories_finds_yaml_only(tmp_path):
    from beware.web import list_stories
    app, root = make_app(tmp_path)
    os.makedirs(os.path.join(root, 'deeper'))
    open(os.path.join(root, 'a.yaml'), 'w').write('x: 1\n')
    open(os.path.join(root, 'b.yml'), 'w').write('y: 2\n')
    open(os.path.join(root, 'ignore.txt'), 'w').write('nope\n')
    open(os.path.join(root, 'deeper', 'c.yaml'), 'w').write('z: 3\n')
    stories = list_stories(root)
    assert sorted(stories) == ['a.yaml', 'b.yml',
                                os.path.join('deeper', 'c.yaml').replace(
                                    os.sep, '/')]


def test_serve_command_registered():
    from click.testing import CliRunner
    runner = CliRunner()
    result = runner.invoke(cli_group, ['serve', '--help'])
    assert result.exit_code == 0
    assert '--root' in result.output and '--port' in result.output
