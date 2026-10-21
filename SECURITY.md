# Security

v0.1 is a LAN prototype, not security audited for WAN exposure. [Report vulnerabilities privately through GitHub](https://github.com/leodenglovescode/Finstalgia/security/advisories/new). Do not post credentials, tokens, personal media metadata or private keys in public issues.

## Threat model

Assume a trusted operator/bridge host and fixed Jellyfin server, potentially hostile browser inputs, other signed-in users, and LAN network observers. Jellyfin remains the source of account/media authorization. The bridge protects user isolation with server-only access tokens and random session IDs; per-user item routes authorize browsing and artwork, and PlaybackInfo plus user-scoped item lookup authorize creation of media grants. Artwork authorization is cached per session for up to 120 seconds after browsing. Upstream permission revocation may have that delay for cached artwork; upstream 401 invalidates the session. Browser-private poster caching can also retain artwork for 120 seconds.

No arbitrary proxy URL exists. Resource maps admit only same configured origin/base path, specific item ID and MPEG-TS HLS paths. Redirects are not followed. Sensitive query parameters are removed; opaque resource IDs replace complete URLs. Quoted tag URIs are rewritten, unsupported/unsafe formats fail closed. Segments are streamed, metadata bounded. CSRF tokens and optional Origin checks cover all mutating forms including login. Login limiting uses direct peer IP and bounded global state. HTML autoescaping, no third-party resources, restrictive CSP and no-referrer policy reduce script/information exposure. Legacy browsers may ignore some headers, including SameSite/CSP; CSRF does not depend on those headers.

HTTPS has secure cookies and TLS >=1.2, verified upstream TLS and private CA/server keys stored outside public routes with restricted permissions. A newly trusted root has broad authority: verify fingerprints independently. Only parsed/re-encoded public CA DER is downloadable. HTTP allows credential/session interception and is explicitly warned about. Transport mode is a CLI setting; don't run HTTPS mode behind plaintext browser access or bypass the CLI's single-worker deployment.

Configuration can be loaded automatically from `./.env` or an explicit `--env-file`; process environment and CLI flags override it. Files are data, not shell scripts, and no parent-directory search or variable expansion occurs in Finstalgia. Keep config files controlled by the operator and never store Jellyfin passwords/tokens there. Docker Compose and systemd supply their own environment-file processing; see docs/DEPLOYMENT.md for the differences. Docker's build context uses an allowlist that excludes local environment files, certificates and keys. The Docker image uses an unprivileged user; the persistent certificate volume remains sensitive operator state.

## Known limitations

- Single-process, memory-only sessions. Restart logs everyone out. Separate processes/replicas are unsupported, even when each reports one worker. Local logout removes bridge access but does not call an upstream global logout or promise immediate transcode-job deletion. Jellyfin cleans up abandoned transcodes.
- A media ticket is a bearer capability for one playback, limited to 15 minutes and the owning session lifetime; logout revokes it. No-cookie clients with a stolen ticket can use that one stream. A different authenticated bridge account cannot. URL logging is disabled in the CLI; proxies/operators must also redact logs. Tickets do not reveal or substitute for Jellyfin API credentials.
- Rate limiting and bounded state reduce accidental overload; they are not DDoS protection. Login passwords are processed in Python memory briefly, not persisted. Python cannot promise immediate secure memory erasure.
- Large unknown upstream responses fail closed. Stream errors after headers cause truncation; status cannot be changed to 502 after headers. No transcoder process runs on the bridge.
- No public Internet security audit, account administration, MFA integration or trusted reverse-proxy header configuration. No certificate auto-renewal, telemetry, external assets or persistent session database. No device validation yet.
- Don't enable request-body/debug/HTTP tracing logs around this app. They could expose credentials. Do not publish Jellyfin/ffmpeg logs without redaction.

| Target | Current evidence |
| --- | --- |
| Python 3.10+ | Declared minimum; host tests performed on 3.11 |
| Jellyfin 10.11 | Published API checked; both browse-route families mocked |
| iPad 2 A1395, iOS 9.3.5 Safari | Primary design target; real device **untested** |
| Modern Safari | Native HLS expected; real playback **untested** |
| Modern Chromium/Firefox | UI preview only; native HLS depends on platform |
