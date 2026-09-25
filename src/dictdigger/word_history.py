#!/usr/bin/python3
# -*- coding: utf-8 -*-

# =============================================================================
#
#        FILE:  word_history.py
#     CREATED:  2026-09-20
# DESCRIPTION:  A local, append-only log of every dictionary lookup, stored as
#               a JSON array in word_history.json.
#
# =============================================================================

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dictdigger.atomic_io import atomic_write_bytes

logger = logging.getLogger(__name__)

HISTORY_FILENAME = "word_history.json"


@dataclass(frozen=True)
class HistoryRecord:
    """One logged lookup."""

    word: str
    timestamp: str  # ISO 8601, UTC
    found: bool = True


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WordHistory:
    """Append-only lookup log kept as a valid JSON array.

    The tool only ever *adds* entries; it never edits or removes them. Each
    append rewrites the file atomically (temp file + ``os.replace``), so the
    log is always valid JSON that ``jq`` and friends can read. The trade-off
    is that two *processes* appending at the very same instant can lose one
    entry; that is acceptable for a single-user tool. Threads inside one
    process (the web interface) are serialised by a lock.

    A log that cannot be parsed is never overwritten: it is moved aside to
    ``word_history.json.corrupt-<timestamp>`` and a fresh log is started.

    Args:
        path: Location of the JSON log.
        clock: Returns the current time as a timezone-aware datetime;
            injectable so timestamps are deterministic in tests.
    """

    def __init__(self, path: Path, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._path = Path(path)
        self._clock = clock
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def record(self, word: str, *, found: bool = True) -> None:
        """Append one lookup to the log."""
        with self._lock:
            raw = self._load_raw(repair=True)
            raw.append(
                {
                    "word": word,
                    "timestamp": self._clock().isoformat(timespec="seconds"),
                    "found": found,
                }
            )
            text = json.dumps(raw, indent=2, ensure_ascii=False) + "\n"
            atomic_write_bytes(self._path, text.encode("utf-8"))

    def read(self) -> list[HistoryRecord]:
        """Return every logged lookup, oldest first.

        A missing or unreadable log yields an empty list (with a warning in
        the latter case); reading never modifies the file.
        """
        records: list[HistoryRecord] = []
        for item in self._load_raw(repair=False):
            if (
                isinstance(item, dict)
                and isinstance(item.get("word"), str)
                and isinstance(item.get("timestamp"), str)
            ):
                records.append(
                    HistoryRecord(
                        word=item["word"],
                        timestamp=item["timestamp"],
                        found=bool(item.get("found", True)),
                    )
                )
            else:
                logger.warning("skipping a malformed history entry: %r", item)
        return records

    def _load_raw(self, *, repair: bool) -> list[Any]:
        try:
            content = self._path.read_bytes()
        except FileNotFoundError:
            return []

        try:
            data = json.loads(content)  # bytes in, so bad encodings raise too
            if not isinstance(data, list):
                raise ValueError("the top-level JSON value is not an array")
        except ValueError as exc:
            if not repair:
                logger.warning("the history file %s is unreadable: %s", self._path, exc)
                return []
            stamp = self._clock().strftime("%Y%m%dT%H%M%S")
            backup = self._path.with_name(f"{self._path.name}.corrupt-{stamp}")
            self._path.replace(backup)
            logger.warning(
                "the history file was unreadable (%s); moved it to %s and "
                "started a new log",
                exc,
                backup.name,
            )
            return []
        return data


def record_history(history: WordHistory | None, word: str, *, found: bool) -> None:
    """Log a lookup if a history is in use.

    The log is a convenience, so a failure to write it only warns.
    """
    if history is None:
        return
    try:
        history.record(word, found=found)
    except OSError as exc:
        logger.warning("could not update the word history: %s", exc)
