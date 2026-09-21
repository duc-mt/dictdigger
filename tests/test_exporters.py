"""Unit tests for exporters.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import exporters
import functions as func

SERENDIPITY = func.Entry(
    word="serendipity",
    definitions=("the faculty of finding things", "an instance of this"),
    audio_url="https://media.example.com/serendipity.mp3",
)
EPHEMERAL = func.Entry(word="ephemeral", definitions=("short-lived",))
EMPTY = func.Entry(word="hollow", definitions=())


class TestRenderText:
    def test_single_definition_is_printed_under_the_upper_cased_word(self):
        assert exporters.render_text([EPHEMERAL]) == "EPHEMERAL\nshort-lived\n"

    def test_multiple_definitions_are_numbered(self):
        assert exporters.render_text([SERENDIPITY]) == (
            "SERENDIPITY\n"
            "Entry 1: the faculty of finding things\n"
            "Entry 2: an instance of this\n"
        )

    def test_entries_are_separated_by_a_blank_line(self):
        text = exporters.render_text([EPHEMERAL, EPHEMERAL])
        assert text == "EPHEMERAL\nshort-lived\n\nEPHEMERAL\nshort-lived\n"

    def test_an_entry_without_definitions_says_so(self):
        assert "NO DEFINITION FOUND" in exporters.render_text([EMPTY])

    def test_a_colon_inside_an_unprefixed_definition_is_not_mistaken_for_a_marker(
        self,
    ):
        entry = func.Entry("w", ("first", "second: with a colon"))
        assert "Entry 2: second: with a colon" in exporters.render_text([entry])


class TestRenderMarkdown:
    def test_heading_numbered_list_and_audio_link(self):
        assert exporters.render_markdown([SERENDIPITY]) == (
            "# serendipity\n"
            "\n"
            "1. the faculty of finding things\n"
            "2. an instance of this\n"
            "\n"
            "[Pronunciation audio](https://media.example.com/serendipity.mp3)\n"
        )

    def test_no_audio_line_when_there_is_no_recording(self):
        assert "Pronunciation" not in exporters.render_markdown([EPHEMERAL])

    def test_an_entry_without_definitions_says_so(self):
        assert "_No definition found._" in exporters.render_markdown([EMPTY])

    def test_entries_are_separated_by_a_blank_line(self):
        text = exporters.render_markdown([EPHEMERAL, EMPTY])
        assert "1. short-lived\n\n# hollow" in text


class TestRenderJson:
    def test_always_an_array_even_for_one_entry(self):
        assert isinstance(json.loads(exporters.render_json([EPHEMERAL])), list)

    def test_schema(self):
        assert json.loads(exporters.render_json([SERENDIPITY, EPHEMERAL])) == [
            {
                "word": "serendipity",
                "definitions": ["the faculty of finding things", "an instance of this"],
                "audio_url": "https://media.example.com/serendipity.mp3",
            },
            {"word": "ephemeral", "definitions": ["short-lived"], "audio_url": None},
        ]

    def test_non_ascii_text_is_not_escaped(self):
        assert "café" in exporters.render_json([func.Entry("café", ("x",))])

    def test_ends_with_a_newline_for_shell_friendliness(self):
        assert exporters.render_json([EPHEMERAL]).endswith("\n")


class TestRender:
    @pytest.mark.parametrize("fmt", exporters.FORMATS)
    def test_every_advertised_format_is_supported(self, fmt):
        assert exporters.render([EPHEMERAL], fmt)

    def test_unknown_format_raises_value_error(self):
        with pytest.raises(ValueError, match="unsupported format"):
            exporters.render([EPHEMERAL], "xml")


class TestFormatForPath:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [("a.txt", "text"), ("a.md", "md"), ("a.json", "json"), ("A.JSON", "json")],
    )
    def test_maps_extensions(self, name, expected):
        assert exporters.format_for_path(Path(name)) == expected

    @pytest.mark.parametrize("name", ["a.csv", "a", "a.json.bak"])
    def test_rejects_other_extensions(self, name):
        with pytest.raises(ValueError, match="extension must be one of"):
            exporters.format_for_path(Path(name))


class TestWriteExport:
    @pytest.mark.parametrize("name", ["out.txt", "out.md", "out.json"])
    def test_writes_the_format_implied_by_the_extension(self, tmp_path, name):
        target = tmp_path / name
        exporters.write_export(target, [SERENDIPITY])
        fmt = exporters.format_for_path(target)
        assert target.read_text(encoding="utf-8") == exporters.render(
            [SERENDIPITY], fmt
        )

    def test_overwrites_an_existing_file(self, tmp_path):
        target = tmp_path / "out.txt"
        target.write_text("stale", encoding="utf-8")
        exporters.write_export(target, [EPHEMERAL])
        assert "stale" not in target.read_text(encoding="utf-8")

    def test_rejects_unsupported_extensions_before_writing(self, tmp_path):
        target = tmp_path / "out.csv"
        with pytest.raises(ValueError):
            exporters.write_export(target, [EPHEMERAL])
        assert not target.exists()

    def test_utf8_round_trip(self, tmp_path):
        target = tmp_path / "out.md"
        exporters.write_export(target, [func.Entry("café", ("crème",))])
        assert "crème" in target.read_text(encoding="utf-8")
"""Unit tests for exporters.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import exporters
import functions as func

