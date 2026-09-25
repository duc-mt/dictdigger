#!/usr/bin/python3
# -*- coding: utf-8 -*-

# =============================================================================
#
#        FILE:  page_cache.py
#     CREATED:  2026-09-20
# DESCRIPTION:  A small on-disk cache mapping a dictionary word to the HTML of
#               its Merriam-Webster page, so repeated lookups do not hit the
#               network again until the entry's time-to-live has elapsed.
#
# =============================================================================

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import time
import zlib
from collections.abc import Callable
from pathlib import Path

from dictdigger.atomic_io import atomic_write_bytes

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60  # definitions rarely change: one week
CACHE_FORMAT_VERSION = 1


class HtmlCache:
    """Persist page HTML per word, one gzip-compressed JSON file per entry.

    Design notes:

    * File names are the SHA-256 of the normalised word, so user input never
      becomes part of a path (no traversal, no illegal characters).
    * Entries are JSON, never pickles, so reading a tampered cache cannot
      execute code.
    * Writes are atomic, so concurrent runs and crashes cannot leave a
      half-written entry behind.
    * The cache is an optimisation only: an unreadable, corrupt, or expired
      entry is simply a miss, and a failed write is logged, not raised.

    Args:
        directory: Folder holding the cache files (created on first write).
        ttl: Seconds an entry stays valid. ``0`` makes every entry stale,
            which forces a refresh while still updating the cache.
        clock: Returns the current time in seconds since the epoch;
            injectable so expiry can be tested without sleeping.
    """

    def __init__(
        self,
        directory: Path,
        ttl: float = DEFAULT_TTL_SECONDS,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._directory = Path(directory)
        self._ttl = ttl
        self._clock = clock

    def get(self, word: str) -> str | None:
        """Return the cached HTML for ``word``, or ``None`` on a miss."""
        path = self._path_for(word)
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
        except FileNotFoundError:
            return None
        except (OSError, EOFError, ValueError, zlib.error) as exc:
            logger.debug("ignoring unreadable cache entry %s: %s", path.name, exc)
            return None

        html = payload.get("html") if isinstance(payload, dict) else None
        fetched_at = payload.get("fetched_at") if isinstance(payload, dict) else None
        if (
            not isinstance(html, str)
            or not isinstance(fetched_at, int | float)
            or payload.get("v") != CACHE_FORMAT_VERSION
        ):
            logger.debug("ignoring malformed cache entry %s", path.name)
            return None

        age = self._clock() - fetched_at
        if not 0 <= age < self._ttl:  # also rejects timestamps from the future
            logger.debug("cache entry for %r expired (age %.0fs)", word, age)
            return None
        return html

    def set(self, word: str, html: str) -> None:
        """Store ``html`` for ``word``; failures are logged, never raised."""
        payload = {
            "v": CACHE_FORMAT_VERSION,
            "word": self._normalise(word),
            "fetched_at": self._clock(),
            "html": html,
        }
        data = gzip.compress(json.dumps(payload).encode("utf-8"))
        try:
            atomic_write_bytes(self._path_for(word), data)
        except OSError as exc:
            logger.warning("could not write the cache entry for %r: %s", word, exc)

    @staticmethod
    def _normalise(word: str) -> str:
        return " ".join(word.split()).casefold()

    def _path_for(self, word: str) -> Path:
        digest = hashlib.sha256(self._normalise(word).encode("utf-8")).hexdigest()
        return self._directory / f"{digest}.json.gz"
