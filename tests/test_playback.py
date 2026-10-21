import re
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from finstalgia.app import COOKIE, create_app
from finstalgia.config import Config

from .conftest import MOVIE, SOURCE, csrf, sign_in, start_play


def report(client, app, media, event="progress", position=7200000000):
    gid = media.split("/")[2]
    session = app.state.sessions.values[client.cookies.get(COOKIE)]
    session.grants[gid].last_report_at = 0
    return client.post(
        "/playback/" + gid, data={"csrf": session.csrf, "event": event, "position": str(position)}
    )


def test_resume_start_over_and_no_double_transcode_offset(client, app, upstream):
    upstream.user_data["alice"]["PlaybackPositionTicks"] = 7200000000
    sign_in(client)
    detail = client.get("/item/" + MOVIE)
    assert "Resume 12:00" in detail.text and "Start over" in detail.text
    media = start_play(client)
    grant = app.state.sessions.values[client.cookies.get(COOKIE)].grants[media.split("/")[2]]
    assert grant.resume_ticks == 7200000000
    assert "StartTimeTicks" not in grant.root_url
    page = client.get("/watch/" + grant.gid)
    assert 'data-resume="7200000000"' in page.text
    assert 'src="/static/player.js"' in page.text
    assert SOURCE not in page.text
    response = client.post(
        "/play/" + MOVIE, data={"csrf": csrf(detail), "start": "over"}, follow_redirects=False
    )
    grant_id = response.headers["location"].split("/")[-1]
    assert app.state.sessions.values[client.cookies.get(COOKIE)].grants[grant_id].resume_ticks == 0


def test_progress_pause_resume_end_and_continue_watching(client, app, upstream):
    sign_in(client)
    media = start_play(client)
    assert report(client, app, media, "start", 0).status_code == 204
    assert report(client, app, media, "progress").status_code == 204
    assert upstream.reports[-1][1] == "/Sessions/Playing/Progress"
    assert upstream.reports[-1][2]["MediaSourceId"] == SOURCE
    assert upstream.reports[-1][2]["PlaySessionId"] == "play-id"
    assert report(client, app, media, "pause").status_code == 204
    assert upstream.reports[-1][2]["IsPaused"] is True
    assert report(client, app, media, "start").status_code == 204
    assert upstream.reports[-1][2]["IsPaused"] is False
    home = client.get("/")
    assert "Continue watching" in home.text and "Resume 12:00" in home.text
    assert "watch-progress" in home.text
    assert report(client, app, media, "ended", 54000000000).status_code == 204
    assert upstream.reports[-1][1] == "/Sessions/Playing/Stopped"
    assert upstream.user_data["alice"]["Played"]
    assert "Mark unwatched" in client.get("/item/" + MOVIE).text
    count = len(upstream.reports)
    assert report(client, app, media, "ended", 54000000000).status_code == 204
    assert len(upstream.reports) == count


def test_progress_persists_in_jellyfin_after_new_bridge_session(client, app, upstream):
    sign_in(client)
    media = start_play(client)
    assert report(client, app, media).status_code == 204
    client.post("/logout", data={"csrf": csrf(client.get("/"))})
    sign_in(client)
    assert "Resume 12:00" in client.get("/item/" + MOVIE).text
    fresh = create_app(
        Config(jellyfin_url=app.state.config.jellyfin_url), transport=httpx.MockTransport(upstream)
    )
    with TestClient(fresh, base_url="http://bridge.test") as other:
        sign_in(other)
        assert "Resume 12:00" in other.get("/item/" + MOVIE).text


@pytest.mark.parametrize("modern_only", [False, True])
def test_manual_watched_controls_work_without_javascript(client, upstream, modern_only):
    upstream.modern_only = modern_only
    sign_in(client)
    for played, label in [("yes", "Mark unwatched"), ("no", "Mark watched")]:
        page = client.get("/item/" + MOVIE)
        response = client.post("/played/" + MOVIE, data={"csrf": csrf(page), "played": played})
        assert response.status_code == 200 and label in response.text
        assert upstream.user_data["alice"]["Played"] is (played == "yes")


def test_progress_uses_modern_resume_route_and_coalesces_frequent_reports(client, app, upstream):
    upstream.modern_only = True
    sign_in(client)
    media = start_play(client)
    assert report(client, app, media).status_code == 204
    count = len(upstream.reports)
    session = app.state.sessions.values[client.cookies.get(COOKIE)]
    endpoint = "/playback/" + media.split("/")[2]
    assert (
        client.post(
            endpoint, data={"csrf": session.csrf, "event": "progress", "position": "1"}
        ).status_code
        == 204
    )
    assert len(upstream.reports) == count
    assert "Resume 12:00" in client.get("/").text


def test_reports_are_session_scoped_and_csrf_protected(client, app, upstream):
    sign_in(client)
    media = start_play(client, ticket=True)
    endpoint = "/playback/" + media.split("/")[2]
    assert client.post(endpoint, data={"event": "progress", "position": "0"}).status_code == 403
    assert client.post("/played/" + MOVIE, data={"played": "yes"}).status_code == 403
    with TestClient(app, base_url="http://bridge.test") as bob:
        sign_in(bob, "bob")
        response = bob.post(
            endpoint, data={"csrf": csrf(bob.get("/")), "event": "progress", "position": "0"}
        )
        assert response.status_code == 404
        assert not upstream.reports
        assert "Continue watching" not in bob.get("/").text


@pytest.mark.parametrize(
    "event,position",
    [
        ("bogus", "1"),
        ("progress", "-1"),
        ("progress", "NaN"),
        ("progress", "1.5"),
        ("progress", "9999999999999999"),
    ],
)
def test_bad_reports_do_not_reach_jellyfin(client, app, upstream, event, position):
    sign_in(client)
    media = start_play(client)
    assert report(client, app, media, event, position).status_code == 400
    assert not upstream.reports


def test_revoked_reporting_session_returns_401_not_login_redirect(client, app, upstream):
    sign_in(client)
    media = start_play(client)
    upstream.fail = 401
    assert report(client, app, media).status_code == 401


def test_legacy_player_events_and_es5_source():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is optional for the browser event test")
    script = Path(__file__).parents[1] / "finstalgia/static/player.js"
    assert not re.search(
        r"\b(?:let|const|class|async|await|fetch|Promise)\b|=>|`", script.read_text()
    )
    subprocess.run(
        [node, str(Path(__file__).with_name("player_events.cjs")), str(script)], check=True
    )
