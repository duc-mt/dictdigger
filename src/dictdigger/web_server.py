#!/usr/bin/python3
# -*- coding: utf-8 -*-

# =============================================================================
#
#        FILE:  web_server.py
#     CREATED:  2026-09-21
# DESCRIPTION:  A small local web interface built on the standard library
#               alone. ``DictionaryApp`` turns a ``Request`` into a
#               ``Response`` (no sockets, so it is easy to test), and a thin
#               ``http.server`` handler connects it to the network.
#
#               There is no login: the server is meant for the person who
#               started it, so it binds to the loopback address by default and
#               refuses requests that other websites try to send through the
#               visitor's browser.
#
# =============================================================================

from __future__ import annotations

import logging
import socket
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from curl_cffi import requests

from dictdigger import exporters, web_views
from dictdigger import functions as func
from dictdigger.word_history import WordHistory, record_history

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")
_TRUSTED_HOST_NAMES = frozenset({"localhost", "127.0.0.1", "[::1]"})
MAX_BODY_BYTES = 64 * 1024
MAX_FORM_FIELDS = 20
MAX_STATIC_BYTES = 1024 * 1024
MAX_BATCH_WORDS = 50
MAX_HISTORY_ROWS = 200
RECENT_WORDS = 10
SOCKET_TIMEOUT = 15  # seconds a client may stall before its connection is dropped

_STATIC_TYPES = {".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}
_EXPORT_TYPES = {
    "text": ("text/plain; charset=utf-8", "txt"),
    "md": ("text/markdown; charset=utf-8", "md"),
    "json": ("application/json", "json"),
}
CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'none'",
        "style-src 'self'",
        "img-src 'self'",
        f"media-src https://{web_views.MEDIA_HOST}",
        "form-action 'self'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
    )
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


@dataclass(frozen=True)
class Request:
    """What the app needs to know about one HTTP request.

    Header names are lower-case.
    """

    method: str
    path: str
    query: Mapping[str, Sequence[str]] = field(default_factory=dict)
    form: Mapping[str, Sequence[str]] = field(default_factory=dict)
    headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Response:
    status: HTTPStatus
    body: bytes = b""
    content_type: str = "text/html; charset=utf-8"
    headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class StaticFile:
    content: bytes
    content_type: str


@dataclass(frozen=True)
class Failure:
    """Why a lookup produced no entry."""

    status: HTTPStatus
    message: str


def is_loopback(host: str) -> bool:
    """Whether binding to ``host`` keeps the server reachable only from here."""
    return host in LOOPBACK_HOSTS


def trusted_hosts(host: str) -> frozenset[str] | None:
    """Host names a server bound to ``host`` should answer to.

    A loopback server accepts only loopback names, which stops a malicious
    website from reaching it through DNS rebinding. ``None`` (any name) is for
    a server the owner deliberately exposed.
    """
    return _TRUSTED_HOST_NAMES if is_loopback(host) else None


def hostname(host_header: str) -> str:
    """The name part of a Host header: ``localhost:8000`` -> ``localhost``."""
    value = host_header.strip().lower()
    if value.startswith("["):  # IPv6 literal, such as [::1]:8000
        end = value.find("]")
        return value[: end + 1] if end != -1 else value
    return value.rsplit(":", 1)[0] if ":" in value else value


def first(values: Mapping[str, Sequence[str]], key: str) -> str | None:
    found = values.get(key)
    return found[0] if found else None


def load_static_files(directory: Path) -> dict[str, StaticFile]:
    """Read the stylesheet and icon once, so requests can never reach the disk."""
    files: dict[str, StaticFile] = {}
    if not directory.is_dir():
        logger.warning("static folder %s not found: pages will be unstyled", directory)
        return files
    for path in sorted(directory.iterdir()):
        content_type = _STATIC_TYPES.get(path.suffix.lower())
        if content_type and path.is_file() and path.stat().st_size <= MAX_STATIC_BYTES:
            files[path.name] = StaticFile(path.read_bytes(), content_type)
    return files


def _secured(response: Response) -> Response:
    headers = {"Cache-Control": "no-store", **SECURITY_HEADERS, **response.headers}
    return Response(response.status, response.body, response.content_type, headers)


