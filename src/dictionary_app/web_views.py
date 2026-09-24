#!/usr/bin/python3
# -*- coding: utf-8 -*-

# =============================================================================
#
#        FILE:  web_views.py
#     CREATED:  2026-09-21
# DESCRIPTION:  The pages of the web interface, as pure functions from data to
#               HTML text. Definitions come from a scraped website, so they are
#               untrusted: every dynamic value goes through ``esc`` here, and
#               nothing in the pages needs JavaScript.
#
# =============================================================================

from __future__ import annotations

import html
from collections.abc import Sequence
from urllib.parse import quote

from dictionary_app import exporters
from dictionary_app import functions as func
from dictionary_app.word_history import HistoryRecord

MEDIA_HOST = "media.merriam-webster.com"  # the only host audio may come from
STYLESHEET = "/static/style.css"
FAVICON = "/static/favicon.svg"

_FORMAT_LABELS = {"text": ".txt", "md": ".md", "json": ".json"}
_NAV = (("/", "Search"), ("/batch", "Batch"), ("/history", "History"))


def esc(value: str) -> str:
    """Escape text for HTML content and attribute values."""
    return html.escape(value, quote=True)


def word_url(word: str) -> str:
    """The address of a word's page; the word is percent-encoded."""
    return f"/?word={quote(word, safe='')}"


def export_url(word: str, fmt: str) -> str:
    return f"/export?word={quote(word, safe='')}&format={quote(fmt, safe='')}"


def audio_src(entry: func.Entry) -> str | None:
    """The pronunciation URL, but only if it points at the expected media host.

    The URL is scraped, so anything else (another host, another scheme) is
    dropped rather than handed to the browser.
    """
    url = entry.audio_url
    if url is not None and url.startswith(f"https://{MEDIA_HOST}/"):
        return url
    return None


_ICONS = {
    "Search": '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" /></svg>',
    "Batch": '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M3.75 12h16.5m-16.5 3.75h16.5M3.75 19.5h16.5M5.625 4.5h12.75a1.875 1.875 0 010 3.75H5.625a1.875 1.875 0 010-3.75z" /></svg>',
    "History": '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>'
}

def layout(title: str, body: str, *, active: str = "") -> str:
    """Wrap ``body`` (already-safe HTML) in the shared page frame."""
    links = "".join(
        f'<a href="{href}"' + (' aria-current="page"' if href == active else "") + ">"
        f"{_ICONS.get(label, '')}{label}</a>"
        for href, label in _NAV
    )
    brand_svg = '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" /></svg>'
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<link rel="stylesheet" href="{STYLESHEET}">
<link rel="icon" href="{FAVICON}" type="image/svg+xml">
</head>
<body>
<header class="site-header">
<a class="brand" href="/">{brand_svg}Dictionary</a>
<nav aria-label="Main">{links}</nav>
</header>
<main>
{body}
</main>
<footer>Definitions from Merriam-Webster, for personal use.</footer>
</body>
</html>
"""


def search_form(value: str = "") -> str:
    search_svg = '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" /></svg>'
    return f"""<form class="search" action="/" method="get" role="search">
<label class="visually-hidden" for="word">Word to look up</label>
<input id="word" name="word" type="search" value="{esc(value)}"
 placeholder="Look up a word" maxlength="{func.MAX_WORD_LENGTH}"
 autocomplete="off" autocapitalize="none" spellcheck="false" required autofocus>
