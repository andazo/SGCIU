from starlette.requests import Request

from app.main import _cors_headers_for_error


def _request(origin: str | None) -> Request:
    headers = [] if origin is None else [(b"origin", origin.encode())]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def test_allowed_origin_is_preserved_on_handled_error():
    origin = "http://localhost:5173"

    assert _cors_headers_for_error(_request(origin)) == {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
        "Vary": "Origin",
    }


def test_disallowed_origin_is_not_reflected_on_handled_error():
    assert _cors_headers_for_error(_request("https://untrusted.example")) == {}