class DictionaryApp:
    """The pages of the web interface, independent of any network code.

    Args:
        lookup: Returns the ``Entry`` for a word (cache and rate limiter bound).
        history: Where lookups are recorded and listed; ``None`` turns the
            history off.
        static_files: The stylesheet and icon, by file name.
        allowed_hosts: Host names the server answers to; ``None`` allows any.
            Restricting it defeats DNS-rebinding attacks on a local server.
        max_batch: Most words accepted in one batch request.
    """

    def __init__(
        self,
        lookup: func.Lookup,
        history: WordHistory | None,
        *,
        static_files: Mapping[str, StaticFile] | None = None,
        allowed_hosts: frozenset[str] | None = None,
        max_batch: int = MAX_BATCH_WORDS,
    ) -> None:
        self._lookup = lookup
        self._history = history
        self._static = dict(static_files or {})
        self._allowed_hosts = allowed_hosts
        self._max_batch = max_batch

    # ------------------------------------------------------------- dispatch
    def handle(self, request: Request) -> Response:
        rejected = self._reject_untrusted(request)
        if rejected is not None:
            return _secured(rejected)
        try:
            response = self._route(request)
        except Exception:  # never show the visitor a traceback
            logger.exception("unhandled error for %s %s", request.method, request.path)
            response = self.message(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "Something went wrong",
                "The error was logged by the server.",
            )
        return _secured(response)

    def message(
        self, status: HTTPStatus, title: str, text: str, *, word: str = ""
    ) -> Response:
        return self._html(status, web_views.render_message(title, text, word=word))

    def _reject_untrusted(self, request: Request) -> Response | None:
        headers = request.headers
        host = headers.get("host", "")
        if (
            self._allowed_hosts is not None
            and hostname(host) not in self._allowed_hosts
        ):
            return self.message(
                HTTPStatus.BAD_REQUEST,
                "Unexpected host name",
                "This server only answers to localhost addresses.",
            )
        site = headers.get("sec-fetch-site")
        origin = headers.get("origin")
        cross_site = site is not None and site not in ("same-origin", "none")
        cross_origin = (
            origin is not None and urlsplit(origin).netloc.lower() != host.lower()
        )
        if cross_site or cross_origin:
            return self.message(
                HTTPStatus.FORBIDDEN,
                "Cross-site request refused",
                "Requests started by another website are not allowed.",
            )
        return None

    def _route(self, request: Request) -> Response:
        path = request.path
        if path.startswith("/static/"):
            return self._static_file(request)
        routes = {
            "/": (("GET",), self._home),
            "/history": (("GET",), self._history_page),
            "/batch": (("GET", "POST"), self._batch),
            "/export": (("GET", "POST"), self._export),
            "/favicon.ico": (("GET",), self._favicon),
        }
        if path not in routes:
            return self.message(
                HTTPStatus.NOT_FOUND,
                "Page not found",
                "There is nothing at this address.",
            )
        methods, handler = routes[path]
        if request.method not in methods:
            response = self.message(
                HTTPStatus.METHOD_NOT_ALLOWED,
                "Method not allowed",
                f"This page accepts {' and '.join(methods)}.",
            )
            return Response(
                response.status, response.body, headers={"Allow": ", ".join(methods)}
            )
        return handler(request)

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _html(status: HTTPStatus, text: str) -> Response:
        return Response(status, text.encode("utf-8"))

    def _look_up(self, word: str) -> func.Entry | Failure:
        """Look a word up and log it, like the command line does."""
        try:
            entry = self._lookup(word)
        except func.WordNotFoundError:
            record_history(self._history, word, found=False)
            return Failure(HTTPStatus.NOT_FOUND, f'"{word}" isn\'t in the dictionary.')
        except requests.exceptions.RequestException as exc:
            logger.warning("lookup of %r failed: %s", word, exc)
            reason = func.describe_network_error(exc)
            return Failure(
                HTTPStatus.BAD_GATEWAY,
                f'Could not get "{word}" from the dictionary website.\n{reason}',
            )
        record_history(self._history, word, found=True)
        return entry

    def _parse_words(self, text: str) -> tuple[list[str], str]:
        """Split a word list, returning ``(words, problem)``."""
        try:
            words = func.parse_word_list(text)
        except ValueError as exc:
            return [], str(exc)
        if not words:
            return [], "Enter at least one word."
        if len(words) > self._max_batch:
            return (
                [],
                f"At most {self._max_batch} words at a time (you sent {len(words)}).",
            )
        return words, ""

    def _look_up_all(
        self, words: Sequence[str]
    ) -> tuple[list[func.Entry], list[tuple[str, str]]]:
        entries: list[func.Entry] = []
        failures: list[tuple[str, str]] = []
        for word in words:
            result = self._look_up(word)
            if isinstance(result, Failure):
                failures.append((word, result.message.splitlines()[-1]))
            else:
                entries.append(result)
        return entries, failures

    def _recent_words(self) -> list[str]:
        if self._history is None:
            return []
        seen: set[str] = set()
        recent: list[str] = []
        for record in reversed(self._history.read()):
            key = record.word.casefold()
            if record.found and key not in seen:
                seen.add(key)
                recent.append(record.word)
            if len(recent) == RECENT_WORDS:
                break
        return recent

    # -------------------------------------------------------------- routes
    def _home(self, request: Request) -> Response:
        raw = first(request.query, "word")
        if raw is None:
            page = web_views.render_home(
                self._recent_words(), history_enabled=self._history is not None
            )
            return self._html(HTTPStatus.OK, page)
        try:
            word = func.normalize_word(raw)
        except ValueError as exc:
            return self.message(HTTPStatus.BAD_REQUEST, "Invalid word", str(exc))
        result = self._look_up(word)
        if isinstance(result, Failure):
            title = (
                "Not found"
                if result.status == HTTPStatus.NOT_FOUND
                else "Lookup failed"
            )
            return self.message(result.status, title, result.message, word=word)
        return self._html(HTTPStatus.OK, web_views.render_entry(result))

    def _history_page(self, request: Request) -> Response:
        records = None
        if self._history is not None:
            records = list(reversed(self._history.read()))[:MAX_HISTORY_ROWS]
        return self._html(HTTPStatus.OK, web_views.render_history(records))

    def _batch(self, request: Request) -> Response:
        if request.method == "GET":
            return self._html(HTTPStatus.OK, web_views.render_batch_form())
        text = first(request.form, "words") or ""
        fmt = first(request.form, "format") or "text"
        words, problem = self._parse_words(text)
        if problem:
            page = web_views.render_batch_form(text, fmt, error=problem)
            return self._html(HTTPStatus.BAD_REQUEST, page)
        entries, failures = self._look_up_all(words)
        page = web_views.render_batch_results(entries, failures, text=text, fmt=fmt)
        return self._html(HTTPStatus.OK, page)

    def _export(self, request: Request) -> Response:
        if request.method == "GET":
            source, fmt = first(request.query, "word"), first(request.query, "format")
        else:
            source, fmt = first(request.form, "words"), first(request.form, "format")
        fmt = fmt or "text"
        if fmt not in exporters.FORMATS:
            return self.message(
                HTTPStatus.BAD_REQUEST,
                "Unknown format",
                f"Choose one of: {', '.join(exporters.FORMATS)}.",
            )
        words, problem = self._parse_words(source or "")
        if problem:
            return self.message(HTTPStatus.BAD_REQUEST, "Nothing to download", problem)
        entries: list[func.Entry] = []
        failure: Failure | None = None
        for word in words:
            result = self._look_up(word)
            if isinstance(result, Failure):
                failure = failure or result
            else:
                entries.append(result)
        if not entries:
            failure = failure or Failure(HTTPStatus.NOT_FOUND, "Nothing was found.")
            return self.message(failure.status, "Nothing to download", failure.message)
        content_type, extension = _EXPORT_TYPES[fmt]
        return Response(
            HTTPStatus.OK,
            exporters.render(entries, fmt).encode("utf-8"),
            content_type,
            {"Content-Disposition": f'attachment; filename="definitions.{extension}"'},
        )

    def _static_file(self, request: Request) -> Response:
        if request.method != "GET":
            return self.message(
                HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed", "Use GET."
            )
        asset = self._static.get(request.path.removeprefix("/static/"))
        if asset is None:
            return self.message(HTTPStatus.NOT_FOUND, "Page not found", "No such file.")
        return Response(
            HTTPStatus.OK,
            asset.content,
            asset.content_type,
            {"Cache-Control": "public, max-age=3600"},
        )

    def _favicon(self, request: Request) -> Response:
        return Response(HTTPStatus.NO_CONTENT)


