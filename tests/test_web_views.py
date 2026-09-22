"""Unit tests for web_views.py.

Definitions come from a scraped website, so the main job of these tests is to
show that untrusted text can never become markup.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

import pytest

import functions as func
import web_views as views
from word_history import HistoryRecord

HOSTILE = "<script>alert(1)</script> \"quoted\" 'single' & more"
AUDIO = "https://media.merriam-webster.com/audio/prons/en/us/mp3/t/test0001.mp3"
VOID = {"meta", "link", "input", "br", "hr", "img", "source"}


def make_entry(
    word: str = "test",
    definitions: tuple[str, ...] = ("first", "second"),
    audio_url: str | None = None,
) -> func.Entry:
    return func.Entry(word=word, definitions=definitions, audio_url=audio_url)


class TagChecker(HTMLParser):
    """Records tags that are opened but never closed, or closed out of order."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.problems: list[str] = []

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack[-1] != tag:
            self.problems.append(f"unexpected </{tag}> (open: {self.stack})")
        else:
            self.stack.pop()


def assert_well_formed(page: str) -> None:
    checker = TagChecker()
    checker.feed(page)
    assert checker.problems == []
    assert checker.stack == []
    assert page.startswith("<!doctype html>")


def every_page() -> list[str]:
    entry = make_entry(audio_url=AUDIO)
    record = HistoryRecord("test", "2026-09-21T10:00:00+00:00", found=True)
    return [
        views.render_home(["one", "two"], history_enabled=True),
        views.render_home([], history_enabled=False),
        views.render_entry(entry),
        views.render_entry(make_entry(definitions=())),
        views.render_message("Not found", "Line one.\nLine two.", word="x"),
        views.render_batch_form(),
        views.render_batch_form("a\nb", "md", error="Enter at least one word."),
        views.render_batch_results(
            [entry], [("zzz", "not found")], text="a", fmt="json"
        ),
        views.render_history([record]),
        views.render_history([]),
        views.render_history(None),
    ]


class TestWellFormed:
    @pytest.mark.parametrize("page", every_page())
    def test_every_page_is_balanced_html(self, page):
        assert_well_formed(page)

    @pytest.mark.parametrize("page", every_page())
    def test_no_page_needs_javascript(self, page):
        assert "<script" not in page.lower()
        assert re.search(r"\son[a-z]+\s*=", page, re.IGNORECASE) is None
        assert "javascript:" not in page.lower()


class TestEscaping:
    def test_definitions_cannot_inject_markup(self):
        page = views.render_entry(make_entry(definitions=(HOSTILE,)))

        assert "<script>" not in page
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
        assert "&quot;quoted&quot;" in page
        assert "&amp; more" in page

    def test_the_word_is_escaped_in_the_title_heading_and_search_box(self):
        page = views.render_entry(make_entry(word=HOSTILE))

        assert "<script>" not in page
        assert page.count("&lt;script&gt;") >= 3  # title, search box, heading

    def test_a_quote_cannot_break_out_of_the_search_box_attribute(self):
        page = views.render_entry(make_entry(word='x" autofocus onfocus="alert(1)'))
        assert 'value="x&quot; autofocus onfocus=&quot;alert(1)"' in page

    def test_messages_are_escaped_and_lines_are_kept_apart(self):
        page = views.render_message("<b>Title</b>", "<i>one</i>\ntwo", word=HOSTILE)

        assert "<b>Title</b>" not in page
        assert "&lt;i&gt;one&lt;/i&gt;<br>two" in page
        assert "<script>" not in page

    def test_batch_failures_and_the_text_box_are_escaped(self):
        text = "</textarea><script>alert(1)</script>"
        page = views.render_batch_results(
            [], [(HOSTILE, "<b>reason</b>")], text=text, fmt="text"
        )

        assert "<script>" not in page
        assert "</textarea><script>" not in page
        assert "&lt;b&gt;reason&lt;/b&gt;" in page

    def test_the_batch_error_is_escaped(self):
        page = views.render_batch_form(error="<script>x</script>")
        assert "<script>" not in page

    def test_history_rows_are_escaped(self):
        record = HistoryRecord(HOSTILE, "<b>when</b>", found=True)
        page = views.render_history([record])

        assert "<script>" not in page
        assert "<b>when</b>" not in page

    def test_a_format_value_cannot_break_the_select(self):
        page = views.render_batch_form(fmt='"><script>alert(1)</script>')
        assert "<script>" not in page

    def test_audio_urls_are_escaped_in_the_attribute(self):
        url = 'https://media.merriam-webster.com/x" onerror="alert(1)'
        page = views.render_entry(make_entry(audio_url=url))

        assert 'src="https://media.merriam-webster.com/x&quot; onerror=&quot;' in page
        assert '" onerror="' not in page


