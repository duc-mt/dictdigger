<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
# Table of Contents

- [Aim](#aim)
- [Modules](#modules)
- [Implementation](#implementation)
- [Installation](#installation)
- [Usage](#usage)
- [Command-Line Mode](#command-line-mode)
- [Web Interface](#web-interface)
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
Besides the interactive prompt, the program also runs as a one-shot command line
tool (see [Command-Line Mode](#command-line-mode)) and as a small local website
(see [Web Interface](#web-interface)).

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
   the on-disk cache, the lookup log, the .txt / .md / .json output, and
   crash-safe file writing. They only use the standard library.
1. web_server and web_views - user-defined modules for the
   [web interface](#web-interface). web_server is the HTTP layer, built on
   `http.server` from the standard library alone (no framework, no third-party
   dependency); web_views turns a lookup into an HTML page. Every value from a
   scraped page or from a visitor is escaped in web_views before it reaches a
   page, so a word or a definition can never inject markup.

# Implementation

To make the program more like a dictionary, before getting into any definition,
I make a welcome statement. To find a definition, I get the URL of the website,
then use the requests and bs4 modules to extract the HTML data from the page and
search through it. The steps are:

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
git clone https://github.com/duc-mt/dictionary-web-scraping-machine.git
cd web-scraping-dictionary
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Audio playback (`--pronounce`, and the pronunciation prompt) needs `pygame`,
which is optional: everything else works without it. `requirements.txt` skips it
on Python 3.14, which has no pygame build yet. If `pip` tries to compile pygame
and fails (`SDL.h file not found`), install the other packages instead, or use
Python 3.13 or older:

```bash
pip install beautifulsoup4==4.15.0 requests==2.34.2
```

If the website answers `403 Forbidden`, see
[If you get HTTP 403](#if-you-get-http-403).

# Usage

```bash
python3 main.py
```

You'll be prompted to look up a word. If a
pronunciation recording is available, you can choose to play it. To use the
program from scripts and pipes instead, see [Command-Line Mode](#command-line-mode);
to use it from a browser instead, see [Web Interface](#web-interface).

## If you get HTTP 403

merriam-webster.com sometimes refuses scripted requests with `403 Forbidden`. It
looks intermittent: on one machine every lookup was refused at first, and later
the same machine could look words up again. I do not know what triggers it, and
there is nothing to configure. Wait a while and try again; words you have already
looked up come from the [cache](#caching) and need no request. For a long word
list, raise `--delay` to be gentler on the site. Requests identify themselves
with a browser-compatible `User-Agent`, which you can replace with the
`DICTIONARY_USER_AGENT` environment variable. (Press Ctrl-C to leave the
interactive prompt.)

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

The HTML of every word page that was found is kept in the `.cache/` folder as one
small gzip-compressed JSON file per word, and reused until it is older than
`--cache-ttl`. Unknown words and failed requests are never cached. A damaged
cache file is simply ignored and replaced. Delete the `.cache/` folder to start
afresh.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Every lookup succeeded. |
| 1 | A lookup, download or file write failed (for example an unknown word or no network). |
| 2 | Invalid command line or word-list file. |

# Web Interface

```bash
python3 main.py --serve
```

This starts a small website on your own computer at `http://127.0.0.1:8000/`
(add `--open` to launch your browser automatically). It has three pages:

- **Search** (`/`) - a search box; recently found words are listed below it.
- **Batch** (`/batch`) - paste a list of words (same rules as
  [Batch lookups](#batch-lookups)) and either see them all on the page or
  download them as `.txt`, `.md` or `.json`.
- **History** (`/history`) - the same log as `--history`, as a table.

There is no login, no account, and no JavaScript: every page is plain HTML
and works with images and scripts turned off. The definitions still come from
merriam-webster.com, so the same [HTTP 403](#if-you-get-http-403) note applies,
and every page it serves goes through the same cache, rate limiter and history
as the command line.

**This is meant for you, alone, on your own computer.** By default the server
only answers `127.0.0.1` (this machine) and refuses requests where the `Host`
header, `Origin`, or `Sec-Fetch-Site` don't match, which is enough to stop a
malicious web page from using your browser to reach it. It is not enough to put
on the open internet: there is no login, so `--host 0.0.0.0` or a
reverse-proxied public deployment would let anyone who can reach it look up
words as you and read your history. `--host` and `--port` are there for
reaching it from another device on your own network (a phone on the same
Wi-Fi, say), not for exposing it publicly. The connection is also plain HTTP,
with no encryption, so on a shared or untrusted network the words you look up
and your history are visible to anyone who can observe that network segment —
there's no password to steal, but the traffic itself isn't private.

| Option | What it does |
| --- | --- |
| `--serve` | Start the web interface instead of a lookup. |
| `--host ADDRESS` | Address to listen on (default `127.0.0.1`, this computer only). |
| `--port PORT` | Port to listen on (default `8000`; `0` picks a free one). |
| `--open` | Open the web interface in your default browser. |

`--serve` cannot be combined with `--word`, `--word-list`, `--history`,
`--output`, `--format` or `--pronounce`; `--no-history`, `--no-cache`,
`--cache-ttl`, `--delay` and `--data-dir` all apply as they do on the command
line. Stop the server with Ctrl-C.

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
├── static/
│   ├── favicon.svg
│   └── style.css
├── tests/
│   ├── test_atomic_io.py
│   ├── test_cli.py
│   ├── test_exporters.py
│   ├── test_functions.py
│   ├── test_main.py
│   ├── test_page_cache.py
│   ├── test_web_server.py
│   ├── test_web_views.py
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
├── web_server.py
├── web_views.py
└── word_history.py
```