SERENDIPITY = func.Entry(
    word="serendipity",
    definitions=("the faculty of finding things", "an instance of this"),
    audio_url="https://media.example.com/serendipity.mp3",
)
EPHEMERAL = func.Entry(word="ephemeral", definitions=("short-lived",))
EMPTY = func.Entry(word="hollow", definitions=())


class TestRenderText:
    def test_single_definition_is_printed_under_the_upper_cased_word(self):
        assert exporters.render_text([EPHEMERAL]) == "EPHEMERAL\nshort-lived\n"

    def test_multiple_definitions_are_numbered(self):
        assert exporters.render_text([SERENDIPITY]) == (
            "SERENDIPITY\n"
            "Entry 1: the faculty of finding things\n"
            "Entry 2: an instance of this\n"
        )

    def test_entries_are_separated_by_a_blank_line(self):
        text = exporters.render_text([EPHEMERAL, EPHEMERAL])
        assert text == "EPHEMERAL\nshort-lived\n\nEPHEMERAL\nshort-lived\n"

    def test_an_entry_without_definitions_says_so(self):
        assert "NO DEFINITION FOUND" in exporters.render_text([EMPTY])

    def test_a_colon_inside_an_unprefixed_definition_is_not_mistaken_for_a_marker(
        self,
    ):
        entry = func.Entry("w", ("first", "second: with a colon"))
        assert "Entry 2: second: with a colon" in exporters.render_text([entry])


class TestRenderMarkdown:
    def test_heading_numbered_list_and_audio_link(self):
        assert exporters.render_markdown([SERENDIPITY]) == (
            "# serendipity\n"
            "\n"
            "1. the faculty of finding things\n"
            "2. an instance of this\n"
            "\n"
            "[Pronunciation audio](https://media.example.com/serendipity.mp3)\n"
        )

    def test_no_audio_line_when_there_is_no_recording(self):
        assert "Pronunciation" not in exporters.render_markdown([EPHEMERAL])

    def test_an_entry_without_definitions_says_so(self):
        assert "_No definition found._" in exporters.render_markdown([EMPTY])

    def test_entries_are_separated_by_a_blank_line(self):
        text = exporters.render_markdown([EPHEMERAL, EMPTY])
        assert "1. short-lived\n\n# hollow" in text


