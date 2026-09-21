"""Unit tests for word_history.py."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from word_history import HISTORY_FILENAME, HistoryRecord, WordHistory


class FakeClock:
    """A clock that advances one minute each time it is read."""

    def __init__(self) -> None:
        self.now = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        current = self.now
        self.now += timedelta(minutes=1)
        return current


@pytest.fixture
def history(tmp_path) -> WordHistory:
    return WordHistory(tmp_path / HISTORY_FILENAME, clock=FakeClock())


class TestRecord:
    def test_creates_the_file_with_the_first_entry(self, history):
        history.record("serendipity")
        assert json.loads(history.path.read_text(encoding="utf-8")) == [
            {
                "word": "serendipity",
                "timestamp": "2026-09-20T12:00:00+00:00",
                "found": True,
            }
        ]

    def test_appends_in_order_and_keeps_every_earlier_entry(self, history):
        for word in ("one", "two", "three"):
            history.record(word)
        assert [r.word for r in history.read()] == ["one", "two", "three"]

    def test_the_same_word_is_logged_each_time_it_is_looked_up(self, history):
        history.record("again")
        history.record("again")
        assert [r.word for r in history.read()] == ["again", "again"]

    def test_records_whether_the_word_was_found(self, history):
        history.record("asdf", found=False)
        assert history.read() == [
            HistoryRecord("asdf", "2026-09-20T12:00:00+00:00", found=False)
        ]

    def test_the_file_is_always_valid_json(self, history):
        history.record("café")
        history.record("ice cream")
        json.loads(history.path.read_text(encoding="utf-8"))

    def test_non_ascii_words_are_stored_readably(self, history):
        history.record("café")
        assert "café" in history.path.read_text(encoding="utf-8")

    def test_default_clock_writes_a_timezone_aware_utc_timestamp(self, tmp_path):
        log = WordHistory(tmp_path / HISTORY_FILENAME)
        log.record("word")
        stamp = datetime.fromisoformat(log.read()[0].timestamp)
        assert stamp.utcoffset() == timedelta(0)

    def test_unknown_fields_from_other_tools_survive_an_append(self, history):
        history.path.write_text(
            json.dumps([{"word": "old", "timestamp": "t", "note": "keep me"}]),
            encoding="utf-8",
        )
        history.record("new")
        raw = json.loads(history.path.read_text(encoding="utf-8"))
        assert raw[0]["note"] == "keep me"
        assert raw[1]["word"] == "new"


class TestRead:
    def test_a_missing_file_is_an_empty_history(self, history):
        assert history.read() == []
        assert not history.path.exists()  # reading never creates the file

    def test_entries_without_a_found_field_count_as_found(self, history):
        history.path.write_text(
            json.dumps([{"word": "w", "timestamp": "t"}]), encoding="utf-8"
        )
        assert history.read() == [HistoryRecord("w", "t", found=True)]

    def test_malformed_entries_are_skipped_with_a_warning(self, history, caplog):
        history.path.write_text(
            json.dumps([{"word": "ok", "timestamp": "t"}, "junk", {"word": 1}]),
            encoding="utf-8",
        )
        assert [r.word for r in history.read()] == ["ok"]
        assert "malformed history entry" in caplog.text

    def test_reading_a_corrupt_file_warns_and_leaves_it_untouched(
        self, history, caplog
    ):
        history.path.write_text("{oops", encoding="utf-8")
        assert history.read() == []
        assert history.path.read_text(encoding="utf-8") == "{oops"
        assert "unreadable" in caplog.text


class TestCorruptFileRecovery:
    @pytest.mark.parametrize(
        "content",
        [b"{not json", b'{"an": "object"}', b"\xff\xfe\x00garbage"],
        ids=["bad-json", "wrong-root-type", "bad-encoding"],
    )
    def test_a_corrupt_log_is_moved_aside_not_destroyed(self, history, content):
        history.path.write_bytes(content)

        history.record("fresh")

        (backup,) = history.path.parent.glob(f"{HISTORY_FILENAME}.corrupt-*")
        assert backup.read_bytes() == content
        assert [r.word for r in history.read()] == ["fresh"]
"""Unit tests for word_history.py."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from word_history import HISTORY_FILENAME, HistoryRecord, WordHistory


