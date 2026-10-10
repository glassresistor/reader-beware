"""Tests for beware.cli."""

import os
import zipfile

from beware.cli import cli as cli_group

HERE = os.path.dirname(os.path.abspath(__file__))
NARRATIVES = os.path.join(HERE, 'narratives')


def narrative(name):
    return os.path.join(NARRATIVES, name)


def test_build_html_cli(tmp_path):
    from click.testing import CliRunner
    runner = CliRunner()
    out_dir = str(tmp_path / 'html')
    result = runner.invoke(
        cli_group,
        ['build-html', '--narative-path', narrative('simple.yaml'),
         '--output', out_dir])
    assert result.exit_code == 0, result.output
    assert '3 sections written' in result.output
    assert len(os.listdir(out_dir)) == 3


def test_build_epub_cli(tmp_path):
    from click.testing import CliRunner
    runner = CliRunner()
    out_base = str(tmp_path / 'epub')
    result = runner.invoke(
        cli_group,
        ['build-epub', '--narative-path', narrative('simple.yaml'),
         '--output', out_base])
    assert result.exit_code == 0, result.output
    assert os.path.exists(out_base + '.epub')


def test_build_epub_cli_with_book_config(tmp_path):
    from click.testing import CliRunner
    runner = CliRunner()
    cfg = str(tmp_path / 'cfg.yaml')
    with open(cfg, 'w') as f:
        f.write('title: CLI Book\nauthor: Someone\n'
                'description: From the cli.\n')
    out_base = str(tmp_path / 'epub2')
    result = runner.invoke(
        cli_group,
        ['build-epub', '--narative-path', narrative('simple.yaml'),
         '--output', out_base, '--book-config', cfg])
    assert result.exit_code == 0, result.output
    with zipfile.ZipFile(out_base + '.epub') as z:
        opf = z.read('EPUB/content.opf').decode()
    assert 'CLI Book' in opf
    assert 'Someone' in opf
    assert '<dc:description>From the cli.</dc:description>' in opf


def test_help_lists_commands():
    from click.testing import CliRunner
    runner = CliRunner()
    result = runner.invoke(cli_group, ['--help'])
    assert result.exit_code == 0
    assert 'build-html' in result.output
    assert 'build-epub' in result.output
