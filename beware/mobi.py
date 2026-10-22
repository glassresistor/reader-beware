"""Generate MOBI/AZW ebooks for Kindle devices.

There is no pure-Python MOBI *writer* (the `mobi`/iscc libraries only unpack
existing files), so this module shells out to Calibre's ``ebook-convert``
binary when it is available on the PATH -- exactly what the README describes
doing by hand in the Calibre GUI.  When Calibre is not installed, building a
MOBI falls back to producing a Kindle-ready `.epub` file and returning a note
explaining how to finish the conversion (or send-to-Kindle email).

The fallback keeps `beware build-mobi` useful on machines without Calibre:
the story still gets built and packaged, just in EPUB form.
"""

import os
import shutil
import subprocess


def calibre_available():
    """True if the Calibre ``ebook-convert`` executable is on the PATH."""
    return (
        shutil.which("ebook-convert") is not None or shutil.which("calibre") is not None
    )


def _conversion_command(src, dst):
    ebook_convert = shutil.which("ebook-convert")
    if ebook_convert:
        exe = ebook_convert
    else:  # pragma: no cover - exercised only when calibre installed oddly
        exe = "ebook-convert"
    return [exe, src, dst]


class MobiWorldBuilder(object):

    #: builder used to produce the source file that gets converted ('epub')
    source_format = "epub"

    def __init__(self, yaml_path, output_path, meta=None, epub_builder=None):
        """Create a MOBI builder.

        ``epub_builder`` may be supplied (a built `EPubWorldBuilder`) to
        avoid duplicating the build step; otherwise one is created lazily.
        """
        self.yaml_path = yaml_path
        self.output_path = output_path
        if meta is None:
            from beware.meta import BookMetadata

            meta = BookMetadata.from_config(None)
        self.meta = meta
        self._epub_builder = epub_builder

    @property
    def epub_file(self):
        return "%s.epub" % self.output_path

    @property
    def mobi_file(self):
        return "%s.mobi" % self.output_path

    @property
    def azw_file(self):
        return "%s.azw" % self.output_path

    def ensure_epub(self):
        """Build the epub source file if it has not been built yet."""
        if self._epub_builder is None:
            from beware.build_epub import EPubWorldBuilder

            self._epub_builder = EPubWorldBuilder(
                self.yaml_path, "%s_src" % self.output_path, meta=self.meta
            )
            self._epub_builder.build()
        src = self._epub_builder.build_epub(self.meta)
        if os.path.abspath(src) != os.path.abspath(self.epub_file):
            shutil.copyfile(src, self.epub_file)
        return self.epub_file

    def build(self):
        """Build the book and convert it to MOBI (or fall back).

        Returns ``(artifact_path, note)`` where ``note`` is empty when a real
        MOBI was produced by Calibre.
        """
        src = self.ensure_epub()
        if not calibre_available():
            return None, _missing_calibre_note(self.epub_file)
        result = subprocess.run(  # noqa: S603 - trusted local exe
            _conversion_command(src, self.mobi_file), capture_output=True, text=True
        )
        if result.returncode != 0 and not os.path.exists(self.mobi_file):
            raise IOError("ebook-convert failed: %s" % (result.stderr or ""))
        return self.mobi_file, ""

    def build_azw(self):
        """Convert to AZW (Kindle format) instead of MOBI."""
        src = self.ensure_epub()
        if not calibre_available():
            return None, _missing_calibre_note(self.epub_file)
        result = subprocess.run(  # noqa: S603 - trusted local exe
            _conversion_command(src, self.azw_file), capture_output=True, text=True
        )
        if result.returncode != 0 and not os.path.exists(self.azw_file):
            raise IOError("ebook-convert failed: %s" % (result.stderr or ""))
        return self.azw_file, ""


def _missing_calibre_note(epub_path):
    return (
        "Calibre/ebook-convert is not installed so no MOBI was produced; "
        "%s was built instead and can be sent to a Kindle via the "
        '"Send to Kindle" email or converted locally with ebook-convert.' % epub_path
    )
