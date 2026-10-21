import asyncio
import json
import re
import ssl
from contextlib import asynccontextmanager

import httpx

from . import __version__

ID = re.compile(r"^[a-fA-F0-9-]{20,40}$")
JSON_LIMIT = 2 * 1024 * 1024
VIDEO_QUALITIES = {
    "480": {"width": 854, "height": 480, "bitrate": 1400000, "level": 31},
    "720": {"width": 1280, "height": 720, "bitrate": 2500000, "level": 31},
    "1080": {"width": 1920, "height": 1080, "bitrate": 5000000, "level": 40},
}


class UpstreamError(Exception):
    def __init__(self, status=502):
        self.status = status


def checked_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError("Invalid item identifier")
    return value


def authorization(session=None):
    device = session.device if session else "finstalgia-login"
    value = (
        f'MediaBrowser Client="Finstalgia", Device="Legacy web bridge", '
        f'DeviceId="{device}", Version="{__version__}"'
    )
    if session and session.token:
        # Defense against malformed authentication responses injecting headers.
        if not re.fullmatch(r"[A-Za-z0-9._~-]{1,2048}", session.token):
            raise UpstreamError()
        value += f', Token="{session.token}"'
    return value


class Jellyfin:
    def __init__(self, config, transport=None):
        self.config = config
        context = ssl.create_default_context(cafile=config.upstream_ca)
        self.client = httpx.AsyncClient(
            verify=context,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
            timeout=httpx.Timeout(120, connect=10, pool=10),
            limits=httpx.Limits(max_connections=config.max_upstream, max_keepalive_connections=8),
        )
        self.slots = asyncio.Semaphore(config.max_upstream)

    @asynccontextmanager
    async def stream(self, method, url, session=None, **kwargs):
        headers = {"Authorization": authorization(session), "Accept-Encoding": "identity"}
        headers.update(kwargs.pop("headers", {}))
        try:
            await asyncio.wait_for(self.slots.acquire(), timeout=10)
        except asyncio.TimeoutError:
            raise UpstreamError(503) from None
        try:
            async with self.client.stream(method, url, headers=headers, **kwargs) as response:
                yield response
        except (httpx.HTTPError, OSError):
            # Never propagate an exception string containing the request URL or token.
            raise UpstreamError() from None
        finally:
            self.slots.release()

    async def limited(self, response, limit):
        data = bytearray()
        async for chunk in response.aiter_bytes(64 * 1024):
            if len(data) + len(chunk) > limit:
                raise UpstreamError()
            data.extend(chunk)
        return bytes(data)

    async def api(self, path, session=None, *, method="GET", params=None, body=None):
        async with self.stream(
            method, self.config.jellyfin_url + path, session, params=params, json=body
        ) as response:
            if response.status_code in (401, 403):
                raise UpstreamError(response.status_code)
            if response.status_code != 200:
                raise UpstreamError(404 if response.status_code == 404 else 502)
            raw = await self.limited(response, JSON_LIMIT)
        try:
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except (ValueError, UnicodeError):
            raise UpstreamError() from None

    async def item(self, session, item_id):
        # Preserve the working prototype's per-user route and permission filtering.
        item_id = checked_id(item_id)
        return await self.user_route(session, f"Items/{item_id}", f"/Items/{item_id}")

    async def user_route(self, session, legacy, modern, params=None):
        try:
            return await self.api(f"/Users/{session.user_id}/{legacy}", session, params=params)
        except UpstreamError as exc:
            if exc.status != 404:
                raise
        # 10.11 OpenAPI publishes these routes. Some servers retain the prototype's aliases.
        return await self.api(modern, session, params={**(params or {}), "UserId": session.user_id})

    async def items(self, session, params):
        return await self.user_route(session, "Items", "/Items", params)

    async def views(self, session):
        return await self.user_route(session, "Views", "/UserViews")

    async def mutate(self, path, session, *, method="POST", body=None, params=None):
        async with self.stream(
            method, self.config.jellyfin_url + path, session, json=body, params=params
        ) as response:
            if response.status_code in (401, 403, 404):
                raise UpstreamError(response.status_code)
            if response.status_code not in (200, 204):
                raise UpstreamError()
            await self.limited(response, JSON_LIMIT)

    async def resume(self, session):
        try:
            result = await self.user_route(
                session,
                "Items/Resume",
                "/UserItems/Resume",
                {
                    "Limit": 6,
                    "MediaTypes": "Video",
                    "EnableUserData": "true",
                    "ImageTypeLimit": 1,
                    "EnableImageTypes": "Primary",
                },
            )
        except UpstreamError as exc:
            if exc.status == 404:
                return []
            raise
        return result.get("Items", [])[:6]

    async def mark_played(self, session, item_id, played):
        item_id = checked_id(item_id)
        method = "POST" if played else "DELETE"
        try:
            await self.mutate(
                f"/Users/{session.user_id}/PlayedItems/{item_id}", session, method=method
            )
        except UpstreamError as exc:
            if exc.status != 404:
                raise
            await self.mutate(
                f"/UserPlayedItems/{item_id}",
                session,
                method=method,
                params={"UserId": session.user_id},
            )


def playback_time(ticks):
    seconds = max(0, int(ticks or 0)) // 10000000
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"


def transcode_settings(source_id, quality, play_session):
    video = VIDEO_QUALITIES.get(quality, VIDEO_QUALITIES["720"])
    return {
        "MediaSourceId": source_id,
        "PlaySessionId": play_session,
        "VideoCodec": "h264",
        "AudioCodec": "aac",
        "VideoBitRate": video["bitrate"],
        "AudioBitRate": 128000,
        "MaxWidth": video["width"],
        "MaxHeight": video["height"],
        "MaxFramerate": 30,
        "TranscodingMaxAudioChannels": 2,
        "MaxVideoBitDepth": 8,
        "h264-profile": "main",
        "h264-level": video["level"],
        "Profile": "main",
        "Level": f"{video['level'] // 10}.{video['level'] % 10}",
        "MaxAudioChannels": 2,
        "AudioChannels": 2,
        "SegmentContainer": "ts",
        "MinSegments": 2,
        "AllowVideoStreamCopy": "false",
        "AllowAudioStreamCopy": "false",
        "RequireAvc": "true",
        "SubtitleStreamIndex": -1,
    }


def device_profile(quality):
    video = VIDEO_QUALITIES.get(quality, VIDEO_QUALITIES["720"])
    return {
        "Name": "Finstalgia iPad 2",
        "MaxStreamingBitrate": video["bitrate"] + 200000,
        "DirectPlayProfiles": [],
        "TranscodingProfiles": [
            {
                "Type": "Video",
                "Context": "Streaming",
                "Protocol": "hls",
                "Container": "ts",
                "VideoCodec": "h264",
                "AudioCodec": "aac",
                "MaxAudioChannels": "2",
                "MinSegments": 2,
                "SegmentLength": 6,
                "BreakOnNonKeyFrames": True,
            }
        ],
        "CodecProfiles": [
            {
                "Type": "Video",
                "Codec": "h264",
                "Conditions": [
                    {
                        "Condition": "LessThanEqual",
                        "Property": prop,
                        "Value": val,
                        "IsRequired": True,
                    }
                    for prop, val in [
                        ("Width", str(video["width"])),
                        ("Height", str(video["height"])),
                        ("VideoFramerate", "30"),
                        ("VideoBitDepth", "8"),
                        ("VideoLevel", str(video["level"])),
                    ]
                ],
            }
        ],
        "SubtitleProfiles": [],
    }
