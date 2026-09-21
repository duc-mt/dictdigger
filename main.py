#!/usr/bin/python3
# -*- coding: utf-8 -*-

# =============================================================================
#
#        FILE:  main.py
#      AUTHOR:  Mai Tan Duc <ducmai.network@gmail.com>
#     CREATED:  2021-08-20
# DESCRIPTION:  Retrieve the content of Merriam-Webster online dictionary.
#
# =============================================================================

# ------------------------------- Module Imports ------------------------------
"""Description of all imported modules.

The argparse module - ArgumentParser class - defines the command-line
interface, so the program can also run without prompting (scripts, pipes, cron).

The bs4 module - BeautifulSoup() class - parses the HTML of the website.

The pygame module - mixer submodule - loads and plays the downloaded
pronunciation mp3 file. It is imported only when audio is requested: pygame
prints a banner to stdout on import, which would corrupt piped output, and
plain lookups do not need it.

The requests module - RequestException - is caught so that network problems
produce a friendly message instead of a crash.

The functions module - a user-defined module - contains reusable helpers
that are separated from the main program to improve legibility, reuse, and
unit-testability. The page_cache, word_history, and exporters modules follow
the same idea for the on-disk page cache, the lookup log, and the .txt / .md /
.json output respectively.
"""
from __future__ import annotations

import argparse
import functools
import json
import logging
import math
import os
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from time import sleep
from types import ModuleType

import requests
from bs4 import BeautifulSoup

import exporters
import functions as func
from page_cache import DEFAULT_TTL_SECONDS, HtmlCache
from word_history import HISTORY_FILENAME, WordHistory

logger = logging.getLogger(__name__)

ACCEPTABLE_RESPONSES = ("Y", "y", "N", "n", "")
MP3_FILENAME = "word_to_pronounce.mp3"
CACHE_DIRNAME = ".cache"
DATA_DIR_ENV_VAR = "DICTIONARY_DATA_DIR"
DEFAULT_DATA_DIR = Path(__file__).resolve().parent
EXIT_OK = 0
EXIT_FAILED = 1  # a lookup, download, or file write did not succeed
EXIT_USAGE = 2  # bad command line or word-list file (argparse also uses 2)


# ------------------------------ Input Helpers ---------------------------------
def prompt_non_empty(prompt: str) -> str:
    """Repeatedly ask the user for input until they provide a non-empty value."""
    value = ""
    while not value:
        value = input(prompt).strip()
        if not value:
            print("Please Enter a non-empty word.", end="\n\n")
    return value


def prompt_yes_no(prompt: str) -> str:
    """Ask a yes/no question, re-prompting until an acceptable answer is given."""
    response = None
    while response not in ACCEPTABLE_RESPONSES:
        response = input(prompt)
        if response not in ACCEPTABLE_RESPONSES:
            print("Please Enter an appropriate command.", end="\n\n")
    return response


# ------------------------------- Audio Helpers --------------------------------
def load_mixer() -> ModuleType:
    """Import pygame's mixer on demand (see the module notes above).

    Raises:
        ImportError: If pygame is not installed.
    """
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    from pygame import mixer

    return mixer


def play_audio(path: Path, *, mixer: ModuleType | None = None) -> None:
    """Play an audio file and block until it has finished.

    Raises:
        ImportError: If pygame is not installed.
        RuntimeError: If there is no usable audio device (pygame.error).
    """
    mixer = mixer or load_mixer()
    mixer.init()
    try:
        mixer.music.load(str(path))
        mixer.music.play()
        while mixer.music.get_busy():
            sleep(0.1)
    finally:
        mixer.quit()


# ------------------------------- Program Steps --------------------------------
def show_word_of_the_day() -> None:
    """Print today's featured word. Prints a friendly message on failure
    instead of crashing, since this is a non-essential nicety."""
    try:
        _, soup = func.fetch_page()
        print("Word of the Day:", func.get_word_of_the_day(soup))
    except (requests.exceptions.RequestException, ValueError) as exc:
        print(f"(Could not retrieve the Word of the Day: {exc})")


