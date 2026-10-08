import click

from beware.build_html import NarativeWorldBuilder
from beware.build_epub import EPubWorldBuilder
from beware.meta import BookMetadata


@click.group()
def cli():
    pass


@cli.command()
@click.option(
    '--narative-path',
    default='narative.yaml',
    help='Path to natarive yaml file')
@click.option(
    '--output',
    default='output',
    help='Output folder')
def build_html(narative_path, output):
    NarativeWorldBuilder(narative_path, output).build()


@cli.command()
@click.option(
    '--narative-path',
    default='narative.yaml',
    help='Path to natarive yaml file')
@click.option(
    '--output',
    default='output',
    help='Output folder and file (the epub is written as <output>.epub)')
@click.option(
    '--book-config',
    default=None,
    help='Path to a yaml/json file with ebook metadata '
         '(title, description, cover, ...)')
def build_epub(narative_path, output, book_config):
    meta = BookMetadata.from_config(book_config)
    builder = EPubWorldBuilder(narative_path, output, meta=meta)
    builder.build()
    epub_file = builder.build_epub(meta)
    print('epub written to %s' % epub_file)


if __name__ == '__main__':
    cli()