class FakeClock:
    """A clock that advances one minute each time it is read."""

    def __init__(self) -> None:
        self.now = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        current = self.now
        self.now += timedelta(minutes=1)
        return current


@pytest.fixture
def history(tmp_path) -> WordHistory:
    return WordHistory(tmp_path / HISTORY_FILENAME, clock=FakeClock())


class TestRecord:
    def test_creates_the_file_with_the_first_entry(self, history):
        history.record("serendipity")
        assert json.loads(history.path.read_text(encoding="utf-8")) == [
            {
                "word": "serendipity",
                "timestamp": "2026-09-20T12:00:00+00:00",
                "found": True,
            }
        ]

    def test_appends_in_order_and_keeps_every_earlier_entry(self, history):
        for word in ("one", "two", "three"):
            history.record(word)
        assert [r.word for r in history.read()] == ["one", "two", "three"]

    def test_the_same_word_is_logged_each_time_it_is_looked_up(self, history):
        history.record("again")
        history.record("again")
        assert [r.word for r in history.read()] == ["again", "again"]

    def test_records_whether_the_word_was_found(self, history):
        history.record("asdf", found=False)
        assert history.read() == [
            HistoryRecord("asdf", "2026-09-20T12:00:00+00:00", found=False)
        ]

    def test_the_file_is_always_valid_json(self, history):
        history.record("café")
        history.record("ice cream")
        json.loads(history.path.read_text(encoding="utf-8"))

    def test_non_ascii_words_are_stored_readably(self, history):
        history.record("café")
        assert "café" in history.path.read_text(encoding="utf-8")

    def test_default_clock_writes_a_timezone_aware_utc_timestamp(self, tmp_path):
        log = WordHistory(tmp_path / HISTORY_FILENAME)
        log.record("word")
        stamp = datetime.fromisoformat(log.read()[0].timestamp)
        assert stamp.utcoffset() == timedelta(0)

    def test_unknown_fields_from_other_tools_survive_an_append(self, history):
        history.path.write_text(
            json.dumps([{"word": "old", "timestamp": "t", "note": "keep me"}]),
            encoding="utf-8",
        )
        history.record("new")
        raw = json.loads(history.path.read_text(encoding="utf-8"))
        assert raw[0]["note"] == "keep me"
        assert raw[1]["word"] == "new"


class TestRead:
    def test_a_missing_file_is_an_empty_history(self, history):
        assert history.read() == []
        assert not history.path.exists()  # reading never creates the file

    def test_entries_without_a_found_field_count_as_found(self, history):
        history.path.write_text(
            json.dumps([{"word": "w", "timestamp": "t"}]), encoding="utf-8"
        )
        assert history.read() == [HistoryRecord("w", "t", found=True)]

    def test_malformed_entries_are_skipped_with_a_warning(self, history, caplog):
        history.path.write_text(
            json.dumps([{"word": "ok", "timestamp": "t"}, "junk", {"word": 1}]),
            encoding="utf-8",
        )
        assert [r.word for r in history.read()] == ["ok"]
        assert "malformed history entry" in caplog.text

    def test_reading_a_corrupt_file_warns_and_leaves_it_untouched(
        self, history, caplog
    ):
        history.path.write_text("{oops", encoding="utf-8")
        assert history.read() == []
        assert history.path.read_text(encoding="utf-8") == "{oops"
        assert "unreadable" in caplog.text


class TestCorruptFileRecovery:
    @pytest.mark.parametrize(
        "content",
        [b"{not json", b'{"an": "object"}', b"\xff\xfe\x00garbage"],
        ids=["bad-json", "wrong-root-type", "bad-encoding"],
    )
    def test_a_corrupt_log_is_moved_aside_not_destroyed(self, history, content):
        history.path.write_bytes(content)

        history.record("fresh")

        (backup,) = history.path.parent.glob(f"{HISTORY_FILENAME}.corrupt-*")
        assert backup.read_bytes() == content
        assert [r.word for r in history.read()] == ["fresh"]
