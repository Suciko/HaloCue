"""Writing request errors are client errors, before any domain command or unsafe read."""

import http.client
import io
import json
import threading
from email.message import Message
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from halocue_writing.app import WritingRequestHandler, make_handler
from halocue_writing.errors import DomainError
from halocue_writing.service import WritingService


@pytest.fixture
def running_service(tmp_path):
    service = WritingService(tmp_path / "writing")
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), make_handler(service, Path(__file__).parents[1] / "web")
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield service, server
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)
    service.close()


@pytest.mark.parametrize("raw", [b"[]", b"null", b"1", b"true", b'"text"', b"{bad", b"\xff"])
def test_nonobject_or_invalid_json_is_400_without_creating_work(running_service, raw):
    service, server = running_service
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    try:
        connection.request(
            "POST", "/api/v1/works", body=raw, headers={"Content-Type": "application/json"}
        )
        response = connection.getresponse()
        result = json.loads(response.read())
        assert response.status == 400
        assert result["error"]["code"] == "invalid_json"
        with service.repo.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM works").fetchone()[0] == 0
    finally:
        connection.close()


def test_object_request_preserves_success_contract(running_service):
    _, server = running_service
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    try:
        connection.request(
            "POST",
            "/api/v1/works",
            body=json.dumps({"title": "Synthetic client"}),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        result = json.loads(response.read())
        assert response.status == 201
        assert result["ok"] is True
        assert result["data"]["title"] == "Synthetic client"
    finally:
        connection.close()


class MustNotRead:
    def read(self, count=-1):
        raise AssertionError(f"Unsafe or unnecessary body read: {count}")


def handler_with_headers(headers):
    handler = object.__new__(WritingRequestHandler)
    handler.headers = Message()
    for name, value in headers:
        handler.headers.add_header(name, value)
    handler.rfile = MustNotRead()
    return handler


@pytest.mark.parametrize("length", ["invalid", "-1", "+1", "1.5", "", "１２"])
def test_invalid_content_length_is_rejected_without_read(length):
    handler = handler_with_headers([("Content-Length", length)])
    with pytest.raises(DomainError) as rejected:
        handler._body()
    assert rejected.value.status == 400
    assert rejected.value.code == "invalid_content_length"


@pytest.mark.parametrize(
    "headers",
    [
        [("Content-Length", "2"), ("Content-Length", "2")],
        [("Transfer-Encoding", "chunked")],
        [("Content-Length", "2"), ("Transfer-Encoding", "chunked")],
    ],
)
def test_ambiguous_or_unsupported_body_framing_never_reads(headers):
    handler = handler_with_headers(headers)
    with pytest.raises(DomainError) as rejected:
        handler._body()
    assert rejected.value.status == 400


def test_oversized_body_retains_route_bound_without_read():
    handler = handler_with_headers([("Content-Length", "11")])
    with pytest.raises(DomainError) as rejected:
        handler._body(max_bytes=10)
    assert rejected.value.code == "payload_too_large"
    assert rejected.value.status == 413


@pytest.mark.parametrize("headers", [[], [("Content-Length", "0")]])
def test_absent_or_empty_body_remains_empty_object(headers):
    assert handler_with_headers(headers)._body() == {}


def test_truncated_body_is_client_error():
    handler = handler_with_headers([("Content-Length", "5")])
    handler.rfile = io.BytesIO(b"{}")
    with pytest.raises(DomainError) as rejected:
        handler._body()
    assert rejected.value.status == 400


def test_very_large_decimal_length_is_bounded_without_integer_conversion():
    handler = handler_with_headers([("Content-Length", "9" * 5000)])
    with pytest.raises(DomainError) as rejected:
        handler._body()
    assert rejected.value.status == 413


@pytest.mark.parametrize(
    "headers",
    [
        [("Content-Length", "-1")],
        [("Content-Length", "bad")],
        [("Content-Length", "2"), ("Content-Length", "2")],
        [("Transfer-Encoding", "chunked")],
    ],
)
def test_bad_framing_returns_a_response_without_waiting_for_body(running_service, headers):
    _, server = running_service
    client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    try:
        client.putrequest("POST", "/api/v1/works")
        for name, value in headers:
            client.putheader(name, value)
        client.endheaders()
        response = client.getresponse()
        assert response.status == 400
        assert json.loads(response.read())["error"]["code"] == "invalid_content_length"
    finally:
        client.close()


@pytest.mark.parametrize("declared", ["2", "0002", " 2 ", "0" * 5000 + "2"])
def test_decimal_length_normalization_keeps_valid_object_bodies(declared):
    handler = handler_with_headers([("Content-Length", declared)])
    handler.rfile = io.BytesIO(b"{}")
    assert handler._body(max_bytes=2) == {}


@pytest.mark.parametrize(
    "wire", [b"Content-Length: \xa02\xa0\r\n\r\n", b"Content-Length: \x852\x85\r\n\r\n"]
)
def test_nonascii_header_whitespace_cannot_hide_invalid_framing(wire):
    handler = handler_with_headers([])
    handler.headers = http.client.parse_headers(io.BytesIO(wire))
    with pytest.raises(DomainError) as rejected:
        handler._body()
    assert rejected.value.code == "invalid_content_length"


def test_invalid_preference_http_update_keeps_saved_file(running_service):
    service, server = running_service
    service.save_user_preferences({"char_warning_threshold": 40})
    path = service.preferences.path
    original = path.read_bytes()
    client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    try:
        client.request(
            "POST",
            "/api/v1/settings/preferences",
            body=b'{"char_warning_threshold":true}',
            headers={"Content-Type": "application/json"},
        )
        response = client.getresponse()
        assert response.status == 400
        assert json.loads(response.read())["error"]["code"] == "invalid_user_preferences"
        assert path.read_bytes() == original
    finally:
        client.close()


def test_corrupt_preference_http_read_is_observable_not_defaults(running_service):
    service, server = running_service
    service.preferences.path.write_bytes(b"{broken")
    client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    try:
        client.request("GET", "/api/v1/settings/preferences")
        response = client.getresponse()
        assert response.status == 400
        assert json.loads(response.read())["error"]["code"] == "invalid_user_preferences"
        assert service.preferences.path.read_bytes() == b"{broken"
    finally:
        client.close()
