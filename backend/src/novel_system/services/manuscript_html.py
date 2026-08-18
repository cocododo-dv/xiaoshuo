from __future__ import annotations

from html import escape
from html.parser import HTMLParser


ALLOWED_MANUSCRIPT_TAGS = frozenset(
    {
        "p",
        "br",
        "div",
        "span",
        "strong",
        "b",
        "em",
        "i",
        "u",
        "s",
        "strike",
        "blockquote",
        "ul",
        "ol",
        "li",
        "pre",
        "code",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "mark",
        "sub",
        "sup",
    }
)

_VOID_TAGS = frozenset({"br"})
_DROP_WITH_CONTENT = frozenset(
    {
        "script",
        "style",
        "iframe",
        "object",
        "embed",
        "svg",
        "math",
        "template",
        "noscript",
    }
)
_DROP_EMPTY = frozenset({"img", "audio", "video", "source", "track", "link", "meta", "base", "input"})


class _ManuscriptSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.output: list[str] = []
        self.suppressed: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if self.suppressed:
            if normalized in _DROP_WITH_CONTENT:
                self.suppressed.append(normalized)
            return
        if normalized in _DROP_WITH_CONTENT:
            self.suppressed.append(normalized)
            return
        if normalized in _DROP_EMPTY:
            return
        if normalized in ALLOWED_MANUSCRIPT_TAGS:
            # The manuscript format does not need user-controlled attributes.
            # Removing all of them drops on* handlers, style URLs, ids and data-*.
            self.output.append(f"<{normalized}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.suppressed:
            return
        normalized = tag.lower()
        if normalized in ALLOWED_MANUSCRIPT_TAGS:
            self.output.append(f"<{normalized}>")

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if self.suppressed:
            if normalized == self.suppressed[-1]:
                self.suppressed.pop()
            return
        if normalized in ALLOWED_MANUSCRIPT_TAGS and normalized not in _VOID_TAGS:
            self.output.append(f"</{normalized}>")

    def handle_data(self, data: str) -> None:
        if not self.suppressed:
            self.output.append(escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:
        if not self.suppressed:
            self.output.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self.suppressed:
            self.output.append(f"&#{name};")


def sanitize_manuscript_html(content: str | None) -> str:
    """Remove executable/remote-content markup from manuscript rich text."""

    if not content:
        return ""
    text = str(content)
    if "<" not in text:
        return text
    parser = _ManuscriptSanitizer()
    parser.feed(text)
    parser.close()
    return "".join(parser.output)
