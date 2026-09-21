<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
# Table of Contents

- [Aim](#aim)
- [Modules](#modules)
- [Implementation](#implementation)
- [Installation](#installation)
- [Usage](#usage)
- [Command-Line Mode](#command-line-mode)
- [Testing](#testing)
- [Development](#development)
- [Tree Structure](#tree-structure)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

# Aim

In this project, I will propose a program that simulates a dictionary.
Specifically, I will web scrap an online dictionary
[Merriam-Webster](https://www.merriam-webster.com/) - and extracts data from it,
printing out the definition(s) as the user inputs a word. Moreover, I also
retrieve the pronunciation from the dictionary and play it if the user asks for.

# Modules

Throughout the project, I use Python's standard library together with three
third-party packages (bs4, pygame and requests) which the user has to install
in order to run the program.

1. time - its sleep() function gives a short break (0.5 second) between each
   major part of the interactive session, and between network requests in
   command-line mode.
1. argparse – defines the command-line options (see
   [Command-Line Mode](#command-line-mode)).
1. bs4 – its BeautifulSoup() function pulls data out of HTML files of the
   website.
1. pygame – its mixer module plays the mp3 file (pronunciation file).
    - It is imported only when audio is requested: pygame prints a banner when
      imported, which would corrupt piped output, and it is not needed for
      plain lookups. There are no pygame wheels for Python 3.14 yet, so there
      the program simply runs without audio.
1. requests - its get() function allows for the exchange of HTTP requests. It
   also downloads the pronunciation file, with a timeout and a size limit.
1. functions - this is a user-defined module that contains the reusable helpers
   which I separate from the main program to improve code legibility, code reuse
   and unit-testability.
1. page_cache, word_history, exporters and atomic_io - user-defined modules for
   the on-disk page cache, the lookup log, the .txt / .md / .json output, and
   crash-safe file writing. They only use the standard library.

# Implementation

To make the program more like a dictionary, before getting into any definition,
I make a welcome statement and show the top lookup today. I get the URL of the
website, then use the requests and bs4 module to extract the HTML data from the
page. Then, I search through the HTML data to find the *a* tag which contains
the information /word-of-the-day. Since the one I want to find is the third *a*
tag containing the information /word-of-the-day, I use the *find_next()*
function twice to find it. Lastly, I use the *get_text()* function to get
the actual information without any HTML – which is the word of the day I am
looking for.

I use a similar procedure to find the definition. Some slight differences are:

- Ask the user to enter a word, then utilise the order of the URL, which is
  <https://www.merriam-webster.com/dictionary/{word}>, I just need to add the
  inputted word into the last curly brackets. Then I can get the URL to the
  entry of that word.
- I rule out word that is not in the dictionary by checking whether the "false"
  message "isn't in the dictionary" is in the HTML data extracted from the URL.
  If yes, I use a while loop to keep inviting the user to re-enter a word until
  the "false" message is not in the extracted HTML data.
- After having a valid word, I use the defined function *find_all_definitions()*
  to collect every *dtText* element in the HTML data. A single definition is
  printed as it is; several are numbered ("Entry 1", "Entry 2", ...).

Lastly, I use the defined function called *extract_mp3_url()* to return the URL
of the mp3 of the word’s pronunciation. I simply assign the argument text, which
is the HTML data of the word in the dictionary, to the function and locate the
text "contentURL". Because that URL comes from a web page, the function only
accepts an https:// address. After receiving the URL, I will ask the user
whether they want to hear the pronunciation. If yes, I will use the
*download_audio()* function to download the recording to the same folder as
this program and name it word_to_pronounce.mp3. After that, I will use the
*mixer.init()*, *mixer.music.load()*, *mixer.music.play()* functions from the
pygame library to play it. I then use a while loop to keep asking whether the
user wants to re-play the pronunciation.  The loop stops if the user inputs 'n'
or 'N'. The try block is used to test the mp3 URL, and the except block is used
to handle the error where the recording is not available – which means there is
not any pronunciation available for this word. This situation usually happens
with phrases and abbreviations. In this case, I will just send a message saying
sorry to the user.

The dictionary program culminates with a little thank you note.

# Installation

```bash
git clone https://github.com/tanducmai/web-scraping-dictionary.git
cd web-scraping-dictionary
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

# Usage

```bash
python3 main.py
```

You'll see today's Word of the Day, then be prompted to look up a word. If a
pronunciation recording is available, you can choose to play it. To use the
program from scripts and pipes instead, see [Command-Line Mode](#command-line-mode).

# Command-Line Mode

Give the program a word (or a list of words) and it runs without any prompts.
Only the results go to stdout; warnings and errors go to stderr, so the output
is safe to pipe.

```bash
python3 main.py --word serendipity                    # definitions on stdout
python3 main.py -w serendipity -w ephemeral --format json | jq .
python3 main.py --word-list words.txt --output definitions.md
cat words.txt | python3 main.py --word-list - --format json
python3 main.py --word serendipity --pronounce        # also plays the audio
python3 main.py --history                             # every lookup so far
python3 main.py --help
```

| Option | What it does |
| --- | --- |
| `-w`, `--word WORD` | Word or phrase to look up. Repeat it for several words. |
| `-l`, `--word-list FILE` | Look up every word in a text file (`-` reads stdin). |
| `-p`, `--pronounce` | Download and play each word's pronunciation (needs pygame). |
| `-o`, `--output FILE` | Write the results to `FILE` (`.txt`, `.md` or `.json`) instead of stdout. |
| `-f`, `--format {text,md,json}` | Format for stdout (default `text`). |
| `--history` | Print the lookup history and exit. |
| `--no-history` | Do not record this run in the history. |
| `--no-cache` | Neither read nor write the page cache. |
| `--cache-ttl SECONDS` | How long a cached page stays valid (default one week; `0` forces a refresh). |
| `--delay SECONDS` | Minimum pause between network requests (default 0.5). |
| `--data-dir DIR` | Where the history and cache are kept (default: the program folder, or `$DICTIONARY_DATA_DIR`). |
| `-v`, `--verbose` | Log cache hits and requests to stderr (`-vv` for more). |

## Batch lookups

A word list is a plain text file with one word or phrase per line. Blank lines
and lines starting with `#` are ignored, and repeated words (in any letter
case) are looked up once. A line that is not a valid word stops the run before
any request is made, and the error names the line number.

## Exporting

`--output` picks the format from the file extension:

- `.txt` – the word in capitals, followed by its definitions.
- `.md` – a heading per word, a numbered list, and a link to the audio.
- `.json` – an array of `{"word", "definitions", "audio_url"}` objects. The same
  structure is printed with `--format json`, and `audio_url` is always
  included, so a script can fetch the recording itself.

An existing file is overwritten, but never when every lookup failed.

## History

Every lookup is appended to `word_history.json` with a UTC timestamp and whether
the word was found. Lookups answered from the cache count too; lookups that
failed because of the network do not. The tool only ever adds entries: the file
stays a valid JSON array (it is rewritten atomically on each lookup), and a file
that cannot be parsed is moved aside to `word_history.json.corrupt-<time>`
rather than overwritten. The file is listed in `.gitignore`. Use `--history`
(tab-separated: timestamp, word, `found`/`not-found`) or
`--history --format json` to read it.

## Caching

The HTML of every word page that was found is kept in the `.cache/` folder as
one small gzip-compressed JSON file per word, and reused until it is older than
`--cache-ttl`. The homepage (Word of the Day) is never cached, and neither are
unknown words. A damaged cache file is simply ignored and replaced. Delete the
`.cache/` folder to start afresh.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Every lookup succeeded. |
| 1 | A lookup, download or file write failed (for example an unknown word or no network). |
| 2 | Invalid command line or word-list file. |

# Testing

Install the development dependencies (this includes the runtime ones) and run
the test suite:

```bash
pip install -r requirements-dev.txt
pytest
```

Tests never contact the real Merriam-Webster website — all HTTP calls are
mocked — so they run quickly and deterministically. `pytest` fails if coverage
drops below the floor set in `pyproject.toml`. `ruff`, `black --check`, and
`mypy` are also available for linting, formatting, and type checking; to run
them automatically before each commit, use `pip install pre-commit &&
pre-commit install`.

# Development

CI runs on every pull request and push via GitHub Actions
(`.github/workflows/ci.yml`): linting, formatting, type checking, tests
across Python 3.10-3.14, a smoke test of the command line, and a dependency
vulnerability scan. Alongside it: CodeQL, a dependency review of pull requests,
a secret scan, and an OpenSSF Scorecard run. Pushing a tag such as `v1.0.0`
publishes a GitHub release with a CycloneDX SBOM (`release.yml`); the tag must
match `version` in `pyproject.toml`. Dependabot keeps dependencies and actions
current.

**A note on scraping:** this project fetches pages from
merriam-webster.com for personal/educational use. Please review the site's
terms of service before deploying it at any scale or frequency beyond
occasional personal lookups.

# Tree Structure

```
.
├── .github/
│   ├── CODEOWNERS
│   ├── dependabot.yml
│   ├── pull_request_template.md
│   └── workflows/
│       ├── ci.yml
│       ├── codeql.yml
│       ├── dependency-review.yml
│       ├── release.yml
│       ├── scorecard.yml
│       └── secret-scan.yml
├── tests/
│   ├── test_atomic_io.py
│   ├── test_cli.py
│   ├── test_exporters.py
│   ├── test_functions.py
│   ├── test_main.py
│   ├── test_page_cache.py
│   └── test_word_history.py
├── .gitignore
├── .pre-commit-config.yaml
├── LICENSE
├── README.md
├── SECURITY.md
├── atomic_io.py
├── exporters.py
├── functions.py
├── main.py
├── page_cache.py
├── pyproject.toml
├── requirements-dev.txt
├── requirements.txt
├── video_production.mp4
└── word_history.py
```
