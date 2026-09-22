"""Tests for the non-interactive command-line mode of main.py.

Only ``requests.get`` is replaced (by a tiny fake of merriam-webster.com), so
each test exercises the real argument parsing, cache, history log, parser and
exporters together. Every run gets its own ``--data-dir`` under ``tmp_path``
and ``--delay 0``, so nothing touches the repository or sleeps.
"""

from __future__ import annotations

import http.client
import io
import json
import logging
import re
import signal
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import unquote

import pytest
import requests

import functions as func
import main
from word_history import WordHistory

SERENDIPITY_HTML = """
<html><head><script type="application/ld+json">
{"contentURL": "https://media.example.com/serendipity.mp3"}
</script></head><body>
  <span class="dtText">: the faculty of finding valuable things</span>
  <span class="dtText">: an instance of this</span>
</body></html>
"""
EPHEMERAL_HTML = (
    "<html><body>"
    '<span class="dtText">: lasting a very short time</span>'
    "</body></html>"
)
PROJECT_DIR = Path(main.__file__).resolve().parent


class FakeResponse:
    def __init__(self, text: str, status: int = 200) -> None:
        self.text = text
        self.content = text.encode()
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(
                f"{self.status_code} error", response=self  # type: ignore[arg-type]
            )


class FakeWeb:
    """Stands in for merriam-webster.com, routing requests.get by word."""

    def __init__(self) -> None:
        self.pages = {"serendipity": SERENDIPITY_HTML, "ephemeral": EPHEMERAL_HTML}
        self.errors: dict[str, Exception] = {}
        self.urls: list[str] = []
        self.headers: list[object] = []

    def __call__(self, url: str, timeout: float, **kwargs: object) -> FakeResponse:
        self.urls.append(url)
        self.headers.append(kwargs.get("headers"))
        word = unquote(url.rsplit("/", 1)[-1])
        if word in self.errors:
            raise self.errors[word]
        if word in self.pages:
            return FakeResponse(self.pages[word])
        return FakeResponse("Sorry, that word isn't in the dictionary.", 404)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """A developer's own User-Agent setting must not leak into the tests."""
    monkeypatch.delenv(func.USER_AGENT_ENV_VAR, raising=False)


@pytest.fixture
def web(monkeypatch) -> FakeWeb:
    fake = FakeWeb()
    monkeypatch.setattr(requests, "get", fake)
    return fake


@pytest.fixture
def run(tmp_path, capsys):
    """Run main.main() and return (exit code, stdout, stderr)."""

    def _run(*argv: str, delay: str = "0"):
        full = [*argv, "--data-dir", str(tmp_path), "--delay", delay]
        try:
            code = main.main(full)
        except SystemExit as exit_request:  # argparse errors
            code = exit_request.code
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run


