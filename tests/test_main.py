"""Unit tests for main.py.

All network access, audio playback, and file downloads are mocked/monkey-
patched so these tests run instantly and require no external services.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import requests

import main


def make_input(values: list[str]):
    """Return a fake `input()` that yields each value in turn."""
    iterator: Iterator[str] = iter(values)

    def fake_input(_prompt: str = "") -> str:
        return next(iterator)

    return fake_input


class TestPromptNonEmpty:
    def test_returns_first_non_empty_value(self, monkeypatch):
        monkeypatch.setattr("builtins.input", make_input(["hello"]))
        assert main.prompt_non_empty("Enter: ") == "hello"

    def test_reprompts_on_empty_input(self, monkeypatch, capsys):
        monkeypatch.setattr("builtins.input", make_input(["", "  ", "word"]))
        assert main.prompt_non_empty("Enter: ") == "word"
        assert "non-empty" in capsys.readouterr().out


class TestPromptYesNo:
    @pytest.mark.parametrize("answer", ["Y", "y", "N", "n", ""])
    def test_accepts_valid_answers(self, monkeypatch, answer):
        monkeypatch.setattr("builtins.input", make_input([answer]))
        assert main.prompt_yes_no("? ") == answer

    def test_reprompts_on_invalid_answer(self, monkeypatch, capsys):
        monkeypatch.setattr("builtins.input", make_input(["maybe", "Y"]))
        assert main.prompt_yes_no("? ") == "Y"
        assert "appropriate command" in capsys.readouterr().out


class TestShowWordOfTheDay:
    def test_prints_word_on_success(self, monkeypatch, capsys):
        monkeypatch.setattr(main.func, "fetch_page", lambda: ("text", "soup"))
        monkeypatch.setattr(main.func, "get_word_of_the_day", lambda soup: "ephemeral")
        main.show_word_of_the_day()
        assert "ephemeral" in capsys.readouterr().out

    def test_prints_friendly_message_on_network_error(self, monkeypatch, capsys):
        def raise_error():
            raise requests.exceptions.ConnectionError("no network")

        monkeypatch.setattr(main.func, "fetch_page", raise_error)
        main.show_word_of_the_day()  # must not raise
        assert "Could not retrieve" in capsys.readouterr().out


class TestLookUpWord:
    def test_returns_on_first_valid_word(self, monkeypatch):
        monkeypatch.setattr("builtins.input", make_input(["hello"]))
        monkeypatch.setattr(
            main.func, "fetch_page", lambda word: (f"page for {word}", "soup")
        )
        monkeypatch.setattr(main.func, "word_exists", lambda text: True)

        word, text, soup = main.look_up_word()

        assert word == "hello"
        assert text == "page for hello"

    def test_reprompts_after_word_not_found(self, monkeypatch, capsys):
        monkeypatch.setattr("builtins.input", make_input(["asdf", "hello"]))
        monkeypatch.setattr(
            main.func, "fetch_page", lambda word: (f"page for {word}", "soup")
        )
        monkeypatch.setattr(main.func, "word_exists", lambda text: "hello" in text)

        word, _text, _soup = main.look_up_word()

        assert word == "hello"
        assert "isn't in the dictionary" in capsys.readouterr().out

    def test_reprompts_after_network_error(self, monkeypatch, capsys):
        monkeypatch.setattr("builtins.input", make_input(["fail", "hello"]))
        calls = {"n": 0}

        def fake_fetch(word):
            calls["n"] += 1
            if word == "fail":
                raise requests.exceptions.Timeout("slow")
            return f"page for {word}", "soup"

        monkeypatch.setattr(main.func, "fetch_page", fake_fetch)
        monkeypatch.setattr(main.func, "word_exists", lambda text: True)

        word, _text, _soup = main.look_up_word()

        assert word == "hello"
        assert "Network error" in capsys.readouterr().out


class TestOfferPronunciation:
    def test_declines_gracefully_when_no_audio(self, monkeypatch, capsys):
        def raise_value_error(text):
            raise ValueError("no pre-recorded pronunciation is available for this word")

        monkeypatch.setattr(main.func, "extract_mp3_url", raise_value_error)
        main.offer_pronunciation("some html")
        assert "Sorry!" in capsys.readouterr().out

    def test_skips_download_when_user_declines(self, monkeypatch):
        monkeypatch.setattr(main.func, "extract_mp3_url", lambda text: "http://x/a.mp3")
        monkeypatch.setattr("builtins.input", make_input(["n"]))

        download_calls = []
        monkeypatch.setattr(
            main, "urlretrieve", lambda url, filename: download_calls.append(url)
        )

        main.offer_pronunciation("some html")

        assert download_calls == []