class TestRenderJson:
    def test_always_an_array_even_for_one_entry(self):
        assert isinstance(json.loads(exporters.render_json([EPHEMERAL])), list)

    def test_schema(self):
        assert json.loads(exporters.render_json([SERENDIPITY, EPHEMERAL])) == [
            {
                "word": "serendipity",
                "definitions": ["the faculty of finding things", "an instance of this"],
                "audio_url": "https://media.example.com/serendipity.mp3",
            },
            {"word": "ephemeral", "definitions": ["short-lived"], "audio_url": None},
        ]

    def test_non_ascii_text_is_not_escaped(self):
        assert "café" in exporters.render_json([func.Entry("café", ("x",))])

    def test_ends_with_a_newline_for_shell_friendliness(self):
        assert exporters.render_json([EPHEMERAL]).endswith("\n")


class TestRender:
    @pytest.mark.parametrize("fmt", exporters.FORMATS)
    def test_every_advertised_format_is_supported(self, fmt):
        assert exporters.render([EPHEMERAL], fmt)

    def test_unknown_format_raises_value_error(self):
        with pytest.raises(ValueError, match="unsupported format"):
            exporters.render([EPHEMERAL], "xml")


class TestFormatForPath:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [("a.txt", "text"), ("a.md", "md"), ("a.json", "json"), ("A.JSON", "json")],
    )
    def test_maps_extensions(self, name, expected):
        assert exporters.format_for_path(Path(name)) == expected

    @pytest.mark.parametrize("name", ["a.csv", "a", "a.json.bak"])
    def test_rejects_other_extensions(self, name):
        with pytest.raises(ValueError, match="extension must be one of"):
            exporters.format_for_path(Path(name))


class TestWriteExport:
    @pytest.mark.parametrize("name", ["out.txt", "out.md", "out.json"])
    def test_writes_the_format_implied_by_the_extension(self, tmp_path, name):
        target = tmp_path / name
        exporters.write_export(target, [SERENDIPITY])
        fmt = exporters.format_for_path(target)
        assert target.read_text(encoding="utf-8") == exporters.render(
            [SERENDIPITY], fmt
        )

    def test_overwrites_an_existing_file(self, tmp_path):
        target = tmp_path / "out.txt"
        target.write_text("stale", encoding="utf-8")
        exporters.write_export(target, [EPHEMERAL])
        assert "stale" not in target.read_text(encoding="utf-8")

    def test_rejects_unsupported_extensions_before_writing(self, tmp_path):
        target = tmp_path / "out.csv"
        with pytest.raises(ValueError):
            exporters.write_export(target, [EPHEMERAL])
        assert not target.exists()

    def test_utf8_round_trip(self, tmp_path):
        target = tmp_path / "out.md"
        exporters.write_export(target, [func.Entry("café", ("crème",))])
        assert "crème" in target.read_text(encoding="utf-8")
