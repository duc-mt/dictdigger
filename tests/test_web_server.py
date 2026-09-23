"""Tests for web_server.py.

``DictionaryApp`` is exercised directly (no sockets) for behaviour and
security, and a real ``ThreadingHTTPServer`` on an ephemeral port checks the
HTTP plumbing. The dictionary itself is always a fake: nothing here reaches
the network.
"""

from __future__ import annotations

import html
import http.client
import logging
import socket
import threading
import time
from collections.abc import Iterator
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from curl_cffi import requests

import functions as func
import web_server as web
from word_history import WordHistory

AUDIO = "https://media.merriam-webster.com/audio/prons/en/us/mp3/t/test0001.mp3"
TEST = func.Entry("test", ("a means of testing", "a positive result"), AUDIO)
EXAM = func.Entry("exam", ("a formal test",))
FORM = {"Content-Type": "application/x-www-form-urlencoded"}


def make_http_error(status_code: int) -> requests.exceptions.HTTPError:
    response = requests.Response()
    response.status_code = status_code
    return requests.exceptions.HTTPError(
        f"{status_code} Client Error", response=response
    )


class FakeLookup:
    """A dictionary that knows a few words and records every call."""

    def __init__(self) -> None:
        self.entries = {"test": TEST, "exam": EXAM}
        self.errors: dict[str, Exception] = {}
        self.calls: list[str] = []

    def __call__(self, word: str) -> func.Entry:
        self.calls.append(word)
        key = word.casefold()
        if key in self.errors:
            raise self.errors[key]
        if key in self.entries:
            return self.entries[key]
        raise func.WordNotFoundError(word)


@pytest.fixture
def lookup() -> FakeLookup:
    return FakeLookup()


@pytest.fixture
def history(tmp_path) -> WordHistory:
    return WordHistory(tmp_path / "word_history.json")


@pytest.fixture
def app(lookup, history) -> web.DictionaryApp:
    return web.DictionaryApp(
        lookup,
        history,
        static_files={
            "style.css": web.StaticFile(b"body{}", "text/css; charset=utf-8"),
            "favicon.svg": web.StaticFile(b"<svg/>", "image/svg+xml"),
        },
        allowed_hosts=web.trusted_hosts("127.0.0.1"),
        max_batch=3,
    )