def look_up_word(
    fetch: func.Fetcher | None = None, history: WordHistory | None = None
) -> tuple[str, str, BeautifulSoup]:
    """Prompt for a word until a valid dictionary entry is fetched.

    Args:
        fetch: Callable returning ``(html, soup)`` for a word; defaults to
            ``func.fetch_page``. Pass a wrapper to add caching or throttling.
        history: Optional log that every attempted word is recorded in.

    Returns:
        The validated word, the raw page HTML, and the parsed page.
    """
    fetch = fetch or func.fetch_page  # resolved at call time so tests can patch it
    word = prompt_non_empty("Search for a Word: ")
    while True:
        found = True
        try:
            text, soup = fetch(word)
            found = func.word_exists(text)
        except requests.exceptions.RequestException as exc:
            if not func.is_not_found_error(exc):
                print(f"Network error while looking up '{word}': {exc}\n")
                word = prompt_non_empty("Try again: ")
                continue
            found = False  # HTTP 404: the dictionary has no such entry

        record_history(history, word, found=found)
        if found:
            return word, text, soup

        print(f"The word you've entered, \"{word}\", isn't in the dictionary.\n")
        word = prompt_non_empty("Try again: ")


def show_definition(word: str, soup: BeautifulSoup) -> None:
    """Print the definition(s) of an already-validated word."""
    print(f"-> Definition of {word.upper()}:", end="\n\n")
    definitions = func.find_all_definitions(soup)
    print(func.format_definitions(definitions))


def offer_pronunciation(text: str) -> None:
    """Offer to download and play the word's pronunciation, if available."""
    try:
        mp3_url = func.extract_mp3_url(text)
    except ValueError as exc:
        print(f"Sorry! {exc}.")
        return

    pronounce = prompt_yes_no("Do you want to hear its pronunciation? [Y/n] ")
    if pronounce.lower() == "n":
        return

    try:
        func.download_audio(mp3_url, MP3_FILENAME)
    except (requests.exceptions.RequestException, OSError, ValueError) as exc:
        print(f"Could not download the pronunciation audio: {exc}")
        return

    try:
        mixer = load_mixer()
        mixer.init()
    except (ImportError, RuntimeError) as exc:  # no pygame, or no audio device
        print(f"Could not start audio playback: {exc}")
        return
    try:
        while pronounce == "" or pronounce.lower() == "y":
            mixer.music.load(MP3_FILENAME)
            mixer.music.play()
            pronounce = prompt_yes_no("One more time? [Y/n] ")
    finally:
        mixer.quit()


# ------------------------------ History & Output ------------------------------
def record_history(history: WordHistory | None, word: str, *, found: bool) -> None:
    """Log a lookup. The log is a convenience, so a failure only warns."""
    if history is None:
        return
    try:
        history.record(word, found=found)
    except OSError as exc:
        logger.warning("could not update the word history: %s", exc)


def show_history(history: WordHistory, fmt: str) -> int:
    """Print the lookup log: tab-separated text (default) or a JSON array."""
    records = history.read()
    if fmt == "json":
        print(json.dumps([asdict(r) for r in records], indent=2, ensure_ascii=False))
        return EXIT_OK
    for record in records:
        status = "found" if record.found else "not-found"
        print(f"{record.timestamp}\t{record.word}\t{status}")
    if not records:
        logger.warning("no lookups have been recorded yet")
    return EXIT_OK


def emit_results(entries: Sequence[func.Entry], output: Path | None, fmt: str) -> None:
    """Write results to ``output`` if given, otherwise to stdout."""
    if output is not None:
        exporters.write_export(output, entries)
        logger.info("wrote %d entries to %s", len(entries), output)
    else:
        sys.stdout.write(exporters.render(entries, fmt))


# ------------------------------ Command-Line Mode -----------------------------
EXAMPLES = """\
exit codes:
  0  every lookup succeeded
  1  a lookup, download, or file write failed (e.g. unknown word, no network)
  2  invalid command line or word-list file

examples:
  python main.py --word serendipity
  python main.py -w serendipity -w ephemeral --format json | jq .
  python main.py --word-list words.txt --output definitions.md
  cat words.txt | python main.py --word-list - --format json
  python main.py --word serendipity --pronounce
  python main.py --history

With no lookup options an interactive session starts. Results go to stdout;
warnings and errors go to stderr, so the output is safe to pipe.
"""


