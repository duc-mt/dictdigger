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

import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from time import monotonic, sleep
from typing import Protocol
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DICTIONARY_URL = "https://www.merriam-webster.com/dictionary"
REQUEST_TIMEOUT = 10  # seconds
DTTEXT_CLASS = "dtText"
NOT_FOUND_MESSAGE = "isn't in the dictionary"
MAX_WORD_LENGTH = 100
MAX_AUDIO_BYTES = 5 * 1024 * 1024  # pronunciation clips are a few KB
DEFAULT_REQUEST_DELAY = 0.5  # seconds between network requests

# Matches e.g. "contentURL":"https://.../word.mp3" regardless of surrounding
# whitespace. Using a regex instead of manually walking characters (the
# original approach) is both easier to read and correct when the field is
# missing or the JSON formatting changes slightly.
_CONTENT_URL_PATTERN = re.compile(r'"contentURL"\s*:\s*"([^"]+)"')


class PageCache(Protocol):
    """Anything that can remember a word's page HTML (see ``page_cache``)."""

    def get(self, word: str) -> str | None: ...

    def set(self, word: str, html: str) -> None: ...


# A callable that fetches a word's page: ``fetch_page`` or a wrapper around it.
Fetcher = Callable[[str], tuple[str, BeautifulSoup]]


@dataclass(frozen=True)
class Entry:
    """A parsed dictionary entry."""

    word: str
    definitions: tuple[str, ...]
    audio_url: str | None = None


class WordNotFoundError(LookupError):
    """Raised when the dictionary has no entry for the requested word."""


class RateLimiter:
    """Enforce a minimum pause between consecutive network requests.

    Args:
        min_interval: Seconds that must separate two calls to ``wait``.
        clock: Monotonic time source, injectable for tests.
        pause: Function that sleeps for a number of seconds, injectable for
            tests.
    """

    def __init__(
        self,
        min_interval: float,
        *,
        clock: Callable[[], float] | None = None,
        pause: Callable[[float], None] | None = None,
    ) -> None:
        self._min_interval = max(0.0, min_interval)
        self._clock = clock or monotonic
        self._pause = pause or sleep
        self._last_request: float | None = None

    def wait(self) -> None:
        """Block until enough time has passed since the previous request."""
        if self._last_request is not None:
            remaining = self._min_interval - (self._clock() - self._last_request)
            if remaining > 0:
                self._pause(remaining)
        self._last_request = self._clock()


def draw_line_break() -> None:
    """Print a visual line break and pause briefly for readability."""
    print("\n", "-" * 71, "\n")
    sleep(0.5)


def fetch_page(
    word: str | None = None,
    *,
    timeout: int = REQUEST_TIMEOUT,
    cache: PageCache | None = None,
    limiter: RateLimiter | None = None,
) -> tuple[str, BeautifulSoup]:
    """Fetch a Merriam-Webster dictionary page.

    Args:
        word: The word to look up. If ``None``, fetches the dictionary
            homepage instead (used for the Word of the Day).
        timeout: Seconds to wait for a server response before giving up.
        cache: Optional page cache consulted before, and filled after, a
            network request. Only word pages are cached; the homepage
            changes daily and is always fetched.
        limiter: Optional rate limiter consulted before each network
            request. Cache hits never wait.

    Returns:
        A tuple of ``(raw HTML text, parsed BeautifulSoup document)``.

    Raises:
        requests.exceptions.RequestException: On network failure, timeout,
            or a non-2xx HTTP response.
    """
    if word and cache is not None:
        cached = cache.get(word)
        if cached is not None:
            logger.info("cache hit for %r", word)
            return cached, BeautifulSoup(cached, "html.parser")
        logger.info("cache miss for %r", word)

    # safe="" also escapes "/", so a word can never add path segments.
    url = f"{DICTIONARY_URL}/{quote(word, safe='')}" if word else DICTIONARY_URL
    if limiter is not None:
        limiter.wait()
    logger.debug("GET %s", url)
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    if word and cache is not None:
        cache.set(word, response.text)
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
        separator = "" if text.startswith(":") else ": "
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
    url = match.group(1)
    if not url.startswith("https://"):
        # The URL comes from scraped HTML, so never follow file://, ftp:// etc.
        raise ValueError("the pronunciation audio is not served over HTTPS")
    return url


