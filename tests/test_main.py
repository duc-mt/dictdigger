"""Unit tests for main.py.

All network access, audio playback, and file downloads are mocked/monkey-
patched so these tests run instantly and require no external services.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
import requests
from bs4 import BeautifulSoup

import main
from word_history import WordHistory


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
        monkeypatch.setattr(
            main.func, "extract_mp3_url", lambda text: "https://x/a.mp3"
        )
        monkeypatch.setattr("builtins.input", make_input(["n"]))

        download_calls = []
        monkeypatch.setattr(
            main.func,
            "download_audio",
            lambda url, destination: download_calls.append(url),
        )

        main.offer_pronunciation("some html")

        assert download_calls == []


def make_http_error(status_code: int) -> requests.exceptions.HTTPError:
    """Build an HTTPError carrying a real Response, like raise_for_status()."""
    response = requests.Response()
    response.status_code = status_code
    return requests.exceptions.HTTPError(f"{status_code} error", response=response)


class TestLookUpWordExtras:
    def test_http_404_is_reported_as_unknown_word_not_network_error(
        self, monkeypatch, capsys
    ):
        monkeypatch.setattr("builtins.input", make_input(["asdf", "hello"]))

        def fake_fetch(word):
            if word == "asdf":
                raise make_http_error(404)
            return f"page for {word}", "soup"

        monkeypatch.setattr(main.func, "fetch_page", fake_fetch)
        monkeypatch.setattr(main.func, "word_exists", lambda text: True)

        word, _text, _soup = main.look_up_word()

        out = capsys.readouterr().out
        assert word == "hello"
        assert "isn't in the dictionary" in out
        assert "Network error" not in out

    def test_other_http_errors_are_still_network_errors(self, monkeypatch, capsys):
        monkeypatch.setattr("builtins.input", make_input(["boom", "hello"]))

        def fake_fetch(word):
            if word == "boom":
                raise make_http_error(503)
            return f"page for {word}", "soup"

        monkeypatch.setattr(main.func, "fetch_page", fake_fetch)
        monkeypatch.setattr(main.func, "word_exists", lambda text: True)

        main.look_up_word()

        assert "Network error" in capsys.readouterr().out

    def test_uses_the_injected_fetch_instead_of_fetch_page(self, monkeypatch):
        monkeypatch.setattr("builtins.input", make_input(["hello"]))
        monkeypatch.setattr(main.func, "word_exists", lambda text: True)

        def explode(word):
            raise AssertionError("fetch_page must not be used")

        monkeypatch.setattr(main.func, "fetch_page", explode)

        word, text, _soup = main.look_up_word(fetch=lambda w: (f"cached {w}", "soup"))

        assert (word, text) == ("hello", "cached hello")

    def test_records_every_attempt_in_the_history(self, monkeypatch, tmp_path):
        monkeypatch.setattr("builtins.input", make_input(["asdf", "hello"]))
        monkeypatch.setattr(main.func, "word_exists", lambda text: "hello" in text)
        history = WordHistory(tmp_path / "word_history.json")

        main.look_up_word(fetch=lambda w: (f"page for {w}", "soup"), history=history)

        assert [(r.word, r.found) for r in history.read()] == [
            ("asdf", False),
            ("hello", True),
        ]


class TestOfferPronunciationExtras:
    def test_reports_download_failures_without_crashing(self, monkeypatch, capsys):
        monkeypatch.setattr(
            main.func, "extract_mp3_url", lambda text: "https://x/a.mp3"
        )
        monkeypatch.setattr("builtins.input", make_input(["y"]))

        def fail(url, destination):
            raise requests.exceptions.ConnectionError("offline")

        monkeypatch.setattr(main.func, "download_audio", fail)

        main.offer_pronunciation("some html")

        assert "Could not download" in capsys.readouterr().out

    def test_reports_missing_audio_device_without_crashing(self, monkeypatch, capsys):
        monkeypatch.setattr(
            main.func, "extract_mp3_url", lambda text: "https://x/a.mp3"
        )
        monkeypatch.setattr("builtins.input", make_input(["y"]))
        monkeypatch.setattr(main.func, "download_audio", lambda url, destination: None)

        class NoAudioMixer:
            @staticmethod
            def init():
                raise RuntimeError("No audio device")

        monkeypatch.setattr(main, "load_mixer", lambda: NoAudioMixer)

        main.offer_pronunciation("some html")

        assert "Could not start audio playback" in capsys.readouterr().out

    def test_plays_until_the_user_declines_a_replay(self, monkeypatch):
        monkeypatch.setattr(
            main.func, "extract_mp3_url", lambda text: "https://x/a.mp3"
        )
        monkeypatch.setattr("builtins.input", make_input(["y", "y", "n"]))
        monkeypatch.setattr(main.func, "download_audio", lambda url, destination: None)

        class FakeMixer:
            plays = 0
            quit_called = False

            class music:
                @staticmethod
                def load(path):
                    pass

                @staticmethod
                def play():
                    FakeMixer.plays += 1

            @staticmethod
            def init():
                pass

            @staticmethod
            def quit():
                FakeMixer.quit_called = True

        monkeypatch.setattr(main, "load_mixer", lambda: FakeMixer)

        main.offer_pronunciation("some html")

        assert FakeMixer.plays == 2
        assert FakeMixer.quit_called


class TestLoadMixer:
    def test_silences_the_pygame_banner(self, monkeypatch):
        """pygame prints a banner to stdout on import unless this is set."""
        pytest.importorskip("pygame")  # audio is optional (no wheel on 3.14 yet)
        monkeypatch.delenv("PYGAME_HIDE_SUPPORT_PROMPT", raising=False)
        main.load_mixer()
        assert os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] == "1"

    def test_importing_main_does_not_import_pygame(self):
        result = subprocess.run(
            [sys.executable, "-c", "import main, sys; print('pygame' in sys.modules)"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(main.__file__).parent,
        )
        assert result.stdout.strip() == "False"


class TestShowDefinition:
    def test_prints_the_upper_cased_word_and_its_definitions(self, capsys):
        soup = BeautifulSoup(
            '<span class="dtText">: a thing</span>'
            '<span class="dtText">: another</span>',
            "html.parser",
        )

        main.show_definition("word", soup)

        out = capsys.readouterr().out
        assert "-> Definition of WORD:" in out
        assert "Entry 1: a thing" in out
        assert "Entry 2: another" in out


class FakeMixer:
    """Records mixer calls; ``get_busy`` stays true for a few polls."""

    def __init__(self, busy_polls: int = 2, load_error: Exception | None = None):
        self.events: list[str] = []
        self.music = self  # so mixer.music.load(...) lands on this object
        self._busy_polls = busy_polls
        self._load_error = load_error

    def init(self):
        self.events.append("init")

    def load(self, path):
        if self._load_error:
            raise self._load_error
        self.events.append(f"load:{path}")

    def play(self):
        self.events.append("play")

    def get_busy(self):
        self._busy_polls -= 1
        return self._busy_polls >= 0

    def quit(self):
        self.events.append("quit")


class TestPlayAudio:
    def test_blocks_until_playback_finishes_then_shuts_the_mixer_down(
        self, monkeypatch
    ):
        naps: list[float] = []
        monkeypatch.setattr(main, "sleep", naps.append)
        mixer = FakeMixer(busy_polls=3)

        main.play_audio(Path("clip.mp3"), mixer=mixer)

        assert mixer.events == ["init", "load:clip.mp3", "play", "quit"]
        assert len(naps) == 3  # it polled while the clip was still playing

    def test_shuts_the_mixer_down_even_if_the_clip_cannot_be_loaded(self):
        mixer = FakeMixer(load_error=RuntimeError("bad mp3"))

        with pytest.raises(RuntimeError, match="bad mp3"):
            main.play_audio(Path("clip.mp3"), mixer=mixer)

        assert mixer.events[-1] == "quit"


class TestRunInteractive:
    def test_runs_the_whole_original_session_and_logs_the_lookup(
        self, monkeypatch, capsys, tmp_path
    ):
        html = '<html><span class="dtText">: a greeting</span></html>'
        monkeypatch.setattr(main.func, "draw_line_break", lambda: None)
        monkeypatch.setattr(main, "show_word_of_the_day", lambda: print("<wotd>"))
        monkeypatch.setattr(
            main, "offer_pronunciation", lambda text: print("<offer pronunciation>")
        )
        monkeypatch.setattr("builtins.input", make_input(["hello"]))
        history = WordHistory(tmp_path / "word_history.json")

        code = main.run_interactive(
            fetch=lambda word: (html, BeautifulSoup(html, "html.parser")),
            history=history,
        )

        out = capsys.readouterr().out
        assert code == 0
        order = [
            "Welcome to the Dictionary of Merriam-Webster",
            "<wotd>",
            "-> Definition of HELLO:",
            "a greeting",
            "<offer pronunciation>",
            "Thank you",
        ]
        assert [out.index(part) for part in order] == sorted(
            out.index(part) for part in order
        )
        assert [(r.word, r.found) for r in history.read()] == [("hello", True)]