"""Unit tests for exporters.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import exporters
import functions as func

SERENDIPITY = func.Entry(
    word="serendipity",
    definitions=("the faculty of finding things", "an instance of this"),
    audio_url="https://media.example.com/serendipity.mp3",
)
EPHEMERAL = func.Entry(word="ephemeral", definitions=("short-lived",))
EMPTY = func.Entry(word="hollow", definitions=())


class TestRenderText:
    def test_single_definition_is_printed_under_the_upper_cased_word(self):
        assert exporters.render_text([EPHEMERAL]) == "EPHEMERAL\nshort-lived\n"

    def test_multiple_definitions_are_numbered(self):
        assert exporters.render_text([SERENDIPITY]) == (
            "SERENDIPITY\n"
            "Entry 1: the faculty of finding things\n"
            "Entry 2: an instance of this\n"
        )

    def test_entries_are_separated_by_a_blank_line(self):
        text = exporters.render_text([EPHEMERAL, EPHEMERAL])
        assert text == "EPHEMERAL\nshort-lived\n\nEPHEMERAL\nshort-lived\n"

    def test_an_entry_without_definitions_says_so(self):
        assert "NO DEFINITION FOUND" in exporters.render_text([EMPTY])

    def test_a_colon_inside_an_unprefixed_definition_is_not_mistaken_for_a_marker(
        self,
    ):
        entry = func.Entry("w", ("first", "second: with a colon"))
        assert "Entry 2: second: with a colon" in exporters.render_text([entry])


class TestRenderMarkdown:
    def test_heading_numbered_list_and_audio_link(self):
        assert exporters.render_markdown([SERENDIPITY]) == (
            "# serendipity\n"
            "\n"
            "1. the faculty of finding things\n"
            "2. an instance of this\n"
            "\n"
            "[Pronunciation audio](https://media.example.com/serendipity.mp3)\n"
        )

    def test_no_audio_line_when_there_is_no_recording(self):
        assert "Pronunciation" not in exporters.render_markdown([EPHEMERAL])

    def test_an_entry_without_definitions_says_so(self):
        assert "_No definition found._" in exporters.render_markdown([EMPTY])

    def test_entries_are_separated_by_a_blank_line(self):
        text = exporters.render_markdown([EPHEMERAL, EMPTY])
        assert "1. short-lived\n\n# hollow" in text


class TestRenderJson:
    def test_always_an_array_even_for_one_entry(self):
        assert isinstance(json.loads(exporters.render_json([EPHEMERAL])), list)

    def test_schema(self):
        assert json.loads(exporters.render_json([SERENDIPITY, EPHEMERAL])) == [
            {
                "word": "serendipity",
                "definitions": ["the faculty of finding things", "an instance of this"],
                "audio_url": "https://media.example.com/serendipity.mp3",
            },
            {"word": "ephemeral", "definitions": ["short-lived"], "audio_url": None},
        ]

    def test_non_ascii_text_is_not_escaped(self):
        assert "café" in exporters.render_json([func.Entry("café", ("x",))])

    def test_ends_with_a_newline_for_shell_friendliness(self):
        assert exporters.render_json([EPHEMERAL]).endswith("\n")


class TestRender:
    @pytest.mark.parametrize("fmt", exporters.FORMATS)
    def test_every_advertised_format_is_supported(self, fmt):
        assert exporters.render([EPHEMERAL], fmt)

    def test_unknown_format_raises_value_error(self):
        with pytest.raises(ValueError, match="unsupported format"):
            exporters.render([EPHEMERAL], "xml")


class TestFormatForPath:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [("a.txt", "text"), ("a.md", "md"), ("a.json", "json"), ("A.JSON", "json")],
    )
    def test_maps_extensions(self, name, expected):
        assert exporters.format_for_path(Path(name)) == expected

    @pytest.mark.parametrize("name", ["a.csv", "a", "a.json.bak"])
    def test_rejects_other_extensions(self, name):
        with pytest.raises(ValueError, match="extension must be one of"):
            exporters.format_for_path(Path(name))


class TestWriteExport:
    @pytest.mark.parametrize("name", ["out.txt", "out.md", "out.json"])
    def test_writes_the_format_implied_by_the_extension(self, tmp_path, name):
        target = tmp_path / name
        exporters.write_export(target, [SERENDIPITY])
        fmt = exporters.format_for_path(target)
        assert target.read_text(encoding="utf-8") == exporters.render(
            [SERENDIPITY], fmt
        )

    def test_overwrites_an_existing_file(self, tmp_path):
        target = tmp_path / "out.txt"
        target.write_text("stale", encoding="utf-8")
        exporters.write_export(target, [EPHEMERAL])
        assert "stale" not in target.read_text(encoding="utf-8")

    def test_rejects_unsupported_extensions_before_writing(self, tmp_path):
        target = tmp_path / "out.csv"
        with pytest.raises(ValueError):
            exporters.write_export(target, [EPHEMERAL])
        assert not target.exists()

    def test_utf8_round_trip(self, tmp_path):
        target = tmp_path / "out.md"
        exporters.write_export(target, [func.Entry("café", ("crème",))])
        assert "crème" in target.read_text(encoding="utf-8")
