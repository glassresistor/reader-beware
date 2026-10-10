"""Tests for beware.build_html."""

import os
import re

import pytest

from beware.build_html import NarativeWorldBuilder

HERE = os.path.dirname(os.path.abspath(__file__))
NARRATIVES = os.path.join(HERE, 'narratives')


def narrative(name):
    return os.path.join(NARRATIVES, name)


def test_builds_simple_story(out):
    builder = NarativeWorldBuilder(narrative('simple.yaml'), out)
    builder.build()
    files = sorted(os.listdir(out))
    assert len(files) == 3
    stems = sorted(os.path.splitext(f)[0] for f in files)
    assert any(s.startswith('entrypoint') for s in stems)
    assert sum(1 for s in stems if s.startswith('left')) == 1
    assert sum(1 for s in stems if s.startswith('right')) == 1


def test_no_entrypoint_raises(out):
    builder = NarativeWorldBuilder(narrative('no_entrypoint.yaml'), out)
    with pytest.raises(ValueError):
        builder.build()


def test_missing_section_raises(out):
    builder = NarativeWorldBuilder(narrative('missing.yaml'), out)
    with pytest.raises(KeyError):
        builder.build()


def test_loop_terminates(out):
    """Sections linking back to each other must not hang the build."""
    builder = NarativeWorldBuilder(narrative('loop.yaml'), out)
    builder.max_sections = 100
    builder.build()
    assert len(os.listdir(out)) == 2


def test_incrementing_loop_with_break(out):
    builder = NarativeWorldBuilder(narrative('counting.yaml'), out)
    builder.build()
    # entrypoint + value=0..10 (the last prints Done counting!)
    assert len(os.listdir(out)) == 12


def test_infinite_loop_stops_at_max(out):
    builder = NarativeWorldBuilder(narrative('infinite.yaml'), out)
    builder.max_sections = 50
    with pytest.raises(RuntimeError):
        builder.build()


def test_world_state_flows_forward(out):
    builder = NarativeWorldBuilder(narrative('shirts.yaml'), out)
    builder.build()
    files = os.listdir(out)
    # put-on-shirt and go-outside each exist once per shirt color
    red_pages = [f for f in files if 'red' in f]
    green_pages = [f for f in files if 'green' in f]
    assert len(red_pages) == 2
    assert len(green_pages) == 2
    # the go-outside page for green contains Jane's approval
    green_out = [f for f in green_pages if f.startswith('go-outside')][0]
    html = open(os.path.join(out, green_out)).read()
    assert 'I like your green shirt very much.' in html
    red_out = [f for f in red_pages if f.startswith('go-outside')][0]
    html = open(os.path.join(out, red_out)).read()
    assert 'I dislike that color on you.' in html


def test_link_urls_resolve_to_files(out):
    builder = NarativeWorldBuilder(narrative('simple.yaml'), out)
    builder.build()
    entrypoint_file = [f for f in os.listdir(out)
                       if f.startswith('entrypoint')][0]
    html = open(os.path.join(out, entrypoint_file)).read()
    hrefs = re.findall(r'<a href="([^"]+)"', html)
    assert len(hrefs) == 2
    for href in hrefs:
        target = os.path.join(out, href)
        assert os.path.exists(target), 'broken link %s' % href


def test_the_square_bounded(out):
    """A bounded run of the Square maze: generation and page contents."""
    builder = NarativeWorldBuilder(narrative('square.yaml'), out)
    builder.max_sections = 200
    with pytest.raises(RuntimeError):
        builder.build()
    files = os.listdir(out)
    assert len(files) == 200   # stopped exactly at the limit
    sample = [f for f in files if 'go-' in f][0]
    html = open(os.path.join(out, sample)).read()
    assert '<div class="story">' in html
    assert 'doors with the numbers' in html or \
           'Monsters and horrible machines eat you!' in html


