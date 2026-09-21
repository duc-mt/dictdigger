"""Unit tests for dictionary_api.py.

The API's reply shapes below follow its public documentation. They are hand-
written fixtures: this suite never contacts the real service.
"""

from __future__ import annotations

import json

import pytest
import requests

import dictionary_api as api
import functions as func

KEY = "abcd-1234-secret"


def make_entry_json(
    *,
    fl: str | None = "noun",
    shortdef: object = ("first sense", "second sense"),
    audio: str | None = "serend01",
) -> dict:
    entry: dict = {"meta": {"id": "word"}, "hwi": {"hw": "word"}}
    if fl is not None:
        entry["fl"] = fl
    if shortdef is not None:
        entry["shortdef"] = list(shortdef) if isinstance(shortdef, tuple) else shortdef
    if audio is not None:
        entry["hwi"]["prs"] = [{"mw": "x", "sound": {"audio": audio}}]
    return entry


class FakeResponse:
    def __init__(self, text: str = "[]", status: int = 200) -> None:
        self.text = text
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(
                f"{self.status_code} Client Error: Forbidden for url: "
                f"{api.API_URL}/word?key={KEY}",
                response=self,  # type: ignore[arg-type]
            )


class FakeCache:
    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self.store = dict(initial or {})
        self.sets: list[tuple[str, str]] = []

    def get(self, word: str) -> str | None:
        return self.store.get(word)

    def set(self, word: str, html: str) -> None:
        self.sets.append((word, html))
        self.store[word] = html


class TestAudioUrl:
    @pytest.mark.parametrize(
        ("name", "folder"),
        [
            ("serend01", "s"),
            ("bixby001", "bix"),
            ("ggrow001", "gg"),
            ("1abc0001", "number"),
            ("_abc0001", "number"),
            ("test0001", "t"),
        ],
    )
    def test_follows_the_documented_folder_rule(self, name, folder):
        assert api.audio_url(name) == f"{api.AUDIO_URL}/{folder}/{name}.mp3"

    @pytest.mark.parametrize("name", ["", "../etc/passwd", "a/b", "a b", "a.mp3", "é"])
    def test_rejects_anything_that_is_not_a_plain_file_name(self, name):
        with pytest.raises(ValueError, match="unexpected audio file name"):
            api.audio_url(name)


