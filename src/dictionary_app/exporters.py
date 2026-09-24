#!/usr/bin/python3
# -*- coding: utf-8 -*-

# =============================================================================
#
#        FILE:  exporters.py
#     CREATED:  2026-09-20
# DESCRIPTION:  Turn parsed dictionary entries into plain text, Markdown, or
#               JSON, and write them to a file chosen by its extension.
#
# =============================================================================

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path

from dictionary_app import functions as func

FORMATS = ("text", "md", "json")
_SUFFIX_TO_FORMAT = {".txt": "text", ".md": "md", ".json": "json"}


def render_text(entries: Sequence[func.Entry]) -> str:
    """Plain text: the upper-cased word, then its (numbered) definitions."""
    blocks = [
        f"{entry.word.upper()}\n{func.format_definitions(list(entry.definitions))}"
        for entry in entries
    ]
    return "\n\n".join(blocks) + "\n"


def render_markdown(entries: Sequence[func.Entry]) -> str:
    """Markdown: one heading per word, a numbered list, and the audio link."""
    blocks = []
    for entry in entries:
        lines = [f"# {entry.word}", ""]
        if entry.definitions:
            lines.extend(
                f"{number}. {text}"
                for number, text in enumerate(entry.definitions, start=1)
            )
        else:
            lines.append("_No definition found._")
        if entry.audio_url:
            lines.extend(["", f"[Pronunciation audio]({entry.audio_url})"])
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def render_json(entries: Sequence[func.Entry]) -> str:
    """JSON: always an array of ``{word, definitions, audio_url}`` objects."""
    payload = [
        {
            "word": entry.word,
            "definitions": list(entry.definitions),
            "audio_url": entry.audio_url,
        }
        for entry in entries
    ]
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


_RENDERERS: dict[str, Callable[[Sequence[func.Entry]], str]] = {
    "text": render_text,
    "md": render_markdown,
    "json": render_json,
}


def render(entries: Sequence[func.Entry], fmt: str) -> str:
    """Render ``entries`` in one of ``FORMATS``."""
    try:
        renderer = _RENDERERS[fmt]
    except KeyError:
        raise ValueError(
            f"unsupported format {fmt!r}; choose from {', '.join(FORMATS)}"
        ) from None
    return renderer(entries)


def format_for_path(path: Path) -> str:
    """Pick the output format from a file extension.

    Raises:
        ValueError: If the extension is not ``.txt``, ``.md`` or ``.json``.
    """
    try:
        return _SUFFIX_TO_FORMAT[path.suffix.lower()]
    except KeyError:
        supported = ", ".join(_SUFFIX_TO_FORMAT)
        raise ValueError(
            f"cannot export to {path.name!r}: the extension must be one of {supported}"
        ) from None


def write_export(path: Path, entries: Sequence[func.Entry]) -> None:
    """Write ``entries`` to ``path`` in the format its extension implies."""
    content = render(entries, format_for_path(path))
    path.write_text(content, encoding="utf-8")
