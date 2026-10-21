import re
import time
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from finstalgia.app import COOKIE, create_app
from finstalgia.config import Config

from .conftest import (
    EPISODE,
    LIBRARY,
    MOVIE,
    SEASON,
    SERIES,
    SOURCE,
    TOKENS,
    csrf,
    sign_in,
    start_play,
)


def test_login_invalid_success_and_fixation(client, app):
    response = client.get("/login")
    old_sid = client.cookies.get(COOKIE)
    assert "HTTP connection" in response.text
    assert "WWW-Authenticate" not in response.headers
    bad = client.post(
        "/login", data={"csrf": csrf(response), "username": "alice", "password": "bad"}
    )
    assert bad.status_code == 401
    assert "Sign-in failed" in bad.text
    sign_in(client)
    assert old_sid not in app.state.sessions.values
    assert "alice" in client.get("/").text


@pytest.mark.parametrize("path", ["/art/" + MOVIE, "/media/anything/anything"])
def test_unauthorized_media(client, path):
    assert client.get(path).status_code == 401


def test_csrf_forms_and_origin(client):
    assert (
        client.post("/login", data={"username": "alice", "password": "correct"}).status_code == 403
    )
    page = client.get("/login")
    assert (
        client.post(
            "/login", data={"csrf": csrf(page)}, headers={"Origin": "http://evil.test"}
        ).status_code
        == 403
    )
    sign_in(client)
    for path in ("/logout", "/mode", "/play/" + MOVIE):
        assert client.post(path, data={"csrf": "wrong"}).status_code == 403


def test_opaque_browser_origin_requires_valid_session_csrf(client):
    page = client.get("/login")
    assert (
        client.post(
            "/mode", headers={"Origin": "null"}, data={"csrf": "wrong", "mode": "retro"}
        ).status_code
        == 403
    )
    response = client.post(
        "/mode",
        headers={"Origin": "null"},
        data={"csrf": csrf(page), "mode": "retro", "return": "/login"},
    )
    assert response.status_code == 200 and 'class="retro"' in response.text


def test_non_ascii_security_inputs_fail_safely(client):
    client.get("/login")
    assert client.post("/mode", data={"csrf": "☃"}).status_code == 403
    sign_in(client)
    media = start_play(client, ticket=True)
    # Drop authentication so this exercises the ticket comparison rather than the cookie.
    client.cookies.clear()
    assert client.get(urlsplit(media).path + "?ticket=☃").status_code == 401


def test_logout_and_expiry(client, app):
    sid = sign_in(client)
    media = start_play(client, ticket=True)
    assert (
        client.post(
            "/logout", data={"csrf": csrf(client.get("/"))}, follow_redirects=False
        ).status_code
        == 303
    )
    assert sid not in app.state.sessions.values
    assert client.get(media).status_code == 401
    sid = sign_in(client)
    app.state.sessions.values[sid].touched -= 1801
    assert client.get("/", follow_redirects=False).headers["location"] == "/login"
    sid = sign_in(client)
    app.state.sessions.values[sid].created -= 14401
    assert client.get("/", follow_redirects=False).status_code == 303


def test_cookie_settings(upstream, tmp_path):
    for secure in (False, True):
        app = create_app(
            Config(https=secure, config_dir=tmp_path), transport=httpx.MockTransport(upstream)
        )
        with TestClient(
            app, base_url=("https" if secure else "http") + "://bridge.test"
        ) as browser:
            response = browser.get("/login")
            cookie = response.headers["set-cookie"]
            assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
            assert ("Secure" in cookie) is secure
            assert ("HTTP connection" in response.text) is not secure


def test_two_users_are_isolated(client, app):
    alice_sid = sign_in(client)
    alice_stream = start_play(client)
    with TestClient(app, base_url="http://bridge.test") as bob:
        sign_in(bob, "bob")
        text = bob.get("/").text
        assert "bob&#39;s films" in text and "alice&#39;s films" not in text
        assert bob.get(alice_stream).status_code == 401
        assert bob.get("/watch/" + alice_stream.split("/")[2]).status_code == 404
        assert app.state.sessions.values[alice_sid].token == TOKENS["alice"]


def test_browse_tv_pagination_search_escape_and_no_js(client, upstream):
    sign_in(client)
    page = client.get("/item/" + LIBRARY)
    assert "&lt;script&gt;" in page.text and "<script>" not in page.text
    assert "page=1" in page.text
    client.get("/item/" + LIBRARY + "?page=1")
    assert upstream.requests[-1].url.params["StartIndex"] == "24"
    assert client.get("/item/" + SERIES).status_code == 200
    page = client.get("/item/" + SEASON)
    assert "/item/" + EPISODE in page.text
    page = client.get("/item/" + EPISODE)
    assert "S1 E2" in page.text
    page = client.get("/search?q=Orbit")
    assert "Orbit" in page.text
    assert upstream.requests[-1].url.params["SearchTerm"] == "Orbit"
    assert 'src="http' not in page.text


def test_modern_routes_fallback_only_on_404(client, upstream):
    upstream.modern_only = True
    sign_in(client)
    assert client.get("/").status_code == 200
    assert client.get("/item/" + LIBRARY).status_code == 200
    assert client.get("/item/" + MOVIE).status_code == 200
    assert any(r.url.path == "/jellyfin/UserViews" for r in upstream.requests)


