import json
import re

import httpx
import pytest
from fastapi.testclient import TestClient

from finstalgia.app import COOKIE, create_app
from finstalgia.config import Config

A = "a" * 32
B = "b" * 32
MOVIE = "1" * 32
LIBRARY = "2" * 32
SERIES = "3" * 32
SEASON = "4" * 32
EPISODE = "5" * 32
SOURCE = "source-distinct-from-item"
TOKENS = {"alice": "secret-alice-jellyfin-token", "bob": "secret-bob-jellyfin-token"}


class Chunks(httpx.AsyncByteStream):
    def __init__(self, data):
        self.data = data
        self.closed = False
        self.count = 0

    async def __aiter__(self):
        for part in self.data:
            self.count += 1
            yield part

    async def aclose(self):
        self.closed = True


class MockJellyfin:
    def __init__(self):
        self.requests = []
        self.fail = None
        self.image_missing = False
        self.modern_only = False
        self.segment = None
        self.network_failure = False
        self.playlist = None
        self.user_data = {"alice": {}, "bob": {}}
        self.reports = []

    def __call__(self, request):
        self.requests.append(request)
        path = request.url.path.removeprefix("/jellyfin")
        auth = request.headers.get("authorization", "")
        assert auth.startswith("MediaBrowser ")
        assert "X-Emby-Token" not in request.headers
        assert "api_key" not in request.url.params
        if path == "/Users/AuthenticateByName":
            fields = json.loads(request.content)
            if fields.get("Username") not in TOKENS or fields.get("Pw") != "correct":
                return httpx.Response(401)
            user = fields["Username"]
            return httpx.Response(
                200,
                json={
                    "AccessToken": TOKENS[user],
                    "User": {"Id": A if user == "alice" else B, "Name": user},
                },
            )
        user = "alice" if TOKENS["alice"] in auth else "bob" if TOKENS["bob"] in auth else None
        if not user:
            return httpx.Response(401)
        if self.network_failure:
            raise httpx.ConnectError("must-not-expose-network-details", request=request)
        if self.fail:
            return httpx.Response(self.fail, text="upstream-secret-details")
        uid = A if user == "alice" else B
        if path.startswith("/Sessions/Playing"):
            report = json.loads(request.content)
            self.reports.append((user, path, report))
            state = self.user_data[user]
            state["PlaybackPositionTicks"] = report["PositionTicks"]
            if path.endswith("/Stopped") and report["PositionTicks"] >= 54000000000 * 0.9:
                state.update(Played=True, PlaybackPositionTicks=0)
            return httpx.Response(204)
        if self.modern_only and path.startswith("/Users/"):
            return httpx.Response(404)
        if "/PlayedItems/" in path or path.startswith("/UserPlayedItems/"):
            if path.startswith("/UserPlayedItems/"):
                assert request.url.params["UserId"] == uid
            else:
                assert path.startswith(f"/Users/{uid}/")
            self.user_data[user].update(Played=request.method == "POST", PlaybackPositionTicks=0)
            return httpx.Response(200, json=self.user_data[user])
        if path.startswith("/Users/"):
            assert path.startswith(f"/Users/{uid}/")
        if path in ("/Items", "/UserViews", f"/Items/{MOVIE}"):
            assert request.url.params["UserId"] == uid
        movie = {
            "Id": MOVIE,
            "Name": "The Quiet Orbit <script>",
            "Type": "Movie",
            "Overview": "A fictional film. <img src=x onerror=alert(1)>",
            "ImageTags": {"Primary": "tag"},
            "ProductionYear": 2001,
            "RunTimeTicks": 54000000000,
            "Genres": ["Drama"],
            "UserData": self.user_data[user],
        }
        if path in (f"/Users/{uid}/Items/Resume", "/UserItems/Resume"):
            if path == "/UserItems/Resume":
                assert request.url.params["UserId"] == uid
            resumed = bool(self.user_data[user].get("PlaybackPositionTicks"))
            return httpx.Response(200, json={"Items": [movie] if resumed else []})
        catalog = {
            LIBRARY: {"Id": LIBRARY, "Name": user + "'s films", "Type": "CollectionFolder"},
            MOVIE: movie,
            SERIES: {"Id": SERIES, "Name": "Small Signals", "Type": "Series"},
            SEASON: {"Id": SEASON, "Name": "Season 1", "Type": "Season", "SeriesId": SERIES},
            EPISODE: {
                **movie,
                "Id": EPISODE,
                "Type": "Episode",
                "Name": "The Return",
                "SeriesId": SERIES,
                "SeriesName": "Small Signals",
                "SeasonId": SEASON,
                "SeasonName": "Season 1",
                "IndexNumber": 2,
                "ParentIndexNumber": 1,
            },
        }
        if path.endswith("/Views") or path == "/UserViews":
            return httpx.Response(200, json={"Items": [catalog[LIBRARY]]})
        if path.endswith("/Items") or path == "/Items":
            parent = request.url.params.get("ParentId")
            items = [catalog[SEASON]] if parent == SERIES else [movie, catalog[SERIES]]
            return httpx.Response(200, json={"Items": items, "TotalRecordCount": 26})
        if path == f"/Shows/{SERIES}/Episodes":
            assert request.url.params["UserId"] == uid
            assert request.url.params["SeasonId"] == SEASON
            return httpx.Response(200, json={"Items": [catalog[EPISODE]], "TotalRecordCount": 1})
        if "/Items/" in path and path.rsplit("/", 1)[-1] in catalog:
            return httpx.Response(200, json=catalog[path.rsplit("/", 1)[-1]])
        if path.endswith("/PlaybackInfo"):
            fields = json.loads(request.content)
            assert fields["UserId"] == uid
            assert fields["EnableDirectPlay"] is False
            assert fields["DeviceProfile"]["TranscodingProfiles"][0]["Container"] == "ts"
            return httpx.Response(
                200,
                json={
                    "MediaSources": [{"Id": SOURCE, "SupportsTranscoding": True}],
                    "PlaySessionId": "play-id",
                },
            )
        if path.endswith("/Images/Primary"):
            return (
                httpx.Response(404)
                if self.image_missing
                else httpx.Response(
                    200, content=b"fake-jpeg", headers={"Content-Type": "image/jpeg"}
                )
            )
        if path.endswith("master.m3u8"):
            if self.playlist is not None:
                return httpx.Response(200, content=self.playlist)
            assert request.url.params["MediaSourceId"] == SOURCE
            assert request.url.params["SegmentContainer"] == "ts"
            return httpx.Response(
                200,
                text="#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=2600000\n"
                "main.m3u8?api_key=do-not-expose\n",
            )
        if path.endswith("main.m3u8"):
            return httpx.Response(
                200,
                text="#EXTM3U\n#EXT-X-TARGETDURATION:6\n"
                '#EXT-X-KEY:METHOD=AES-128,URI="key.key?api_key=secret"\n'
                "#EXTINF:6,\nhls1/main/0.ts?api_key=secret\n#EXT-X-ENDLIST\n",
            )
        if path.endswith(".key"):
            return httpx.Response(200, content=b"1234567890123456")
        if path.endswith(".ts"):
            self.segment = Chunks([b"a" * 65536, b"b" * 65536, b"c" * 17])
            if request.headers.get("range"):
                if request.headers["range"] == "bytes=999999-":
                    return httpx.Response(416, headers={"Content-Range": "bytes */131089"})
                assert request.headers["range"] == "bytes=0-3"
                return httpx.Response(
                    206,
                    stream=Chunks([b"ab", b"cd"]),
                    headers={
                        "Content-Type": "video/mp2t",
                        "Content-Length": "4",
                        "Content-Range": "bytes 0-3/131089",
                        "Accept-Ranges": "bytes",
                    },
                )
            return httpx.Response(200, stream=self.segment, headers={"Content-Type": "video/mp2t"})
        return httpx.Response(404)


@pytest.fixture
def upstream():
    return MockJellyfin()


@pytest.fixture
def app(upstream, tmp_path):
    return create_app(
        Config(jellyfin_url="http://jellyfin.test/jellyfin", config_dir=tmp_path),
        transport=httpx.MockTransport(upstream),
    )


@pytest.fixture
def client(app):
    with TestClient(app, base_url="http://bridge.test") as browser:
        yield browser


def csrf(response):
    return re.search(r'name="csrf" value="([^"]+)"', response.text).group(1)


def sign_in(client, user="alice"):
    page = client.get("/login")
    old = client.cookies.get(COOKIE)
    response = client.post(
        "/login",
        data={"csrf": csrf(page), "username": user, "password": "correct"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert client.cookies.get(COOKIE) != old
    return client.cookies.get(COOKIE)


def start_play(client, ticket=False, quality="720"):
    page = client.get("/item/" + MOVIE)
    response = client.post(
        "/play/" + MOVIE,
        data={"csrf": csrf(page), "quality": quality, "ticket": "yes" if ticket else ""},
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = client.get(response.headers["location"])
    assert page.status_code == 200
    return re.search(r'<video[^>]+src="([^"]+)"', page.text).group(1)
