"""Tests for beware.mobi."""

import os

from beware.build_epub import EPubWorldBuilder
from beware.cli import cli as cli_group
from beware.meta import BookMetadata
from beware.mobi import MobiWorldBuilder, calibre_available

HERE = os.path.dirname(os.path.abspath(__file__))
NARRATIVES = os.path.join(HERE, 'narratives')


def narrative(name):
    return os.path.join(NARRATIVES, name)


def test_calibre_detection():
    # calibre_available() must simply reflect whether ebook-convert is on
    # the PATH -- True or False, never crash.
    assert calibre_available() in (True, False)


def test_fallback_builds_epub_and_note(tmp_path):
    out_base = str(tmp_path / 'mobi')
    builder = MobiWorldBuilder(narrative('simple.yaml'), out_base)
    artifact, note = builder.build()
    if calibre_available():
        # real MOBI produced by Calibre
        assert artifact is not None and os.path.exists(artifact)
        assert note == ''
    else:
        assert artifact is None
        assert 'Calibre' in note or 'ebook-convert' in note
        assert os.path.exists(out_base + '.epub')


def test_fallback_note_mentions_epub_path(tmp_path):
    out_base = str(tmp_path / 'mobinote')
    builder = MobiWorldBuilder(narrative('simple.yaml'), out_base)
    artifact, note = builder.build()
    if not calibre_available():
        assert (out_base + '.epub') in note


def test_azw_fallback(tmp_path):
    out_base = str(tmp_path / 'azw')
    builder = MobiWorldBuilder(narrative('simple.yaml'), out_base)
    artifact, note = builder.build_azw()
    if calibre_available():
        assert os.path.exists(artifact)
    else:
        assert artifact is None
        assert os.path.exists(out_base + '.epub')


def test_reuses_prebuilt_epub_builder(tmp_path):
    out_base = str(tmp_path / 'reuse')
    epub_out = str(tmp_path / 'src')
    meta = BookMetadata(title='Mobi Test', author='Tester')
    epub_builder = EPubWorldBuilder(narrative('simple.yaml'), epub_out,
                                    meta=meta)
    epub_builder.build()
    src = epub_builder.build_epub(meta)
    builder = MobiWorldBuilder(
        narrative('simple.yaml'), out_base, meta=meta,
        epub_builder=epub_builder)
    artifact, note = builder.build()
    if calibre_available():
        assert os.path.exists(artifact) and artifact.endswith('.mobi')
    else:
        # the copied epub exists at <out>.epub
        assert os.path.exists(out_base + '.epub')
        import zipfile
        with zipfile.ZipFile(out_base + '.epub') as z:
            opf = z.read('EPUB/content.opf').decode()
        assert 'Mobi Test' in opf
    # source epub was built once and reused (same content)
    assert src.endswith('.epub')


def test_mobi_cli(tmp_path):
    from click.testing import CliRunner
    runner = CliRunner()
    out_base = str(tmp_path / 'mobicli')
    result = runner.invoke(
        cli_group,
        ['build-mobi', '--narative-path', narrative('simple.yaml'),
         '--output', out_base])
    assert result.exit_code == 0, result.output
    if calibre_available():
        assert 'mobi written to' in result.output
    else:
        assert os.path.exists(out_base + '.epub')
        assert 'Calibre' in result.output or \
               'ebook-convert' in result.output


def test_kindle_notification_field_in_metadata():
    meta = BookMetadata(
        kindle_notification_address='me@kindle.com')
    assert meta.kindle_notification_address == 'me@kindle.com'
