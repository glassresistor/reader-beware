# Reader Beware — Agent Skill

How to best use `beware` (the reader-beware CLI) when writing, building and
debugging gamebook stories.  Read this before touching a narrative file.

## What it is

Reader Beware compiles one yaml "narrative" file into every page of a branching
gamebook (choose-your-own-adventure).  Each section is markdown rendered
through jinja2, and links between sections are expressed as jinja filter calls
inside the markdown.  The build walks the link graph from `entrypoint` and
emits one output page per reachable `(section, world-state)` combination — so a
single section can produce many pages depending on state.

## Workflow (do these in order)

```bash
# 1. Validate structure before building (exit 0 = ok, 1 = errors, 2 = unreadable file)
beware check --narrative-path narative.yaml

# 2. Build html for fast visual debugging (pages land in <output>/entrypoint-*.html etc.)
beware build-html --narative-path narative.yaml --output output_folder

# 3. Build the real ebook (+ unzipped pages folder for inspection)
beware build-epub --narative-path narative.yaml --output book \
    --book-config book.yaml        # optional; see example-book.yaml

# 4. Optional: Kindle mobi (needs Calibre; falls back to .epub + instructions)
beware build-mobi --narative-path narative.yaml --output book \
    --book-config book.yaml
```

For live editing instead of the CLI, `beware serve --root <folder>` runs a
flask editor with per-section cards, link tools and a live preview.

## Writing narrative yaml — the rules that matter

- File starts with `---`; each section is `<name>:` followed by `body: |`
  containing markdown (jinja2-templated).
- Exactly one section must be named `entrypoint`.
- Links are written as markdown links whose URL is a jinja filter call:
  - `[text]({{ 'target'|explore }})` — go to `target`, world state unchanged.
  - `[text]({{ 'target'|choice(var=value, ...) }})` — go to `target` after
    setting/overriding world variables.  Values are python expressions:
    `choice(x=x+1)` reads and updates; `choice(karate=True)` sets a flag.
- World variables persist across every subsequent section and are readable in
  any body (`{{ x }}`, `{% if karate %}...{% endif %}`).  An unset variable
  renders as `None`.
- A section is only emitted if reachable from `entrypoint`; beware never
  emits the same `(section, state)` twice, so a story can loop forever in the
  reader while still terminating as a build — unless a variable grows without
  bound (then it fills your disk).

Minimal working example:

```yaml
---
entrypoint:
  body: |
    This is your opening page.

    [go left]({{ 'left'|explore }})

    [go right]({{ 'right'|explore }})

left:
  body: |
    This is going left

right:
  body: |
    This is going right
```

## Gotchas (the ones that waste the most time)

- **Option spelling differs between commands.** `build-html`, `build-epub` and
  `build-mobi` take `--narative-path` (sic, one 'r' missing); `check` takes
  `--narrative-path`.  Defaults are `narative.yaml` for the builders but
  `narrative.yaml` for `check`.
- **`--output` means different things.** For `build-html` it is a folder.
  For `build-epub`/`build-mobi` it is a base name: the ebook is written as
  `<output>.epub` / `<output>.mobi`, and an unzipped `<output>/` folder is
  also created for debugging.
- **Infinite state growth.** Any loop that increments/appends to a variable
  without a `{% if %}` guard will build forever.  Guard loops explicitly:

  ```yaml
  loop:
    body: |
      {% if value < 10 %}
      [loop]({{ 'loop'|choice(value=value+1) }})
      {% endif %}
  ```

- **Unreachable sections are a `check` error** (not just a warning).  If you
  intentionally keep alternate endings unreachable, fix the links.
- **Dead ends are reported but not errors** — sections with no outgoing links
  are fine if they are intentional endings; `check` lists them so you can
  verify.
- **`check` does not render jinja.**  It parses link targets textually, so a
  typo in a section name inside a `{% if %}` branch is still caught (good),
  but runtime template errors only show up at build time.
- **Book metadata** (`title`, `description`, `cover`, ...) goes in a separate
  file passed via `--book-config` (see `example-book.yaml`); it is not part of
  the narrative file.  `cover` paths are relative to the narrative file.

## Python API (when scripting instead of CLI)

```python
from beware.build_html import NarativeWorldBuilder
from beware.build_epub import EPubWorldBuilder
from beware.meta import BookMetadata

builder = NarativeWorldBuilder('narative.yaml', 'output')
builder.max_sections = 5000              # fail fast on runaway stories
builder.markdown_extras = ('fenced-code-blocks',)   # optional markdown2 extras
builder.register_filter('shout', lambda v: v.upper() + '!!!')  # custom jinja filter
builder.build()

meta = BookMetadata.from_config('book.yaml')
epub_builder = EPubWorldBuilder('narative.yaml', 'output', meta=meta)
epub_builder.build()
epub_file = epub_builder.build_epub(meta)
```

`register_filter(name, fn)` can also replace or remove the built-in
`explore`/`choice` filters.

## Quick reference

| Command        | Purpose                              | Key options                                   |
|----------------|--------------------------------------|-----------------------------------------------|
| `build-html`   | Debug pages in a browser             | `--narative-path`, `--output <folder>`        |
| `build-epub`   | EPUB 3 ebook + unzipped pages        | `--narative-path`, `--output <base>`, `--book-config` |
| `build-mobi`   | Kindle mobi (via Calibre)            | same as build-epub                            |
| `check`        | Validate links/reachability/dead ends| `--narrative-path`, `--dot-output FILE|-`, `--quiet` |
| `serve`        | Flask web editor                     | `--root <folder>`, `--port 8181`              |

Full option text: see the "Running commands" section of README.markdown or
run `beware <command> --help`.
