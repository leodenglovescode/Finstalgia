# Technical reference

[Back to README](../README.md) · [Deployment](DEPLOYMENT.md)

## HTTPS and your own local CA

```sh
python -m finstalgia cert-init --ip 192.168.3.15 --dns finstalgia.home.arpa
python -m finstalgia cert-info
python -m finstalgia serve --https --host 0.0.0.0 --port 18443
```

Replace the IP and hostname with the actual address you will use. DNS names must resolve to the bridge (configure your LAN DNS). Repeat `--ip` / `--dns` to include multiple names. Certificates default to `~/.config/finstalgia` (override `FINSTALGIA_CONFIG_DIR` or `--config-dir`). Files: private `ca.key` and `server.key`, public `ca.pem`, `ca.cer` (DER), `server.pem`. Directory permission is 0700; generated files are 0600. Nothing is written to the repository. Keep the CA key offline when practical and back it up securely; `serve` needs only server cert/key and optionally the public `ca.cer`. Never distribute a private key. Git ignores certificate/key files as a second safeguard.

The root uses RSA 3072/SHA-256 and a 10-year lifetime; leaf RSA 2048/SHA-256, server-auth EKU, correct CA constraints and a 365-day lifetime. `cert-init` reuses an existing matching CA and replaces the leaf with the supplied SAN set; include **all** still-needed names each time. Restart the bridge after renewal. A new IP/host absent from the SAN requires leaf regeneration. A new or expired CA requires reinstalling the root. Keep the device clock accurate. Protect config files from other local users.

Public certificate distribution is limited to `/ca.cer`. For bootstrap, use a trusted transfer (Mail attachment from a verified source or Apple Configurator), or run HTTP temporarily and visit `http://192.168.3.15:18095/ca.cer` **without signing in**. Compare the CLI's SHA-256 fingerprint through an independent trusted path before installing the root. A fingerprint displayed over that same untrusted HTTP connection is not independent verification. A trusted root can authorize certificates for other sites, so install only a CA you control. After installation, stop HTTP and open `https://192.168.3.15:18443` in Safari without bypassing certificate errors.

### iOS 9 / iPad 2 iOS 9.3.5

1. Check Settings → General → Date & Time, Wi-Fi and the exact IP/DNS SAN.
2. Obtain and verify the **public root** `.cer`. Opening it in Safari, opening a Mail attachment, or deploying a certificate profile with Apple Configurator can start certificate/profile installation. Follow the device's profile prompts (normally Settings → General → Profiles / Profiles & Device Management; wording varies).
3. On iOS 9 a manually installed private root was generally trusted after installation. **Do not look for the iOS 10.3+ “Enable Full Trust for Root Certificates” switch on iOS 9.** Verify actual trust by visiting the exact HTTPS bridge address and ensure Safari reports no trust error.
4. If trust fails, confirm you installed the CA rather than the leaf, compare fingerprints again, inspect the installed profile, check time/SAN/expiry, and confirm TLS 1.2 cipher negotiation. Remove an incorrect profile and reinstall the correct root via a trusted transfer. Do not bypass trust or enable TLS 1.0.

### iOS 10.3 and later

