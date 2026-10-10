"""Tests for beware.build_epub."""

import os
import re
import zipfile

import pytest

from beware.build_epub import EPubWorldBuilder
from beware.meta import BookMetadata

HERE = os.path.dirname(os.path.abspath(__file__))
NARRATIVES = os.path.join(HERE, 'narratives')


def narrative(name):
    return os.path.join(NARRATIVES, name)


def test_builds_epub(out):
    builder = EPubWorldBuilder(narrative('simple.yaml'), out)
    builder.build()
    epub_file = builder.build_epub()
    assert os.path.exists(epub_file)
    with zipfile.ZipFile(epub_file) as z:
        names = z.namelist()
    # mimetype + container + opf + css + 3 pages
    assert len(names) == 7
    check_structure(epub_file)


def check_structure(epub_file):
    with zipfile.ZipFile(epub_file) as z:
        infos = z.infolist()
        assert infos[0].filename == 'mimetype'
        assert infos[0].compress_type == zipfile.ZIP_STORED
        opf = z.read('EPUB/content.opf').decode()
        assert '<dc:title>' in opf
        assert 'version="3.0"' in opf or '4.0' in opf


def test_links_work_inside_epub(out):
    import posixpath
    builder = EPubWorldBuilder(narrative('shirts.yaml'), out)
    builder.build()
    epub_file = builder.build_epub()
    with zipfile.ZipFile(epub_file) as z:
        names = set(z.namelist())
        total_links = 0
        for name in sorted(names):
            if not name.endswith('.xhtml'):
                continue
            content = z.read(name).decode('utf-8')
            hrefs = re.findall(r'<a[^>]*href="([^"]+)"', content)
            assert all(h.startswith('../xhtml/') for h in hrefs), (
                'bad links %s in %s' % (hrefs, name))
            base = posixpath.dirname(name)   # e.g. EPUB/xhtml
            for href in hrefs:
                target = posixpath.normpath(posixpath.join(base, href))
                assert target in names, 'broken epub link %s -> %s' % (
                    name, href)
                total_links += 1
        # entrypoint links to two shirts; each shirt page links outside
        assert total_links == 4


def test_metadata_is_written(out):
    meta = BookMetadata(title='The Adventures of Sam',
                        author='Margaret Killjoy',
                        description='A test story.',
                        publisher='Test Publisher',
                        rights='Some rights.')
    builder = EPubWorldBuilder(narrative('simple.yaml'), out)
    builder.build()
    epub_file = builder.build_epub(meta)
    with zipfile.ZipFile(epub_file) as z:
        opf = z.read('EPUB/content.opf').decode()
    assert 'The Adventures of Sam' in opf
    assert 'Margaret Killjoy' in opf
    assert '<dc:description>A test story.</dc:description>' in opf
    assert '<dc:publisher>Test Publisher</dc:publisher>' in opf
    assert 'Some rights.' in opf


def test_cover_image_included(out):
    meta = BookMetadata(cover='Images/cover.png')
    cover_dir = os.path.join(NARRATIVES, 'Images')
    os.makedirs(cover_dir, exist_ok=True)
    write_tiny_png(os.path.join(NARRATIVES, str(meta.cover)))
    builder = EPubWorldBuilder(narrative('simple.yaml'), out)
    builder.build()
    epub_file = builder.build_epub(meta)
    with zipfile.ZipFile(epub_file) as z:
        names = z.namelist()
        image_names = [n for n in names if 'images/' in n]
        assert len(image_names) == 1
        opf = z.read('EPUB/content.opf').decode()
    assert 'cover' in opf.lower() or 'image' in opf.lower()
    assert image_names[0].endswith('.png')


def test_missing_cover_raises(out):
    meta = BookMetadata(cover='Images/missing.png')
    builder = EPubWorldBuilder(narrative('simple.yaml'), out)
    builder.build()
    with pytest.raises(IOError):
        builder.build_epub(meta)


def test_world_state_in_epub_pages(out):
    builder = EPubWorldBuilder(narrative('shirts.yaml'), out)
    builder.build()
    epub_file = builder.build_epub()
    with zipfile.ZipFile(epub_file) as z:
        pages = [n for n in z.namelist() if 'go-outside' in n]
        assert len(pages) == 2
        bodies = [z.read(p).decode('utf-8') for p in sorted(pages)]
    assert any('I like your green shirt very much.' in b for b in bodies)
    assert any('I dislike that color on you.' in b for b in bodies)


def test_epub_pages_are_well_formed_xhtml(out):
    from lxml import etree
    builder = EPubWorldBuilder(narrative('simple.yaml'), out)
    builder.build()
    epub_file = builder.build_epub()
    with zipfile.ZipFile(epub_file) as z:
        for name in z.namelist():
            if not name.endswith('.xhtml'):
                continue
            data = z.read(name)
            root = etree.fromstring(data)
            assert root is not None


def test_css_is_included(out):
    builder = EPubWorldBuilder(narrative('simple.yaml'), out)
    builder.build()
    epub_file = builder.build_epub()
    with zipfile.ZipFile(epub_file) as z:
        css_names = [n for n in z.namelist() if n.endswith('.css')]
        assert len(css_names) == 1
        css = z.read('EPUB/style/default.css').decode()
    assert 'font-weight' in css or 'text-decoration' in css


def write_tiny_png(path):
    """Write a minimal valid 1x1 transparent png file."""
    import struct
    import zlib

    def chunk(name, data):
        return (struct.pack('>I', len(data)) + name + data +
                struct.pack('>I', zlib.crc32(name + data) & 0xffffffff))

    sig = b'\x89PNG\r\n\x1a\n'
    ihdr_data = struct.pack('>II', 1, 1) + bytes([8, 6, 0, 0, 0])
    raw = bytearray()
    raw.append(0)
    raw.extend(bytes(4))
    png = (sig + chunk(b'IHDR', ihdr_data) +
           chunk(b'IDAT', zlib.compress(bytes(raw))) + chunk(b'IEND', b''))
    with open(path, 'wb') as f:
        f.write(png)
