# Deploying Finstalgia

Use one Finstalgia process, pointed at one fixed Jellyfin server. Sessions are in memory; restarts log users out. No GPU or ffmpeg installation is needed on the bridge: transcoding remains in Jellyfin. Playback is confirmed working by the project owner. Docker/systemd use the same player and certificate setup. Keep access on your private LAN; there is no WAN security audit.

## Local Python / development

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
```

Edit `.env`, then run `python -m finstalgia serve`. The default is HTTP on loopback. An example for native LAN HTTPS, after certificate setup:

```dotenv
FINSTALGIA_JELLYFIN_URL=http://192.168.1.10:8096
FINSTALGIA_SCHEME=https
FINSTALGIA_HOST=192.168.1.20
FINSTALGIA_PORT=18443
FINSTALGIA_CONFIG_DIR=~/.config/finstalgia
```

```sh
python -m finstalgia cert-init --ip 192.168.1.20 --dns finstalgia.home.arpa
python -m finstalgia serve
```

Replace example IPs with your server addresses. Set up LAN DNS for optional DNS names. Install and verify the root CA on the iPad following the README. To use an explicit config file from any directory: `python -m finstalgia serve --env-file /path/to/finstalgia.env`. CLI flags override process environment, which overrides file values. Automatic loading reads only `./.env`, without parent searching or shell expansion. Keep passwords/tokens out of every deployment config.

## Docker Compose

Requires Docker Engine/Desktop and the Compose plugin. The supplied Dockerfile uses the official Python slim image, a fixed unprivileged UID/GID (10001), no frontend build or ffmpeg, and a single application process. Compose uses a read-only application filesystem, drops capabilities, prevents privilege escalation, and provides a writable named volume only for certificate state plus temporary storage. Public images are available at `leodengdev/finstalgia` for Linux AMD64 and ARM64. Anonymous pulls need no login. Use `latest` for updates or `0.3.0` to pin the release.

No source checkout is needed:

```sh
mkdir finstalgia && cd finstalgia
curl -fsSLO https://raw.githubusercontent.com/leodenglovescode/Finstalgia/main/compose.yaml
curl -fsSLo .env https://raw.githubusercontent.com/leodenglovescode/Finstalgia/main/deploy/compose.env.example
```

Or, in a source checkout, copy `deploy/compose.env.example` to `.env`. Edit it, then run:

```sh
docker compose config --quiet
docker compose pull
docker compose run --rm finstalgia cert-init --ip 192.168.1.20 --dns finstalgia.home.arpa
docker compose run --rm finstalgia cert-info
docker compose up -d
docker compose ps
docker compose logs --tail=50 finstalgia
```

The Compose example defaults to HTTPS on **127.0.0.1:18443**; run `cert-init` first. For iPad access, edit `FINSTALGIA_BIND_IP` in `.env` to the Docker host's actual LAN IP (the same IP used in the certificate SAN). Restrict the host firewall to your LAN. A `0.0.0.0` publication opts into all IPv4 interfaces. Compose keeps its internal listening port at 18095 for either protocol and maps your chosen external `FINSTALGIA_PORT` to it. Set that external port explicitly when choosing HTTPS; without a Compose port value it defaults to 18095.

```dotenv
FINSTALGIA_JELLYFIN_URL=http://host.docker.internal:8096
FINSTALGIA_SCHEME=https
FINSTALGIA_PORT=18443
FINSTALGIA_BIND_IP=192.168.1.20
```

**Jellyfin addressing matters:** `127.0.0.1` inside the bridge container refers to that container. Use the host's LAN IP or `host.docker.internal` for host-hosted Jellyfin; the Compose host-gateway mapping also supplies that name on Linux. On Linux, Jellyfin must listen on an address reachable from the Docker bridge; a loopback-only listener is not enough. For an existing Jellyfin container, connect Finstalgia to that container's network in a local Compose override and use its service name, such as `http://jellyfin:8096`. Jellyfin need not be bundled or reconfigured by this project. Avoid `network_mode: host` as a default, since it changes isolation and platform behavior.