def make_request(
    method: str = "GET",
    target: str = "/",
    *,
    form: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> web.Request:
    parts = urlsplit(target)
    return web.Request(
        method,
        parts.path,
        parse_qs(parts.query, keep_blank_values=True),
        {name: [value] for name, value in (form or {}).items()},
        {"host": "localhost:8000", **(headers or {})},
    )


def get(app: web.DictionaryApp, target: str = "/", **kwargs) -> web.Response:
    return app.handle(make_request("GET", target, **kwargs))


def post(app: web.DictionaryApp, target: str, form: dict[str, str], **kwargs):
    return app.handle(make_request("POST", target, form=form, **kwargs))


def text(response: web.Response) -> str:
    return response.body.decode("utf-8")


def shown(response: web.Response) -> str:
    """The page as a visitor reads it: entities such as &#x27; decoded."""
    return html.unescape(text(response))


# --------------------------------------------------------------------- home
class TestHome:
    def test_serves_the_search_page(self, app):
        response = get(app)

        assert response.status == HTTPStatus.OK
        assert response.content_type == "text/html; charset=utf-8"
        assert 'name="word"' in text(response)

    def test_lists_recent_successful_words_newest_first(self, app, history):
        for word, found in (("old", True), ("typo", False), ("new", True)):
            history.record(word, found=found)

        page = text(get(app))

        assert page.index(">new<") < page.index(">old<")
        assert "typo" not in page

    def test_recent_words_are_unique_and_limited(self, app, history):
        for number in range(web.RECENT_WORDS + 5):
            history.record(f"word{number}", found=True)
        history.record("WORD14", found=True)  # repeat, different case

        page = text(get(app))

        assert page.count('<li><a href="/?word=') == web.RECENT_WORDS
        assert page.count(">word14<") + page.count(">WORD14<") == 1

    def test_history_switched_off_says_so(self, lookup):
        page = text(get(web.DictionaryApp(lookup, None)))
        assert "History is turned off" in page

    def test_no_lookup_happens_on_the_home_page(self, app, lookup):
        get(app)
        assert lookup.calls == []


# ------------------------------------------------------------------- lookup
class TestLookup:
    def test_shows_the_entry(self, app):
        response = get(app, "/?word=test")

        assert response.status == HTTPStatus.OK
        page = text(response)
        assert "<h1>test</h1>" in page
        assert "a means of testing" in page
        assert f'src="{AUDIO}"' in page

    def test_records_the_lookup_in_the_history(self, app, history):
        get(app, "/?word=test")
        assert [(r.word, r.found) for r in history.read()] == [("test", True)]

    def test_unknown_words_are_404_and_logged_as_not_found(self, app, history):
        response = get(app, "/?word=asdf")

        assert response.status == HTTPStatus.NOT_FOUND
        assert "isn't in the dictionary" in shown(response)
        assert [(r.word, r.found) for r in history.read()] == [("asdf", False)]

    def test_website_failures_are_502_with_a_hint_and_not_logged(
        self, app, lookup, history
    ):
        lookup.errors["test"] = make_http_error(403)

        response = get(app, "/?word=test")

        assert response.status == HTTPStatus.BAD_GATEWAY
        assert "refused the request" in text(response)
        assert history.read() == []

    def test_connection_errors_are_502(self, app, lookup):
        lookup.errors["test"] = requests.exceptions.ConnectionError("no route")

        response = get(app, "/?word=test")

        assert response.status == HTTPStatus.BAD_GATEWAY
        assert "no route" in text(response)

    def test_whitespace_is_normalised_and_case_is_kept(self, app, lookup):
        get(app, "/?word=++Ice++Cream+")
        assert lookup.calls == ["Ice Cream"]

    @pytest.mark.parametrize("bad", ["", "%20%20", "bad%00word", "a" * 101])
    def test_invalid_words_are_400_and_never_looked_up(self, app, lookup, bad):
        response = get(app, f"/?word={bad}")

        assert response.status == HTTPStatus.BAD_REQUEST
        assert lookup.calls == []

    def test_only_the_first_word_parameter_is_used(self, app, lookup):
        get(app, "/?word=test&word=exam")
        assert lookup.calls == ["test"]

    def test_the_search_box_keeps_the_word_after_an_error(self, app):
        page = text(get(app, "/?word=asdf"))
        assert 'value="asdf"' in page


# -------------------------------------------------------------------- batch
class TestBatch:
    def test_get_shows_the_form(self, app):
        response = get(app, "/batch")

        assert response.status == HTTPStatus.OK
        assert "<textarea" in text(response)

    def test_looks_up_every_word_and_reports_the_ones_not_found(self, app, history):
        response = post(app, "/batch", {"words": "test\nasdf\nexam", "format": "md"})

        page = text(response)
        assert response.status == HTTPStatus.OK
        assert "Found 2 of 3." in page
        assert "<strong>asdf</strong>" in page
        assert [(r.word, r.found) for r in history.read()] == [
            ("test", True),
            ("asdf", False),
            ("exam", True),
        ]

    def test_comments_blank_lines_and_duplicates_are_ignored(self, app, lookup):
        post(app, "/batch", {"words": "# my list\n\ntest\nTEST\nexam\r\n"})
        assert lookup.calls == ["test", "exam"]

    def test_one_failing_word_does_not_stop_the_rest(self, app, lookup):
        lookup.errors["test"] = requests.exceptions.Timeout("slow")

        page = text(post(app, "/batch", {"words": "test\nexam"}))

        assert "Found 1 of 2." in page
        assert "slow" in page

    def test_more_words_than_the_limit_are_refused_before_any_lookup(self, app, lookup):
        response = post(app, "/batch", {"words": "a\nb\nc\nd"})

        assert response.status == HTTPStatus.BAD_REQUEST
        assert "At most 3 words" in text(response)
        assert lookup.calls == []

    def test_an_empty_list_is_refused(self, app):
        response = post(app, "/batch", {"words": "# nothing\n\n"})

        assert response.status == HTTPStatus.BAD_REQUEST
        assert "Enter at least one word." in text(response)

    def test_a_bad_line_is_reported_with_its_number_and_the_text_is_kept(
        self, app, lookup
    ):
        response = post(app, "/batch", {"words": "test\nbad\x00word"})

        page = text(response)
        assert response.status == HTTPStatus.BAD_REQUEST
        assert "line 2" in page
        assert "test\nbad" in page  # the visitor's text is not lost
        assert lookup.calls == []

    def test_a_missing_words_field_is_refused(self, app):
        assert post(app, "/batch", {}).status == HTTPStatus.BAD_REQUEST


# ------------------------------------------------------------------- export
class TestExport:
    @pytest.mark.parametrize(
        ("fmt", "content_type", "filename", "marker"),
        [
            ("text", "text/plain; charset=utf-8", "definitions.txt", "TEST"),
            ("md", "text/markdown; charset=utf-8", "definitions.md", "# test"),
            ("json", "application/json", "definitions.json", '"word": "test"'),
        ],
    )
    def test_downloads_a_word_in_each_format(
        self, app, fmt, content_type, filename, marker
    ):
        response = get(app, f"/export?word=test&format={fmt}")

        assert response.status == HTTPStatus.OK
        assert response.content_type == content_type
        assert response.headers["Content-Disposition"] == (
            f'attachment; filename="{filename}"'
        )
        assert marker in text(response)

    def test_the_format_defaults_to_text(self, app):
        response = get(app, "/export?word=test")
        assert response.content_type.startswith("text/plain")

    def test_a_list_can_be_downloaded_with_post(self, app):
        response = post(app, "/export", {"words": "test\nexam", "format": "json"})

        assert response.status == HTTPStatus.OK
        assert text(response).count('"word"') == 2

    def test_words_that_were_not_found_are_left_out(self, app):
        body = text(post(app, "/export", {"words": "test\nasdf", "format": "json"}))

        assert '"word": "test"' in body
        assert "asdf" not in body

    def test_nothing_found_returns_the_failure_page_not_an_empty_file(self, app):
        response = post(app, "/export", {"words": "asdf", "format": "json"})

        assert response.status == HTTPStatus.NOT_FOUND
        assert "Content-Disposition" not in response.headers

    def test_website_failures_are_502(self, app, lookup):
        lookup.errors["test"] = requests.exceptions.ConnectionError("down")
        response = get(app, "/export?word=test&format=md")
        assert response.status == HTTPStatus.BAD_GATEWAY

    def test_unknown_formats_are_refused(self, app, lookup):
        response = get(app, "/export?word=test&format=exe")

        assert response.status == HTTPStatus.BAD_REQUEST
        assert lookup.calls == []

    def test_the_file_name_never_comes_from_user_input(self, app):
        response = get(app, '/export?word=test&format=json&filename=x"; evil="1')
        assert response.headers["Content-Disposition"] == (
            'attachment; filename="definitions.json"'
        )

    def test_a_missing_word_is_refused(self, app):
        assert get(app, "/export").status == HTTPStatus.BAD_REQUEST


# ------------------------------------------------------------------ history
class TestHistoryPage:
    def test_lists_lookups_newest_first(self, app, history):
        history.record("first", found=True)
        history.record("second", found=False)

        page = text(get(app, "/history"))

        assert page.index(">second<") < page.index(">first<")
        assert "not found" in page

    def test_is_capped(self, app, history):
        for number in range(web.MAX_HISTORY_ROWS + 20):
            history.record(f"w{number}", found=True)

        page = text(get(app, "/history"))

        assert page.count("<tr>") == web.MAX_HISTORY_ROWS + 1  # + header row
        assert f">w{web.MAX_HISTORY_ROWS + 19}<" in page
        assert ">w0<" not in page

    def test_is_empty_before_any_lookup(self, app):
        assert "Nothing has been looked up yet." in text(get(app, "/history"))

    def test_switched_off_says_so(self, lookup):
        page = text(get(web.DictionaryApp(lookup, None), "/history"))
        assert "turned off" in page

    def test_reading_it_records_nothing(self, app, history):
        get(app, "/history")
        assert history.read() == []


# ------------------------------------------------------------ static & routes
class TestStaticFiles:
    def test_serves_known_files_with_their_types(self, app):
        css = get(app, "/static/style.css")
        icon = get(app, "/static/favicon.svg")

        assert (css.status, css.content_type, css.body) == (
            HTTPStatus.OK,
            "text/css; charset=utf-8",
            b"body{}",
        )
        assert icon.content_type == "image/svg+xml"
        assert css.headers["Cache-Control"] == "public, max-age=3600"

    @pytest.mark.parametrize(
        "path",
        [
            "/static/../main.py",
            "/static/%2e%2e/main.py",
            "/static/..%2fmain.py",
            "/static/",
            "/static/style.css/",
            "/static/missing.css",
            "/static//etc/passwd",
            "/static/style.css%00.png",
        ],
    )
    def test_nothing_outside_the_allowlist_is_reachable(self, app, path):
        assert get(app, path).status == HTTPStatus.NOT_FOUND

    def test_only_get_is_allowed(self, app):
        assert (
            post(app, "/static/style.css", {}).status == HTTPStatus.METHOD_NOT_ALLOWED
        )

    def test_load_static_files_reads_only_known_types(self, tmp_path):
        (tmp_path / "style.css").write_text("a{}", encoding="utf-8")
        (tmp_path / "icon.svg").write_text("<svg/>", encoding="utf-8")
        (tmp_path / "secret.py").write_text("KEY = 1", encoding="utf-8")
        (tmp_path / "sub").mkdir()

        files = web.load_static_files(tmp_path)

        assert sorted(files) == ["icon.svg", "style.css"]

    def test_load_static_files_skips_huge_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(web, "MAX_STATIC_BYTES", 5)
        (tmp_path / "big.css").write_text("a" * 10, encoding="utf-8")
        assert web.load_static_files(tmp_path) == {}

    def test_a_missing_folder_warns_instead_of_failing(self, tmp_path, caplog):
        assert web.load_static_files(tmp_path / "nope") == {}
        assert "pages will be unstyled" in caplog.text

    def test_the_bundled_stylesheet_and_icon_are_found(self):
        files = web.load_static_files(web.STATIC_DIR)
        assert {"style.css", "favicon.svg"} <= set(files)


class TestRouting:
    def test_unknown_paths_are_404(self, app):
        assert get(app, "/nope").status == HTTPStatus.NOT_FOUND

    @pytest.mark.parametrize(
        ("path", "method", "allow"),
        [
            ("/", "POST", "GET"),
            ("/history", "POST", "GET"),
            ("/batch", "DELETE", "GET, POST"),
            ("/export", "PUT", "GET, POST"),
        ],
    )
    def test_wrong_methods_are_405_with_an_allow_header(self, app, path, method, allow):
        response = app.handle(make_request(method, path))

        assert response.status == HTTPStatus.METHOD_NOT_ALLOWED
        assert response.headers["Allow"] == allow

    def test_the_favicon_request_is_answered_quietly(self, app):
        response = get(app, "/favicon.ico")
        assert (response.status, response.body) == (HTTPStatus.NO_CONTENT, b"")

    def test_unexpected_errors_never_show_a_traceback(self, app, lookup, caplog):
        lookup.errors["test"] = RuntimeError("secret internal detail")

        response = get(app, "/?word=test")

        assert response.status == HTTPStatus.INTERNAL_SERVER_ERROR
        assert "secret internal detail" not in text(response)
        assert "Traceback" not in text(response)
        assert "secret internal detail" in caplog.text  # but the server logs it


# ----------------------------------------------------------------- security
class TestSecurityHeaders:
    @pytest.mark.parametrize(
        "make",
        [
            lambda app: get(app),
            lambda app: get(app, "/?word=test"),
            lambda app: get(app, "/?word=asdf"),
            lambda app: get(app, "/nope"),
            lambda app: get(app, "/static/style.css"),
            lambda app: get(app, "/favicon.ico"),
            lambda app: post(app, "/", {}),
            lambda app: get(app, "/", headers={"host": "evil.example"}),
        ],
        ids=[
            "home",
            "entry",
            "not-found",
            "404",
            "static",
            "favicon",
            "405",
            "bad-host",
        ],
    )
    def test_every_response_carries_the_protective_headers(self, app, make):
        headers = make(app).headers

        for name, value in web.SECURITY_HEADERS.items():
            assert headers[name] == value

    def test_pages_are_never_cached_but_static_files_are(self, app):
        assert get(app, "/?word=test").headers["Cache-Control"] == "no-store"
        assert "max-age" in get(app, "/static/style.css").headers["Cache-Control"]

    def test_the_content_security_policy_forbids_scripts_and_inline_styles(self):
        policy = web.CONTENT_SECURITY_POLICY

        assert "default-src 'none'" in policy
        assert "script-src" not in policy  # falls back to 'none'
        assert "unsafe-inline" not in policy
        assert "unsafe-eval" not in policy
        assert "media-src https://media.merriam-webster.com" in policy
        assert "frame-ancestors 'none'" in policy
        assert "form-action 'self'" in policy
        assert "base-uri 'none'" in policy


class TestHostValidation:
    @pytest.mark.parametrize(
        "host",
        ["localhost", "localhost:8000", "127.0.0.1:1234", "[::1]:8000", "LOCALHOST:9"],
    )
    def test_loopback_names_are_accepted(self, app, host):
        assert get(app, headers={"host": host}).status == HTTPStatus.OK

    @pytest.mark.parametrize(
        "host",
        [
            "evil.example",
            "evil.example:8000",
            "127.0.0.1.evil.example",
            "localhost.evil.example",
            "192.168.1.10:8000",
            "",
        ],
    )
    def test_other_names_are_refused_which_stops_dns_rebinding(self, app, lookup, host):
        response = get(app, "/?word=test", headers={"host": host})

        assert response.status == HTTPStatus.BAD_REQUEST
        assert lookup.calls == []

    def test_a_missing_host_header_is_refused(self, app):
        request = web.Request("GET", "/", {}, {}, {})
        assert app.handle(request).status == HTTPStatus.BAD_REQUEST

    def test_an_exposed_server_accepts_any_name(self, lookup, history):
        app = web.DictionaryApp(
            lookup, history, allowed_hosts=web.trusted_hosts("192.0.2.1")
        )
        assert get(app, headers={"host": "printer.lan:8000"}).status == HTTPStatus.OK

    @pytest.mark.parametrize(
        ("bound", "expected"),
        [("127.0.0.1", True), ("::1", True), ("localhost", True), ("192.0.2.1", False)],
    )
    def test_only_loopback_addresses_count_as_local(self, bound, expected):
        assert web.is_loopback(bound) is expected
        assert (web.trusted_hosts(bound) is not None) is expected

    @pytest.mark.parametrize(
        ("header", "name"),
        [
            ("localhost:8000", "localhost"),
            ("Example.COM", "example.com"),
            ("[::1]:8000", "[::1]"),
            ("[::1]", "[::1]"),
            ("  127.0.0.1  ", "127.0.0.1"),
            ("[broken", "[broken"),
        ],
    )
    def test_hostname_parsing(self, header, name):
        assert web.hostname(header) == name


class TestCrossSiteProtection:
    @pytest.mark.parametrize("site", ["cross-site", "same-site", "weird"])
    def test_requests_started_by_other_sites_are_refused(self, app, lookup, site):
        response = get(app, "/?word=test", headers={"sec-fetch-site": site})

        assert response.status == HTTPStatus.FORBIDDEN
        assert lookup.calls == []

    @pytest.mark.parametrize("site", ["same-origin", "none"])
    def test_same_origin_and_typed_addresses_are_allowed(self, app, site):
        assert get(app, headers={"sec-fetch-site": site}).status == HTTPStatus.OK

    def test_a_cross_site_post_cannot_trigger_lookups_or_history(
        self, app, lookup, history
    ):
        response = post(
            app,
            "/batch",
            {"words": "test"},
            headers={"origin": "https://evil.example", "sec-fetch-site": "cross-site"},
        )

        assert response.status == HTTPStatus.FORBIDDEN
        assert lookup.calls == []
        assert history.read() == []

    def test_a_matching_origin_is_allowed(self, app):
        response = post(
            app,
            "/batch",
            {"words": "test"},
            headers={"origin": "http://localhost:8000"},
        )
        assert response.status == HTTPStatus.OK

    @pytest.mark.parametrize(
        "origin",
        ["http://localhost:9999", "https://evil.example", "null", "http://localhost"],
    )
    def test_a_different_origin_is_refused_even_without_fetch_metadata(
        self, app, origin
    ):
        response = post(app, "/batch", {"words": "test"}, headers={"origin": origin})
        assert response.status == HTTPStatus.FORBIDDEN

    def test_no_origin_header_is_fine(self, app):
        assert post(app, "/batch", {"words": "test"}).status == HTTPStatus.OK


# ---------------------------------------------------------- real HTTP server
class Live:
    def __init__(self, server: web.ThreadingHTTPServer) -> None:
        self.server = server
        self.host = str(server.server_address[0])
        self.port = int(server.server_address[1])

    def request(
        self,
        method: str,
        path: str,
        body: bytes | str | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection(self.host, self.port, timeout=10)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def raw(self, data: bytes) -> bytes:
        with socket.create_connection((self.host, self.port), timeout=10) as sock:
            sock.sendall(data)
            chunks = []
            while chunk := sock.recv(4096):
                chunks.append(chunk)
        return b"".join(chunks)


@pytest.fixture
def live(lookup, history, tmp_path) -> Iterator[Live]:
    static = tmp_path / "static"
    static.mkdir()
    (static / "style.css").write_text("body{}", encoding="utf-8")
    server = web.create_server(
        lookup=lookup, history=history, port=0, static_dir=static, max_batch=5
    )
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield Live(server)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class TestOverHttp:
    def test_serves_pages_with_protective_headers(self, live):
        status, headers, body = live.request("GET", "/")

        assert status == 200
        assert headers["Content-Type"] == "text/html; charset=utf-8"
        assert headers["Content-Length"] == str(len(body))
        assert headers["Content-Security-Policy"] == web.CONTENT_SECURITY_POLICY
        assert headers["Cache-Control"] == "no-store"

    def test_does_not_advertise_the_python_version(self, live):
        _status, headers, _body = live.request("GET", "/")

        assert headers["Server"] == "dictionary-web"
        assert "Python" not in headers["Server"]

    def test_a_lookup_works_end_to_end_and_lands_in_the_history(self, live, history):
        status, _headers, body = live.request("GET", "/?word=test")

        assert status == 200
        assert b"a means of testing" in body
        assert [r.word for r in history.read()] == ["test"]

    def test_a_form_post_works(self, live):
        status, _headers, body = live.request(
            "POST", "/batch", "words=test%0Aexam&format=md", FORM
        )

        assert status == 200
        assert b"Found 2 of 2." in body

    def test_a_download_is_an_attachment(self, live):
        status, headers, body = live.request("GET", "/export?word=test&format=json")

        assert status == 200
        assert (
            headers["Content-Disposition"] == 'attachment; filename="definitions.json"'
        )
        assert b'"word": "test"' in body

    def test_serves_the_stylesheet(self, live):
        status, headers, body = live.request("GET", "/static/style.css")
        assert (status, headers["Content-Type"], body) == (
            200,
            "text/css; charset=utf-8",
            b"body{}",
        )

    def test_a_wrong_host_name_is_refused_over_the_wire(self, live):
        status, _headers, _body = live.request(
            "GET", "/", headers={"Host": "evil.example"}
        )
        assert status == 400

    def test_a_cross_site_request_is_refused_over_the_wire(self, live, lookup):
        status, _headers, _body = live.request(
            "GET", "/?word=test", headers={"Sec-Fetch-Site": "cross-site"}
        )

        assert status == 403
        assert lookup.calls == []

    def test_other_methods_are_not_implemented(self, live):
        assert live.request("PUT", "/")[0] == 501

    def test_head_requests_are_not_implemented(self, live):
        assert live.request("HEAD", "/")[0] == 501


class TestRequestLimits:
    def test_a_body_that_is_not_form_encoded_is_415(self, live):
        status, *_ = live.request(
            "POST", "/batch", "{}", {"Content-Type": "application/json"}
        )
        assert status == 415

    def test_a_missing_content_length_is_411(self, live):
        reply = live.raw(
            b"POST /batch HTTP/1.0\r\n"
            b"Content-Type: application/x-www-form-urlencoded\r\n\r\n"
        )
        assert reply.startswith(b"HTTP/1.0 411")

    def test_an_oversized_body_is_refused_without_reading_it(self, live):
        length = web.MAX_BODY_BYTES + 1
        reply = live.raw(
            b"POST /batch HTTP/1.0\r\n"
            b"Content-Type: application/x-www-form-urlencoded\r\n"
            + f"Content-Length: {length}\r\n\r\n".encode()
        )
        assert reply.startswith(b"HTTP/1.0 413")

    @pytest.mark.parametrize("length", ["abc", "-5"])
    def test_a_bad_content_length_is_400(self, live, length):
        reply = live.raw(
            b"POST /batch HTTP/1.0\r\n"
            b"Content-Type: application/x-www-form-urlencoded\r\n"
            + f"Content-Length: {length}\r\n\r\n".encode()
        )
        assert reply.startswith(b"HTTP/1.0 400")

    def test_a_body_that_is_not_utf8_is_400(self, live):
        status, *_ = live.request("POST", "/batch", b"words=\xff\xfe", FORM)
        assert status == 400

    def test_too_many_form_fields_are_400(self, live):
        body = "&".join(f"f{i}=1" for i in range(web.MAX_FORM_FIELDS + 1))
        assert live.request("POST", "/batch", body, FORM)[0] == 400

    def test_too_many_query_fields_are_400(self, live):
        query = "&".join(f"f{i}=1" for i in range(web.MAX_FORM_FIELDS + 1))
        assert live.request("GET", f"/?{query}")[0] == 400

    def test_a_body_at_the_limit_is_accepted(self, live):
        padding = "x" * (web.MAX_BODY_BYTES - len("words=test&pad="))
        status, *_ = live.request("POST", "/batch", f"words=test&pad={padding}", FORM)
        assert status == 200

    def test_error_pages_from_the_plumbing_are_protected_too(self, live):
        _status, headers, _body = live.request(
            "POST", "/batch", "{}", {"Content-Type": "application/json"}
        )
        assert headers["Content-Security-Policy"] == web.CONTENT_SECURITY_POLICY


class TestServerBehaviour:
    def test_requests_are_logged_not_printed(self, live, caplog, capsys):
        caplog.set_level(logging.INFO, logger="web_server")

        live.request("GET", "/")

        assert any("GET / HTTP" in record.getMessage() for record in caplog.records)
        assert capsys.readouterr().err == ""

    def test_lookups_from_many_visitors_at_once_are_all_kept(
        self, live, lookup, history
    ):
        def slow(word: str) -> func.Entry:
            time.sleep(0.02)
            return func.Entry(word, ("definition",))

        live.server.RequestHandlerClass.app._lookup = slow  # type: ignore[attr-defined]
        results: list[int] = []

        def visit(number: int) -> None:
            results.append(live.request("GET", f"/?word=w{number}")[0])

        threads = [threading.Thread(target=visit, args=(n,)) for n in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        assert results == [200] * 12
        assert sorted(r.word for r in history.read()) == sorted(
            f"w{n}" for n in range(12)
        )

    def test_a_port_that_is_taken_raises_oserror(self, live, lookup, history):
        with pytest.raises(OSError):
            web.create_server(lookup=lookup, history=history, port=live.port)

    def test_connection_drops_are_quiet_but_real_errors_are_logged(self, live, caplog):
        caplog.set_level(logging.DEBUG, logger="web_server")
        try:
            raise ConnectionResetError("browser went away")
        except ConnectionResetError:
            live.server.handle_error(None, ("127.0.0.1", 1))
        assert not [r for r in caplog.records if r.levelno >= logging.ERROR]

        try:
            raise RuntimeError("boom")
        except RuntimeError:
            live.server.handle_error(None, ("127.0.0.1", 1))
        assert "error while handling a request" in caplog.text

    def test_an_ipv6_loopback_server_works(self, lookup, history, tmp_path):
        try:
            server = web.create_server(
                lookup=lookup, history=history, host="::1", port=0, static_dir=tmp_path
            )
        except OSError:
            pytest.skip("IPv6 loopback is not available here")
        thread = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        thread.start()
        try:
            connection = http.client.HTTPConnection(
                "::1", server.server_address[1], timeout=10
            )
            connection.request("GET", "/")
            assert connection.getresponse().status == 200
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


class TestCollaborators:
    def test_the_lookup_callable_is_what_the_app_calls(self, history):
        seen: list[str] = []

        def lookup(word: str) -> func.Entry:
            seen.append(word)
            return func.Entry(word, ("x",))

        get(web.DictionaryApp(lookup, history), "/?word=hello")

        assert seen == ["hello"]

    def test_history_failures_do_not_break_a_lookup(
        self, app, history, monkeypatch, caplog
    ):
        def boom(word: str, *, found: bool = True) -> None:
            raise OSError("read-only file system")

        monkeypatch.setattr(history, "record", boom)

        response = get(app, "/?word=test")

        assert response.status == HTTPStatus.OK
        assert "could not update the word history" in caplog.text

    def test_first_returns_none_for_missing_or_empty(self):
        assert web.first({}, "a") is None
        assert web.first({"a": []}, "a") is None
        assert web.first({"a": ["1", "2"]}, "a") == "1"


def test_module_default_static_dir_exists():
    assert isinstance(web.STATIC_DIR, Path)
    assert web.STATIC_DIR.is_dir()


def test_any_callable_is_accepted_as_the_lookup(history):
    def handler(word: str) -> func.Entry:
        return func.Entry(word, ("x",))

    assert isinstance(web.DictionaryApp(handler, history), web.DictionaryApp)
