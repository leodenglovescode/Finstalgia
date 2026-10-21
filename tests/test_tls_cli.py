import ssl
import subprocess
import sys

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID

from finstalgia.tls import cert_init, tls_context


def test_certificates_sans_signature_permissions_and_renewal(tmp_path):
    directory = tmp_path / "certs"
    fingerprint = cert_init(directory, ["192.168.3.15", "127.0.0.1"], ["finstalgia.home.arpa"])
    root = x509.load_pem_x509_certificate((directory / "ca.pem").read_bytes())
    leaf = x509.load_pem_x509_certificate((directory / "server.pem").read_bytes())
    assert x509.load_der_x509_certificate((directory / "ca.cer").read_bytes()) == root
    assert root.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    assert not leaf.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    sans = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert sans.get_values_for_type(x509.DNSName) == ["finstalgia.home.arpa"]
    assert [str(ip) for ip in sans.get_values_for_type(x509.IPAddress)] == [
        "192.168.3.15",
        "127.0.0.1",
    ]
    assert (
        ExtendedKeyUsageOID.SERVER_AUTH
        in leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    )
    assert isinstance(leaf.public_key(), rsa.RSAPublicKey)
    assert leaf.public_key().key_size >= 2048
    assert leaf.signature_hash_algorithm.name == "sha256"
    root.public_key().verify(
        leaf.signature,
        leaf.tbs_certificate_bytes,
        padding.PKCS1v15(),
        leaf.signature_hash_algorithm,
    )
    assert (directory / "ca.key").stat().st_mode & 0o777 == 0o600
    assert (directory / "server.key").stat().st_mode & 0o777 == 0o600
    assert directory.stat().st_mode & 0o777 == 0o700
    context = tls_context(directory / "server.pem", directory / "server.key")
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2
    assert cert_init(directory, ["192.168.3.16"], []) == fingerprint
    assert x509.load_pem_x509_certificate((directory / "ca.pem").read_bytes()) == root


def test_cert_init_invalid_san_and_missing_files(tmp_path):
    for ips, names in [([], []), (["not-an-ip"], []), ([], ["https://bad"]), ([], ["*.example"])]:
        with pytest.raises(ValueError):
            cert_init(tmp_path / "invalid", ips, names)
    with pytest.raises(ValueError):
        tls_context(tmp_path / "absent", tmp_path / "absent.key")


def test_cli_help_and_multiple_workers_rejected():
    result = subprocess.run(
        [sys.executable, "-m", "finstalgia", "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0 and "cert-init" in result.stdout
    result = subprocess.run(
        [sys.executable, "-m", "finstalgia", "serve", "--http", "--workers", "2"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2 and "exactly one worker" in result.stderr


def test_public_ca_route_never_serves_key(client, app):
    directory = app.state.config.config_dir
    cert_init(directory, ["127.0.0.1"], [])
    public = client.get("/ca.cer")
    assert public.status_code == 200
    x509.load_der_x509_certificate(public.content)
    for path in ("/ca.key", "/server.key", "/certs/ca.key", "/static/../ca.key"):
        assert client.get(path).status_code == 404
    (directory / "ca.cer").write_bytes((directory / "ca.key").read_bytes())
    assert client.get("/ca.cer").status_code == 400
