"""Opaque, per-playback resource maps. No upstream URLs reach the browser."""

import asyncio
import re
import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

from .jellyfin import checked_id

MAX_PLAYLIST = 512 * 1024
URI_ATTRIBUTE = re.compile(r'URI="([^"]*)"', re.I)
SENSITIVE = {"api_key", "apikey", "token", "access_token", "authorization"}


class UnsafeMedia(ValueError):
    pass


@dataclass
class Grant:
    item_id: str
    title: str
    quality: str
    source_id: str = ""
    play_session_id: str = ""
    resume_ticks: int = 0
    duration_ticks: int = 0
    last_position_ticks: int = 0
    last_report_at: float = 0
    reported_started: bool = False
    reported_stopped: bool = False
    report_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    gid: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    ticket: str | None = None
    ticket_expires: float = 0
    root_url: str = ""
    resources: OrderedDict = field(default_factory=OrderedDict)
    reverse: dict = field(default_factory=dict)

    def add(self, url):
        if not self.root_url:
            self.root_url = url
        resource = self.reverse.get(url)
        if resource:
            self.resources.move_to_end(resource)
            return resource
        resource = secrets.token_urlsafe(18)
        if len(self.resources) >= 4096:
            _, old_url = self.resources.popitem(last=False)
            self.reverse.pop(old_url, None)
        self.resources[resource] = url
        self.reverse[url] = resource
        return resource

    def local(self, url):
        path = f"/media/{self.gid}/{self.add(url)}"
        return path + ("?ticket=" + self.ticket if self.ticket else "")

    def valid_ticket(self, value):
        return (
            self.ticket
            and value
            and time.monotonic() < self.ticket_expires
            and secrets.compare_digest(self.ticket.encode(), value.encode())
        )


def safe_url(base, current, ref, item_id):
    """Validate both raw and decoded paths before normalizing; permit item-scoped HLS only."""
    checked_id(item_id)
    if len(ref) > 8192 or not ref or ref != ref.strip():
        raise UnsafeMedia("Invalid HLS reference")
    decoded = ref
    for _ in range(4):
        if (
            "\\" in decoded
            or any(ord(c) < 32 or ord(c) == 127 for c in decoded)
            or any(p in (".", "..") for p in urlsplit(decoded).path.split("/") if p == "..")
        ):
            raise UnsafeMedia("Unsafe HLS path")
        newer = unquote(decoded)
        if newer == decoded:
            break
        decoded = newer
    if "%" in urlsplit(decoded).path:
        raise UnsafeMedia("Encoded HLS path is unsupported")
    target = urlsplit(urljoin(current, ref))
    origin = urlsplit(base)
    if (
        target.scheme != origin.scheme
        or target.netloc.lower() != origin.netloc.lower()
        or target.username
        or target.password
        or target.fragment
    ):
        raise UnsafeMedia("External HLS references are unsupported")
    # Jellyfin's TS HLS resources stay under Videos/{itemId}; no admin/image/file routes.
    prefix = origin.path.rstrip("/") + "/Videos/" + item_id + "/"
    path = unquote(target.path)
    if not path.lower().startswith(prefix.lower()) or "//" in path:
        raise UnsafeMedia("HLS reference is outside this playback")
    if not path.lower().endswith((".m3u8", ".ts", ".key")):
        raise UnsafeMedia("Only MPEG-TS HLS playlists, segments and keys are supported")
    query = [
        (k, v)
        for k, v in parse_qsl(target.query, keep_blank_values=True)
        if k.lower() not in SENSITIVE
    ]
    return urlunsplit((target.scheme, target.netloc, target.path, urlencode(query), ""))


def rewrite_playlist(raw, current, base, grant):
    if len(raw) > MAX_PLAYLIST:
        raise UnsafeMedia("HLS playlist is too large")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError:
        raise UnsafeMedia("Invalid HLS playlist") from None
    if not text.startswith("#EXTM3U"):
        raise UnsafeMedia("Expected an HLS playlist")
    lines = []

    def relay(ref):
        return grant.local(safe_url(base, current, ref, grant.item_id))

    for line in text.splitlines():
        line = line.strip()
        if line.startswith(
            (
                "#EXT-X-MAP",
                "#EXT-X-PART",
                "#EXT-X-PRELOAD-HINT",
                "#EXT-X-SESSION-DATA",
                "#EXT-X-DEFINE",
            )
        ):
            raise UnsafeMedia("fMP4, low-latency or variable HLS is unsupported; select TS HLS")
        if line.startswith(("#EXT-X-KEY:", "#EXT-X-SESSION-KEY:")):
            if "METHOD=NONE" not in line and "METHOD=AES-128" not in line:
                raise UnsafeMedia("DRM and SAMPLE-AES HLS are unsupported")
        if line.startswith("#"):
            if re.search(r"(?:^|[, :])URI=", line, re.I) and not URI_ATTRIBUTE.search(line):
                raise UnsafeMedia("Malformed HLS URI attribute")
            line = URI_ATTRIBUTE.sub(lambda m: 'URI="' + relay(m.group(1)) + '"', line)
        elif line:
            line = relay(line)
        lines.append(line)
    return ("\n".join(lines) + "\n").encode()
