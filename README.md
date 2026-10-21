<p align="center">
  <img src="finstalgia/static/logo.svg" width="72" height="72" alt="Finstalgia logo">
</p>

<h1 align="center">Finstalgia</h1>

A lightweight Jellyfin web client for older iPads. Browse your library and play video through Jellyfin’s H.264/AAC transcoding—no app, jailbreak, JavaScript, or frontend build required.

- **Modern and Retro modes**, with native video controls.
- Movies, TV seasons and episodes, search, and 480p/720p profiles.
- Individual Jellyfin accounts, with access tokens kept on the server.

**v0.1 prototype.** Designed for iPad 2 / iOS 9.3.5; actual device playback remains untested.

## Screenshots

| Modern mode | Retro mode |
| --- | --- |
| ![Modern library design preview](docs/preview-modern.png) | ![Retro library design preview](docs/preview-retro.png) |

*Design previews with fictional media. No video is attached.*

## Quick start

Requires Python 3.10+ and a running Jellyfin server.

```sh
git clone https://github.com/leodenglovescode/Finstalgia.git
cd Finstalgia
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
cp .env.example .env
```

Edit `FINSTALGIA_JELLYFIN_URL` in `.env`, then run:

```sh
python -m finstalgia serve
```

Open **http://127.0.0.1:18095** and sign in with your Jellyfin account. `.env` is loaded automatically and Git-ignored. Existing environment variables and CLI flags override it.

**HTTP sends passwords and sessions unencrypted.** Use HTTPS for regular LAN use; do not expose Finstalgia to the public Internet.

## HTTPS on your LAN

Replace the example IP with the bridge’s LAN address:

```sh
python -m finstalgia cert-init --ip 192.168.1.20
python -m finstalgia serve --https --host 0.0.0.0 --port 18443
```

Verify the root CA fingerprint through a trusted channel before installing its public `.cer` file.

- **iOS 9:** install the root certificate/profile, then verify that Safari trusts the exact HTTPS address. It does not have the newer full-trust switch.
- **iOS 10.3+:** after installation, enable the root under **Settings → General → About → Certificate Trust Settings**.

See [certificate setup and troubleshooting](docs/REFERENCE.md#https-and-your-own-local-ca) for transfer options, SANs, clock checks, and custom certificates.

## Deployment

[Docker Compose and Linux systemd setup →](docs/DEPLOYMENT.md)

The Docker image runs as a non-root user and keeps certificates in a persistent volume. Deployment defaults to loopback; LAN access is an explicit setting. Run one instance with one worker. Restarts clear login sessions.

## Status and limitations

Automated tests and local Docker HTTP/HTTPS checks pass. Real Jellyfin transcoding and iPad playback still need validation. Output depends on Jellyfin and ffmpeg; hardware acceleration is configured there. v0.1 has no subtitle/audio selection, watch-progress reporting, offline playback, or DRM support.

[Device checklist](docs/DEVICE_CHECKLIST.md) · [Technical reference](docs/REFERENCE.md) · [Security](SECURITY.md) · [Contributing](CONTRIBUTING.md)

[MIT license](LICENSE)
