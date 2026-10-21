import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values


@dataclass(frozen=True)
class Config:
    jellyfin_url: str = "http://127.0.0.1:8096"
    https: bool = False
    host: str = "127.0.0.1"
    port: int | None = None
    config_dir: Path = field(default_factory=lambda: Path.home() / ".config/finstalgia")
    upstream_ca: str | None = None
    idle_seconds: int = 1800
    max_seconds: int = 14400
    ticket_seconds: int = 900
    page_size: int = 24
    max_sessions: int = 1000
    max_upstream: int = 16

    def __post_init__(self):
        p = urlsplit(self.jellyfin_url)
        if (
            p.scheme not in ("http", "https")
            or not p.hostname
            or p.username
            or p.password
            or p.query
            or p.fragment
            or ".." in p.path
            or "%" in p.path
            or "\\" in self.jellyfin_url
            or any(ord(c) < 33 for c in self.jellyfin_url)
        ):
            raise ValueError(
                "Jellyfin URL must be one fixed HTTP(S) origin with an optional base path"
            )
        if not 60 <= self.idle_seconds <= self.max_seconds <= 86400:
            raise ValueError("Session lifetimes require 60 <= idle <= maximum <= 86400 seconds")
        if not self.host or any(ord(c) < 33 for c in self.host):
            raise ValueError("Bind host must not be empty or contain whitespace")
        if self.port is not None and not 1 <= self.port <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        object.__setattr__(self, "jellyfin_url", self.jellyfin_url.rstrip("/"))
        object.__setattr__(self, "config_dir", Path(self.config_dir).expanduser())

    @classmethod
    def from_env(cls, *, env_file=None, load_env_file=True, **overrides):
        # Only the current directory is searched. Never walk parents or execute shell code.
        file_values = {}
        if load_env_file:
            path = Path(env_file).expanduser() if env_file is not None else Path.cwd() / ".env"
            if env_file is not None and not path.is_file():
                raise ValueError("The specified environment file does not exist")
            if path.is_file():
                file_values = {
                    key: value
                    for key, value in dotenv_values(path, interpolate=False).items()
                    if value is not None
                }
        settings = {**file_values, **os.environ}
        scheme = settings.get("FINSTALGIA_SCHEME", "http")
        if "https" not in overrides and scheme not in ("http", "https"):
            raise ValueError("FINSTALGIA_SCHEME must be http or https")
        configured_port = settings.get("FINSTALGIA_PORT")
        values = dict(
            jellyfin_url=settings.get("FINSTALGIA_JELLYFIN_URL", "http://127.0.0.1:8096"),
            https=scheme == "https",
            host=settings.get("FINSTALGIA_HOST", "127.0.0.1"),
            port=configured_port,
            config_dir=settings.get("FINSTALGIA_CONFIG_DIR", "~/.config/finstalgia"),
            upstream_ca=settings.get("FINSTALGIA_UPSTREAM_CA") or None,
            idle_seconds=settings.get("FINSTALGIA_IDLE_SECONDS", "1800"),
            max_seconds=settings.get("FINSTALGIA_MAX_SECONDS", "14400"),
        )
        values.update(overrides)
        values["port"] = int(values["port"]) if values["port"] not in (None, "") else None
        values["idle_seconds"] = int(values["idle_seconds"])
        values["max_seconds"] = int(values["max_seconds"])
        return cls(**values)
