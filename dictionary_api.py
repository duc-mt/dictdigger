#!/usr/bin/python3
# -*- coding: utf-8 -*-

# =============================================================================
#
#        FILE:  dictionary_api.py
#     CREATED:  2026-09-21
# DESCRIPTION:  Look words up through the official Merriam-Webster Dictionary
#               API instead of scraping the website, which answers scripted
#               requests with HTTP 403. Needs a free API key (MW_API_KEY).
#
# =============================================================================

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

import requests

import functions as func

logger = logging.getLogger(__name__)

API_URL = "https://www.dictionaryapi.com/api/v3/references/collegiate/json"
AUDIO_URL = "https://media.merriam-webster.com/audio/prons/en/us/mp3"
API_KEY_ENV_VAR = "MW_API_KEY"
MAX_SUGGESTIONS = 5
_AUDIO_NAME = re.compile(r"[A-Za-z0-9_-]+")


class ApiError(requests.exceptions.RequestException):
    """A request to the API failed, or its reply could not be understood.

    It subclasses ``RequestException`` so callers handle it like any other
    network failure. Its message never contains the API key.

    Attributes:
        status_code: The HTTP status, when there was one.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _redact(text: str, api_key: str) -> str:
    """Remove the API key from ``text`` (requests puts the URL in its errors)."""
    for secret in {api_key, quote(api_key, safe="")}:
        if secret:
            text = text.replace(secret, "***")
    return text


def audio_url(name: str) -> str:
    """Build the URL of a pronunciation clip from the file name the API gives.

    The API documents the folder rule: names starting with ``bix`` or ``gg``
    have their own folders, names starting with a digit or punctuation go in
    ``number``, and everything else uses its first letter.

    Raises:
        ValueError: If ``name`` is not a plain file name (the name comes from
            the network, so it is never trusted to build a URL).
    """
    if not _AUDIO_NAME.fullmatch(name):
        raise ValueError(f"unexpected audio file name: {name!r}")
    if name.startswith("bix"):
        folder = "bix"
    elif name.startswith("gg"):
        folder = "gg"
    elif not name[0].isalpha():
        folder = "number"
    else:
        folder = name[0]
    return f"{AUDIO_URL}/{folder}/{name}.mp3"


def _first_audio_url(entry: Mapping[str, Any]) -> str | None:
    hwi = entry.get("hwi")
    pronunciations = hwi.get("prs") if isinstance(hwi, dict) else None
    if not isinstance(pronunciations, list):
        return None
    for pronunciation in pronunciations:
        sound = pronunciation.get("sound") if isinstance(pronunciation, dict) else None
        name = sound.get("audio") if isinstance(sound, dict) else None
        if isinstance(name, str):
            try:
                return audio_url(name)
            except ValueError:
                logger.debug("ignoring an unusable audio file name")
    return None


def parse_entry(word: str, payload: str) -> func.Entry:
    """Turn the API's JSON reply into an ``Entry``.

    The API answers an unknown word with a JSON list of spelling suggestions
    (plain strings) instead of entries, and answers a bad or unauthorised key
    with a plain-text message rather than JSON.

    Raises:
        WordNotFoundError: If the reply holds no definitions.
        ApiError: If the reply is not what the API documents.
    """
    try:
        data = json.loads(payload)
    except ValueError:
        message = " ".join(payload.split())[:100]
        raise ApiError(
            f"unexpected reply from the dictionary API: {message!r}"
        ) from None
    if not isinstance(data, list):
        raise ApiError("unexpected reply from the dictionary API")

    definitions: list[str] = []
    audio: str | None = None
    for item in data:
        if not isinstance(item, dict):
            continue
        label = item.get("fl")
        prefix = f"({label}) " if isinstance(label, str) and label else ""
        short_definitions = item.get("shortdef")
        if isinstance(short_definitions, list):
            definitions.extend(
                prefix + " ".join(text.split())
                for text in short_definitions
                if isinstance(text, str) and text.strip()
            )
        if audio is None:
            audio = _first_audio_url(item)

    if not definitions:
        suggestions = [item for item in data if isinstance(item, str)]
        raise func.WordNotFoundError(word, suggestions[:MAX_SUGGESTIONS])
    return func.Entry(word=word, definitions=tuple(definitions), audio_url=audio)


def fetch_payload(
    word: str,
    *,
    api_key: str,
    timeout: int = func.REQUEST_TIMEOUT,
    limiter: func.RateLimiter | None = None,
    headers: Mapping[str, str] | None = None,
) -> str:
    """Request one word from the API and return the raw reply text.

    Raises:
        ApiError: On any network or HTTP failure (key redacted).
    """
    if limiter is not None:
        limiter.wait()
    url = f"{API_URL}/{quote(word, safe='')}"
    logger.debug("GET %s", url)  # the key travels as a query parameter: never log it
    try:
        response = requests.get(
            url,
            params={"key": api_key},
            timeout=timeout,
            headers=headers or func.request_headers(),
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise ApiError(
            _redact(str(exc), api_key), status_code=func.http_status(exc)
        ) from None
    return response.text


def lookup_word(
    word: str,
    *,
    api_key: str,
    timeout: int = func.REQUEST_TIMEOUT,
    cache: func.PageCache | None = None,
    limiter: func.RateLimiter | None = None,
    headers: Mapping[str, str] | None = None,
) -> func.Entry:
    """Look a word up through the API, using the cache when it has the answer.

    Only replies that produced an entry are cached, so unknown words and
    error messages are never stored.

    Raises:
        WordNotFoundError: If the API has no definitions for the word.
        ApiError: On network failures or an unusable reply.
    """
    if cache is not None:
        cached = cache.get(word)
        if cached is not None:
            try:
                entry = parse_entry(word, cached)
            except (ApiError, func.WordNotFoundError):
                logger.info("ignoring an unusable cache entry for %r", word)
            else:
                logger.info("cache hit for %r", word)
                return entry
        else:
            logger.info("cache miss for %r", word)

    payload = fetch_payload(
        word, api_key=api_key, timeout=timeout, limiter=limiter, headers=headers
    )
    entry = parse_entry(word, payload)
    if cache is not None:
        cache.set(word, payload)
    return entry