class TestLinks:
    def test_word_urls_are_percent_encoded(self):
        assert views.word_url("ice cream") == "/?word=ice%20cream"
        assert views.word_url("a/b&c=d") == "/?word=a%2Fb%26c%3Dd"

    def test_export_urls_carry_the_word_and_format(self):
        assert (
            views.export_url("ice cream", "md") == "/export?word=ice%20cream&format=md"
        )

    def test_history_links_use_encoded_words(self):
        record = HistoryRecord("a&b", "t", found=True)
        assert 'href="/?word=a%26b"' in views.render_history([record])

    def test_recent_words_link_to_their_pages(self):
        page = views.render_home(["ice cream"], history_enabled=True)
        assert '<a href="/?word=ice%20cream">ice cream</a>' in page


class TestAudioAllowlist:
    def test_the_expected_media_host_gets_a_player(self):
        page = views.render_entry(make_entry(audio_url=AUDIO))
        assert f'<audio controls preload="none" src="{AUDIO}"></audio>' in page

    @pytest.mark.parametrize(
        "url",
        [
            None,
            "http://media.merriam-webster.com/a.mp3",
            "https://evil.example/a.mp3",
            "https://media.merriam-webster.com.evil.example/a.mp3",
            "https://media.merriam-webster.com@evil.example/a.mp3",
            "https://media.merriam-webster.com",
            "javascript:alert(1)",
            "data:audio/mp3;base64,AAAA",
            "//media.merriam-webster.com/a.mp3",
        ],
    )
    def test_anything_else_gets_no_player(self, url):
        entry = make_entry(audio_url=url)

        assert views.audio_src(entry) is None
        assert "<audio" not in views.render_entry(entry)


class TestContent:
    def test_the_home_page_has_a_search_form_that_uses_get(self):
        page = views.render_home([], history_enabled=True)

        assert 'action="/" method="get"' in page
        assert 'name="word"' in page
        assert f'maxlength="{func.MAX_WORD_LENGTH}"' in page

    def test_the_home_page_says_what_to_expect_without_recent_words(self):
        assert "will be listed here" in views.render_home([], history_enabled=True)
        assert "turned off" in views.render_home([], history_enabled=False)

    def test_the_current_page_is_marked_in_the_navigation(self):
        page = views.render_history([])
        assert '<a href="/history" aria-current="page">History</a>' in page
        assert page.count("aria-current") == 1

    def test_definitions_are_a_numbered_list_in_order(self):
        page = views.render_entry(make_entry(definitions=("one", "two", "three")))
        assert (
            '<ol class="definitions"><li>one</li><li>two</li><li>three</li></ol>'
            in page
        )

    def test_an_entry_without_definitions_says_so(self):
        assert "No definition found." in views.render_entry(make_entry(definitions=()))

    def test_every_export_format_has_a_download_link(self):
        page = views.render_entry(make_entry())
        for fmt in ("text", "md", "json"):
            assert f'href="/export?word=test&amp;format={fmt}"' in page

    def test_messages_are_announced_as_alerts(self):
        assert 'role="alert"' in views.render_message("Oops", "text")

    def test_the_batch_form_has_lookup_and_download_buttons(self):
        page = views.render_batch_form("a\nb", "md")

        assert '<textarea id="words" name="words"' in page
        assert 'formaction="/batch"' in page
        assert 'formaction="/export"' in page
        assert '<option value="md" selected>.md</option>' in page
        assert ">a\nb</textarea>" in page

    def test_batch_results_count_and_list_failures(self):
        page = views.render_batch_results(
            [make_entry("one"), make_entry("two")],
            [("three", "not found")],
            text="one\ntwo\nthree",
            fmt="text",
        )

        assert "Found 2 of 3." in page
        assert "<strong>three</strong>: not found" in page
        assert "<h2>one</h2>" in page

    def test_history_rows_show_time_word_and_result(self):
        rows = [
            HistoryRecord("a", "2026-09-21T10:00:00+00:00", found=True),
            HistoryRecord("b", "2026-09-21T09:00:00+00:00", found=False),
        ]
        page = views.render_history(rows)

        assert "2026-09-21T10:00:00+00:00" in page
        assert ">found<" in page
        assert ">not found<" in page

    def test_empty_and_disabled_history_have_their_own_messages(self):
        assert "Nothing has been looked up yet." in views.render_history([])
        assert "turned off" in views.render_history(None)

    def test_pages_link_the_stylesheet_and_icon_from_the_same_origin(self):
        page = views.render_home([], history_enabled=True)

        assert '<link rel="stylesheet" href="/static/style.css">' in page
        assert 'href="/static/favicon.svg"' in page