class TestParseEntry:
    def test_builds_an_entry_with_labelled_definitions_and_audio(self):
        payload = json.dumps([make_entry_json()])

        entry = api.parse_entry("word", payload)

        assert entry == func.Entry(
            word="word",
            definitions=("(noun) first sense", "(noun) second sense"),
            audio_url=f"{api.AUDIO_URL}/s/serend01.mp3",
        )

    def test_definitions_from_every_entry_are_combined_in_order(self):
        payload = json.dumps(
            [
                make_entry_json(fl="noun", shortdef=("a",)),
                make_entry_json(fl="verb", shortdef=("b", "c")),
            ]
        )

        entry = api.parse_entry("word", payload)

        assert entry.definitions == ("(noun) a", "(verb) b", "(verb) c")

    def test_no_label_means_no_prefix(self):
        payload = json.dumps([make_entry_json(fl=None, shortdef=("plain",))])
        assert api.parse_entry("word", payload).definitions == ("plain",)

    def test_whitespace_is_collapsed(self):
        payload = json.dumps([make_entry_json(fl=None, shortdef=("a \n  b",))])
        assert api.parse_entry("word", payload).definitions == ("a b",)

    def test_audio_comes_from_the_first_entry_that_has_one(self):
        payload = json.dumps(
            [make_entry_json(audio=None), make_entry_json(audio="test0001")]
        )
        assert api.parse_entry("word", payload).audio_url.endswith("/t/test0001.mp3")

    def test_an_unusable_audio_name_is_ignored_not_trusted(self):
        payload = json.dumps([make_entry_json(audio="../../evil")])
        assert api.parse_entry("word", payload).audio_url is None

    def test_no_audio_is_fine(self):
        payload = json.dumps([make_entry_json(audio=None)])
        assert api.parse_entry("word", payload).audio_url is None

    def test_empty_and_odd_definition_lists_are_skipped(self):
        payload = json.dumps(
            [
                make_entry_json(shortdef=None),
                make_entry_json(shortdef="not a list"),
                make_entry_json(shortdef=("", "  ", 5, "kept")),
            ]
        )
        assert api.parse_entry("word", payload).definitions == ("(noun) kept",)

    def test_an_unknown_word_yields_suggestions(self):
        payload = json.dumps(["test", "set", "tent", "text", "tempt", "tenet"])

        with pytest.raises(func.WordNotFoundError) as info:
            api.parse_entry("tset", payload)

        assert info.value.suggestions == ("test", "set", "tent", "text", "tempt")

    def test_an_empty_list_means_not_found(self):
        with pytest.raises(func.WordNotFoundError) as info:
            api.parse_entry("word", "[]")
        assert info.value.suggestions == ()

    def test_entries_without_definitions_mean_not_found(self):
        payload = json.dumps([make_entry_json(shortdef=())])
        with pytest.raises(func.WordNotFoundError):
            api.parse_entry("word", payload)

    def test_the_plain_text_reply_for_a_bad_key_is_an_api_error(self):
        with pytest.raises(api.ApiError, match="Invalid API key"):
            api.parse_entry(
                "word", "Invalid API key. Not subscribed for this reference."
            )

    def test_long_plain_text_replies_are_truncated(self):
        with pytest.raises(api.ApiError) as info:
            api.parse_entry("word", "x" * 1000)
        assert len(str(info.value)) < 200

    @pytest.mark.parametrize("payload", ['{"an": "object"}', '"a string"', "42"])
    def test_json_that_is_not_a_list_is_an_api_error(self, payload):
        with pytest.raises(api.ApiError, match="unexpected reply"):
            api.parse_entry("word", payload)


class TestFetchPayload:
    def test_sends_the_key_as_a_parameter_and_the_word_in_the_path(self, monkeypatch):
        seen = {}

        def fake_get(url, **kwargs):
            seen.update(url=url, **kwargs)
            return FakeResponse("[]")

        monkeypatch.setattr(requests, "get", fake_get)

        api.fetch_payload("ice cream", api_key=KEY)

        assert seen["url"] == f"{api.API_URL}/ice%20cream"
        assert seen["params"] == {"key": KEY}
        assert KEY not in seen["url"]
        assert seen["timeout"] == func.REQUEST_TIMEOUT

    def test_slashes_in_a_word_are_percent_encoded(self, monkeypatch):
        urls = []
        monkeypatch.setattr(
            requests, "get", lambda url, **kw: urls.append(url) or FakeResponse()
        )

        api.fetch_payload("a/../b", api_key=KEY)

        assert urls == [f"{api.API_URL}/a%2F..%2Fb"]

    def test_sends_the_user_agent(self, monkeypatch):
        monkeypatch.delenv(func.USER_AGENT_ENV_VAR, raising=False)
        seen = {}
        monkeypatch.setattr(
            requests, "get", lambda url, **kw: seen.update(kw) or FakeResponse()
        )

        api.fetch_payload("word", api_key=KEY)

        assert seen["headers"] == {"User-Agent": func.DEFAULT_USER_AGENT}

    def test_waits_on_the_limiter_before_requesting(self, monkeypatch):
        order = []

        class Limiter:
            def wait(self):
                order.append("wait")

        monkeypatch.setattr(
            requests,
            "get",
            lambda url, **kw: order.append("get") or FakeResponse(),
        )

        api.fetch_payload("word", api_key=KEY, limiter=Limiter())  # type: ignore[arg-type]

        assert order == ["wait", "get"]

    def test_the_key_is_removed_from_http_errors(self, monkeypatch):
        monkeypatch.setattr(requests, "get", lambda url, **kw: FakeResponse("", 403))

        with pytest.raises(api.ApiError) as info:
            api.fetch_payload("word", api_key=KEY)

        assert KEY not in str(info.value)
        assert "***" in str(info.value)
        assert info.value.status_code == 403

    def test_the_key_is_removed_from_connection_errors(self, monkeypatch):
        def fake_get(url, **kwargs):
            raise requests.exceptions.ConnectionError(
                f"Max retries exceeded with url: /x/word?key={KEY} (Caused by ...)"
            )

        monkeypatch.setattr(requests, "get", fake_get)

        with pytest.raises(api.ApiError) as info:
            api.fetch_payload("word", api_key=KEY)

        assert KEY not in str(info.value)
        assert info.value.status_code is None

    def test_a_url_encoded_key_is_removed_too(self, monkeypatch):
        odd_key = "a b/c"

        def fake_get(url, **kwargs):
            raise requests.exceptions.ConnectionError("url: /x?key=a%20b%2Fc")

        monkeypatch.setattr(requests, "get", fake_get)

        with pytest.raises(api.ApiError) as info:
            api.fetch_payload("word", api_key=odd_key)

        assert "a%20b%2Fc" not in str(info.value)

    def test_the_original_error_is_not_chained_into_tracebacks(self, monkeypatch):
        def fake_get(url, **kwargs):
            raise requests.exceptions.ConnectionError(f"boom key={KEY}")

        monkeypatch.setattr(requests, "get", fake_get)

        with pytest.raises(api.ApiError) as info:
            api.fetch_payload("word", api_key=KEY)

        assert info.value.__suppress_context__ is True

    def test_api_error_is_a_request_exception(self):
        assert issubclass(api.ApiError, requests.exceptions.RequestException)


