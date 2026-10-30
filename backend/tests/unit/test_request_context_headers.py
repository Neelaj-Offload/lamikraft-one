"""RequestContextMiddleware adds its security headers only when the route has not set them."""

from __future__ import annotations

from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from app.core.http.middleware import RequestContextMiddleware


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/plain")
    def plain() -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/own")
    def own() -> Response:
        return Response(b"%PDF-", media_type="application/pdf", headers={
            "X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=60", "Referrer-Policy": "same-origin"})

    return app


def test_defaults_are_added_once() -> None:
    r = TestClient(_app()).get("/plain")
    assert r.headers.get_list("x-content-type-options") == ["nosniff"]
    assert r.headers.get_list("cache-control") == ["no-store"]
    assert r.headers.get_list("referrer-policy") == ["no-referrer"]
    assert r.headers["x-request-id"]


def test_route_headers_win_and_are_not_duplicated() -> None:
    r = TestClient(_app()).get("/own")
    assert r.headers.get_list("x-content-type-options") == ["nosniff"]
    assert r.headers.get_list("cache-control") == ["private, max-age=60"]
    assert r.headers.get_list("referrer-policy") == ["same-origin"]