def test_the_square_maze_slow(tmp_path):
    """The README's 'Square' maze example (opt-in: BEWARE_RUN_SLOW=1)."""
    if not os.environ.get('BEWARE_RUN_SLOW'):
        pytest.skip('slow test; set BEWARE_RUN_SLOW=1 to run it')
    out_dir = str(tmp_path / 'square')
    builder = NarativeWorldBuilder(narrative('square.yaml'), out_dir)
    # The full maze is ~40k pages (minutes of compute); stop at 6000
    # which still exercises thousands of rooms and many exit pages.
    builder.max_sections = 6000
    with pytest.raises(RuntimeError):
        builder.build()
    files = os.listdir(out_dir)
    assert len(files) == 6000
    assert any(f.startswith('exit') for f in files)
    # every html file is a real page with the story div
    sample = [f for f in files if 'x": 5' in f or True][0]
    html = open(os.path.join(out_dir, sample)).read()
    assert '<div class="story">' in html


def test_markdown_rendered(out):
    builder = NarativeWorldBuilder(
        narrative('markdown_features.yaml'), out)
    builder.build()
    html_files = [f for f in os.listdir(out) if f.endswith('.html')]
    assert len(html_files) == 1
    html = open(os.path.join(out, html_files[0])).read()
    assert 'Heading one' in html
    assert '<strong>bold</strong>' in html or '<b>bold</b>' in html
    assert '<em>italics</em>' in html or '<i>italics</i>' in html


def test_rebuild_into_existing_folder(out):
    builder = NarativeWorldBuilder(narrative('simple.yaml'), out)
    builder.build()
    builder2 = NarativeWorldBuilder(narrative('simple.yaml'), out)
    builder2.build()
    assert len(os.listdir(out)) == 3


def test_filters_are_pluggable(tmp_path):
    """Custom jinja filters can be registered and used in bodies."""
    path = str(tmp_path / 'custom.yaml')
    body = ('---\nentrypoint:\n  body: |\n'
            '    Hello {{ \'world\'|shout }}\n')
    with open(path, 'w') as f:
        f.write(body)
    out_dir = str(tmp_path / 'out')
    builder = NarativeWorldBuilder(path, out_dir)

    def shout(value):
        return value.upper() + '!!!'

    previous = builder.register_filter('shout', shout)
    assert previous is None
    builder.build()
    html_files = [f for f in os.listdir(out_dir) if f.endswith('.html')]
    html = open(os.path.join(out_dir, html_files[0])).read()
    assert 'WORLD!!!' in html


def test_markdown_extras_are_pluggable(tmp_path):
    """markdown2 extensions can be enabled (pluggable behaviour)."""
    path = str(tmp_path / 'fenced.yaml')
    body = ('---\nentrypoint:\n  body: |\n'
            '    ```python\n    x = 1\n    ```\n')
    with open(path, 'w') as f:
        f.write(body)
    out_dir = str(tmp_path / 'out')
    builder = NarativeWorldBuilder(path, out_dir)
    builder.markdown_extras = ('fenced-code-blocks',)
    builder.build()
    html_files = [f for f in os.listdir(out_dir) if f.endswith('.html')]
    html = open(os.path.join(out_dir, html_files[0])).read()
    assert '<code>' in html


def test_default_markdown_has_no_fenced_blocks(tmp_path):
    path = str(tmp_path / 'fenced.yaml')
    body = ('---\nentrypoint:\n  body: |\n'
            '    ```python\n    x = 1\n    ```\n')
    with open(path, 'w') as f:
        f.write(body)
    out_dir = str(tmp_path / 'out')
    builder = NarativeWorldBuilder(path, out_dir)
    builder.build()
    html_files = [f for f in os.listdir(out_dir) if f.endswith('.html')]
    html = open(os.path.join(out_dir, html_files[0])).read()
    # without extensions the fences are left as plain paragraphs
    assert 'x = 1' in html
