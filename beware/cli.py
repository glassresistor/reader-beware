import click

from build_html import NarativeWorldBuilder
from build_epub import EPubWorldBuilder


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
    help='Output folder and file')
def build_epub(narative_path, output):
    EPubWorldBuilder(narative_path, output).build()


if __name__ == '__main__':
    cli()
