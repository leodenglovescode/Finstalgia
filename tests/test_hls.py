import pytest

from finstalgia.hls import MAX_PLAYLIST, Grant, UnsafeMedia, rewrite_playlist, safe_url

from .conftest import MOVIE

BASE = "https://jf.test/jellyfin"
ROOT = BASE + "/Videos/" + MOVIE + "/master.m3u8"


def test_rewrites_relative_absolute_and_uri_attributes():
    grant = Grant(MOVIE, "Film", "720")
    playlist = (
        '#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,URI="audio.m3u8?Token=private"\n'
        '#EXT-X-I-FRAME-STREAM-INF:BANDWIDTH=100,URI="iframe.m3u8"\n'
        '#EXT-X-KEY:METHOD=AES-128,URI="key.key?api_key=private"\n'
        "main.m3u8?foo=bar&api_key=private\n" + BASE + "/Videos/" + MOVIE + "/0.ts\n"
    )
    raw = rewrite_playlist(playlist.encode(), ROOT, BASE, grant).decode()
    assert 'URI="/media/' in raw
    assert "private" not in raw and "jf.test" not in raw
    assert len(grant.resources) == 5
    assert any("foo=bar" in value for value in grant.resources.values())
    assert all(
        "api_key" not in value and "Token" not in value for value in grant.resources.values()
    )


@pytest.mark.parametrize(
    "ref",
    [
        "https://evil.test/0.ts",
        "//evil.test/0.ts",
        "http://jf.test/0.ts",
        "/jellyfin/System/Info",
        "../other.ts",
        "%2e%2e/other.ts",
        "%252e%252e/other.ts",
        "main.m3u8#token",
        "file:///etc/passwd",
        "data:text/plain,secret",
        "\\evil.test\\0.ts",
        "/jellyfin/Videos/" + "f" * 32 + "/0.ts",
        "segment.m4s",
        "main.m3u8\r\nX: y",
    ],
)
def test_unsafe_references_rejected(ref):
    with pytest.raises(UnsafeMedia):
        safe_url(BASE, ROOT, ref, MOVIE)


@pytest.mark.parametrize(
    "tag",
    [
        '#EXT-X-MAP:URI="init.mp4"',
        '#EXT-X-PART:URI="part.ts"',
        '#EXT-X-KEY:METHOD=SAMPLE-AES,URI="key.key"',
        '#EXT-X-KEY:METHOD=AES-128,URI="https://evil.test/key.key"',
        "#EXT-X-MEDIA:URI=broken.m3u8",
        '#EXT-X-DEFINE:NAME="HOST",VALUE="evil"',
    ],
)
def test_unsupported_and_off_origin_tags_rejected(tag):
    with pytest.raises(UnsafeMedia):
        rewrite_playlist(("#EXTM3U\n" + tag).encode(), ROOT, BASE, Grant(MOVIE, "Film", "720"))


def test_playlist_size_and_syntax_bounds():
    for raw in (b"not-hls", b"#EXTM3U\n" + b"x" * MAX_PLAYLIST):
        with pytest.raises(UnsafeMedia):
            rewrite_playlist(raw, ROOT, BASE, Grant(MOVIE, "Film", "720"))


def test_resource_map_bounds_and_deduplication():
    grant = Grant(MOVIE, "Film", "720")
    first = grant.add("first")
    assert grant.add("first") == first
    for i in range(4200):
        grant.add(str(i))
    assert len(grant.resources) == len(grant.reverse) == 4096
    assert first not in grant.resources