"""Unit tests for word_history.py."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from word_history import HISTORY_FILENAME, HistoryRecord, WordHistory


class FakeClock:
    """A clock that advances one minute each time it is read."""

    def __init__(self) -> None:
        self.now = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        current = self.now
        self.now += timedelta(minutes=1)
        return current


@pytest.fixture
def history(tmp_path) -> WordHistory:
    return WordHistory(tmp_path / HISTORY_FILENAME, clock=FakeClock())


class TestRecord:
    def test_creates_the_file_with_the_first_entry(self, history):
        history.record("serendipity")
        assert json.loads(history.path.read_text(encoding="utf-8")) == [
            {
                "word": "serendipity",
                "timestamp": "2026-09-20T12:00:00+00:00",
                "found": True,
            }
        ]

    def test_appends_in_order_and_keeps_every_earlier_entry(self, history):
        for word in ("one", "two", "three"):
            history.record(word)
        assert [r.word for r in history.read()] == ["one", "two", "three"]

    def test_the_same_word_is_logged_each_time_it_is_looked_up(self, history):
        history.record("again")
        history.record("again")
        assert [r.word for r in history.read()] == ["again", "again"]

    def test_records_whether_the_word_was_found(self, history):
        history.record("asdf", found=False)
        assert history.read() == [
            HistoryRecord("asdf", "2026-09-20T12:00:00+00:00", found=False)
        ]

    def test_the_file_is_always_valid_json(self, history):
        history.record("café")
        history.record("ice cream")
        json.loads(history.path.read_text(encoding="utf-8"))

    def test_non_ascii_words_are_stored_readably(self, history):
        history.record("café")
        assert "café" in history.path.read_text(encoding="utf-8")

    def test_default_clock_writes_a_timezone_aware_utc_timestamp(self, tmp_path):
        log = WordHistory(tmp_path / HISTORY_FILENAME)
        log.record("word")
        stamp = datetime.fromisoformat(log.read()[0].timestamp)
        assert stamp.utcoffset() == timedelta(0)

    def test_unknown_fields_from_other_tools_survive_an_append(self, history):
        history.path.write_text(
            json.dumps([{"word": "old", "timestamp": "t", "note": "keep me"}]),
            encoding="utf-8",
        )
        history.record("new")
        raw = json.loads(history.path.read_text(encoding="utf-8"))
        assert raw[0]["note"] == "keep me"
        assert raw[1]["word"] == "new"


class TestRead:
    def test_a_missing_file_is_an_empty_history(self, history):
        assert history.read() == []
        assert not history.path.exists()  # reading never creates the file

    def test_entries_without_a_found_field_count_as_found(self, history):
        history.path.write_text(
            json.dumps([{"word": "w", "timestamp": "t"}]), encoding="utf-8"
        )
        assert history.read() == [HistoryRecord("w", "t", found=True)]

    def test_malformed_entries_are_skipped_with_a_warning(self, history, caplog):
        history.path.write_text(
            json.dumps([{"word": "ok", "timestamp": "t"}, "junk", {"word": 1}]),
            encoding="utf-8",
        )
        assert [r.word for r in history.read()] == ["ok"]
        assert "malformed history entry" in caplog.text

    def test_reading_a_corrupt_file_warns_and_leaves_it_untouched(
        self, history, caplog
    ):
        history.path.write_text("{oops", encoding="utf-8")
        assert history.read() == []
        assert history.path.read_text(encoding="utf-8") == "{oops"
        assert "unreadable" in caplog.text


class TestCorruptFileRecovery:
    @pytest.mark.parametrize(
        "content",
        [b"{not json", b'{"an": "object"}', b"\xff\xfe\x00garbage"],
        ids=["bad-json", "wrong-root-type", "bad-encoding"],
    )
    def test_a_corrupt_log_is_moved_aside_not_destroyed(self, history, content):
        history.path.write_bytes(content)

        history.record("fresh")

        (backup,) = history.path.parent.glob(f"{HISTORY_FILENAME}.corrupt-*")
        assert backup.read_bytes() == content
        assert [r.word for r in history.read()] == ["fresh"]
