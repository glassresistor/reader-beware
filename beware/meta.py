"""Metadata for a reader-beware book (title, description, cover, ...).

The metadata can be passed to the CLI with ``--book-config`` pointing at a
YAML/JSON file.  This keeps ebook specific settings (title, description,
publisher, cover image, ...) separate from the narrative itself.

A minimal config looks like::

    title: The Blood Meriction
    author: Margaret Killjoy
    language: en-US
    description: |
      A novel about ...
    publisher: Free Editions
    date: 2018-08-03
    rights: Some rights reserved.
    identifier: urn:uuid:...
    cover: Images/ebook-cover_fmt.jpeg
"""

import json
import mimetypes
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

try:
    import yaml as _yaml
except ImportError:  # pragma: no cover - yaml is a hard dependency anyway
    _yaml = None


DEFAULT_RIGHTS = (
    "This work is licensed under the Creative Commons Attribution-"
    "NonCommercial-ShareAlike 3.0 Unported License. To view a copy of "
    "this license, visit http://creativecommons.org/licenses/by-nc-sa/"
    "3.0/ or send a letter to Creative Commons, 171 Second Street, "
    "Suite 300, San Francisco, California, 94105, USA."
)

#: Deterrent copy for interstitial "dead" pages, in the idiom of the
#: long-term nuclear waste warning messages (WIPP / the Clapp report):
#: "not a place of honor", "nothing here is worth your desire", "go home
#: and tell them what you have seen", "do not proceed", "do not dig".
#: Each line also does plain wayfinding so a reader who has drifted off
#: the linked path can orient themselves instead of getting lost.
DEFAULT_DEAD_PAGE_MESSAGES = (
    "You are between passages. Nothing here is worth your desire. Do not "
    "proceed \u2014 turn back to the last page you remember, or follow the "
    "links onward.",
    "This is not a place of honor. The road you walked does not continue "
    "here. Go home to where your story began and tell it what you have seen.",
    "You are approaching a site of deep significance. Do not dig. Do not "
    "linger. Turn the page and return to the path, or you will be lost for "
    "good.",
)


@dataclass
class DeadPageConfig:
    """How many interstitial dead pages to drop between sections, and with
    what copy.  ``messages`` empty means use :data:`DEFAULT_DEAD_PAGE_MESSAGES`
    (they cycle if ``count`` exceeds the number supplied)."""

    count: int = 3
    messages: tuple = ()
    include_after_last: bool = False


def _parse_dead_pages(value):
    """Normalize a raw config value into a :class:`DeadPageConfig` or None.

    Accepts ``True`` (defaults), a mapping (``count`` / ``messages`` /
    ``include_after_last``), or ``None``/``False`` (disabled).
    """
    if value is None or value is False:
        return None
    if value is True:
        return DeadPageConfig()
    if isinstance(value, dict):
        msgs = value.get("messages", [])
        if isinstance(msgs, str):
            msgs = [msgs]
        try:
            count = int(value.get("count", 3))
        except (TypeError, ValueError):
            count = 3
        return DeadPageConfig(
            count=count,
            messages=tuple(str(m) for m in msgs),
            include_after_last=bool(value.get("include_after_last", False)),
        )
    return None


@dataclass
class BookMetadata:
    title: str = "Reader Beware Story"
    author: str = ""
    language: str = "en-US"
    subject: str = "CYOA"
    description: str = ""
    publisher: str = ""
    date: str = ""
    rights: str = DEFAULT_RIGHTS
    identifier: str = "reader-beware-book-id"
    cover: Optional[str] = None
    kindle_notification_address: str = ""
    generator: str = "Reader Beware"
    css_files: tuple = ("template.css",)
    dead_pages: Optional[DeadPageConfig] = None
    extras: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # allow a raw dict/bool to be passed straight to the constructor
        if isinstance(self.dead_pages, (dict, bool)):
            self.dead_pages = _parse_dead_pages(self.dead_pages)

    # -- loading ---------------------------------------------------------
    @classmethod
    def from_config(cls, config_path=None):
        """Load metadata from a YAML/JSON file (or return defaults)."""
        if not config_path:
            return cls()
        with open(config_path, "r") as f:
            text = f.read()
        data = None
        if _yaml is not None:
            try:
                data = _yaml.safe_load(text)
            except Exception:
                data = None
        if data is None:
            try:
                data = json.loads(text)
            except ValueError:
                raise ValueError(
                    "%s is neither valid YAML nor valid JSON" % config_path
                )
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError("book config must be a mapping")
        known = {}
        extras = {}
        for key, value in data.items():
            if key in cls.field_names():
                known[key] = value
            else:
                extras[key] = value
        if "css_files" in known and isinstance(known["css_files"], str):
            known["css_files"] = (known["css_files"],)
        if "date" in known:
            # yaml parses bare dates into datetime.date objects
            known["date"] = str(known["date"])
        if "dead_pages" in known:
            known["dead_pages"] = _parse_dead_pages(known["dead_pages"])
        kwargs = {}
        for name in cls.field_names():
            if name in known:
                kwargs[name] = known[name]
        meta = cls(**kwargs)
        meta.extras.update(extras)
        return meta

    @classmethod
    def field_names(cls):
        names = list(cls.__dataclass_fields__)
        # exclude fields that are not simple metadata (kept in extras dict)
        return [n for n in names if n != "extras"]

    # -- helpers ---------------------------------------------------------
    def as_dict(self, include_extras=True):
        data = asdict(self)
        if not include_extras:
            data.pop("extras", None)
        else:
            data.update(self.extras)
        return data

    @property
    def cover_mime(self):
        if not self.cover:
            return ""
        mime, _ = mimetypes.guess_type(self.cover)
        return mime or "application/octet-stream"

    @property
    def has_cover(self):
        return bool(self.cover)

    def dead_page_texts(self):
        """Ordered list of dead-page body strings, or ``[]`` when disabled.

        The pool (custom messages, else the nuclear-waste defaults) is cycled
        so a ``count`` larger than the number of supplied messages still fills
        every page.
        """
        if self.dead_pages is None:
            return []
        count = max(0, int(self.dead_pages.count))
        if count == 0:
            return []
        pool = list(self.dead_pages.messages) or list(DEFAULT_DEAD_PAGE_MESSAGES)
        return [pool[i % len(pool)] for i in range(count)]
