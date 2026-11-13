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
@click.option(
    "--narrative-path", default="narrative.yaml", help="Path to narrative yaml file"
)
@click.option(
    "--output",
    "output_base",
    default=None,
    metavar="BASE",
    help="Write both <BASE>.dot and <BASE>.svg (unless overridden below).",
)
@click.option(
    "--dot-output",
    default=None,
    metavar="FILE",
    help="Write the Graphviz DOT graph to FILE. Use '-' for stdout.",
)
@click.option(
    "--svg-output",
    default=None,
    metavar="FILE",
    help=(
        "Write a self-contained scalable SVG of the story tree to FILE. "
        "Use '-' for stdout. No Graphviz binary is required."
    ),
)
@click.option(
    "--orientation",
    type=click.Choice(["TB", "LR"]),
    default="TB",
    show_default=True,
    help="Layout direction: TB (top-to-bottom) or LR (left-to-right).",
)
@click.option(
    "--labels",
    type=click.Choice(["name", "preview", "off"]),
    default="name",
    show_default=True,
    help=(
        "What to write in each box: 'name' (section name), 'preview' "
        "(name plus a one-line body preview) or 'off' (boxes only)."
    ),
)
@click.option("--title", default=None, help="Optional heading above the SVG.")
@click.option(
    "--font-size",
    default=13.0,
    show_default=True,
    help="Base font size for the SVG (user units).",
)
def graph(narrative_path, output_base, dot_output, svg_output, orientation,
          labels, title, font_size):
    """Render the story tree as a Graphviz DOT file and/or a scalable SVG."""
    import sys

    from beware.check import check_narrative
    from beware.graph import to_dot, to_svg

    try:
        text = open(narrative_path).read()
    except OSError as exc:
        click.echo("error: %s" % exc, err=True)
        sys.exit(2)

    # Work out which formats to write and where.  --output fills in anything
    # not already set by the explicit per-format flags.
    targets = []
    if dot_output is not None:
        targets.append(("dot", dot_output))
    if svg_output is not None:
        targets.append(("svg", svg_output))
    if output_base is not None:
        if dot_output is None:
            targets.append(("dot", output_base + ".dot"))
        if svg_output is None:
            targets.append(("svg", output_base + ".svg"))
    if not targets:
        click.echo(
            "error: nothing to write; pass --output BASE, --dot-output FILE "
            "or --svg-output FILE (use '-' for stdout)",
            err=True,
        )
        sys.exit(2)

    # Compute the structure once and reuse it for both renderings.
    result = check_narrative(text)
    dot_text = to_dot(result)
    svg_text = None

    def emit(fmt, path):
        nonlocal svg_text
        if fmt == "dot":
            content = dot_text
        else:
            if svg_text is None:
                svg_text = to_svg(
                    text,
                    orientation=orientation,
                    labels=labels,
                    title=title,
                    font_size=font_size,
                    result=result,
                )
            content = svg_text
        if path == "-":
            click.echo(content)
        else:
            with open(path, "w") as f:
                f.write(content)
            click.echo("%s written to %s" % (fmt, path))

    for fmt, path in targets:
        emit(fmt, path)


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
