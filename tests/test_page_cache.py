"""Unit tests for page_cache.py.

Time is injected through a fake clock, so TTL behaviour is tested without
sleeping.
"""

from __future__ import annotations

import gzip
import json

import pytest

from page_cache import CACHE_FORMAT_VERSION, DEFAULT_TTL_SECONDS, HtmlCache


class FakeClock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def cache(tmp_path, clock) -> HtmlCache:
    return HtmlCache(tmp_path / "cache", ttl=60, clock=clock)


class TestGetAndSet:
    def test_miss_when_nothing_is_stored(self, cache):
        assert cache.get("serendipity") is None

    def test_round_trips_html(self, cache):
        cache.set("serendipity", "<html>é</html>")
        assert cache.get("serendipity") == "<html>é</html>"

    def test_words_do_not_share_entries(self, cache):
        cache.set("one", "1")
        cache.set("two", "2")
        assert (cache.get("one"), cache.get("two")) == ("1", "2")

    def test_lookup_ignores_case_and_extra_whitespace(self, cache):
        cache.set("Ice  Cream", "<html>ice</html>")
        assert cache.get(" ice cream ") == "<html>ice</html>"

    def test_set_overwrites_the_previous_entry(self, cache):
        cache.set("word", "old")
        cache.set("word", "new")
        assert cache.get("word") == "new"

    def test_default_ttl_is_one_week(self):
        assert DEFAULT_TTL_SECONDS == 7 * 24 * 60 * 60


class TestExpiry:
    def test_entry_is_valid_before_the_ttl_elapses(self, cache, clock):
        cache.set("word", "html")
        clock.now += 59
        assert cache.get("word") == "html"

    def test_entry_expires_at_the_ttl(self, cache, clock):
        cache.set("word", "html")
        clock.now += 60
        assert cache.get("word") is None

    def test_ttl_zero_always_misses_but_still_writes(self, tmp_path, clock):
        cache = HtmlCache(tmp_path, ttl=0, clock=clock)
        cache.set("word", "html")
        assert cache.get("word") is None
        assert len(list(tmp_path.glob("*.json.gz"))) == 1

    def test_timestamps_from_the_future_are_not_trusted(self, cache, clock):
        cache.set("word", "html")
        clock.now -= 3600  # the system clock moved backwards
        assert cache.get("word") is None


class TestSafety:
    def test_hostile_words_cannot_escape_the_cache_directory(self, tmp_path, clock):
        directory = tmp_path / "cache"
        cache = HtmlCache(directory, ttl=60, clock=clock)

        cache.set("../../etc/passwd", "html")

        files = list(tmp_path.rglob("*"))
        assert all(directory in p.parents or p == directory for p in files)
        assert not (tmp_path / "etc").exists()

    def test_entries_are_stored_as_gzipped_json_not_pickles(self, cache, tmp_path):
        cache.set("word", "<p>hi</p>")
        (path,) = (tmp_path / "cache").glob("*.json.gz")
        payload = json.loads(gzip.decompress(path.read_bytes()))
        assert payload["v"] == CACHE_FORMAT_VERSION
        assert payload["word"] == "word"
        assert payload["html"] == "<p>hi</p>"

    @pytest.mark.parametrize(
        "content",
        [
            b"not gzip at all",
            gzip.compress(b"{not json"),
            gzip.compress(b'["a", "list"]'),
            gzip.compress(b'{"v": 1, "html": 5, "fetched_at": 1}'),
            gzip.compress(b'{"v": 99, "html": "x", "fetched_at": 1000000}'),
            gzip.compress(b'{"v": 1, "html": "x"}'),
            gzip.compress(b'{"v": 1, "html": "x", "fetched_at": 1000000}')[:-6],
        ],
        ids=[
            "not-gzip",
            "bad-json",
            "wrong-shape",
            "bad-html-type",
            "future-version",
            "no-timestamp",
            "truncated",
        ],
    )
    def test_corrupt_entries_are_a_miss_not_an_error(self, cache, tmp_path, content):
        cache.set("word", "html")
        (path,) = (tmp_path / "cache").glob("*.json.gz")
        path.write_bytes(content)

        assert cache.get("word") is None

    def test_a_corrupt_entry_is_repaired_by_the_next_write(self, cache, tmp_path):
        cache.set("word", "html")
        (path,) = (tmp_path / "cache").glob("*.json.gz")
        path.write_bytes(b"garbage")

        cache.set("word", "fresh")

        assert cache.get("word") == "fresh"

    def test_write_failures_are_logged_not_raised(self, tmp_path, clock, caplog):
        blocker = tmp_path / "not-a-directory"
        blocker.write_text("I am a file")
        cache = HtmlCache(blocker / "cache", ttl=60, clock=clock)

        cache.set("word", "html")  # must not raise

        assert "could not write the cache entry" in caplog.text
