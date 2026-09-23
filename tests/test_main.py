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
from curl_cffi import requests
from bs4 import BeautifulSoup

import functions as func
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


def make_entry(
    word: str = "hello",
    definitions: tuple[str, ...] = ("a greeting",),
    audio_url: str | None = None,
) -> func.Entry:
    return func.Entry(word=word, definitions=definitions, audio_url=audio_url)


def make_http_error(status_code: int) -> requests.exceptions.HTTPError:
    """Build an HTTPError carrying a real Response, like raise_for_status()."""
    response = requests.Response()
    response.status_code = status_code
    return requests.exceptions.HTTPError(f"{status_code} error", response=response)


class TestLookUpWord:
    def test_returns_the_entry_for_the_first_valid_word(self, monkeypatch):
        monkeypatch.setattr("builtins.input", make_input(["hello"]))

        entry = main.look_up_word(lookup=lambda word: make_entry(word))

        assert entry == make_entry("hello")

    def test_reprompts_after_word_not_found(self, monkeypatch, capsys):
        monkeypatch.setattr("builtins.input", make_input(["asdf", "hello"]))

        def lookup(word):
            if word == "asdf":
                raise func.WordNotFoundError(word)
            return make_entry(word)

        entry = main.look_up_word(lookup=lookup)

        assert entry.word == "hello"
        assert "isn't in the dictionary" in capsys.readouterr().out

    def test_reprompts_after_network_error(self, monkeypatch, capsys):
        monkeypatch.setattr("builtins.input", make_input(["fail", "hello"]))

        def lookup(word):
            if word == "fail":
                raise requests.exceptions.Timeout("slow")
            return make_entry(word)

        entry = main.look_up_word(lookup=lookup)

        assert entry.word == "hello"
        assert "Network error" in capsys.readouterr().out

    def test_http_404_from_the_website_is_an_unknown_word_not_a_network_error(
        self, monkeypatch, capsys
    ):
        """functions.lookup_word turns a 404 into WordNotFoundError."""
        monkeypatch.setattr("builtins.input", make_input(["asdf", "hello"]))

        def fetch(word):
            if word == "asdf":
                raise make_http_error(404)
            html = "<span class='dtText'>: hi</span>"
            return html, BeautifulSoup(html, "html.parser")

        monkeypatch.setattr(main.func, "fetch_page", fetch)

        main.look_up_word()  # default lookup = the scraper

        out = capsys.readouterr().out
        assert "isn't in the dictionary" in out
        assert "Network error" not in out

    def test_defaults_to_the_scraper(self, monkeypatch):
        monkeypatch.setattr("builtins.input", make_input(["hello"]))
        monkeypatch.setattr(main.func, "lookup_word", lambda word: make_entry(word))

        assert main.look_up_word().word == "hello"

    def test_records_every_attempt_in_the_history(self, monkeypatch, tmp_path):
        monkeypatch.setattr("builtins.input", make_input(["asdf", "hello"]))
        history = WordHistory(tmp_path / "word_history.json")

        def lookup(word):
            if word == "asdf":
                raise func.WordNotFoundError(word)
            return make_entry(word)

        main.look_up_word(lookup=lookup, history=history)

        assert [(r.word, r.found) for r in history.read()] == [
            ("asdf", False),
            ("hello", True),
        ]

    def test_network_failures_are_not_recorded(self, monkeypatch, tmp_path):
        monkeypatch.setattr("builtins.input", make_input(["fail", "hello"]))
        history = WordHistory(tmp_path / "word_history.json")

        def lookup(word):
            if word == "fail":
                raise requests.exceptions.Timeout("slow")
            return make_entry(word)

        main.look_up_word(lookup=lookup, history=history)

        assert [r.word for r in history.read()] == ["hello"]


class TestOfferPronunciation:
    def test_declines_gracefully_when_no_audio(self, capsys):
        main.offer_pronunciation(make_entry(audio_url=None))

        assert "Sorry!" in capsys.readouterr().out

    def test_skips_download_when_user_declines(self, monkeypatch):
        monkeypatch.setattr("builtins.input", make_input(["n"]))
        download_calls = []
        monkeypatch.setattr(
            main.func,
            "download_audio",
            lambda url, destination: download_calls.append(url),
        )

        main.offer_pronunciation(make_entry(audio_url="https://x/a.mp3"))

        assert download_calls == []

    def test_reports_download_failures_without_crashing(self, monkeypatch, capsys):
        monkeypatch.setattr("builtins.input", make_input(["y"]))

        def fail(url, destination):
            raise requests.exceptions.ConnectionError("offline")

        monkeypatch.setattr(main.func, "download_audio", fail)

        main.offer_pronunciation(make_entry(audio_url="https://x/a.mp3"))

        assert "Could not download" in capsys.readouterr().out

    def test_reports_missing_audio_device_without_crashing(self, monkeypatch, capsys):
        monkeypatch.setattr("builtins.input", make_input(["y"]))
        monkeypatch.setattr(main.func, "download_audio", lambda url, destination: None)

        class NoAudioMixer:
            @staticmethod
            def init():
                raise RuntimeError("No audio device")

        monkeypatch.setattr(main, "load_mixer", lambda: NoAudioMixer)

        main.offer_pronunciation(make_entry(audio_url="https://x/a.mp3"))

        assert "Could not start audio playback" in capsys.readouterr().out

    def test_plays_until_the_user_declines_a_replay(self, monkeypatch):
        monkeypatch.setattr("builtins.input", make_input(["y", "y", "n"]))
        monkeypatch.setattr(main.func, "download_audio", lambda url, destination: None)
        mixer = FakeMixer(busy_polls=0)
        monkeypatch.setattr(main, "load_mixer", lambda: mixer)

        main.offer_pronunciation(make_entry(audio_url="https://x/a.mp3"))

        assert mixer.events.count("play") == 2
        assert mixer.events[-1] == "quit"


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
        entry = make_entry("word", ("a thing", "another"))

        main.show_definition(entry)

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
    @pytest.fixture
    def session(self, monkeypatch):
        """Silence the pacing and stub the parts that need the network."""
        monkeypatch.setattr(main.func, "draw_line_break", lambda: None)
        monkeypatch.setattr(
            main, "offer_pronunciation", lambda entry: print("<offer pronunciation>")
        )
        monkeypatch.setattr("builtins.input", make_input(["hello", "n"]))

    def test_runs_the_whole_original_session_and_logs_the_lookup(
        self, session, capsys, tmp_path
    ):
        history = WordHistory(tmp_path / "word_history.json")

        code = main.run_interactive(
            lookup=lambda word: make_entry(word), history=history
        )

        out = capsys.readouterr().out
        assert code == 0
        order = [
            "Welcome to the Dictionary of Merriam-Webster",
            "-> Definition of HELLO:",
            "a greeting",
            "<offer pronunciation>",
            "Thank you",
        ]
        assert [out.index(part) for part in order] == sorted(
            out.index(part) for part in order
        )
        assert [(r.word, r.found) for r in history.read()] == [("hello", True)]
