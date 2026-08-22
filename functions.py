#!/usr/bin/python3
# -*- coding: utf-8 -*-

# =============================================================================
#
#        FILE:  functions.py
#      AUTHOR:  Mai Tan Duc <ducmai.network@gmail.com>
#     CREATED:  2021-08-20
# DESCRIPTION:  Reusable helpers for retrieving and parsing Merriam-Webster
#               dictionary pages. Kept separate from main.py to improve
#               legibility, reuse, and unit-testability.
#
# =============================================================================

from __future__ import annotations

import re
from time import sleep
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

DICTIONARY_URL = "https://www.merriam-webster.com/dictionary"
REQUEST_TIMEOUT = 10  # seconds
DTTEXT_CLASS = "dtText"
NOT_FOUND_MESSAGE = "isn't in the dictionary"

# Matches e.g. "contentURL":"https://.../word.mp3" regardless of surrounding
# whitespace. Using a regex instead of manually walking characters (the
# original approach) is both easier to read and correct when the field is
# missing or the JSON formatting changes slightly.
_CONTENT_URL_PATTERN = re.compile(r'"contentURL"\s*:\s*"([^"]+)"')


def draw_line_break() -> None:
    """Print a visual line break and pause briefly for readability."""
    print("\n", "-" * 71, "\n")
    sleep(0.5)


def fetch_page(
    word: str | None = None, *, timeout: int = REQUEST_TIMEOUT
) -> tuple[str, BeautifulSoup]:
    """Fetch a Merriam-Webster dictionary page.

    Args:
        word: The word to look up. If ``None``, fetches the dictionary
            homepage instead (used for the Word of the Day).
        timeout: Seconds to wait for a server response before giving up.

    Returns:
        A tuple of ``(raw HTML text, parsed BeautifulSoup document)``.

    Raises:
        requests.exceptions.RequestException: On network failure, timeout,
            or a non-2xx HTTP response.
    """
    url = f"{DICTIONARY_URL}/{quote(word)}" if word else DICTIONARY_URL
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text, BeautifulSoup(response.content, "html.parser")


def get_word_of_the_day(soup: BeautifulSoup) -> str:
    """Extract today's featured word from the dictionary homepage.

    Raises:
        ValueError: If the Word of the Day link cannot be located, e.g.
            because the page layout has changed.
    """
    anchor = soup.find("a", attrs={"href": "/word-of-the-day"})
    for _ in range(2):
        if anchor is None:
            break
        anchor = anchor.find_next("a", attrs={"href": "/word-of-the-day"})
    if anchor is None:
        raise ValueError("could not locate the Word of the Day on the homepage")
    return anchor.get_text()


def word_exists(page_text: str) -> bool:
    """Return ``True`` if the fetched page represents a real dictionary entry."""
    return NOT_FOUND_MESSAGE not in page_text


def find_all_definitions(soup: BeautifulSoup) -> list[str]:
    """Return the text of every definition ('dtText' span) on the page.

    Counting the actual parsed tags (rather than counting substring
    occurrences of "dtText" in the raw HTML, as the original implementation
    did) avoids false positives from unrelated occurrences of that string
    elsewhere in the page (e.g. in inline <script> JSON).
    """
    return [tag.get_text() for tag in soup.find_all("span", class_=DTTEXT_CLASS)]


def format_definitions(definitions: list[str]) -> str:
    """Render a list of definitions for display.

    A single definition is printed as-is; multiple definitions are numbered
    as "Entry N".
    """
    if not definitions:
        return ": NO DEFINITION FOUND!"
    if len(definitions) == 1:
        return definitions[0]

    lines = []
    for index, text in enumerate(definitions, start=1):
        separator = "" if ": " in text else ": "
        lines.append(f"Entry {index}{separator}{text}")
    return "\n".join(lines)


def extract_mp3_url(page_text: str) -> str:
    """Extract the pronunciation mp3 URL from a dictionary page's raw HTML.

    Raises:
        ValueError: If no pronunciation audio is available for the word
            (common for phrases and abbreviations).
    """
    match = _CONTENT_URL_PATTERN.search(page_text)
    if not match:
        raise ValueError("no pre-recorded pronunciation is available for this word")
    return match.group(1)
