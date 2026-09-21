"""Unit tests for functions.py.

Network access is always mocked - these tests never hit the real
Merriam-Webster website, so they are fast, deterministic, and safe to run
in CI.
"""

from __future__ import annotations

import pytest
import requests
from bs4 import BeautifulSoup

import functions as func

HOMEPAGE_HTML = """
<html><body>
  <a href="/other-link">skip me</a>
  <a href="/word-of-the-day">placeholder 1</a>
  <a href="/word-of-the-day">placeholder 2</a>
  <a href="/word-of-the-day">ephemeral</a>
</body></html>
"""

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

        def fake_get(url, timeout):
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
            lambda url, timeout: captured_urls.append(url) or FakeResponse(),
        )

        func.fetch_page("ice cream")

        assert captured_urls == [f"{func.DICTIONARY_URL}/ice%20cream"]

    def test_fetches_homepage_when_word_is_none(self, monkeypatch):
        captured_urls = []

        class FakeResponse:
            text = HOMEPAGE_HTML
            content = HOMEPAGE_HTML.encode()

            def raise_for_status(self):
                return None

        monkeypatch.setattr(
            requests,
            "get",
            lambda url, timeout: captured_urls.append(url) or FakeResponse(),
        )

        func.fetch_page()

        assert captured_urls == [func.DICTIONARY_URL]

    def test_propagates_request_exceptions(self, monkeypatch):
        def fake_get(url, timeout):
            raise requests.exceptions.ConnectionError("boom")

        monkeypatch.setattr(requests, "get", fake_get)

        with pytest.raises(requests.exceptions.ConnectionError):
            func.fetch_page("word")

    def test_raises_on_http_error_status(self, monkeypatch):
        class FakeResponse:
            def raise_for_status(self):
                raise requests.exceptions.HTTPError("404")

        monkeypatch.setattr(requests, "get", lambda url, timeout: FakeResponse())

        with pytest.raises(requests.exceptions.HTTPError):
            func.fetch_page("word")


class TestGetWordOfTheDay:
    def test_finds_the_fourth_matching_anchor(self):
        soup = BeautifulSoup(HOMEPAGE_HTML, "html.parser")
        assert func.get_word_of_the_day(soup) == "ephemeral"

    def test_raises_value_error_when_layout_changed(self):
        soup = BeautifulSoup("<html><body>nothing</body></html>", "html.parser")
        with pytest.raises(ValueError):
            func.get_word_of_the_day(soup)

    def test_raises_value_error_when_fewer_than_three_anchors(self):
        soup = BeautifulSoup('<a href="/word-of-the-day">only one</a>', "html.parser")
        with pytest.raises(ValueError):
            func.get_word_of_the_day(soup)


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