<button type="submit">{search_svg}Look up</button>
</form>"""


def _definitions(entry: func.Entry) -> str:
    if not entry.definitions:
        return '<p class="muted">No definition found.</p>'
    items = "".join(f"<li>{esc(text)}</li>" for text in entry.definitions)
    return f'<ol class="definitions">{items}</ol>'


def _audio(entry: func.Entry) -> str:
    src = audio_src(entry)
    if src is None:
        return ""
    return (
        f'<figure class="pronunciation"><figcaption>Pronunciation</figcaption>'
        f'<audio controls preload="none" src="{esc(src)}"></audio></figure>'
    )


def _article(entry: func.Entry, *, level: int = 1) -> str:
    return (
        f'<article class="entry"><h{level}>{esc(entry.word)}</h{level}>'
        f"{_audio(entry)}{_definitions(entry)}</article>"
    )


def render_home(recent: Sequence[str], *, history_enabled: bool) -> str:
    """The landing page: a search box and the most recent successful words."""
    if recent:
        chips = "".join(
            f'<li><a href="{esc(word_url(word))}">{esc(word)}</a></li>'
            for word in recent
        )
        extra = f'<section><h2>Recent</h2><ul class="chips">{chips}</ul></section>'
    elif history_enabled:
        extra = '<p class="muted">Words you look up will be listed here.</p>'
    else:
        extra = '<p class="muted">History is turned off for this session.</p>'
    body = f"""<h1 class="visually-hidden">Dictionary</h1>
{search_form()}
{extra}
<p class="muted">Have a list of words? Use <a href="/batch">Batch</a>.</p>"""
    return layout("Dictionary", body, active="/")


def render_entry(entry: func.Entry) -> str:
    """A looked-up word, with download links for every export format."""
    downloads = "".join(
        f'<li><a href="{esc(export_url(entry.word, fmt))}">{label}</a></li>'
        for fmt, label in _FORMAT_LABELS.items()
        if fmt in exporters.FORMATS
    )
    body = f"""{search_form(entry.word)}
{_article(entry)}
<section class="downloads">
<h2>Download</h2>
<ul class="chips">{downloads}</ul>
</section>"""
    return layout(f"{entry.word} - Dictionary", body, active="/")


def render_message(title: str, message: str, *, word: str = "") -> str:
    """An error or not-found page. ``message`` is plain text, not HTML."""
    text = "<br>".join(
        esc(line.strip()) for line in message.splitlines() if line.strip()
    )
    body = f"""{search_form(word)}
<section class="notice" role="alert"><h1>{esc(title)}</h1><p>{text}</p></section>"""
    return layout(f"{title} - Dictionary", body, active="/")


def _batch_form(text: str, fmt: str, error: str) -> str:
    options = "".join(
        f'<option value="{esc(value)}"'
        + (" selected" if value == fmt else "")
        + f">{label}</option>"
        for value, label in _FORMAT_LABELS.items()
    )
    alert = f'<p class="notice" role="alert">{esc(error)}</p>' if error else ""
    return f"""{alert}<form class="batch" method="post" action="/batch">
<label for="words">One word or phrase per line</label>
<textarea id="words" name="words" rows="10" spellcheck="false"
 placeholder="serendipity&#10;ephemeral&#10;ice cream">{esc(text)}</textarea>
<div class="actions">
<button type="submit" formaction="/batch">Look up</button>
<label for="format">Download as</label>
<select id="format" name="format">{options}</select>
<button type="submit" formaction="/export" class="secondary">Download</button>
</div>
</form>"""


def render_batch_form(text: str = "", fmt: str = "text", *, error: str = "") -> str:
    body = f"<h1>Batch lookup</h1>\n{_batch_form(text, fmt, error)}"
    return layout("Batch lookup - Dictionary", body, active="/batch")


def render_batch_results(
    entries: Sequence[func.Entry],
    failures: Sequence[tuple[str, str]],
    *,
    text: str,
    fmt: str,
) -> str:
    """Results for a word list: every entry, then the words that failed."""
    total = len(entries) + len(failures)
    parts = [
        "<h1>Batch lookup</h1>",
        f'<p class="muted">Found {len(entries)} of {total}.</p>',
    ]
    if failures:
        items = "".join(
            f"<li><strong>{esc(word)}</strong>: {esc(reason)}</li>"
            for word, reason in failures
        )
        parts.append(
            f'<section class="notice"><h2>Not found</h2><ul>{items}</ul></section>'
        )
    parts.extend(_article(entry, level=2) for entry in entries)
    parts.append(_batch_form(text, fmt, ""))
    return layout("Batch lookup - Dictionary", "\n".join(parts), active="/batch")


def render_history(records: Sequence[HistoryRecord] | None) -> str:
    """The lookup log, newest first. ``None`` means history is turned off."""
    if records is None:
        content = '<p class="muted">History is turned off for this session.</p>'
    elif not records:
        content = '<p class="muted">Nothing has been looked up yet.</p>'
    else:
        rows = "".join(
            f"<tr><td>{esc(record.timestamp)}</td>"
            f'<td><a href="{esc(word_url(record.word))}">{esc(record.word)}</a></td>'
            f"<td><span class=\"badge {'found' if record.found else 'not-found'}\">{'found' if record.found else 'not found'}</span></td></tr>"
            for record in records
        )
        content = (
            '<table class="history"><thead><tr><th scope="col">When (UTC)</th>'
            '<th scope="col">Word</th><th scope="col">Result</th></tr></thead>'
            f"<tbody>{rows}</tbody></table>"
        )
    return layout(
        "History - Dictionary", f"<h1>History</h1>\n{content}", active="/history"
    )
