"""Unit tests for functions.py.

Network access is always mocked - these tests never hit the real
Merriam-Webster website, so they are fast, deterministic, and safe to run
in CI.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from curl_cffi import requests

from dictdigger import functions as func

SINGLE_DEFINITION_HTML = """
<html><body>
  <span class="dtText">: a fleeting or short-lived thing</span>
</body></html>
"""

MULTI_DEFINITION_HTML = """
<html><body>
  <span class="dtText">: first sense</span>
  <span class="dtText">second sense (no leading colon)</span>
</body></html>
"""

NO_DEFINITION_HTML = "<html><body><p>nothing here</p></body></html>"


class TestDrawLineBreak:
    def test_prints_and_does_not_raise(self, capsys, monkeypatch):
        monkeypatch.setattr(func, "sleep", lambda _seconds: None)
        func.draw_line_break()
        captured = capsys.readouterr()
        assert "-" * 71 in captured.out


class TestFetchPage:
    def test_builds_word_url_and_returns_soup(self, monkeypatch):
        captured_urls = []

        class FakeResponse:
            text = SINGLE_DEFINITION_HTML
            content = SINGLE_DEFINITION_HTML.encode()

            def raise_for_status(self):
                return None

        def fake_get(url, timeout, **_kwargs):
            captured_urls.append(url)
            assert timeout == func.REQUEST_TIMEOUT
            return FakeResponse()

        monkeypatch.setattr(requests, "get", fake_get)

        text, soup = func.fetch_page("ephemeral")

        assert captured_urls == [f"{func.DICTIONARY_URL}/ephemeral"]
        assert text == SINGLE_DEFINITION_HTML
        assert isinstance(soup, BeautifulSoup)

    def test_url_encodes_words_with_spaces_or_special_characters(self, monkeypatch):
        """Regression test: the original f-string interpolated the word
        directly into the URL path, producing a malformed request for any
        multi-word entry (e.g. "ice cream") or word containing characters
        that need percent-encoding (e.g. "café")."""
        captured_urls = []

        class FakeResponse:
            text = SINGLE_DEFINITION_HTML
            content = SINGLE_DEFINITION_HTML.encode()

            def raise_for_status(self):
                return None

        monkeypatch.setattr(
            requests,
            "get",
            lambda url, timeout, **_kw: captured_urls.append(url) or FakeResponse(),
        )

        func.fetch_page("ice cream")

        assert captured_urls == [f"{func.DICTIONARY_URL}/ice%20cream"]

    def test_propagates_request_exceptions(self, monkeypatch):
        def fake_get(url, timeout, **_kwargs):
            raise requests.exceptions.ConnectionError("boom")

        monkeypatch.setattr(requests, "get", fake_get)

        with pytest.raises(requests.exceptions.ConnectionError):
            func.fetch_page("word")

    def test_raises_on_http_error_status(self, monkeypatch):
        class FakeResponse:
            def raise_for_status(self):
                raise requests.exceptions.HTTPError("404")

        monkeypatch.setattr(requests, "get", lambda url, timeout, **_kw: FakeResponse())

        with pytest.raises(requests.exceptions.HTTPError):
            func.fetch_page("word")


class TestWordExists:
    def test_true_for_valid_word_page(self):
        assert func.word_exists(SINGLE_DEFINITION_HTML) is True

    def test_false_when_not_found_message_present(self):
        text = "Sorry, 'asdf' isn't in the dictionary."
        assert func.word_exists(text) is False


class TestFindAllDefinitions:
    def test_single_definition(self):
        soup = BeautifulSoup(SINGLE_DEFINITION_HTML, "html.parser")
        assert func.find_all_definitions(soup) == [": a fleeting or short-lived thing"]

    def test_multiple_definitions(self):
        soup = BeautifulSoup(MULTI_DEFINITION_HTML, "html.parser")
        assert func.find_all_definitions(soup) == [
            ": first sense",
            "second sense (no leading colon)",
        ]

    def test_no_definitions_returns_empty_list(self):
        soup = BeautifulSoup(NO_DEFINITION_HTML, "html.parser")
        assert func.find_all_definitions(soup) == []

    def test_not_fooled_by_dttext_substring_elsewhere_on_page(self):
        """Regression test: the original implementation counted substring
        occurrences of "dtText" in the raw HTML, which could be thrown off
        by unrelated occurrences (e.g. inside inline <script> JSON)."""
        html = (
            "<html><body>"
            '<script>var x = "dtText appears here too";</script>'
            '<span class="dtText">: only real definition</span>'
            "</body></html>"
        )
        soup = BeautifulSoup(html, "html.parser")
        assert func.find_all_definitions(soup) == [": only real definition"]


class TestFormatDefinitions:
    def test_empty_list(self):
        assert func.format_definitions([]) == ": NO DEFINITION FOUND!"

    def test_single_definition_printed_as_is(self):
        assert func.format_definitions([": a thing"]) == ": a thing"

    def test_multiple_definitions_are_numbered(self):
        result = func.format_definitions([": first", "second"])
        assert result == "Entry 1: first\nEntry 2: second"


class TestExtractMp3Url:
    def test_extracts_url(self):
        text = '..."contentURL":"https://example.com/word.mp3","other":1...'
        assert func.extract_mp3_url(text) == "https://example.com/word.mp3"

    def test_tolerates_whitespace_around_colon(self):
        text = '"contentURL"  :   "https://example.com/word.mp3"'
        assert func.extract_mp3_url(text) == "https://example.com/word.mp3"

    def test_raises_value_error_when_absent(self):
        with pytest.raises(ValueError):
            func.extract_mp3_url("no audio field here")


# --------------------------------------------------------------------------- #
# Helpers shared by the tests below
# --------------------------------------------------------------------------- #

ENTRY_HTML = """
<html><head><script type="application/ld+json">
{"@type": "AudioObject", "contentURL": "https://media.example.com/word.mp3"}
</script></head><body>
  <span class="dtText">
      : the first   sense
  </span>
  <span class="dtText">: </span>
  <span class="dtText">second sense</span>