`host.docker.internal` is a host alias, not the container subnet. Inspect the Compose network with `docker network inspect NETWORK_NAME` to find its subnet and gateway. A host firewall must allow that subnet to reach Jellyfin's host address and TCP port, usually 8096. If Jellyfin disables remote access, include that subnet in its **Dashboard → Networking → LAN networks**, preserving existing entries. A connection timeout suggests routing/firewall filtering; HTTP 503 from an otherwise healthy Jellyfin can indicate its LAN access policy.

Use `docker compose logs -f finstalgia` for upstream failures and rejected/interrupted HLS streams. Logs show route templates and status codes, with no credentials, media tickets, item IDs, or query strings. Routine access logging stays disabled.

Compose reads `.env` for interpolation and passes a specific list of settings into the container. It does not mount or copy `.env`. `FINSTALGIA_CONFIG_DIR` is fixed to `/config` in Compose; `FINSTALGIA_HOST` is replaced by the container's explicit listen address. Settings such as `${VARIABLE}` can be expanded by **Compose itself**, unlike native Finstalgia dotenv parsing. Use simple literal values in both examples. See [Docker's interpolation documentation](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/).

For local-only HTTP testing, edit `.env` to `FINSTALGIA_SCHEME=http`, `FINSTALGIA_PORT=18095`, `FINSTALGIA_BIND_IP=127.0.0.1`, then `docker compose up -d`. HTTP passwords/session cookies are plaintext. `--http`/`--https` are not exposed as UI settings; the operator controls the mode.

### Certificate persistence and backup

`cert-init` and `serve` share the Compose `certificates` named volume at `/config`. The initial volume is populated with the image directory's UID/GID and 0700 permissions; generated keys are 0600. The server runs without root. If you replace the volume with a host bind mount, prepare it for UID/GID 10001 with mode 0700 rather than opening permissions broadly.

Export **only the public root** for device onboarding:

```sh
docker compose cp finstalgia:/config/ca.cer ./finstalgia-ca.cer
docker compose run --rm finstalgia cert-info
```

If the service is not running yet, create it first with `docker compose create`; Compose `cp` can copy from a stopped service container. Transfer that public file via a trusted path and compare its fingerprint. The HTTPS `/ca.cer` route is useful once trust exists; it cannot bootstrap trust without another trusted transfer or temporary HTTP service. Do not expose `/config` as a web directory.

Back up the named volume privately using your Docker host's normal volume-backup procedure. It contains the **CA private key** as well as the server key; protect backups with restricted permissions/encryption and never commit them. Keep a private offline copy of the CA key if removing it from the running volume. A replacement CA requires reinstalling trust on devices; renewing only the leaf with the existing CA normally does not.

```sh
# Renew using ALL still-needed SANs, preserving the existing root:
docker compose run --rm finstalgia cert-init --ip 192.168.1.20 --dns finstalgia.home.arpa
docker compose restart finstalgia
# Apply config changes / stop while retaining certificates:
docker compose up -d
docker compose down
```

Do not add `down --volumes` unless you intend to delete certificate state and have a verified backup. Do not scale replicas or change the worker count. For custom certificates, place the cert/key securely in `/config/server.pem` and `/config/server.key` with UID 10001 ownership and a 0600 private key. Install the corresponding root separately. An optional upstream CA bundle must be available at a container-visible path (for example `/config/upstream-ca.pem`); set `FINSTALGIA_UPSTREAM_CA` to that path, not a host path.

### Updates

Run `docker compose pull` then `docker compose up -d`. Certificates remain in the named volume; login sessions reset. Progress and watched marks remain in Jellyfin. Set `FINSTALGIA_IMAGE=leodengdev/finstalgia:0.3.0` in `.env` to pin a version; use an image digest for a fully fixed deployment. Change it to the previous version and recreate the service to roll back.

To build your own image from a source checkout, use `docker compose -f compose.yaml -f compose.build.yaml up -d --build`. The override selects the local Dockerfile instead of the registry image.

