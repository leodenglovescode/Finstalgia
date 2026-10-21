import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .auth import LoginLimiter, Sessions
from .config import Config
from .hls import MAX_PLAYLIST, Grant, UnsafeMedia, rewrite_playlist, safe_url
from .jellyfin import Jellyfin, UpstreamError, checked_id, device_profile, transcode_settings

PACKAGE = Path(__file__).parent
COOKIE = "finstalgia_session"
PLAYABLE = {"Movie", "Episode", "Video", "MusicVideo", "Trailer"}


class SecurityHeaders:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def safe_send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"no-referrer"),
                        (
                            b"content-security-policy",
                            b"default-src 'none'; style-src 'self'; "
                            b"img-src 'self'; media-src 'self'; form-action 'self'; "
                            b"base-uri 'none'; frame-ancestors 'none'; script-src 'none'",
                        ),
                    ]
                )
                if not any(k.lower() == b"cache-control" for k, _ in headers):
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, safe_send)


def create_app(config=None, *, transport=None):
    config = config or Config.from_env()
    if int(os.getenv("WEB_CONCURRENCY", "1")) != 1:
        raise ValueError("Exactly one worker is required")
    sessions, limiter = Sessions(config), LoginLimiter()
    jf = Jellyfin(config, transport)
    templates = Jinja2Templates(directory=PACKAGE / "templates")
    templates.env.globals["playable"] = PLAYABLE

    @asynccontextmanager
    async def lifespan(app):
        yield
        await jf.client.aclose()
        for sid in list(sessions.values):
            sessions.drop(sid)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.sessions, app.state.jf, app.state.config = sessions, jf, config
    app.add_middleware(SecurityHeaders)
    app.mount("/static", StaticFiles(directory=PACKAGE / "static"), name="static")

    def current(request, required=True):
        session = sessions.get(request.cookies.get(COOKIE))
        request.state.session = session
        if required and (not session or not session.token):
            raise HTTPException(401)
        return session

    def render(request, template, session=None, status=200, **context):
        return templates.TemplateResponse(
            request=request,
            name=template,
            context={
                "session": session,
                "mode": session.mode if session else "modern",
                "secure": config.https,
                **context,
            },
            status_code=status,
        )

    def set_cookie(response, session):
        response.set_cookie(
            COOKIE,
            session.sid,
            httponly=True,
            secure=config.https,
            samesite="lax",
            path="/",
            max_age=config.max_seconds,
        )

    def remember_art(session, items):
        for item in items:
            ident = item.get("Id", "")
            if re.fullmatch(r"[a-fA-F0-9-]{20,40}", ident):
                session.artwork[ident] = time.monotonic()
                session.artwork.move_to_end(ident)
                if len(session.artwork) > 2048:
                    session.artwork.popitem(last=False)

    async def form_data(request, session):
        if not session:
            raise HTTPException(403)
        # Tokens are mandatory even on login. Some embedded/legacy browsers send opaque
        # Origin: null. It grants no authority: those forms must still pass the session token.
        origin = request.headers.get("origin")
        if origin and origin != "null" and origin != str(request.base_url).rstrip("/"):
            raise HTTPException(403)
        if (
            request.headers.get("content-type", "").split(";")[0]
            != "application/x-www-form-urlencoded"
        ):
            raise HTTPException(415)
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 16384:
                raise HTTPException(413)
        try:
            fields = parse_qs(data.decode("utf-8"), keep_blank_values=True, max_num_fields=16)
            fields = {key: values[-1] for key, values in fields.items()}
        except (ValueError, UnicodeError):
            raise HTTPException(400) from None
        if not secrets.compare_digest(fields.get("csrf", "").encode(), session.csrf.encode()):
            raise HTTPException(403)
        return fields

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        if exc.status_code == 401 and not request.url.path.startswith(("/media/", "/art/")):
            response = RedirectResponse("/login", status_code=303)
            response.delete_cookie(
                COOKIE, path="/", secure=config.https, httponly=True, samesite="lax"
            )
            return response
        messages = {
            401: "Please sign in again. This media session has ended.",
            403: "Request not permitted. Reload the page and try again.",
            404: "This page or playback is no longer available.",
            413: "The submitted form is too large.",
            429: "Too many sign-in attempts. Wait a minute.",
        }
        return render(
            request,
            "error.html",
            getattr(request.state, "session", None),
            status=exc.status_code,
            title="Request unavailable",
            message=messages.get(exc.status_code, "The request could not be completed."),
        )

    @app.exception_handler(UpstreamError)
    async def upstream_error(request, exc):
        session = getattr(request.state, "session", None)
        if exc.status == 401:
            if session:
                sessions.drop(session.sid)
            return await http_error(request, HTTPException(401))
        if exc.status == 403:
            return render(
                request,
                "error.html",
                session,
                status=403,
                title="Access unavailable",
                message="Jellyfin does not permit this account to access this item.",
            )
        return render(
            request,
            "error.html",
            session,
            status=502,
            title="Jellyfin is unavailable",
            message="Check the server connection or Jellyfin transcode logs, then try again.",
        )

    @app.exception_handler(UnsafeMedia)
    async def media_error(request, exc):
        return Response(
            "Unsupported or unsafe HLS format. Use Jellyfin MPEG-TS HLS.",
            status_code=502,
            media_type="text/plain",
        )

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return await http_error(request, HTTPException(400))

    @app.get("/login")
    async def login_page(request: Request):
        session = current(request, False)
        if session and session.token:
            return RedirectResponse("/", 303)
        session = session or sessions.new()
        response = render(request, "login.html", session, title="Sign in")
        set_cookie(response, session)
        return response

    @app.post("/login")
    async def login(request: Request):
        session = current(request, False)
        fields = await form_data(request, session)
        address = request.client.host if request.client else "unknown"
        if not limiter.allow(address):
            raise HTTPException(429)
        username, password = fields.get("username", ""), fields.get("password", "")
        if not username or len(username) > 256 or not password or len(password) > 4096:
            return render(
                request,
                "login.html",
                session,
                status=400,
                title="Sign in",
                error="Enter your Jellyfin username and password.",
            )
        try:
            result = await jf.api(
                "/Users/AuthenticateByName",
                session,
                method="POST",
                body={"Username": username, "Pw": password},
            )
        except UpstreamError as exc:
            if exc.status in (401, 403):
                return render(
                    request,
                    "login.html",
                    session,
                    status=401,
                    title="Sign in",
                    error="Sign-in failed. Check your credentials and try again.",
                )
            raise
        try:
            token, user = result["AccessToken"], result["User"]
            if not re.fullmatch(r"[A-Za-z0-9._~-]{1,2048}", token):
                raise ValueError()
            user_id = checked_id(user["Id"])
        except (KeyError, TypeError, ValueError):
            raise UpstreamError() from None
        mode, device = session.mode, session.device
        sessions.drop(session.sid)
        session = sessions.new(
            token=token,
            user_id=user_id,
            name=str(user.get("Name", username)),
            mode=mode,
            device=device,
        )
        response = RedirectResponse("/", 303)
        set_cookie(response, session)
        return response

    @app.post("/logout")
    async def logout(request: Request):
        session = current(request)
        await form_data(request, session)
        sessions.drop(session.sid)
        response = RedirectResponse("/login", 303)
        response.delete_cookie(COOKIE, path="/", secure=config.https, httponly=True, samesite="lax")
        return response

    @app.post("/mode")
    async def mode(request: Request):
        session = current(request, False)
        fields = await form_data(request, session)
        session.mode = "retro" if fields.get("mode") == "retro" else "modern"
        target = fields.get("return", "/")
        if not re.fullmatch(r"/(?:item/[a-fA-F0-9-]{20,40}|watch/[A-Za-z0-9_-]+|login)?", target):
            target = "/"
        return RedirectResponse(target, 303)

    @app.get("/")
    async def home(request: Request, page: int = 0):
        session = current(request)
        if not 0 <= page <= 100000:
            raise HTTPException(400)
        result = await jf.views(session)
        items = result.get("Items", [])
        total = len(items)
        items = items[page * config.page_size : (page + 1) * config.page_size]
        remember_art(session, items)
        return render(
            request,
            "browse.html",
            session,
            title="Libraries",
            items=items,
            description="",
            page=page,
            total=total,
            size=config.page_size,
            page_url="/?",
            crumbs=[],
        )

    @app.get("/search")
    async def search(request: Request, q: str = "", page: int = 0):
        session = current(request)
        q = q.strip()[:120]
        if not 0 <= page <= 100000:
            raise HTTPException(400)
        result = (
            await jf.items(
                session,
                params={
                    "SearchTerm": q,
                    "Recursive": "true",
                    "IncludeItemTypes": "Movie,Series,Episode",
                    "StartIndex": page * config.page_size,
                    "Limit": config.page_size,
                    "Fields": "PrimaryImageAspectRatio",
                    "SortBy": "SortName",
                    "SortOrder": "Ascending",
                },
            )
            if q
            else {"Items": [], "TotalRecordCount": 0}
        )
        items = result.get("Items", [])[: config.page_size]
        remember_art(session, items)
        return render(
            request,
            "browse.html",
            session,
            title="Search",
            items=items,
            q=q,
            description=f"Results for “{q}”" if q else "Find a film, series or episode.",
            page=page,
            total=result.get("TotalRecordCount", len(items)),
            size=config.page_size,
            page_url="/search?" + urlencode({"q": q}) + "&",
            crumbs=[("Search", None)],
        )

    @app.get("/item/{item_id}")
    async def item_page(request: Request, item_id: str, page: int = 0):
        session = current(request)
        if not 0 <= page <= 100000:
            raise HTTPException(400)
        item = await jf.item(session, item_id)
        remember_art(session, [item])
        crumbs = []
        for name_key, id_key in [("SeriesName", "SeriesId"), ("SeasonName", "SeasonId")]:
            if item.get(name_key) and re.fullmatch(r"[a-fA-F0-9-]{20,40}", item.get(id_key, "")):
                crumbs.append((item[name_key], "/item/" + item[id_key]))
        title = item.get("Name", "Untitled")
        crumbs.append((title, None))
        if item.get("Type") in PLAYABLE:
            return render(request, "detail.html", session, title=title, item=item, crumbs=crumbs)
        params = {
            "StartIndex": page * config.page_size,
            "Limit": config.page_size,
            "SortBy": "SortName",
            "SortOrder": "Ascending",
        }
        kind = item.get("Type")
        path = None
        if kind == "Series":
            # Generic per-user item pagination also bounds unusually large season lists.
            params.update(ParentId=item_id, IncludeItemTypes="Season")
        elif kind == "Season" and item.get("SeriesId"):
            path = f"/Shows/{checked_id(item['SeriesId'])}/Episodes"
            params.update(UserId=session.user_id, SeasonId=item_id)
        else:
            params.update(ParentId=item_id)
        result = (
            await jf.api(path, session, params=params) if path else await jf.items(session, params)
        )
        items = result.get("Items", [])[: config.page_size]
        remember_art(session, items)
        return render(
            request,
            "browse.html",
            session,
            title=title,
            items=items,
            description=item.get("Overview", ""),
            crumbs=crumbs,
            page=page,
            total=result.get("TotalRecordCount", len(items)),
            size=config.page_size,
            page_url=f"/item/{item_id}?",
        )

    @app.get("/art/{item_id}")
    async def artwork(request: Request, item_id: str):
        session = current(request)
        checked_id(item_id)
        if time.monotonic() - session.artwork.get(item_id, -9999) > 120:
            item = await jf.item(session, item_id)
            remember_art(session, [item])
        async with jf.stream(
            "GET",
            config.jellyfin_url + f"/Items/{item_id}/Images/Primary",
            session,
            params={"maxWidth": 240, "quality": 65, "format": "jpg"},
        ) as source:
            if source.status_code in (401, 403):
                raise UpstreamError(source.status_code)
            if source.status_code == 404:
                return Response(
                    (PACKAGE / "static/placeholder.svg").read_bytes(), media_type="image/svg+xml"
                )
            if source.status_code != 200 or not source.headers.get("content-type", "").startswith(
                "image/"
            ):
                raise UpstreamError()
            raw = await jf.limited(source, 1024 * 1024)
        return Response(
            raw,
            media_type=source.headers["content-type"],
            headers={"Cache-Control": "private, max-age=120"},
        )

    @app.post("/play/{item_id}")
    async def play(request: Request, item_id: str):
        session = current(request)
        fields = await form_data(request, session)
        item = await jf.item(session, item_id)
        if item.get("Type") not in PLAYABLE:
            raise HTTPException(400)
        quality = "480" if fields.get("quality") == "480" else "720"
        info = await jf.api(
            f"/Items/{checked_id(item_id)}/PlaybackInfo",
            session,
            method="POST",
            body={
                "UserId": session.user_id,
                "EnableDirectPlay": False,
                "EnableDirectStream": False,
                "EnableTranscoding": True,
                "AllowVideoStreamCopy": False,
                "AllowAudioStreamCopy": False,
                "MaxAudioChannels": 2,
                "SubtitleStreamIndex": -1,
                "DeviceProfile": device_profile(quality),
            },
        )
        sources = [
            s
            for s in info.get("MediaSources", [])
            if s.get("Id")
            and s.get("SupportsTranscoding", True)
            and not s.get("RequiresOpening", False)
        ]
        if not sources or info.get("ErrorCode"):
            raise UpstreamError()
        source_id = str(sources[0]["Id"])
        if len(source_id) > 256:
            raise UpstreamError()
        settings = transcode_settings(
            source_id, quality, info.get("PlaySessionId") or secrets.token_hex(16)
        )
        grant = Grant(item_id, str(item.get("Name", "Video")), quality)
        if fields.get("ticket") == "yes":
            grant.ticket = secrets.token_urlsafe(32)
            grant.ticket_expires = time.monotonic() + config.ticket_seconds
        upstream = config.jellyfin_url + f"/Videos/{item_id}/master.m3u8?" + urlencode(settings)
        grant.add(safe_url(config.jellyfin_url, upstream, upstream, item_id))
        if len(session.grants) >= 3:
            session.grants.popitem(last=False)
        session.grants[grant.gid] = grant
        return RedirectResponse("/watch/" + grant.gid, 303)

    @app.get("/watch/{grant_id}")
    async def watch(request: Request, grant_id: str):
        session = current(request)
        grant = session.grants.get(grant_id)
        if not grant:
            raise HTTPException(404)
        return render(
            request,
            "watch.html",
            session,
            title=grant.title,
            grant=grant,
            media_url=grant.local(grant.root_url),
            crumbs=[(grant.title, "/item/" + grant.item_id), ("Player", None)],
        )

    @app.get("/media/{grant_id}/{resource_id}")
    async def media(request: Request, grant_id: str, resource_id: str, ticket: str = ""):
        session = current(request, False)
        grant = session.grants.get(grant_id) if session and session.token else None
        if session and session.token and not grant:
            raise HTTPException(401)
        if not grant and ticket:
            # Validate the ticket BEFORE touching its owning session's idle timer.
            for candidate in list(sessions.values.values()):
                candidate_grant = candidate.grants.get(grant_id)
                if candidate_grant and candidate_grant.valid_ticket(ticket):
                    session = sessions.get(candidate.sid)
                    grant = candidate_grant if session and session.token else None
                    break
        if not grant or not session or not session.token:
            raise HTTPException(401)
        request.state.session = session
        url = grant.resources.get(resource_id)
        if not url:
            raise HTTPException(404)
        headers = {}
        if "range" in request.headers:
            if not re.fullmatch(r"bytes=(?:\d+-\d*|-\d+)", request.headers["range"]):
                raise HTTPException(400)
            headers["Range"] = request.headers["range"]
        if "if-range" in request.headers:
            headers["If-Range"] = request.headers["if-range"][:512]
        context = jf.stream("GET", url, session, headers=headers)
        source = await context.__aenter__()
        streaming = False
        try:
            if source.status_code in (401, 403):
                raise UpstreamError(source.status_code)
            if source.status_code == 416:
                return Response(
                    status_code=416,
                    headers={"Content-Range": source.headers.get("content-range", "bytes */0")},
                )
            if source.status_code not in (200, 206):
                raise UpstreamError()
            if source.headers.get("content-encoding", "identity").lower() != "identity":
                raise UpstreamError()
            is_playlist = urlsplit(url).path.lower().endswith(".m3u8")
            if is_playlist:
                if source.status_code != 200:
                    raise UpstreamError()
                raw = await jf.limited(source, MAX_PLAYLIST)
                rewritten = rewrite_playlist(raw, url, config.jellyfin_url, grant)
                if session.token.encode() in rewritten:
                    raise UnsafeMedia("Sensitive upstream metadata in playlist")
                return Response(rewritten, media_type="application/vnd.apple.mpegurl")
            passthrough = {
                key: source.headers[key]
                for key in ("content-length", "content-range", "accept-ranges", "last-modified")
                if key in source.headers
            }
            mime = (
                "video/mp2t"
                if urlsplit(url).path.lower().endswith(".ts")
                else "application/octet-stream"
            )

            async def chunks():
                try:
                    async for chunk in source.aiter_bytes(64 * 1024):
                        if (
                            not sessions.alive(session)
                            or sessions.values.get(session.sid) is not session
                        ):
                            return
                        yield chunk
                except (UpstreamError, httpx.HTTPError):
                    return  # Headers already sent; end stream. Never leak upstream exceptions.
                finally:
                    await context.__aexit__(None, None, None)

            response = StreamingResponse(
                chunks(), status_code=source.status_code, media_type=mime, headers=passthrough
            )
            streaming = True
            return response
        finally:
            if not streaming:
                await context.__aexit__(None, None, None)

    @app.get("/ca.cer")
    async def ca_download():
        path = config.config_dir / "ca.cer"
        if not path.is_file() or path.is_symlink():
            raise HTTPException(404)
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization

        # Parse then reserialize ONLY a public certificate, even if the file was misconfigured.
        cert = x509.load_der_x509_certificate(path.read_bytes())
        return Response(
            cert.public_bytes(serialization.Encoding.DER),
            media_type="application/x-x509-ca-cert",
            headers={"Content-Disposition": 'attachment; filename="finstalgia-ca.cer"'},
        )

    return app