# --------------------------------------------------------------------- HTTP
class _Handler(BaseHTTPRequestHandler):
    """Translate between sockets and ``DictionaryApp``."""

    server_version = "dictionary-web"
    timeout = SOCKET_TIMEOUT
    app: DictionaryApp

    def version_string(self) -> str:
        return self.server_version  # do not advertise the Python version

    def do_GET(self) -> None:
        self._serve()

    def do_POST(self) -> None:
        self._serve()

    def _serve(self) -> None:
        parts = urlsplit(self.path)
        headers = {name.lower(): value for name, value in self.headers.items()}
        try:
            query = parse_qs(
                parts.query, keep_blank_values=True, max_num_fields=MAX_FORM_FIELDS
            )
        except ValueError:
            self._send(
                self.app.message(
                    HTTPStatus.BAD_REQUEST, "Bad request", "Too many fields."
                )
            )
            return
        form: Mapping[str, Sequence[str]] = {}
        if self.command == "POST":
            parsed = self._read_form(headers)
            if isinstance(parsed, Response):
                self._send(_secured(parsed))
                return
            form = parsed
        request = Request(self.command, parts.path, query, form, headers)
        self._send(self.app.handle(request))

    def _read_form(self, headers: Mapping[str, str]) -> dict[str, list[str]] | Response:
        def refuse(status: HTTPStatus, text: str) -> Response:
            return self.app.message(status, "Request refused", text)

        content_type = headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type != "application/x-www-form-urlencoded":
            return refuse(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Send a form-encoded body."
            )
        length_header = headers.get("content-length")
        if length_header is None:
            return refuse(
                HTTPStatus.LENGTH_REQUIRED, "A Content-Length header is required."
            )
        try:
            length = int(length_header)
        except ValueError:
            return refuse(HTTPStatus.BAD_REQUEST, "Invalid Content-Length.")
        if length < 0:
            return refuse(HTTPStatus.BAD_REQUEST, "Invalid Content-Length.")
        if length > MAX_BODY_BYTES:
            return refuse(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "The request body is too large."
            )
        try:
            text = self.rfile.read(length).decode("utf-8")
            return parse_qs(
                text, keep_blank_values=True, max_num_fields=MAX_FORM_FIELDS
            )
        except (UnicodeDecodeError, ValueError):
            return refuse(HTTPStatus.BAD_REQUEST, "The form could not be read.")

    def _send(self, response: Response) -> None:
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        for name, value in response.headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(response.body)

    def log_message(self, format: str, *args: object) -> None:
        logger.info("%s - %s", self.address_string(), format % args)


class _Server(ThreadingHTTPServer):
    """Threaded, so one slow lookup does not freeze the pages."""

    request_queue_size = 50

    def handle_error(self, request: object, client_address: object) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, ConnectionError | TimeoutError):  # browser went away
            logger.debug("connection from %s dropped: %s", client_address, exc)
        else:
            logger.exception("error while handling a request from %s", client_address)

    def server_bind(self) -> None:
        import socketserver
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = port


def create_server(
    *,
    lookup: func.Lookup,
    history: WordHistory | None,
    host: str = "127.0.0.1",
    port: int = 8000,
    static_dir: Path = STATIC_DIR,
    max_batch: int = MAX_BATCH_WORDS,
) -> ThreadingHTTPServer:
    """Bind a server (port 0 picks a free one); the caller runs and closes it."""
    app = DictionaryApp(
        lookup,
        history,
        static_files=load_static_files(static_dir),
        allowed_hosts=trusted_hosts(host),
        max_batch=max_batch,
    )

    class Handler(_Handler):
        pass

    Handler.app = app

    class Server(_Server):
        address_family = socket.AF_INET6 if ":" in host else socket.AF_INET

    return Server((host, port), Handler)