For maintainers: version tags run tests on Python 3.10/3.12 and build AMD64/ARM64 images. Set the repository variable `DOCKERHUB_USERNAME=leodengdev` and a dedicated read/write `DOCKERHUB_TOKEN` Actions secret to enable automatic publication. Without them the workflow checks the build only. A signed-in maintainer can publish manually with `docker buildx build --platform linux/amd64,linux/arm64 -t leodengdev/finstalgia:0.3.0 -t leodengdev/finstalgia:latest --push .`.

## Linux systemd

The template in `deploy/finstalgia.service` is for a dedicated Linux installation at `/opt/finstalgia`, a system user named `finstalgia`, settings in `/etc/finstalgia/finstalgia.env`, and certificates in `/var/lib/finstalgia`. It uses systemd's restart handling, private temporary storage, restricted privileges and filesystem protections. It does not install itself or change this machine's services.

Run these on the intended **Linux host**, adapting paths if needed:

```sh
sudo useradd --system --home-dir /var/lib/finstalgia --shell /usr/sbin/nologin finstalgia
# Place a trusted source checkout at /opt/finstalgia, owned by the administrator.
sudo python3 -m venv /opt/finstalgia/.venv
sudo /opt/finstalgia/.venv/bin/python -m pip install /opt/finstalgia
sudo install -d -o root -g finstalgia -m 0750 /etc/finstalgia
sudo install -o root -g finstalgia -m 0640 /opt/finstalgia/deploy/finstalgia.env.example /etc/finstalgia/finstalgia.env
sudo install -d -o finstalgia -g finstalgia -m 0700 /var/lib/finstalgia
```

Edit `/etc/finstalgia/finstalgia.env` for your Jellyfin URL and bridge bind address. It defaults to HTTPS on loopback; set the actual LAN IP to enable iPad access. Generate certificates with the same config file, then install/start the service:

```sh
sudo -u finstalgia /opt/finstalgia/.venv/bin/python -m finstalgia cert-init --env-file /etc/finstalgia/finstalgia.env --ip 192.168.1.20
sudo install -o root -g root -m 0644 /opt/finstalgia/deploy/finstalgia.service /etc/systemd/system/finstalgia.service
sudo systemd-analyze verify /etc/systemd/system/finstalgia.service
sudo systemctl daemon-reload
sudo systemctl enable --now finstalgia
sudo systemctl status finstalgia
```

The service uses `EnvironmentFile` with `--no-env-file`: the process environment is the only file source at runtime. Use plain `KEY=value` settings without `export`, shell substitutions or `~`; use absolute paths in the systemd file. See [systemd execution settings](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html). Install package updates into the venv as administrator, then `sudo systemctl restart finstalgia`. Back up `/var/lib/finstalgia` privately and keep `/etc/finstalgia/finstalgia.env` with your private operator configuration. Never run multiple service instances.

## Reverse proxies

Direct HTTPS in Finstalgia is the documented path for the old iPad. A TLS-terminating reverse proxy is not a turnkey deployment option in v0.3: proxy headers are ignored and CSRF Origin checks assume the browser origin matches the application request host/scheme. Do not solve a mismatch by removing CSRF checks or trusting arbitrary forwarded headers. TLS passthrough to the bridge preserves its direct HTTPS behavior. If adding a proxy later, implement a narrowly trusted proxy configuration, correct secure-cookie/origin handling, legacy TLS compatibility and query/cookie log redaction, then test it explicitly.

## Validation status

On 2026-10-21: configuration parsing, precedence and CLI behavior passed automated tests. The Docker image built locally on Docker Desktop (Linux ARM64, Python 3.12); Compose configuration validation, non-root UID, key permissions, container HTTP/HTTPS, and CA persistence across container recreation passed smoke checks. TLS 1.2 ECDHE-RSA negotiated successfully; system trust rejected the unknown CA and an incorrect SAN. Native Python 3.11 startup from `.env` also passed. The project owner has confirmed playback works. The systemd unit is a provided template and has not been started on a Linux system by this project. The public container image uses the same playback flow; GitHub Actions records release build and test results.
