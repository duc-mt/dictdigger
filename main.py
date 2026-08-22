#!/usr/bin/python3
# -*- coding: utf-8 -*-

# =============================================================================
#
#        FILE:  main.py
#      AUTHOR:  Tan Duc Mai <henryfromvietnam@gmail.com>
#     CREATED:  2021-08-20
# DESCRIPTION:  Retrieve the content of Merriam-Webster online dictionary.
#   I hereby declare that I completed this work without any improper help
#   from a third party and without using any aids other than those cited.
#
# =============================================================================

# ------------------------------- Module Imports ------------------------------
"""Description of all imported modules.

The urllib.request module - urlretrieve() function - retrieves the content of
a URL directly into a local location on disk. Used to download the
pronunciation mp3.

The bs4 module - BeautifulSoup() class - parses the HTML of the website.

The pygame module - mixer submodule - loads and plays the downloaded
pronunciation mp3 file.

The requests module - RequestException - is caught so that network problems
produce a friendly message instead of a crash.

The functions module - a user-defined module - contains reusable helpers
that are separated from the main program to improve legibility, reuse, and
unit-testability.
"""
from __future__ import annotations

import sys
from urllib.error import ContentTooShortError, URLError
from urllib.request import urlretrieve

import requests
from bs4 import BeautifulSoup
from pygame import mixer

import functions as func

ACCEPTABLE_RESPONSES = ("Y", "y", "N", "n", "")
MP3_FILENAME = "word_to_pronounce.mp3"


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


# ------------------------------- Program Steps --------------------------------
def show_word_of_the_day() -> None:
    """Print today's featured word. Prints a friendly message on failure
    instead of crashing, since this is a non-essential nicety."""
    try:
        _, soup = func.fetch_page()
        print("Word of the Day:", func.get_word_of_the_day(soup))
    except (requests.exceptions.RequestException, ValueError) as exc:
        print(f"(Could not retrieve the Word of the Day: {exc})")


def look_up_word() -> tuple[str, str, BeautifulSoup]:
    """Prompt for a word until a valid dictionary entry is fetched.

    Returns:
        The validated word, the raw page HTML, and the parsed page.
    """
    word = prompt_non_empty("Search for a Word: ")
    while True:
        try:
            text, soup = func.fetch_page(word)
        except requests.exceptions.RequestException as exc:
            print(f"Network error while looking up '{word}': {exc}\n")
            word = prompt_non_empty("Try again: ")
            continue

        if func.word_exists(text):
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
        urlretrieve(mp3_url, MP3_FILENAME)
    except (URLError, ContentTooShortError, OSError) as exc:
        print(f"Could not download the pronunciation audio: {exc}")
        return

    mixer.init()
    try:
        while pronounce == "" or pronounce.lower() == "y":
            mixer.music.load(MP3_FILENAME)
            mixer.music.play()
            pronounce = prompt_yes_no("One more time? [Y/n] ")
    finally:
        mixer.quit()


# ------------------------------- Main Function -------------------------------
def main() -> int:
    func.draw_line_break()
    print("Welcome to the Dictionary of Merriam-Webster")
    func.draw_line_break()

    show_word_of_the_day()

    func.draw_line_break()
    word, text, soup = look_up_word()

    func.draw_line_break()
    show_definition(word, soup)

    func.draw_line_break()
    offer_pronunciation(text)

    func.draw_line_break()
    print("Thank you for using our translation service!")
    func.draw_line_break()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nGoodbye!")
        sys.exit(130)