After manual certificate/profile installation, go to **Settings → General → About → Certificate Trust Settings** and enable full trust for the installed root. Newer iOS may first require completing “Profile Downloaded” in Settings. Configurator/MDM deployment can have different trust behavior; verify it on the device. [Apple's current trust instructions](https://support.apple.com/en-us/102390) apply to these newer releases, not the iOS 9 settings UI. [Apple's certificate distribution guide](https://developer.apple.com/library/archive/qa/qa1948/_index.html) describes Safari, Mail and Configurator transfers.

TLS is configured for minimum TLS 1.2 and ECDHE-RSA AES suites; newer TLS versions remain available. No SSL/TLS 1.0/1.1. All playlists, TS segments, keys and images use the same trusted bridge origin. The browser never contacts Jellyfin directly, so there is no HTTPS-to-HTTP mixed content even if the operator uses HTTP between the bridge and a local Jellyfin server.

For a user-supplied RSA certificate with a matching chain and 0600 key:

```sh
python -m finstalgia serve --https --cert /protected/fullchain.pem --key /protected/server.key
```

An ECDSA-only certificate will not work with the intended TLS 1.2 RSA suites. Provision the matching public root separately if using your own CA; the built-in download is only the local `ca.cer` file. Missing or invalid cert/key fails startup.

## Browsing and playback

- Per-user login, libraries, paginated folders (24 cards), movies, series → seasons → episodes, search, breadcrumbs, details, 480p/720p/1080p quality selection, and logout. All video profiles cap output at 30 fps; 720p is selected by default. The theme lasts for the current session.
- Passwords are used only for authentication. High-entropy session cookies reference server-memory tokens; no Jellyfin bearer tokens in browser URLs/HTML/playlists. Every user's requests use their own `Authorization: MediaBrowser` header. No legacy `X-Emby-Token` dependency.
- Connections are pooled, upstream concurrency is bounded (16), requests time out, and posters request 800px JPEG/quality 95 with a 4 MiB ceiling. JSON responses are limited to 2 MiB, playlists to 512 KiB. Poster permissions are remembered per session for 120 seconds after authorized browsing. No global media/metadata cache, infinite scrolling, third-party scripts, fonts or frontend runtime.
- The native `<video controls preload="none">` starts media only when Play is tapped. PlaybackInfo selects the media source before the reference prototype's `/Videos/{itemId}/master.m3u8` flow starts. Output is H.264 Main/8-bit with AAC stereo at 128 kbps: 480p uses 1.4 Mbps, 720p uses 2.5 Mbps, and 1080p uses 5 Mbps. The 480p/720p profiles use level 3.1; 1080p uses level 4.0, which allows 1920×1080 at 30 fps. Stream copy remains disabled.
- [Apple lists 1080p30 H.264 support for iPad 2](https://support.apple.com/en-is/111990). 720p30 remains the default. 4K HEVC/AV1 inputs require upstream Jellyfin transcoding. fMP4/CMAF, WebM, HEVC/AV1 output, SAMPLE-AES/DRM and low-latency HLS remain unsupported.
- Media URLs map to random, per-playback resource IDs in server memory. HLS ordinary references and quoted `URI` attributes are rewritten. Only fixed-origin, item-scoped `/Videos/{itemId}/` `.m3u8`/`.ts`/`.key` resources are allowed; upstream redirects, off-origin URLs, traversal, arbitrary proxy targets and other formats fail closed. Segments stream in 64 KiB chunks; byte ranges and 206/416 headers are preserved. Each session keeps at most three playback grants, each with at most 4096 resources. Opening a fourth player evicts the oldest.
- Default HLS authentication uses the session cookie. **First test cookies on actual Safari.** If the native iOS 9 HLS loader omits them, check the item-page media-ticket option. Its separate opaque capability works without cookies, covers only that playback, expires 15 minutes after creation and dies on logout/session expiry. Keep it private. Open a new player after expiry; long uninterrupted fallback playback is a v0.3 limitation. A browser logged into another account cannot use it. Use the default cookie mode unless your browser needs the fallback.
- The native player reports start, progress, pause and stopped events to Jellyfin using the same user token and media source. Positions save about every 10 seconds and on pause; completed playback uses Jellyfin’s completion rules. Resume seeks within the original zero-based HLS timeline. Manual watched/unwatched controls also work without JavaScript. No custom timeline or subtitle/audio selection is included.

### Jellyfin API compatibility

The supplied `jellyfin_ipad2_bridge_no_auth_v2.py` was reviewed and its modern MediaBrowser auth, user-scoped browsing, `master.m3u8` transcoding parameters and TS proxy approach were retained. It was supplied separately and is not bundled, avoiding personal configuration. No other repository implementation code was copied.

Routes and parameters were checked against [Jellyfin's published 10.11.0 OpenAPI](https://api.jellyfin.org/openapi/stable/jellyfin-openapi-10.11.0.json). The working prototype's `/Users/{userId}/Views`, `/Users/{userId}/Items` and item-detail aliases are tried first. On **404 only**, use documented `/UserViews`, `/Items` and `/Items/{itemId}` with explicit `UserId`. Authentication failures never trigger fallback. Playback info uses `POST /Items/{itemId}/PlaybackInfo`; episodes use `/Shows/{seriesId}/Episodes`. These require no admin credentials. Mock coverage includes both browsing route families. Jellyfin 10.11 is the API target, and playback is confirmed working by the project owner.

### Optional NVIDIA acceleration

Finstalgia does not configure GPUs. In Jellyfin Dashboard → Playback → Transcoding, configure NVIDIA NVENC, install supported host drivers/Jellyfin ffmpeg, and provide the GPU to the Jellyfin container if applicable. Enable only supported decoders/encoders and tone mapping. Check ffmpeg logs for actual hardware decode/encode (`h264_nvenc`) and fallback errors. 4K HDR tone mapping or unsupported source codecs may still consume substantial CPU/GPU. Consult [Jellyfin's NVIDIA guide](https://jellyfin.org/docs/general/post-install/transcoding/hardware-acceleration/nvidia/) and [codec support guide](https://jellyfin.org/docs/general/clients/codec-support/). Hardware transcoding and smooth playback are never guaranteed by URL parameters.

## Configuration and security limits

| Setting | Default |
| --- | --- |
| `FINSTALGIA_JELLYFIN_URL` | `http://127.0.0.1:8096` |
| `FINSTALGIA_CONFIG_DIR` | `~/.config/finstalgia` |
| `FINSTALGIA_UPSTREAM_CA` | system trust store |
| `FINSTALGIA_SCHEME` | `http` (`https` uses generated or supplied certificates) |
| `FINSTALGIA_HOST` | `127.0.0.1` for native CLI; Compose listens inside the container on all interfaces |
| `FINSTALGIA_PORT` | 18095 HTTP / 18443 HTTPS natively; Compose publishes 18095 unless configured |
| `FINSTALGIA_IDLE_SECONDS` | 1800 (30 minutes) |
| `FINSTALGIA_MAX_SECONDS` | 14400 (4 hours; max configurable 24 hours) |
| `FINSTALGIA_BIND_IP` | Compose-only published interface, `127.0.0.1` |
| `--host`, `--port`, `--http`, `--https` | override the corresponding file/environment values |

Sessions use `HttpOnly`, `SameSite=Lax`, `Path=/` and HTTPS-mode `Secure`; IDs rotate on login. CSRF tokens protect login, logout, theme and playback forms. Login attempts are limited per direct peer (5/minute) and globally (100/minute). Passwords/bodies/URLs/tickets are not logged by the CLI; access logging is disabled and proxy headers ignored. If you add a reverse proxy, redact query strings and cookies there too. No device/account details are sent to external services.

**Exactly one process/worker.** All sessions, theme selections and media grants disappear on restart. The CLI rejects `--workers` other than 1 and conflicting `WEB_CONCURRENCY`. Start using the provided CLI; do not run imported app instances behind a multi-worker process manager or replicate containers. Separate manually launched processes cannot detect each other and are unsupported. Logout invalidates the local token reference and ongoing bridge access, but does not revoke every Jellyfin session at the upstream server.

Read [SECURITY.md](../SECURITY.md) for the threat model. This is not a WAN-hardened or audited server. Use a non-admin Jellyfin user with appropriate library permissions. Posters/media are limited to the signed-in account. Anyone possessing a session or valid media ticket has its granted access; protect the bridge host and use HTTPS.

## Verify

```sh
pytest -q
ruff check finstalgia tests tools
python -m compileall -q finstalgia
python -m finstalgia --help
curl -I http://127.0.0.1:18095/static/style.css
curl -fsS http://127.0.0.1:18095/login
# With both local HTTP and HTTPS servers running and a CA including 127.0.0.1:
python tools/smoke.py --ca /path/to/public/ca.pem
```

Use [the device checklist](DEVICE_CHECKLIST.md) to validate iPad 2/iOS 9.3.5, certificate trust, both themes, account isolation and actual TS HLS. It explicitly separates mocked/host results from real device evidence. Modern Chromium/Firefox commonly lack native HLS support; their UI can work while playback does not. Modern Safari supports the same native HLS playback path.

## Limitations and roadmap

No App Store, jailbreak or native application. Legacy Safari has rendering/runtime/native control limitations; cookies and seeking may differ. Old hardware has 512 MiB RAM and limited codec support; lists are paginated and 800-pixel posters served at JPEG quality 95. HTTPS requires CA installation, correct time, SAN, expiry and compatible TLS. HTTP credentials are plaintext on the LAN. Input media can demand heavy CPU/GPU transcoding; output depends on Jellyfin and ffmpeg. DRM/streaming-provider content is unsupported. Some subtitle types need upstream burn-in; v0.3 does not expose subtitle choice. Continue watching, resume, progress reporting and manual watched marks sync with Jellyfin. Audio-only libraries, live TV, subtitle/audio selection, offline caching and native apps are outside the current feature set.

Source is available under the [MIT license](../LICENSE). Public images are available at `leodengdev/finstalgia:latest` and `:0.3.0`.

## Preview assets

The static design previews use fictional titles and original SVG artwork. Regenerate them with `python tools/design_preview.py`. They demonstrate the interface, not device compatibility or working playback.

[Modern library](preview-modern.html) · [Retro library](preview-retro.html) · [Modern player](preview-player-modern.html) · [Retro player](preview-player-retro.html)