</body></html>
"""


def make_http_error(status_code: int) -> requests.exceptions.HTTPError:
    response = requests.Response()
    response.status_code = status_code
    return requests.exceptions.HTTPError(f"{status_code} error", response=response)


def make_fetcher(html: str):
    return lambda word: (html, BeautifulSoup(html, "html.parser"))


class FakeCache:
    """A dict-backed stand-in for page_cache.HtmlCache that records calls."""

    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self.store = dict(initial or {})
        self.gets: list[str] = []
        self.sets: list[tuple[str, str]] = []

    def get(self, word: str) -> str | None:
        self.gets.append(word)
        return self.store.get(word)

    def set(self, word: str, html: str) -> None:
        self.sets.append((word, html))
        self.store[word] = html


class FakePage:
    text = SINGLE_DEFINITION_HTML
    content = SINGLE_DEFINITION_HTML.encode()

    def raise_for_status(self):
        return None


class TestFetchPageCaching:
    def test_cache_hit_skips_the_network(self, monkeypatch):
        monkeypatch.setattr(
            requests, "get", lambda *a, **k: pytest.fail("network was used")
        )
        cache = FakeCache({"word": SINGLE_DEFINITION_HTML})

        text, soup = func.fetch_page("word", cache=cache)

        assert text == SINGLE_DEFINITION_HTML
        assert func.find_all_definitions(soup) == [": a fleeting or short-lived thing"]

    def test_cache_miss_fetches_and_then_stores_the_page(self, monkeypatch):
        monkeypatch.setattr(requests, "get", lambda url, timeout, **_kw: FakePage())
        cache = FakeCache()

        func.fetch_page("word", cache=cache)

        assert cache.sets == [("word", SINGLE_DEFINITION_HTML)]

    def test_failed_requests_are_not_cached(self, monkeypatch):
        def fake_get(url, timeout, **_kwargs):
            raise requests.exceptions.ConnectionError("boom")

        monkeypatch.setattr(requests, "get", fake_get)
        cache = FakeCache()

        with pytest.raises(requests.exceptions.ConnectionError):
            func.fetch_page("word", cache=cache)

        assert cache.sets == []

    def test_http_error_pages_are_not_cached(self, monkeypatch):
        class ErrorPage(FakePage):
            def raise_for_status(self):
                raise make_http_error(404)

        monkeypatch.setattr(requests, "get", lambda url, timeout, **_kw: ErrorPage())
        cache = FakeCache()

        with pytest.raises(requests.exceptions.HTTPError):
            func.fetch_page("nope", cache=cache)

        assert cache.sets == []

    def test_slashes_in_a_word_are_percent_encoded(self, monkeypatch):
        """Regression test: quote() leaves "/" alone by default, which let a
        word add path segments (e.g. "a/../word-of-the-day")."""
        urls = []
        monkeypatch.setattr(
            requests, "get", lambda url, timeout, **_kw: urls.append(url) or FakePage()
        )

        func.fetch_page("a/../word-of-the-day")

        assert urls == [f"{func.DICTIONARY_URL}/a%2F..%2Fword-of-the-day"]


class TestRateLimiter:
    class FakeTime:
        def __init__(self):
            self.now = 100.0
            self.sleeps: list[float] = []

        def clock(self):
            return self.now

        def pause(self, seconds):
            self.sleeps.append(seconds)
            self.now += seconds

    def make(self, interval, fake):
        return func.RateLimiter(interval, clock=fake.clock, pause=fake.pause)

    def test_the_first_request_never_waits(self):
        fake = self.FakeTime()
        self.make(5, fake).wait()
        assert fake.sleeps == []

    def test_waits_out_the_rest_of_the_interval(self):
        fake = self.FakeTime()
        limiter = self.make(1.0, fake)
        limiter.wait()
        fake.now += 0.25
        limiter.wait()
        assert fake.sleeps == [pytest.approx(0.75)]

    def test_does_not_wait_when_the_interval_has_already_passed(self):
        fake = self.FakeTime()
        limiter = self.make(1.0, fake)
        limiter.wait()
        fake.now += 2
        limiter.wait()
        assert fake.sleeps == []

    @pytest.mark.parametrize("interval", [0, -3])
    def test_zero_or_negative_intervals_disable_throttling(self, interval):
        fake = self.FakeTime()
        limiter = self.make(interval, fake)
        limiter.wait()
        limiter.wait()
        assert fake.sleeps == []

    def test_fetch_page_waits_before_a_network_request_but_not_for_a_cache_hit(
        self, monkeypatch
    ):
        monkeypatch.setattr(requests, "get", lambda url, timeout, **_kw: FakePage())
        fake = self.FakeTime()
        limiter = self.make(1.0, fake)
        cache = FakeCache({"cached": SINGLE_DEFINITION_HTML})

        func.fetch_page("cached", cache=cache, limiter=limiter)
        func.fetch_page("cached", cache=cache, limiter=limiter)
        func.fetch_page("fresh", cache=cache, limiter=limiter)  # 1st real request
        func.fetch_page("other", cache=cache, limiter=limiter)  # 2nd: must wait

        assert fake.sleeps == [pytest.approx(1.0)]


class TestFormatDefinitionsColonHandling:
    def test_colon_inside_an_unprefixed_definition_does_not_swallow_the_separator(
        self,
    ):
        """Regression test: the old check looked for ": " anywhere in the text,
        producing "Entry 2second sense: ..." instead of "Entry 2: second ..."."""
        result = func.format_definitions([": first", "second sense: with a colon"])
        assert result == "Entry 1: first\nEntry 2: second sense: with a colon"


class TestExtractMp3UrlSecurity:
    @pytest.mark.parametrize(
        "url",
        ["http://example.com/a.mp3", "file:///etc/passwd", "ftp://example.com/a.mp3"],
    )
    def test_rejects_urls_that_are_not_https(self, url):
        with pytest.raises(ValueError, match="HTTPS"):
            func.extract_mp3_url(f'"contentURL":"{url}"')


class TestIsNotFoundError:
    def test_true_for_http_404(self):
        assert func.is_not_found_error(make_http_error(404)) is True

    @pytest.mark.parametrize("status", [403, 500, 503])
    def test_false_for_other_http_errors(self, status):
        assert func.is_not_found_error(make_http_error(status)) is False

    def test_false_for_errors_without_a_response(self):
        assert func.is_not_found_error(requests.exceptions.Timeout("slow")) is False
        assert func.is_not_found_error(requests.exceptions.HTTPError("x")) is False


class TestNormalizeWord:
    def test_collapses_whitespace(self):
        assert func.normalize_word("  ice \t cream\n") == "ice cream"

    def test_keeps_case_and_unicode(self):
        assert func.normalize_word("Café") == "Café"

    @pytest.mark.parametrize("raw", ["", "   ", "\n\t"])
    def test_rejects_empty_input(self, raw):
        with pytest.raises(ValueError, match="empty"):
            func.normalize_word(raw)

    def test_rejects_overlong_input(self):
        with pytest.raises(ValueError, match="longer than"):
            func.normalize_word("a" * (func.MAX_WORD_LENGTH + 1))

    def test_accepts_the_maximum_length(self):
        assert func.normalize_word("a" * func.MAX_WORD_LENGTH)

    @pytest.mark.parametrize("raw", ["bad\x00word", "esc\x1b[31m", "bom\ufeffword"])
    def test_rejects_control_characters(self, raw):
        with pytest.raises(ValueError, match="control characters"):
            func.normalize_word(raw)


class TestUniqueWords:
    def test_keeps_first_spelling_and_order(self):
        assert func.unique_words(["b", "A", "a", "B", "c"]) == ["b", "A", "c"]

    def test_empty(self):
        assert func.unique_words([]) == []


class TestParseWordList:
    def test_one_word_per_line(self):
        assert func.parse_word_list("alpha\nbeta\n") == ["alpha", "beta"]

    def test_ignores_blank_lines_and_comments(self):
        text = "# my words\n\nalpha\n   \n  # indented comment\nbeta"
        assert func.parse_word_list(text) == ["alpha", "beta"]

    def test_phrases_are_kept_whole(self):
        assert func.parse_word_list("ice cream\n") == ["ice cream"]

    def test_drops_case_insensitive_duplicates(self):
        assert func.parse_word_list("Alpha\nalpha\nbeta") == ["Alpha", "beta"]

    def test_handles_windows_line_endings(self):
        assert func.parse_word_list("alpha\r\nbeta\r\n") == ["alpha", "beta"]

    def test_empty_file_yields_no_words(self):
        assert func.parse_word_list("") == []

    def test_an_invalid_line_is_reported_with_its_number(self):
        with pytest.raises(ValueError, match="line 3"):
            func.parse_word_list("alpha\n\nbad\x00word\n")


class TestCleanDefinition:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (": a thing", "a thing"),
            ("\n   : spaced   out\n", "spaced out"),
            ("no marker", "no marker"),
            ("inner: colon stays", "inner: colon stays"),
            (":", ""),
        ],
    )
    def test_cleans(self, raw, expected):
        assert func.clean_definition(raw) == expected


class TestLookupWord:
    def test_parses_definitions_and_audio(self):
        entry = func.lookup_word("word", fetch=make_fetcher(ENTRY_HTML))

        assert entry == func.Entry(
            word="word",
            definitions=("the first sense", "second sense"),
            audio_url="https://media.example.com/word.mp3",
        )

    def test_definitions_that_are_only_a_marker_are_dropped(self):
        entry = func.lookup_word("word", fetch=make_fetcher(ENTRY_HTML))
        assert "" not in entry.definitions

    def test_audio_is_none_when_the_page_has_no_recording(self):
        entry = func.lookup_word("word", fetch=make_fetcher(SINGLE_DEFINITION_HTML))
        assert entry.audio_url is None

    def test_not_found_message_on_a_200_page(self):
        html = "<html>Sorry, that word isn't in the dictionary.</html>"
        with pytest.raises(func.WordNotFoundError):
            func.lookup_word("asdf", fetch=make_fetcher(html))

    def test_http_404_means_not_found(self):
        def fetch(word):
            raise make_http_error(404)

        with pytest.raises(func.WordNotFoundError) as info:
            func.lookup_word("asdf", fetch=fetch)
        assert isinstance(info.value.__cause__, requests.exceptions.HTTPError)

    def test_other_http_errors_propagate(self):
        def fetch(word):
            raise make_http_error(503)

        with pytest.raises(requests.exceptions.HTTPError):
            func.lookup_word("word", fetch=fetch)

    def test_network_errors_propagate(self):
        def fetch(word):
            raise requests.exceptions.Timeout("slow")

        with pytest.raises(requests.exceptions.Timeout):
            func.lookup_word("word", fetch=fetch)

    def test_defaults_to_fetch_page(self, monkeypatch):
        monkeypatch.setattr(func, "fetch_page", make_fetcher(ENTRY_HTML))
        assert func.lookup_word("word").word == "word"

    def test_word_not_found_error_is_a_lookup_error(self):
        assert issubclass(func.WordNotFoundError, LookupError)


class FakeStream:
    """A streaming requests.Response usable as a context manager."""

    def __init__(self, chunks, status=200):
        self.chunks = chunks
        self.status = status
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
        return False

    def close(self):
        self.closed = True

    def raise_for_status(self):
        if self.status >= 400:
            raise make_http_error(self.status)

    def iter_content(self, chunk_size):
        yield from self.chunks


class TestDownloadAudio:
    def test_writes_the_downloaded_bytes(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            requests, "get", lambda url, **kw: FakeStream([b"ab", b"cd"])
        )
        target = tmp_path / "clip.mp3"

        func.download_audio("https://media.example.com/a.mp3", target)

        assert target.read_bytes() == b"abcd"

    def test_uses_a_timeout_and_streams(self, monkeypatch, tmp_path):
        seen = {}

        def fake_get(url, **kwargs):
            seen.update(kwargs)
            return FakeStream([b"x"])

        monkeypatch.setattr(requests, "get", fake_get)

        func.download_audio("https://media.example.com/a.mp3", tmp_path / "c.mp3")

        assert seen["timeout"] == func.REQUEST_TIMEOUT
        assert seen["stream"] is True

    @pytest.mark.parametrize("url", ["http://x/a.mp3", "file:///etc/passwd", ""])
    def test_refuses_non_https_urls_without_any_request(
        self, monkeypatch, tmp_path, url
    ):
        monkeypatch.setattr(
            requests, "get", lambda *a, **k: pytest.fail("network was used")
        )
        target = tmp_path / "clip.mp3"

        with pytest.raises(ValueError, match="HTTPS"):
            func.download_audio(url, target)

        assert not target.exists()

    def test_http_errors_leave_no_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            requests, "get", lambda url, **kw: FakeStream([], status=404)
        )
        target = tmp_path / "clip.mp3"

        with pytest.raises(requests.exceptions.HTTPError):
            func.download_audio("https://x/a.mp3", target)

        assert not target.exists()

    def test_oversized_downloads_are_aborted_and_removed(self, monkeypatch, tmp_path):
        monkeypatch.setattr(func, "MAX_AUDIO_BYTES", 10)
        monkeypatch.setattr(
            requests, "get", lambda url, **kw: FakeStream([b"x" * 6, b"x" * 6])
        )
        target = tmp_path / "clip.mp3"

        with pytest.raises(ValueError, match="unexpectedly large"):
            func.download_audio("https://x/a.mp3", target)

        assert not target.exists()

    def test_accepts_a_string_destination(self, monkeypatch, tmp_path):
        monkeypatch.setattr(requests, "get", lambda url, **kw: FakeStream([b"x"]))
        target = tmp_path / "clip.mp3"

        func.download_audio("https://x/a.mp3", str(target))

        assert Path(target).read_bytes() == b"x"


class TestRequestHeaders:
    """Regression tests: the stock python-requests User-Agent gets HTTP 403."""

    def test_default_user_agent_is_not_the_stock_python_requests_one(self, monkeypatch):
        monkeypatch.delenv(func.USER_AGENT_ENV_VAR, raising=False)

        agent = func.request_headers()["User-Agent"]

        assert agent == func.DEFAULT_USER_AGENT
        assert "python-requests" not in agent

    def test_environment_variable_overrides_it(self, monkeypatch):
        monkeypatch.setenv(func.USER_AGENT_ENV_VAR, "my-agent/2")
        assert func.request_headers()["User-Agent"] == "my-agent/2"

    def test_an_empty_environment_variable_falls_back_to_the_default(self, monkeypatch):
        monkeypatch.setenv(func.USER_AGENT_ENV_VAR, "")
        assert func.request_headers()["User-Agent"] == func.DEFAULT_USER_AGENT

    def test_fetch_page_sends_the_user_agent(self, monkeypatch):
        monkeypatch.delenv(func.USER_AGENT_ENV_VAR, raising=False)
        seen: dict = {}
        monkeypatch.setattr(
            requests, "get", lambda url, timeout, **kw: seen.update(kw) or FakePage()
        )

        func.fetch_page("word")

        assert seen["headers"]["User-Agent"] == func.DEFAULT_USER_AGENT

    def test_fetch_page_prefers_explicitly_passed_headers(self, monkeypatch):
        seen: dict = {}
        monkeypatch.setattr(
            requests, "get", lambda url, timeout, **kw: seen.update(kw) or FakePage()
        )

        func.fetch_page("word", headers={"User-Agent": "explicit/1"})

        assert seen["headers"] == {"User-Agent": "explicit/1"}

    def test_download_audio_sends_the_user_agent(self, monkeypatch, tmp_path):
        monkeypatch.delenv(func.USER_AGENT_ENV_VAR, raising=False)
        seen: dict = {}

        def fake_get(url, **kwargs):
            seen.update(kwargs)
            return FakeStream([b"x"])

        monkeypatch.setattr(requests, "get", fake_get)

        func.download_audio("https://x/a.mp3", tmp_path / "clip.mp3")

        assert seen["headers"]["User-Agent"] == func.DEFAULT_USER_AGENT


class TestDescribeNetworkError:
    def test_plain_errors_are_passed_through(self):
        message = func.describe_network_error(requests.exceptions.Timeout("slow"))
        assert message == "slow"

    def test_http_403_gets_a_hint(self):
        message = func.describe_network_error(make_http_error(403))
        assert "403 error" in message
        assert "refused the request" in message

    def test_other_statuses_get_no_hint(self):
        message = func.describe_network_error(make_http_error(500))
        assert "Hint" not in message


class TestRateLimiterThreads:
    def test_simultaneous_callers_are_queued_not_released_together(self):
        """The web interface calls the limiter from one thread per visitor."""
        interval = 0.05
        limiter = func.RateLimiter(interval)
        start = threading.Barrier(6)
        finished: list[float] = []

        def visit() -> None:
            start.wait()
            limiter.wait()
            finished.append(time.monotonic())

        threads = [threading.Thread(target=visit) for _ in range(6)]
        began = time.monotonic()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        # Five of the six had to wait for their turn, one interval apiece.
        assert max(finished) - began >= 5 * interval * 0.9
