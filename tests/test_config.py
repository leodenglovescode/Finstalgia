import os
import subprocess
import sys

import pytest

from finstalgia.config import Config


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch, tmp_path):
    for key in os.environ:
        if key.startswith("FINSTALGIA_"):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)


def test_dotenv_auto_loading_no_parent_search_and_no_process_mutation(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        'FINSTALGIA_JELLYFIN_URL="http://media.lan:8096/jellyfin"\n'
        "FINSTALGIA_SCHEME=https\nFINSTALGIA_HOST=192.168.1.20\n"
        'FINSTALGIA_PORT=18444\nFINSTALGIA_CONFIG_DIR="~/private certs"\n'
        "FINSTALGIA_IDLE_SECONDS=120\nFINSTALGIA_MAX_SECONDS=3600\n"
    )
    config = Config.from_env()
    assert config.jellyfin_url == "http://media.lan:8096/jellyfin"
    assert config.https and config.port == 18444 and config.host == "192.168.1.20"
    assert config.config_dir.name == "private certs" and config.idle_seconds == 120
    assert "FINSTALGIA_JELLYFIN_URL" not in os.environ
    child = tmp_path / "child"
    child.mkdir()
    monkeypatch.chdir(child)
    assert Config.from_env().jellyfin_url == "http://127.0.0.1:8096"


def test_precedence_flags_process_file_defaults(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "FINSTALGIA_JELLYFIN_URL=http://file.lan:8096\nFINSTALGIA_PORT=18096\n"
    )
    monkeypatch.setenv("FINSTALGIA_JELLYFIN_URL", "http://process.lan:8096")
    monkeypatch.setenv("FINSTALGIA_PORT", "18097")
    assert Config.from_env().jellyfin_url == "http://process.lan:8096"
    assert Config.from_env().port == 18097
    assert Config.from_env(port=18098).port == 18098


def test_explicit_file_missing_file_and_opt_out(tmp_path):
    selected = tmp_path / "custom.env"
    selected.write_text("FINSTALGIA_JELLYFIN_URL=http://custom.lan:8096\n")
    (tmp_path / ".env").write_text("FINSTALGIA_JELLYFIN_URL=http://automatic.lan:8096\n")
    assert Config.from_env(env_file=selected).jellyfin_url == "http://custom.lan:8096"
    assert Config.from_env(load_env_file=False).jellyfin_url == "http://127.0.0.1:8096"
    with pytest.raises(ValueError):
        Config.from_env(env_file=tmp_path / "missing")


def test_dotenv_is_data_not_shell_code_or_interpolation(tmp_path):
    marker = tmp_path / "should-not-exist"
    (tmp_path / ".env").write_text(
        f"UNUSED=$(touch {marker})\n"
        'FINSTALGIA_CONFIG_DIR="/tmp/${HOME}/literal"\n'
        "FINSTALGIA_JELLYFIN_URL\n"
    )
    config = Config.from_env()
    assert str(config.config_dir) == "/tmp/${HOME}/literal"
    assert config.jellyfin_url == "http://127.0.0.1:8096"
    assert not marker.exists()


@pytest.mark.parametrize(
    "setting",
    ["FINSTALGIA_SCHEME=tls", "FINSTALGIA_PORT=0", "FINSTALGIA_PORT=65536", "FINSTALGIA_PORT=no"],
)
def test_bad_settings_fail_closed(tmp_path, setting):
    (tmp_path / ".env").write_text(setting + "\n")
    with pytest.raises(ValueError):
        Config.from_env()


def test_cli_can_override_bad_file_values(tmp_path):
    (tmp_path / ".env").write_text("FINSTALGIA_SCHEME=invalid\nFINSTALGIA_PORT=invalid\n")
    config = Config.from_env(https=False, port=18095)
    assert not config.https and config.port == 18095


def test_empty_port_uses_protocol_default(tmp_path):
    (tmp_path / ".env").write_text("FINSTALGIA_SCHEME=https\nFINSTALGIA_PORT=\n")
    config = Config.from_env()
    assert config.https and config.port is None


def test_cli_consumes_config_and_explicit_overrides_without_starting_server(tmp_path, monkeypatch):
    import uvicorn

    from finstalgia.__main__ import main

    (tmp_path / ".env").write_text(
        "FINSTALGIA_JELLYFIN_URL=http://media.lan:8096\n"
        "FINSTALGIA_SCHEME=http\nFINSTALGIA_HOST=127.0.0.2\nFINSTALGIA_PORT=18096\n"
    )
    configurations = []

    class CaptureServer:
        def __init__(self, config):
            configurations.append(config)

        def run(self):
            pass

    monkeypatch.setattr(uvicorn, "Server", CaptureServer)
    main(["serve"])
    config = configurations[-1]
    assert config.host == "127.0.0.2" and config.port == 18096
    assert config.app.state.config.jellyfin_url == "http://media.lan:8096"
    main(["serve", "--http", "--host", "127.0.0.1", "--port", "18097"])
    assert configurations[-1].host == "127.0.0.1" and configurations[-1].port == 18097
    main(["serve", "--no-env-file"])
    assert configurations[-1].host == "127.0.0.1" and configurations[-1].port == 18095


def test_cli_explicit_file_for_cert_commands(tmp_path):
    env_file = tmp_path / "selected.env"
    directory = tmp_path / "private"
    env_file.write_text(f'FINSTALGIA_CONFIG_DIR="{directory}"\n')
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "finstalgia",
            "cert-init",
            "--ip",
            "127.0.0.1",
            "--env-file",
            str(env_file),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0 and (directory / "ca.cer").is_file()
    assert "SHA-256" in result.stdout