def non_negative_float(value: str) -> float:
    """argparse type: a number of seconds that is zero or greater."""
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid number: {value!r}") from None
    if math.isnan(number) or number < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return number


def build_parser() -> argparse.ArgumentParser:
    """Define the command-line interface."""
    parser = argparse.ArgumentParser(
        description="Look up definitions on Merriam-Webster.",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    lookup = parser.add_argument_group("lookup")
    lookup.add_argument(
        "-w",
        "--word",
        action="append",
        metavar="WORD",
        help="word or phrase to look up (repeat for several)",
    )
    lookup.add_argument(
        "-l",
        "--word-list",
        metavar="FILE",
        help="text file with one word per line ('-' reads stdin); blank lines "
        "and lines starting with # are ignored, duplicates are dropped",
    )
    lookup.add_argument(
        "-p",
        "--pronounce",
        action="store_true",
        help="download and play each word's pronunciation (needs pygame)",
    )

    output = parser.add_argument_group("output")
    output.add_argument(
        "-o",
        "--output",
        type=Path,
        metavar="FILE",
        help="write results to FILE instead of stdout; the format follows the "
        "extension (.txt, .md or .json)",
    )
    output.add_argument(
        "-f",
        "--format",
        choices=exporters.FORMATS,
        help="format for stdout (default: text); with --history only text and "
        "json apply",
    )

    history = parser.add_argument_group("history")
    history.add_argument(
        "--history",
        action="store_true",
        help="print the lookup history (timestamp, word, status) and exit",
    )
    history.add_argument(
        "--no-history",
        action="store_true",
        help="do not record this run's lookups in the history log",
    )

    network = parser.add_argument_group("caching and network")
    network.add_argument(
        "--no-cache",
        action="store_true",
        help="neither read nor write the local page cache",
    )
    network.add_argument(
        "--cache-ttl",
        type=non_negative_float,
        default=DEFAULT_TTL_SECONDS,
        metavar="SECONDS",
        help="how long a cached page stays valid (default: %(default)s, one "
        "week); 0 forces a refresh",
    )
    network.add_argument(
        "--delay",
        type=non_negative_float,
        default=func.DEFAULT_REQUEST_DELAY,
        metavar="SECONDS",
        help="minimum pause between network requests (default: %(default)s); "
        "cached lookups never wait",
    )

    misc = parser.add_argument_group("other")
    misc.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.environ.get(DATA_DIR_ENV_VAR, DEFAULT_DATA_DIR)),
        metavar="DIR",
        help=f"where {HISTORY_FILENAME} and the {CACHE_DIRNAME}/ folder live "
        f"(default: the program folder, or ${DATA_DIR_ENV_VAR})",
    )
    misc.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="log cache hits and requests to stderr (-vv for debug detail)",
    )
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Reject option combinations that make no sense, then fill in defaults."""
    lookups = bool(args.word or args.word_list)

    if args.history:
        if lookups or args.output or args.pronounce:
            parser.error("--history cannot be combined with lookup options")
        if args.format == "md":
            parser.error("--history supports --format text or json")
    elif not lookups:
        for flag, given in (
            ("--output", args.output),
            ("--format", args.format),
            ("--pronounce", args.pronounce),
        ):
            if given:
                parser.error(f"{flag} requires --word or --word-list")

    if args.output is not None:
        try:
            derived = exporters.format_for_path(args.output)
        except ValueError as exc:
            parser.error(str(exc))
        if args.format and args.format != derived:
            parser.error(f"--format {args.format} conflicts with {args.output.name}")
        args.format = derived
    args.format = args.format or "text"


def configure_logging(verbosity: int) -> None:
    """Send diagnostics to stderr; ``-v`` adds INFO, ``-vv`` adds DEBUG."""
    level = (logging.WARNING, logging.INFO, logging.DEBUG)[min(verbosity, 2)]
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def read_word_list(source: str) -> str:
    """Return the text of a word-list file, or of stdin when ``source`` is ``-``."""
    if source == "-":
        return sys.stdin.read()
    return Path(source).read_text(encoding="utf-8-sig")  # tolerate a BOM


def collect_words(args: argparse.Namespace) -> list[str]:
    """Gather, validate, and de-duplicate the words named on the command line.

    Raises:
        ValueError: If a word or a word-list line is invalid.
        OSError: If the word-list file cannot be read.
    """
    words = [func.normalize_word(word) for word in args.word or []]
    if args.word_list:
        words.extend(func.parse_word_list(read_word_list(args.word_list)))
    return func.unique_words(words)


def pronounce_entries(entries: Sequence[func.Entry]) -> None:
    """Download and play each entry's pronunciation, one after the other."""
    with tempfile.TemporaryDirectory(
        prefix="dictionary-audio-", ignore_cleanup_errors=True
    ) as folder:
        for index, entry in enumerate(entries):
            if entry.audio_url is None:
                logger.warning("no pronunciation is available for %r", entry.word)
                continue
            clip = Path(folder) / f"{index}.mp3"  # never build paths from words
            try:
                func.download_audio(entry.audio_url, clip)
                play_audio(clip)
            except ImportError as exc:
                logger.warning("audio playback needs pygame: %s", exc)
                return
            except (
                requests.exceptions.RequestException,
                OSError,
                ValueError,
                RuntimeError,
            ) as exc:
                logger.warning(
                    "could not play the pronunciation of %r: %s", entry.word, exc
                )