class TestLookupWord:
    GOOD = json.dumps([make_entry_json(fl=None, shortdef=("a sense",), audio=None)])

    def test_fetches_parses_and_caches_the_reply(self, monkeypatch):
        monkeypatch.setattr(requests, "get", lambda url, **kw: FakeResponse(self.GOOD))
        cache = FakeCache()

        entry = api.lookup_word("word", api_key=KEY, cache=cache)

        assert entry.definitions == ("a sense",)
        assert cache.sets == [("word", self.GOOD)]

    def test_a_cache_hit_needs_no_network(self, monkeypatch):
        monkeypatch.setattr(
            requests, "get", lambda *a, **k: pytest.fail("network was used")
        )
        cache = FakeCache({"word": self.GOOD})

        assert api.lookup_word("word", api_key=KEY, cache=cache).word == "word"

    def test_an_unusable_cache_entry_is_refetched_and_replaced(self, monkeypatch):
        monkeypatch.setattr(requests, "get", lambda url, **kw: FakeResponse(self.GOOD))
        cache = FakeCache({"word": "Invalid API key."})

        entry = api.lookup_word("word", api_key=KEY, cache=cache)

        assert entry.word == "word"
        assert cache.store["word"] == self.GOOD

    def test_unknown_words_are_not_cached(self, monkeypatch):
        monkeypatch.setattr(
            requests, "get", lambda url, **kw: FakeResponse('["suggestion"]')
        )
        cache = FakeCache()

        with pytest.raises(func.WordNotFoundError):
            api.lookup_word("tset", api_key=KEY, cache=cache)

        assert cache.sets == []

    def test_a_bad_key_reply_is_not_cached(self, monkeypatch):
        monkeypatch.setattr(
            requests, "get", lambda url, **kw: FakeResponse("Invalid API key.")
        )
        cache = FakeCache()

        with pytest.raises(api.ApiError):
            api.lookup_word("word", api_key=KEY, cache=cache)

        assert cache.sets == []

    def test_works_without_a_cache(self, monkeypatch):
        monkeypatch.setattr(requests, "get", lambda url, **kw: FakeResponse(self.GOOD))
        assert api.lookup_word("word", api_key=KEY).word == "word"

    def test_explicit_headers_are_passed_through(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            requests,
            "get",
            lambda url, **kw: seen.update(kw) or FakeResponse(self.GOOD),
        )

        api.lookup_word("word", api_key=KEY, headers={"User-Agent": "x/1"})

        assert seen["headers"] == {"User-Agent": "x/1"}
