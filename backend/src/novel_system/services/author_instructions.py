from __future__ import annotations

from novel_system.services.errors import DomainError


MAX_AUTHOR_NOTE_CHARS = 2_000


def normalize_author_note(value: object | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DomainError(
            "AUTHOR_NOTE_INVALID",
            "author_note must be a string",
            status_code=422,
        )
    note = value.strip()
    if not note:
        return None
    if len(note) > MAX_AUTHOR_NOTE_CHARS:
        raise DomainError(
            "AUTHOR_NOTE_TOO_LONG",
            "author_note exceeds the supported length",
            status_code=422,
            details={"char_count": len(note), "max_char_count": MAX_AUTHOR_NOTE_CHARS},
        )
    return note


def render_author_note_instruction(value: object | None) -> str:
    note = normalize_author_note(value)
    if note is None:
        return ""
    # Escape only our delimiter; the body is intentionally an author command,
    # but it must not be able to forge adjacent prompt sections.
    escaped = note.replace("</author_instruction>", "&lt;/author_instruction&gt;")
    return (
        "\n\n## Author Instruction (highest-priority creative direction)\n"
        "<author_instruction>\n"
        f"{escaped}\n"
        "</author_instruction>\n"
        "Apply it without changing frozen facts, safety gates, or chapter contracts."
    )