def is_not_found_error(exc: requests.exceptions.RequestException) -> bool:
    """Return ``True`` if ``exc`` is an HTTP 404, i.e. the word has no entry.

    Note: a ``requests.Response`` is falsy for 4xx/5xx statuses, so the
    ``response`` attribute must be compared with ``None`` explicitly.
    """
    return (
        isinstance(exc, requests.exceptions.HTTPError)
        and exc.response is not None
        and exc.response.status_code == HTTPStatus.NOT_FOUND
    )


def normalize_word(raw: str) -> str:
    """Tidy user input into a lookup key: collapse whitespace and validate.

    Raises:
        ValueError: If the word is empty, absurdly long, or contains
            control characters.
    """
    word = " ".join(raw.split())
    if not word:
        raise ValueError("the word must not be empty")
    if len(word) > MAX_WORD_LENGTH:
        raise ValueError(f"the word is longer than {MAX_WORD_LENGTH} characters")
    if not word.isprintable():
        raise ValueError("the word contains control characters")
    return word


def unique_words(words: Iterable[str]) -> list[str]:
    """Drop case-insensitive duplicates, keeping the first spelling and order."""
    seen: set[str] = set()
    unique: list[str] = []
    for word in words:
        key = word.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(word)
    return unique


def parse_word_list(text: str) -> list[str]:
    """Parse the contents of a word-list file.

    One word or phrase per line; blank lines and lines starting with ``#``
    are ignored, and duplicates are dropped.

    Raises:
        ValueError: If a line is not a valid word; the message names the
            line number so the file can be fixed before any request is made.
    """
    words: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            words.append(normalize_word(stripped))
        except ValueError as exc:
            raise ValueError(f"line {number}: {exc}") from exc
    return unique_words(words)


def clean_definition(text: str) -> str:
    """Collapse whitespace and drop Merriam-Webster's leading ``:`` marker."""
    return " ".join(text.split()).lstrip(": ")


def lookup_word(word: str, fetch: Fetcher | None = None) -> Entry:
    """Look a word up and parse its definitions and pronunciation URL.

    Args:
        word: A word already passed through ``normalize_word``.
        fetch: Callable returning ``(html, soup)`` for a word. Defaults to
            ``fetch_page``; pass a wrapper to add caching or rate limiting.

    Raises:
        WordNotFoundError: If the dictionary has no entry for the word.
        requests.exceptions.RequestException: On network failure or any HTTP
            error other than 404.
    """
    fetch = fetch or fetch_page  # resolved at call time so tests can patch it
    try:
        text, soup = fetch(word)
    except requests.exceptions.HTTPError as exc:
        if is_not_found_error(exc):
            raise WordNotFoundError(word) from exc
        raise
    if not word_exists(text):
        raise WordNotFoundError(word)

    definitions = tuple(
        cleaned
        for cleaned in map(clean_definition, find_all_definitions(soup))
        if cleaned
    )
    try:
        audio_url: str | None = extract_mp3_url(text)
    except ValueError:  # phrases and abbreviations often have no recording
        audio_url = None
    return Entry(word=word, definitions=definitions, audio_url=audio_url)


def download_audio(
    url: str, destination: Path | str, *, timeout: int = REQUEST_TIMEOUT
) -> None:
    """Download a pronunciation clip to ``destination``.

    Unlike ``urllib.request.urlretrieve`` this enforces a timeout, refuses
    non-HTTPS URLs (the URL is scraped, so it is untrusted), and caps the
    size of the download.

    Raises:
        ValueError: If the URL is not HTTPS or the clip is unexpectedly big.
        requests.exceptions.RequestException: On network failure or an HTTP
            error status.
        OSError: If the destination cannot be written.
    """
    if not url.startswith("https://"):
        raise ValueError("refusing to download audio over a non-HTTPS URL")

    target = Path(destination)
    written = 0
    try:
        with requests.get(url, timeout=timeout, stream=True) as response:
            response.raise_for_status()
            with target.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=8192):
                    written += len(chunk)
                    if written > MAX_AUDIO_BYTES:
                        raise ValueError("the audio download is unexpectedly large")
                    handle.write(chunk)
    except BaseException:
        target.unlink(missing_ok=True)  # never leave a partial clip behind
        raise