def run_cli(
    args: argparse.Namespace, *, fetch: func.Fetcher, history: WordHistory | None
) -> int:
    """Look up every requested word without prompting and emit the results."""
    try:
        words = collect_words(args)
    except (ValueError, OSError) as exc:
        logger.error("%s", exc)
        return EXIT_USAGE
    if not words:
        logger.error("no words to look up")
        return EXIT_USAGE

    entries: list[func.Entry] = []
    failures = 0
    for word in words:
        try:
            entry = func.lookup_word(word, fetch=fetch)
        except func.WordNotFoundError:
            logger.error("%r isn't in the dictionary", word)
            record_history(history, word, found=False)
            failures += 1
        except requests.exceptions.RequestException as exc:
            logger.error("network error while looking up %r: %s", word, exc)
            failures += 1
        else:
            record_history(history, word, found=True)
            entries.append(entry)

    if entries:
        try:
            emit_results(entries, args.output, args.format)
        except OSError as exc:
            logger.error("could not write the results: %s", exc)
            return EXIT_FAILED
        if args.pronounce:
            pronounce_entries(entries)
    return EXIT_FAILED if failures else EXIT_OK


# ------------------------------ Interactive Mode ------------------------------
def run_interactive(*, fetch: func.Fetcher, history: WordHistory | None) -> int:
    """The original prompt-driven session: welcome, look up one word, say bye."""
    func.draw_line_break()
    print("Welcome to the Dictionary of Merriam-Webster")
    func.draw_line_break()

    show_word_of_the_day()

    func.draw_line_break()
    word, text, soup = look_up_word(fetch=fetch, history=history)

    func.draw_line_break()
    show_definition(word, soup)

    func.draw_line_break()
    offer_pronunciation(text)

    func.draw_line_break()
    print("Thank you for using our translation service!")
    func.draw_line_break()
    return EXIT_OK


# ------------------------------- Main Function -------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_args(parser, args)
    configure_logging(args.verbose)

    history_log = WordHistory(args.data_dir / HISTORY_FILENAME)
    if args.history:
        return show_history(history_log, args.format)

    history = None if args.no_history else history_log
    cache = (
        None
        if args.no_cache
        else HtmlCache(args.data_dir / CACHE_DIRNAME, ttl=args.cache_ttl)
    )
    fetch = functools.partial(
        func.fetch_page, cache=cache, limiter=func.RateLimiter(args.delay)
    )

    if args.word or args.word_list:
        return run_cli(args, fetch=fetch, history=history)
    return run_interactive(fetch=fetch, history=history)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nGoodbye!", file=sys.stderr)
        sys.exit(130)
    except EOFError:
        print("\nInput ended unexpectedly; exiting.", file=sys.stderr)
        sys.exit(EXIT_FAILED)
    except BrokenPipeError:
        # The reader (e.g. `head`) closed the pipe early. Point stdout at
        # /dev/null so Python's shutdown flush does not print a traceback.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(EXIT_FAILED)
