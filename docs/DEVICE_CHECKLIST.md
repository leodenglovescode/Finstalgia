# Actual-device validation record

No boxes are pre-checked: mocked tests and desktop previews are not real-device evidence.

Record date, bridge commit/version, Python/OpenSSL, Jellyfin/ffmpeg version, source codec and device/OS. Do not record real passwords, tokens or personal movie metadata.

## TLS / setup

- [ ] iPad 2 A1395 running iOS 9.3.5, correct clock and LAN address recorded.
- [ ] CLI starts on loopback by default; explicit LAN bind and firewall verified.
- [ ] HTTP login displays prominent plaintext warning, without Basic Auth.
- [ ] Public CA fingerprint compared independently with `cert-info` output.
- [ ] Root profile installed on iOS 9; trust verified without assuming the iOS 10.3+ full-trust UI.
- [ ] Separate iOS 10.3+ test completes full trust switch when applicable.
- [ ] HTTPS uses exact SAN IP/DNS with no certificate override and TLS >=1.2.
- [ ] Upstream HTTPS certificate verification fails on an untrusted server; supplied CA bundle succeeds.

## Browse / memory / user isolation

- [ ] Disable JavaScript; sign in, search, paginate, browse films and series → seasons → episodes.
- [ ] Confirm Modern and Retro modes in landscape 1024×768 and portrait 768×1024; readable text, native scrolling, focus/labels and >=44px taps.
- [ ] Browse a large library across many 24-item pages without Safari reloading/crashing under memory pressure. Inspect small JPEG poster transfer sizes and request count.
- [ ] Confirm absent artwork and empty library render graceful placeholders.
- [ ] Invalid credentials, unavailable Jellyfin, and revoked/expired tokens produce safe messages/relogin.
- [ ] Two independent cookie stores signed into different Jellyfin accounts show only their own library access. Other account's watch/media links fail.
- [ ] Logout invalidates media URLs (including ticket fallback), and restart invalidates all sessions.
- [ ] Cookies have HttpOnly, SameSite=Lax and Secure in HTTPS mode; no Jellyfin tokens in browser HTML, URLs, playlists, storage or logs.

## Real transcoding / video

- [ ] Tap native Play using default session-cookie mode, over HTTPS, with every playlist/segment on the same trusted origin.
- [ ] If cookies fail, record that observation and separately test the opt-in 15-minute ticket mode with the native loader. Verify expiry, logout revocation and reopening the player.
- [ ] Try representative H.264, 4K HEVC and AV1 sources through Jellyfin. Do not imply native HEVC/AV1 playback.
- [ ] Inspect actual ffmpeg output: AVC 8-bit `yuv420p`, Main L3.1 or empirically compatible profile, <=1280×720 / <=30fps, ~2.5 Mbps video, AAC-LC stereo ~128 kbps, TS segments rather than fMP4.
- [ ] Verify first-frame delay, continuous playback for at least 30 minutes, pause/resume, forward/back seek, full screen, orientation changes and Wi-Fi interruptions. Record stalls/errors and time to first frame; do not guess improvements.
- [ ] Repeat at 480p and both UI modes. Confirm native controls remain usable in Retro mode.
- [ ] Verify byte-range requests and 200/206/416 statuses on real upstream media; confirm no off-origin or mixed-content requests.
- [ ] If NVENC enabled, confirm actual hardware encode/decode in server logs and inspect HDR tone mapping/resource use. If software encoding used, record CPU and playback behavior.
- [ ] Record limitations of subtitles (no selection/burn-in UI), codec negotiation, cookies and seeking.

## Host smoke commands

```sh
python -m finstalgia --help
pytest -q
ruff check finstalgia tests tools
python -m compileall -q finstalgia
python -m finstalgia cert-init --ip 127.0.0.1 --config-dir /tmp/finstalgia-tls-check
python -m finstalgia serve --https --port 18443 --config-dir /tmp/finstalgia-tls-check
# In another shell: real CA verification, never curl -k.
curl --cacert /tmp/finstalgia-tls-check/ca.pem https://127.0.0.1:18443/login
```