"""Unit tests for page_cache.py.

Time is injected through a fake clock, so TTL behaviour is tested without
sleeping.
"""

from __future__ import annotations

import gzip
import json

import pytest

from page_cache import CACHE_FORMAT_VERSION, DEFAULT_TTL_SECONDS, HtmlCache


class FakeClock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def cache(tmp_path, clock) -> HtmlCache:
    return HtmlCache(tmp_path / "cache", ttl=60, clock=clock)


class TestGetAndSet:
    def test_miss_when_nothing_is_stored(self, cache):
        assert cache.get("serendipity") is None

    def test_round_trips_html(self, cache):
        cache.set("serendipity", "<html>é</html>")
        assert cache.get("serendipity") == "<html>é</html>"

    def test_words_do_not_share_entries(self, cache):
        cache.set("one", "1")
        cache.set("two", "2")
        assert (cache.get("one"), cache.get("two")) == ("1", "2")

    def test_lookup_ignores_case_and_extra_whitespace(self, cache):
        cache.set("Ice  Cream", "<html>ice</html>")
        assert cache.get(" ice cream ") == "<html>ice</html>"

    def test_set_overwrites_the_previous_entry(self, cache):
        cache.set("word", "old")
        cache.set("word", "new")
        assert cache.get("word") == "new"

    def test_default_ttl_is_one_week(self):
        assert DEFAULT_TTL_SECONDS == 7 * 24 * 60 * 60


class TestExpiry:
    def test_entry_is_valid_before_the_ttl_elapses(self, cache, clock):
        cache.set("word", "html")
        clock.now += 59
        assert cache.get("word") == "html"

    def test_entry_expires_at_the_ttl(self, cache, clock):
        cache.set("word", "html")
        clock.now += 60
        assert cache.get("word") is None

    def test_ttl_zero_always_misses_but_still_writes(self, tmp_path, clock):
        cache = HtmlCache(tmp_path, ttl=0, clock=clock)
        cache.set("word", "html")
        assert cache.get("word") is None
        assert len(list(tmp_path.glob("*.json.gz"))) == 1

    def test_timestamps_from_the_future_are_not_trusted(self, cache, clock):
        cache.set("word", "html")
        clock.now -= 3600  # the system clock moved backwards
        assert cache.get("word") is None


class TestSafety:
    def test_hostile_words_cannot_escape_the_cache_directory(self, tmp_path, clock):
        directory = tmp_path / "cache"
        cache = HtmlCache(directory, ttl=60, clock=clock)

        cache.set("../../etc/passwd", "html")

        files = list(tmp_path.rglob("*"))
        assert all(directory in p.parents or p == directory for p in files)
        assert not (tmp_path / "etc").exists()

    def test_entries_are_stored_as_gzipped_json_not_pickles(self, cache, tmp_path):
        cache.set("word", "<p>hi</p>")
        (path,) = (tmp_path / "cache").glob("*.json.gz")
        payload = json.loads(gzip.decompress(path.read_bytes()))
        assert payload["v"] == CACHE_FORMAT_VERSION
        assert payload["word"] == "word"
        assert payload["html"] == "<p>hi</p>"

    @pytest.mark.parametrize(
        "content",
        [
            b"not gzip at all",
            gzip.compress(b"{not json"),
            gzip.compress(b'["a", "list"]'),
            gzip.compress(b'{"v": 1, "html": 5, "fetched_at": 1}'),
            gzip.compress(b'{"v": 99, "html": "x", "fetched_at": 1000000}'),
            gzip.compress(b'{"v": 1, "html": "x"}'),
            gzip.compress(b'{"v": 1, "html": "x", "fetched_at": 1000000}')[:-6],
        ],
        ids=[
            "not-gzip",
            "bad-json",
            "wrong-shape",
            "bad-html-type",
            "future-version",
            "no-timestamp",
            "truncated",
        ],
    )
    def test_corrupt_entries_are_a_miss_not_an_error(self, cache, tmp_path, content):
        cache.set("word", "html")
        (path,) = (tmp_path / "cache").glob("*.json.gz")
        path.write_bytes(content)

        assert cache.get("word") is None

    def test_a_corrupt_entry_is_repaired_by_the_next_write(self, cache, tmp_path):
        cache.set("word", "html")
        (path,) = (tmp_path / "cache").glob("*.json.gz")
        path.write_bytes(b"garbage")

        cache.set("word", "fresh")

        assert cache.get("word") == "fresh"

    def test_write_failures_are_logged_not_raised(self, tmp_path, clock, caplog):
        blocker = tmp_path / "not-a-directory"
        blocker.write_text("I am a file")
        cache = HtmlCache(blocker / "cache", ttl=60, clock=clock)

        cache.set("word", "html")  # must not raise

        assert "could not write the cache entry" in caplog.text
