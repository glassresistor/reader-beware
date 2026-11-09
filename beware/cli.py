import os

import click

from beware.build_html import NarativeWorldBuilder
from beware.build_epub import EPubWorldBuilder
from beware.mobi import MobiWorldBuilder
from beware.meta import BookMetadata


@click.group()
def cli():
    pass


@cli.command()
@click.option(
    "--narative-path", default="narative.yaml", help="Path to natarive yaml file"
)
@click.option("--output", default="output", help="Output folder")
def build_html(narative_path, output):
    NarativeWorldBuilder(narative_path, output).build()


@cli.command()
@click.option(
    "--narative-path", default="narative.yaml", help="Path to natarive yaml file"
)
@click.option(
    "--output",
    default="output",
    help="Output folder and file (the epub is written as <output>.epub)",
)
@click.option(
    "--book-config",
    default=None,
    help="Path to a yaml/json file with ebook metadata "
    "(title, description, cover, ...)",
)
def build_epub(narative_path, output, book_config):
    meta = BookMetadata.from_config(book_config)
    builder = EPubWorldBuilder(narative_path, output, meta=meta)
    builder.build()
    epub_file = builder.build_epub(meta)
    print("epub written to %s" % epub_file)


@cli.command()
@click.option(
    "--narative-path", default="narative.yaml", help="Path to natarive yaml file"
)
@click.option(
    "--output",
    default="output",
    help="Output base name (mobi written as <output>.mobi)",
)
@click.option(
    "--book-config",
    default=None,
    help="Path to a yaml/json file with ebook metadata "
    "(title, description, cover, ...)",
)
def build_mobi(narative_path, output, book_config):
    meta = BookMetadata.from_config(book_config)
    epub_builder = EPubWorldBuilder(narative_path, "%s_epub" % output, meta=meta)
    epub_builder.build()
    epub_builder.build_epub(meta)
    mobi_builder = MobiWorldBuilder(
        narative_path, output, meta=meta, epub_builder=epub_builder
    )
    artifact, note = mobi_builder.build()
    if artifact:
        print("mobi written to %s" % artifact)
    else:
        print(note)


@cli.command()
@click.option(
    "--narrative-path", default="narrative.yaml", help="Path to narrative yaml file"
)
@click.option(
    "--dot-output",
    default=None,
    metavar="FILE",
    help=(
        "Write Graphviz DOT graph to FILE. Use '-' for stdout. "
        "If omitted, no graph is written."
    ),
)
@click.option("--quiet", is_flag=True, help="Suppress the report; only exit code")
def check(narrative_path, dot_output, quiet):
    """Validate narrative structure: broken links, unreachable sections, dead ends."""
    import sys

    from beware.check import check_narrative, to_dot

    try:
        text = open(narrative_path).read()
    except OSError as exc:
        click.echo("error: %s" % exc, err=True)
        sys.exit(2)

    result = check_narrative(text)

    if not quiet:
        click.echo(result.report())

    if dot_output is not None:
        dot = to_dot(result)
        if dot_output == "-":
            click.echo(dot)
        else:
            with open(dot_output, "w") as f:
                f.write(dot)
            if not quiet:
                click.echo("\ndot graph written to %s" % dot_output)

    sys.exit(1 if result.has_errors else 0)


@cli.command()
@click.option("--root", default=".", help="Folder containing story yaml files")
@click.option("--port", default=8181, help="Port for the webapp to listen on")
def serve(root, port):
    """Run a tiny flask editor for narratives under --root."""
    from beware.web import create_app

    app = create_app(root)
    click.echo(
        "serving story editor at http://127.0.0.1:%s (root=%s)"
        % (port, os.path.realpath(root))
    )
    app.run(port=port)


if __name__ == "__main__":
    cli()