def read_history(tmp_path) -> list[dict]:
    return json.loads((tmp_path / "word_history.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ lookups
class TestSingleWord:
    def test_prints_the_definitions_to_stdout(self, web, run):
        code, out, _err = run("--word", "serendipity")

        assert code == 0
        assert out == (
            "SERENDIPITY\n"
            "Entry 1: the faculty of finding valuable things\n"
            "Entry 2: an instance of this\n"
        )

    def test_short_flag(self, web, run):
        assert run("-w", "ephemeral")[0] == 0

    def test_no_decorative_output_or_delays(self, web, run, monkeypatch):
        monkeypatch.setattr(
            func, "draw_line_break", lambda: pytest.fail("banner in CLI mode")
        )
        _code, out, _err = run("--word", "ephemeral")
        assert "Welcome" not in out
        assert "Thank you" not in out

    def test_json_output_is_machine_readable(self, web, run):
        _code, out, _err = run("--word", "serendipity", "--format", "json")

        assert json.loads(out) == [
            {
                "word": "serendipity",
                "definitions": [
                    "the faculty of finding valuable things",
                    "an instance of this",
                ],
                "audio_url": "https://media.example.com/serendipity.mp3",
            }
        ]

    def test_markdown_output(self, web, run):
        _code, out, _err = run("--word", "ephemeral", "--format", "md")
        assert out.startswith("# ephemeral\n\n1. lasting a very short time")

    def test_multi_word_phrases_are_looked_up_whole(self, web, run):
        web.pages["ice cream"] = EPHEMERAL_HTML

        code, out, _err = run("--word", "  ice   cream ")

        assert code == 0
        assert web.urls[0].endswith("/ice%20cream")
        assert out.startswith("ICE CREAM")


class TestFailures:
    def test_unknown_word_exits_1_and_reports_on_stderr_only(self, web, run, caplog):
        code, out, _err = run("--word", "asdfgh")

        assert code == 1
        assert out == ""
        assert "'asdfgh' isn't in the dictionary" in caplog.text

    def test_network_errors_exit_1(self, web, run, caplog):
        web.errors["serendipity"] = requests.exceptions.ConnectionError("no route")

        code, out, _err = run("--word", "serendipity")

        assert (code, out) == (1, "")
        assert "network error while looking up 'serendipity'" in caplog.text

    def test_one_bad_word_does_not_stop_the_rest(self, web, run):
        code, out, _err = run("-w", "serendipity", "-w", "asdfgh", "-w", "ephemeral")

        assert code == 1  # scripts can detect the partial failure
        assert "SERENDIPITY" in out
        assert "EPHEMERAL" in out

    @pytest.mark.parametrize("bad", ["", "   ", "bad\x00word"])
    def test_invalid_words_exit_2_before_any_request(self, web, run, caplog, bad):
        code, _out, _err = run("--word", bad)

        assert code == 2
        assert web.urls == []

    def test_a_failed_run_does_not_clobber_an_existing_export(self, web, run, tmp_path):
        target = tmp_path / "out.json"
        target.write_text("precious", encoding="utf-8")

        code, _out, _err = run("--word", "asdfgh", "--output", str(target))

        assert code == 1
        assert target.read_text(encoding="utf-8") == "precious"


# --------------------------------------------------------------- batch mode
class TestWordList:
    def test_processes_every_word_in_the_file(self, web, run, tmp_path):
        (tmp_path / "words.txt").write_text(
            "# study list\nserendipity\n\nephemeral\n", encoding="utf-8"
        )

        code, out, _err = run("--word-list", str(tmp_path / "words.txt"))

        assert code == 0
        assert out.index("SERENDIPITY") < out.index("EPHEMERAL")

    def test_combines_with_word_and_drops_duplicates(self, web, run, tmp_path):
        (tmp_path / "words.txt").write_text(
            "ephemeral\nSerendipity\n", encoding="utf-8"
        )

        run("-w", "serendipity", "-l", str(tmp_path / "words.txt"))

        assert len(web.urls) == 2  # serendipity once, ephemeral once

    def test_reads_stdin_when_the_path_is_a_dash(self, web, run, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO("ephemeral\nserendipity\n"))

        code, out, _err = run("--word-list", "-", "--format", "json")

        assert code == 0
        assert [e["word"] for e in json.loads(out)] == ["ephemeral", "serendipity"]

    def test_tolerates_a_utf8_bom(self, web, run, tmp_path):
        path = tmp_path / "words.txt"
        path.write_bytes(b"\xef\xbb\xbfephemeral\n")

        assert run("--word-list", str(path))[0] == 0

    def test_a_bad_line_fails_fast_naming_the_line(self, web, run, tmp_path, caplog):
        path = tmp_path / "words.txt"
        path.write_text("ephemeral\nbad\x00word\n", encoding="utf-8")

        code, _out, _err = run("--word-list", str(path))

        assert code == 2
        assert "line 2" in caplog.text
        assert web.urls == []

    def test_missing_file_exits_2(self, web, run, tmp_path, caplog):
        code, _out, _err = run("--word-list", str(tmp_path / "nope.txt"))

        assert code == 2
        assert "nope.txt" in caplog.text

    def test_a_file_with_no_words_exits_2(self, web, run, tmp_path, caplog):
        path = tmp_path / "words.txt"
        path.write_text("# nothing here\n\n", encoding="utf-8")

        assert run("--word-list", str(path))[0] == 2
        assert "no words to look up" in caplog.text


# -------------------------------------------------------------------- export
class TestOutputFile:
    @pytest.mark.parametrize(
        ("name", "marker"),
        [
            ("out.txt", "SERENDIPITY"),
            ("out.md", "# serendipity"),
            ("out.json", '"word"'),
        ],
    )
    def test_writes_the_format_matching_the_extension(
        self, web, run, tmp_path, name, marker, caplog
    ):
        code, out, _err = run("--word", "serendipity", "--output", str(tmp_path / name))

        assert code == 0
        assert out == ""  # results went to the file, not stdout
        assert marker in (tmp_path / name).read_text(encoding="utf-8")

    def test_batch_export(self, web, run, tmp_path):
        run("-w", "serendipity", "-w", "ephemeral", "-o", str(tmp_path / "all.json"))

        exported = json.loads((tmp_path / "all.json").read_text(encoding="utf-8"))
        assert [e["word"] for e in exported] == ["serendipity", "ephemeral"]

    def test_unsupported_extension_is_rejected_up_front(self, web, run, tmp_path):
        code, _out, err = run(
            "--word", "serendipity", "--output", str(tmp_path / "x.csv")
        )

        assert code == 2
        assert "extension must be one of" in err
        assert web.urls == []  # failed before doing any network work

    def test_format_conflicting_with_the_extension_is_rejected(
        self, web, run, tmp_path
    ):
        code, _out, err = run(
            "-w", "serendipity", "-o", str(tmp_path / "x.md"), "--format", "json"
        )

        assert code == 2
        assert "conflicts" in err

    def test_unwritable_destination_exits_1(self, web, run, tmp_path, caplog):
        code, _out, _err = run(
            "--word", "serendipity", "--output", str(tmp_path / "missing" / "x.txt")
        )

        assert code == 1
        assert "could not write the results" in caplog.text


# ------------------------------------------------------------------- history
class TestHistory:
    def test_every_lookup_is_recorded_with_a_timestamp(self, web, run, tmp_path):
        run("-w", "serendipity", "-w", "asdfgh")

        records = read_history(tmp_path)
        assert [(r["word"], r["found"]) for r in records] == [
            ("serendipity", True),
            ("asdfgh", False),
        ]
        assert all("T" in r["timestamp"] for r in records)

    def test_network_failures_are_not_recorded(self, web, run, tmp_path):
        web.errors["serendipity"] = requests.exceptions.Timeout("slow")

        run("--word", "serendipity")

        assert not (tmp_path / "word_history.json").exists()

    def test_the_log_only_ever_grows(self, web, run, tmp_path):
        run("--word", "serendipity")
        run("--word", "ephemeral")
        run("--word", "serendipity")

        assert [r["word"] for r in read_history(tmp_path)] == [
            "serendipity",
            "ephemeral",
            "serendipity",
        ]

    def test_cache_hits_are_lookups_too(self, web, run, tmp_path):
        run("--word", "ephemeral")
        run("--word", "ephemeral")

        assert len(read_history(tmp_path)) == 2
        assert len(web.urls) == 1

    def test_no_history_flag_skips_recording(self, web, run, tmp_path):
        run("--word", "ephemeral", "--no-history")
        assert not (tmp_path / "word_history.json").exists()

    def test_history_flag_prints_tab_separated_lines(self, web, run):
        run("-w", "serendipity", "-w", "asdfgh")

        code, out, _err = run("--history")

        assert code == 0
        rows = [line.split("\t") for line in out.splitlines()]
        assert [(w, status) for _stamp, w, status in rows] == [
            ("serendipity", "found"),
            ("asdfgh", "not-found"),
        ]

    def test_history_as_json(self, web, run):
        run("--word", "ephemeral")

        _code, out, _err = run("--history", "--format", "json")

        (record,) = json.loads(out)
        assert record["word"] == "ephemeral"
        assert record["found"] is True

    def test_empty_history_prints_nothing_on_stdout(self, run, caplog):
        code, out, _err = run("--history")

        assert (code, out) == (0, "")
        assert "no lookups have been recorded" in caplog.text

    def test_empty_history_as_json_is_an_empty_array(self, run):
        assert json.loads(run("--history", "--format", "json")[1]) == []

    def test_history_cannot_be_combined_with_lookups(self, run):
        code, _out, err = run("--history", "--word", "x")
        assert code == 2
        assert "--history cannot be combined" in err

    def test_history_does_not_support_markdown(self, run):
        assert run("--history", "--format", "md")[0] == 2

    def test_a_history_failure_never_breaks_a_lookup(
        self, web, run, tmp_path, monkeypatch, caplog
    ):
        def boom(self, word, *, found=True):
            raise OSError("read-only file system")

        monkeypatch.setattr(main.WordHistory, "record", boom)

        code, out, _err = run("--word", "ephemeral")

        assert code == 0
        assert "EPHEMERAL" in out
        assert "could not update the word history" in caplog.text


# ------------------------------------------------------------------- caching
class TestCaching:
    def test_a_repeat_lookup_does_not_touch_the_network(self, web, run):
        first = run("--word", "serendipity")
        second = run("--word", "serendipity")

        assert first[1] == second[1]  # identical output
        assert len(web.urls) == 1

    def test_the_cache_is_shared_between_batch_and_single_runs(self, web, run):
        run("-w", "ephemeral", "-w", "serendipity")
        run("-w", "serendipity")

        assert len(web.urls) == 2

    def test_cache_files_live_under_the_data_dir(self, web, run, tmp_path):
        run("--word", "ephemeral")
        assert len(list((tmp_path / ".cache").glob("*.json.gz"))) == 1

    def test_no_cache_neither_reads_nor_writes(self, web, run, tmp_path):
        run("--word", "ephemeral", "--no-cache")
        run("--word", "ephemeral", "--no-cache")

        assert len(web.urls) == 2
        assert not (tmp_path / ".cache").exists()

    def test_ttl_zero_forces_a_refresh(self, web, run):
        run("--word", "ephemeral")
        run("--word", "ephemeral", "--cache-ttl", "0")

        assert len(web.urls) == 2

    def test_a_long_ttl_keeps_entries_fresh(self, web, run):
        run("--word", "ephemeral", "--cache-ttl", "3600")
        run("--word", "ephemeral", "--cache-ttl", "3600")

        assert len(web.urls) == 1

    def test_words_that_do_not_exist_are_not_cached(self, web, run):
        run("--word", "asdfgh")
        run("--word", "asdfgh")

        assert len(web.urls) == 2

    def test_verbose_reports_cache_hits(self, web, run, caplog):
        caplog.set_level(logging.INFO)  # basicConfig is a no-op under pytest
        run("--word", "ephemeral", "-v")
        run("--word", "ephemeral", "-v")

        assert "cache miss for 'ephemeral'" in caplog.text
        assert "cache hit for 'ephemeral'" in caplog.text

    def test_cache_hits_never_wait(self, web, run, monkeypatch):
        naps: list[float] = []
        monkeypatch.setattr(func, "sleep", naps.append)
        run("-w", "ephemeral", "-w", "serendipity")  # warm both entries

        run("-w", "ephemeral", "-w", "serendipity", delay="5")

        assert naps == []

    def test_only_uncached_requests_count_towards_the_delay(
        self, web, run, monkeypatch
    ):
        web.pages["third"] = EPHEMERAL_HTML
        naps: list[float] = []
        monkeypatch.setattr(func, "sleep", naps.append)
        run("-w", "ephemeral")  # warm just this one

        run("-w", "serendipity", "-w", "ephemeral", "-w", "third", delay="5")

        # serendipity: first request (no wait); ephemeral: cache hit (no wait);
        # third: second request, so it waits out the delay once.
        assert len(naps) == 1

    def test_consecutive_network_requests_wait_for_the_delay(
        self, web, run, monkeypatch
    ):
        naps: list[float] = []
        monkeypatch.setattr(func, "sleep", naps.append)

        run("-w", "ephemeral", "-w", "serendipity", delay="5")

        assert len(naps) == 1
        assert 4 < naps[0] <= 5


# ----------------------------------------------------------------- pronounce
class TestPronounce:
    @pytest.fixture
    def audio(self, monkeypatch):
        calls = {"downloaded": [], "played": []}

        def fake_download(url, destination, **_kw):
            calls["downloaded"].append(url)
            Path(destination).write_bytes(b"mp3")

        monkeypatch.setattr(func, "download_audio", fake_download)
        monkeypatch.setattr(
            main, "play_audio", lambda path, **_kw: calls["played"].append(path.name)
        )
        return calls

    def test_downloads_and_plays_the_audio(self, web, run, audio):
        code, out, _err = run("--word", "serendipity", "--pronounce")

        assert code == 0
        assert "SERENDIPITY" in out  # results are still printed
        assert audio["downloaded"] == ["https://media.example.com/serendipity.mp3"]
        assert len(audio["played"]) == 1

    def test_uses_a_temporary_folder_and_leaves_nothing_behind(
        self, web, run, audio, tmp_path
    ):
        run("--word", "serendipity", "--pronounce")
        assert not list(tmp_path.glob("**/*.mp3"))

    def test_words_never_become_file_names(self, web, run, audio):
        web.pages["../evil"] = SERENDIPITY_HTML
        run("--word", "../evil", "--pronounce")
        assert audio["played"] == ["0.mp3"]

    def test_words_without_a_recording_only_warn(self, web, run, audio, caplog):
        code, _out, _err = run("--word", "ephemeral", "--pronounce")

        assert code == 0
        assert audio["downloaded"] == []
        assert "no pronunciation is available for 'ephemeral'" in caplog.text

    def test_playback_problems_warn_but_do_not_fail_the_run(
        self, web, run, monkeypatch, audio, caplog
    ):
        def no_device(path, **_kw):
            raise RuntimeError("No audio device")

        monkeypatch.setattr(main, "play_audio", no_device)

        code, out, _err = run("--word", "serendipity", "--pronounce")

        assert code == 0
        assert "SERENDIPITY" in out
        assert "could not play the pronunciation of 'serendipity'" in caplog.text

    def test_missing_pygame_warns_once_and_stops(
        self, web, run, monkeypatch, audio, caplog
    ):
        web.pages["another"] = SERENDIPITY_HTML

        def no_pygame(path, **_kw):
            raise ImportError("No module named 'pygame'")

        monkeypatch.setattr(main, "play_audio", no_pygame)

        code, _out, _err = run("-w", "serendipity", "-w", "another", "--pronounce")

        assert code == 0
        assert caplog.text.count("audio playback needs pygame") == 1

    def test_download_failures_warn(self, web, run, monkeypatch, caplog):
        def fail(url, destination, **_kw):
            raise requests.exceptions.ConnectionError("offline")

        monkeypatch.setattr(func, "download_audio", fail)

        code, _out, _err = run("--word", "serendipity", "--pronounce")

        assert code == 0
        assert "could not play the pronunciation" in caplog.text

    def test_json_always_carries_the_audio_url_without_the_flag(self, web, run):
        _code, out, _err = run("--word", "serendipity", "--format", "json")
        assert json.loads(out)[0]["audio_url"].endswith("serendipity.mp3")

    def test_pronounce_needs_a_word(self, run):
        code, _out, err = run("--pronounce")
        assert code == 2
        assert "requires --word or --word-list" in err


# --------------------------------------------------------- mode & validation
class TestModeSelection:
    def test_no_arguments_starts_the_interactive_session(self, monkeypatch, tmp_path):
        seen = {}

        def fake_interactive(*, lookup, history):
            seen["history"] = history
            return 0

        monkeypatch.setattr(main, "run_interactive", fake_interactive)

        assert main.main(["--data-dir", str(tmp_path)]) == 0
        assert seen["history"] is not None

    def test_interactive_mode_honours_no_history(self, monkeypatch, tmp_path):
        seen = {}
        monkeypatch.setattr(
            main,
            "run_interactive",
            lambda *, lookup, history: seen.update(h=history) or 0,
        )

        main.main(["--data-dir", str(tmp_path), "--no-history"])

        assert seen["h"] is None

    @pytest.mark.parametrize("flag", [["--output", "x.md"], ["--format", "json"]])
    def test_output_options_need_a_lookup(self, run, flag):
        code, _out, err = run(*flag)
        assert code == 2
        assert "requires --word or --word-list" in err

    @pytest.mark.parametrize("flag", ["--delay", "--cache-ttl"])
    @pytest.mark.parametrize("value", ["-1", "abc", "nan"])
    def test_numeric_options_reject_bad_values(self, run, flag, value):
        code, _out, err = run("--word", "x", flag, value)
        assert code == 2

    def test_data_dir_can_come_from_the_environment(self, monkeypatch, tmp_path):
        monkeypatch.setenv(main.DATA_DIR_ENV_VAR, str(tmp_path / "from-env"))

        args = main.build_parser().parse_args(["--word", "x"])

        assert args.data_dir == tmp_path / "from-env"

    def test_data_dir_defaults_to_the_program_folder(self, monkeypatch):
        monkeypatch.delenv(main.DATA_DIR_ENV_VAR, raising=False)

        args = main.build_parser().parse_args(["--word", "x"])

        assert args.data_dir == PROJECT_DIR

    @pytest.mark.parametrize(
        ("verbosity", "level"),
        [
            (0, logging.WARNING),
            (1, logging.INFO),
            (2, logging.DEBUG),
            (5, logging.DEBUG),
        ],
    )
    def test_verbosity_maps_to_a_log_level(self, monkeypatch, verbosity, level):
        seen = {}
        monkeypatch.setattr(
            logging, "basicConfig", lambda **kwargs: seen.update(kwargs)
        )

        main.configure_logging(verbosity)

        assert seen["level"] == level

    def test_requests_carry_a_user_agent_that_can_be_overridden(
        self, web, run, monkeypatch
    ):
        monkeypatch.delenv(func.USER_AGENT_ENV_VAR, raising=False)
        run("--word", "ephemeral", "--no-cache")
        monkeypatch.setenv(func.USER_AGENT_ENV_VAR, "custom/1")
        run("--word", "ephemeral", "--no-cache")

        assert web.headers[0] == {"User-Agent": func.DEFAULT_USER_AGENT}
        assert web.headers[1] == {"User-Agent": "custom/1"}

    def test_help_documents_the_exit_codes_and_examples(self, capsys):
        with pytest.raises(SystemExit) as info:
            main.main(["--help"])

        assert info.value.code == 0
        text = capsys.readouterr().out
        for expected in (
            "--word",
            "--pronounce",
            "--output",
            "--word-list",
            "--history",
        ):
            assert expected in text
        assert "exit codes:" in text
        assert func.USER_AGENT_ENV_VAR in text


# --------------------------------------------------------------- API source
# ------------------------------------------------------------ web interface
class FakeServer:
    """Stands in for the HTTP server: serves until "Ctrl-C", then closes."""

    def __init__(self, address: tuple = ("127.0.0.1", 8000)) -> None:
        self.server_address = address
        self.closed = False

    def serve_forever(self) -> None:
        raise KeyboardInterrupt

    def server_close(self) -> None:
        self.closed = True


class TestServe:
    @pytest.fixture
    def created(self, monkeypatch) -> dict:
        record: dict = {"address": ("127.0.0.1", 8000)}

        def fake_create_server(**kwargs):
            record.update(kwargs)
            record["server"] = FakeServer(record["address"])
            return record["server"]

        monkeypatch.setattr(main.web_server, "create_server", fake_create_server)
        return record

    def test_starts_on_the_default_address_and_stops_on_ctrl_c(self, created, run):
        code, out, err = run("--serve")

        assert code == 0
        assert out == "Serving on http://127.0.0.1:8000/ (press Ctrl-C to stop)\n"
        assert "Stopped." in err
        assert (created["host"], created["port"]) == ("127.0.0.1", 8000)
        assert created["server"].closed

    def test_host_and_port_can_be_chosen(self, created, run):
        created["address"] = ("127.0.0.1", 9999)

        run("--serve", "--host", "localhost", "--port", "9999")

        assert (created["host"], created["port"]) == ("localhost", 9999)

    def test_port_zero_reports_the_port_the_system_picked(self, created, run):
        created["address"] = ("127.0.0.1", 54321)

        code, out, _err = run("--serve", "--port", "0")

        assert created["port"] == 0
        assert "http://127.0.0.1:54321/" in out

    def test_ipv6_addresses_are_shown_in_brackets(self, created, run):
        created["address"] = ("::1", 8000, 0, 0)

        _code, out, _err = run("--serve", "--host", "::1")

        assert "http://[::1]:8000/" in out

    def test_the_lookup_it_serves_uses_the_cache_and_data_dir(
        self, created, web, run, tmp_path
    ):
        run("--serve")

        entry = created["lookup"]("ephemeral")

        assert entry.definitions == ("lasting a very short time",)
        assert len(list((tmp_path / ".cache").glob("*.json.gz"))) == 1
        created["lookup"]("ephemeral")
        assert len(web.urls) == 1  # the second call came from the cache

    def test_the_history_it_records_lives_in_the_data_dir(self, created, run, tmp_path):
        run("--serve")

        history = created["history"]
        assert isinstance(history, WordHistory)
        assert history.path == tmp_path / "word_history.json"

    def test_no_history_turns_recording_off(self, created, run):
        run("--serve", "--no-history")
        assert created["history"] is None

    def test_a_non_local_address_gets_a_warning_about_the_missing_login(
        self, created, run, caplog
    ):
        created["address"] = ("192.0.2.1", 8000)

        run("--serve", "--host", "192.0.2.1")

        assert "there is no login" in caplog.text

    def test_a_local_address_gets_no_warning(self, created, run, caplog):
        run("--serve")
        assert "no login" not in caplog.text

    def test_open_launches_the_browser(self, created, run, monkeypatch):
        opened: list[str] = []
        monkeypatch.setattr(main.webbrowser, "open", opened.append)

        run("--serve", "--open")

        assert opened == ["http://127.0.0.1:8000/"]

    def test_the_browser_is_not_opened_by_default(self, created, run, monkeypatch):
        monkeypatch.setattr(
            main.webbrowser, "open", lambda url: pytest.fail("browser opened")
        )
        run("--serve")

    def test_a_port_that_cannot_be_bound_exits_1(self, monkeypatch, run, caplog):
        def refuse(**kwargs):
            raise OSError("Address already in use")

        monkeypatch.setattr(main.web_server, "create_server", refuse)

        code, out, _err = run("--serve")

        assert (code, out) == (1, "")
        assert "could not start the web interface" in caplog.text
        assert "Address already in use" in caplog.text

    @pytest.mark.parametrize(
        "option",
        [
            ["--word", "x"],
            ["--word-list", "words.txt"],
            ["--history"],
            ["--output", "out.md"],
            ["--format", "json"],
            ["--pronounce"],
        ],
    )
    def test_serve_cannot_be_combined_with_lookup_options(self, run, option):
        code, _out, err = run("--serve", *option)

        assert code == 2
        assert "--serve cannot be combined with" in err

    @pytest.mark.parametrize(
        "option", [["--host", "localhost"], ["--port", "80"], ["--open"]]
    )
    def test_web_options_need_serve(self, run, option):
        code, _out, err = run(*option)

        assert code == 2
        assert "requires --serve" in err

    @pytest.mark.parametrize("port", ["70000", "-1", "abc", "8.5"])
    def test_invalid_ports_are_rejected(self, run, port):
        assert run("--serve", "--port", port)[0] == 2

    def test_help_documents_the_web_interface(self, capsys):
        with pytest.raises(SystemExit):
            main.main(["--help"])

        text = capsys.readouterr().out
        for expected in ("--serve", "--host", "--port", "--open", "web interface"):
            assert expected in text


# ---------------------------------------------------- real-process behaviour
class TestAsAPipeline:
    """Run main.py in a real subprocess to check what a shell would see."""

    def run_script(self, *argv: str, data_dir: Path, stdin: str = ""):
        return subprocess.run(
            [sys.executable, "main.py", *argv, "--data-dir", str(data_dir)],
            capture_output=True,
            text=True,
            input=stdin,
            cwd=PROJECT_DIR,
            timeout=60,
            check=False,
        )

    def test_stdout_holds_only_results_never_a_pygame_banner(self, tmp_path):
        (tmp_path / "word_history.json").write_text(
            json.dumps([{"word": "w", "timestamp": "2026-01-01T00:00:00+00:00"}]),
            encoding="utf-8",
        )

        result = self.run_script("--history", data_dir=tmp_path)

        assert result.stdout == "2026-01-01T00:00:00+00:00\tw\tfound\n"
        assert result.returncode == 0

    def test_errors_go_to_stderr_with_a_failing_exit_code(self, tmp_path):
        result = self.run_script("--word-list", "no-such-file.txt", data_dir=tmp_path)

        assert result.returncode == 2
        assert result.stdout == ""
        assert "ERROR: " in result.stderr
        assert "no-such-file.txt" in result.stderr

    def test_closed_stdin_in_interactive_mode_exits_cleanly(self, tmp_path):
        # The first prompt hits end-of-file before any request is made.
        result = self.run_script("--no-history", "--no-cache", data_dir=tmp_path)

        assert "Traceback" not in result.stderr
        assert result.returncode != 0

    @pytest.mark.skipif(sys.platform == "win32", reason="needs POSIX signals")
    def test_serve_starts_answers_and_stops_on_ctrl_c(self, tmp_path):
        process = subprocess.Popen(
            [sys.executable, "main.py", "--serve", "--port", "0"]
            + ["--data-dir", str(tmp_path), "--no-cache"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=PROJECT_DIR,
        )
        try:
            first_line: list[str] = []
            reader = threading.Thread(
                target=lambda: first_line.append(process.stdout.readline()), daemon=True
            )
            reader.start()
            reader.join(timeout=30)
            assert first_line, "the server printed nothing"
            match = re.match(r"Serving on http://127\.0\.0\.1:(\d+)/", first_line[0])
            assert match, first_line[0]

            connection = http.client.HTTPConnection(
                "127.0.0.1", int(match.group(1)), timeout=10
            )
            connection.request("GET", "/")
            response = connection.getresponse()
            assert response.status == 200
            assert b"Look up" in response.read()
            connection.close()

            process.send_signal(signal.SIGINT)
            _out, err = process.communicate(timeout=15)
            assert process.returncode == 0
            assert "Stopped." in err
            assert "Traceback" not in err
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_a_closed_pipe_does_not_print_a_traceback(self, tmp_path):
        rows = [
            {"word": f"w{i}", "timestamp": "2026-01-01T00:00:00+00:00"}
            for i in range(5000)
        ]
        (tmp_path / "word_history.json").write_text(json.dumps(rows), encoding="utf-8")

        result = subprocess.run(
            f"{sys.executable} main.py --history --data-dir {tmp_path} | head -n 1",
            shell=True,
            capture_output=True,
            text=True,
            cwd=PROJECT_DIR,
            timeout=60,
            check=False,
        )

        assert result.stdout.count("\n") == 1
        assert "Traceback" not in result.stderr
        assert "BrokenPipeError" not in result.stderr