"""Unit tests for page_cache.py.

Time is injected through a fake clock, so TTL behaviour is tested without
sleeping.
"""

from __future__ import annotations

import gzip
import json

import pytest

from page_cache import CACHE_FORMAT_VERSION, DEFAULT_TTL_SECONDS, HtmlCache


class FakeClock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def cache(tmp_path, clock) -> HtmlCache:
    return HtmlCache(tmp_path / "cache", ttl=60, clock=clock)


class TestGetAndSet:
    def test_miss_when_nothing_is_stored(self, cache):
        assert cache.get("serendipity") is None

    def test_round_trips_html(self, cache):
        cache.set("serendipity", "<html>é</html>")
        assert cache.get("serendipity") == "<html>é</html>"

    def test_words_do_not_share_entries(self, cache):
        cache.set("one", "1")
        cache.set("two", "2")
        assert (cache.get("one"), cache.get("two")) == ("1", "2")

    def test_lookup_ignores_case_and_extra_whitespace(self, cache):
        cache.set("Ice  Cream", "<html>ice</html>")
        assert cache.get(" ice cream ") == "<html>ice</html>"

    def test_set_overwrites_the_previous_entry(self, cache):
        cache.set("word", "old")
        cache.set("word", "new")
        assert cache.get("word") == "new"

    def test_default_ttl_is_one_week(self):
        assert DEFAULT_TTL_SECONDS == 7 * 24 * 60 * 60


class TestExpiry:
    def test_entry_is_valid_before_the_ttl_elapses(self, cache, clock):
        cache.set("word", "html")
        clock.now += 59
        assert cache.get("word") == "html"

    def test_entry_expires_at_the_ttl(self, cache, clock):
        cache.set("word", "html")
        clock.now += 60
        assert cache.get("word") is None

    def test_ttl_zero_always_misses_but_still_writes(self, tmp_path, clock):
        cache = HtmlCache(tmp_path, ttl=0, clock=clock)
        cache.set("word", "html")
        assert cache.get("word") is None
        assert len(list(tmp_path.glob("*.json.gz"))) == 1

    def test_timestamps_from_the_future_are_not_trusted(self, cache, clock):
        cache.set("word", "html")
        clock.now -= 3600  # the system clock moved backwards
        assert cache.get("word") is None


class TestSafety:
    def test_hostile_words_cannot_escape_the_cache_directory(self, tmp_path, clock):
        directory = tmp_path / "cache"
        cache = HtmlCache(directory, ttl=60, clock=clock)

        cache.set("../../etc/passwd", "html")

        files = list(tmp_path.rglob("*"))
        assert all(directory in p.parents or p == directory for p in files)
        assert not (tmp_path / "etc").exists()

    def test_entries_are_stored_as_gzipped_json_not_pickles(self, cache, tmp_path):
        cache.set("word", "<p>hi</p>")
        (path,) = (tmp_path / "cache").glob("*.json.gz")
        payload = json.loads(gzip.decompress(path.read_bytes()))
        assert payload["v"] == CACHE_FORMAT_VERSION
        assert payload["word"] == "word"
        assert payload["html"] == "<p>hi</p>"

    @pytest.mark.parametrize(
        "content",
        [
            b"not gzip at all",
            gzip.compress(b"{not json"),
            gzip.compress(b'["a", "list"]'),
            gzip.compress(b'{"v": 1, "html": 5, "fetched_at": 1}'),
            gzip.compress(b'{"v": 99, "html": "x", "fetched_at": 1000000}'),
            gzip.compress(b'{"v": 1, "html": "x"}'),
            gzip.compress(b'{"v": 1, "html": "x", "fetched_at": 1000000}')[:-6],
        ],
        ids=[
            "not-gzip",
            "bad-json",
            "wrong-shape",
            "bad-html-type",
            "future-version",
            "no-timestamp",
            "truncated",
        ],
    )
    def test_corrupt_entries_are_a_miss_not_an_error(self, cache, tmp_path, content):
        cache.set("word", "html")
        (path,) = (tmp_path / "cache").glob("*.json.gz")
        path.write_bytes(content)

        assert cache.get("word") is None

    def test_a_corrupt_entry_is_repaired_by_the_next_write(self, cache, tmp_path):
        cache.set("word", "html")
        (path,) = (tmp_path / "cache").glob("*.json.gz")
        path.write_bytes(b"garbage")

        cache.set("word", "fresh")

        assert cache.get("word") == "fresh"

    def test_write_failures_are_logged_not_raised(self, tmp_path, clock, caplog):
        blocker = tmp_path / "not-a-directory"
        blocker.write_text("I am a file")
        cache = HtmlCache(blocker / "cache", ttl=60, clock=clock)

        cache.set("word", "html")  # must not raise

        assert "could not write the cache entry" in caplog.text