def test_stream_chain_range_chunking_and_no_tokens(client, upstream):
    sign_in(client)
    master = start_play(client)
    response = client.get(master)
    assert response.headers["content-type"].startswith("application/vnd.apple.mpegurl")
    assert "api_key" not in response.text and "do-not-expose" not in response.text
    main = response.text.splitlines()[-1]
    response = client.get(main)
    assert 'URI="/media/' in response.text
    assert "api_key" not in response.text
    key = re.search(r'URI="([^"]+)"', response.text).group(1)
    assert client.get(key).content == b"1234567890123456"
    segment = next(line for line in response.text.splitlines() if line.startswith("/media/"))
    partial = client.get(segment, headers={"Range": "bytes=0-3"})
    assert partial.status_code == 206 and partial.content == b"abcd"
    assert partial.headers["content-range"] == "bytes 0-3/131089"
    unsatisfied = client.get(segment, headers={"Range": "bytes=999999-"})
    assert unsatisfied.status_code == 416
    assert unsatisfied.headers["content-range"] == "bytes */131089"
    whole = client.get(segment)
    assert whole.status_code == 200 and len(whole.content) == 131089
    assert upstream.segment.closed and upstream.segment.count == 3
    assert client.get(segment, headers={"Range": "bytes=0-3,5-8"}).status_code == 400
    for token in TOKENS.values():
        assert token not in response.text
        assert token not in client.get("/item/" + MOVIE).text
    master_request = next(r for r in upstream.requests if r.url.path.endswith("master.m3u8"))
    assert master_request.url.params["MediaSourceId"] == SOURCE
    assert master_request.url.params["AllowVideoStreamCopy"] == "false"
    assert master_request.url.params["MaxWidth"] == "1280"
    watch_url = "/watch/" + master.split("/")[2]
    # Resource LRU updates must never change the player's root playlist on reload.
    for _ in range(3):
        watch = client.get(watch_url)
        assert re.search(r'<video[^>]+src="([^"]+)"', watch.text).group(1) == master


def test_ticket_is_scoped_revocable_and_expires(client, app):
    sid = sign_in(client)
    media = start_play(client, ticket=True, quality="480")
    grant = next(iter(app.state.sessions.values[sid].grants.values()))
    # Native fetcher may have no cookies: capability is limited to one grant and one session.
    with (
        TestClient(app, base_url="http://bridge.test") as native,
        TestClient(app, base_url="http://bridge.test") as bob,
    ):
        assert native.get(media).status_code == 200
        assert native.get(urlsplit(media).path).status_code == 401
        assert native.get(media.replace(grant.ticket, "wrong")).status_code == 401
        sign_in(bob, "bob")
        assert bob.get(media).status_code == 401
        grant.ticket_expires = time.monotonic() - 1
        assert native.get(media).status_code == 401


@pytest.mark.parametrize("status,expected", [(401, 303), (403, 403), (500, 502), (302, 502)])
def test_upstream_failure_safe(client, upstream, status, expected):
    sign_in(client)
    upstream.fail = status
    result = client.get("/", follow_redirects=False)
    assert result.status_code == expected
    assert "upstream-secret-details" not in result.text


def test_missing_images_and_security_headers(client, upstream):
    sign_in(client)
    upstream.image_missing = True
    image = client.get("/art/" + MOVIE)
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/svg+xml")
    assert image.headers["x-content-type-options"] == "nosniff"
    assert "script-src 'none'" in image.headers["content-security-policy"]
    assert image.headers["referrer-policy"] == "no-referrer"


def test_upstream_connection_failure_is_safe_502(client, upstream):
    sign_in(client)
    upstream.network_failure = True
    response = client.get("/")
    assert response.status_code == 502
    assert "must-not-expose" not in response.text


@pytest.mark.parametrize(
    "playlist",
    [
        b"#EXTM3U\nhttps://evil.test/0.ts\n",
        b'#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n',
        b"#EXTM3U\n# " + TOKENS["alice"].encode() + b"\nmain.m3u8\n",
    ],
)
def test_unsafe_playlist_never_reaches_browser(client, upstream, playlist):
    sign_in(client)
    media = start_play(client)
    upstream.playlist = playlist
    response = client.get(media)
    assert response.status_code == 502
    assert TOKENS["alice"] not in response.text and "evil.test" not in response.text


def test_upstream_revocation_invalidates_media_grant(client, app, upstream):
    sid = sign_in(client)
    media = start_play(client, ticket=True)
    upstream.fail = 401
    assert client.get(media).status_code == 401
    assert sid not in app.state.sessions.values


def test_retro_modern_mode_switch_without_javascript(client):
    sign_in(client)
    response = client.post(
        "/mode", data={"csrf": csrf(client.get("/")), "mode": "retro", "return": "/"}
    )
    assert 'class="retro"' in response.text and "Modern" in response.text
    media = start_play(client)
    assert client.get(media).status_code == 200
    assert "FINSTALGIA MEDIA PLAYER" in client.get("/watch/" + media.split("/")[2]).text
    response = client.post(
        "/mode", data={"csrf": csrf(response), "mode": "modern", "return": "//evil.test"}
    )
    assert 'class="modern"' in response.text


def test_rate_limit(client):
    page = client.get("/login")
    for _ in range(5):
        assert (
            client.post(
                "/login", data={"csrf": csrf(page), "username": "alice", "password": "bad"}
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/login", data={"csrf": csrf(page), "username": "alice", "password": "bad"}
        ).status_code
        == 429
    )
