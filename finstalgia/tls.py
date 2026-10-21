import ipaddress
import os
import ssl
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

# TLS 1.2 ECDHE + RSA authentication, supported by iOS 9; no TLS 1.0/1.1.
CIPHERS = "ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-RSA-AES128-SHA256"


def fingerprint(cert):
    return ":".join(f"{b:02X}" for b in cert.fingerprint(hashes.SHA256()))


def write_private(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)


def cert_init(directory, ips, dns_names):
    directory = Path(directory).expanduser()
    sans = [x509.IPAddress(ipaddress.ip_address(value)) for value in ips]
    for name in dns_names:
        if (
            len(name) > 253
            or not name
            or any(
                not label
                or len(label) > 63
                or label.startswith("-")
                or label.endswith("-")
                or not all(c.isascii() and (c.isalnum() or c == "-") for c in label)
                for label in name.split(".")
            )
        ):
            raise ValueError("Use a literal DNS hostname, without wildcards or a URL")
        sans.append(x509.DNSName(name))
    if not sans:
        raise ValueError("Provide at least one --ip or --dns SAN")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.is_symlink():
        raise ValueError("Certificate directory must not be a symbolic link")
    directory.chmod(0o700)
    root_key_path = directory / "ca.key"
    root_path = directory / "ca.pem"
    now = datetime.now(timezone.utc)
    if root_key_path.exists() != root_path.exists():
        raise ValueError("Incomplete CA files; restore both CA files or use a new directory")
    if root_key_path.exists():
        if root_key_path.stat().st_mode & 0o077:
            raise ValueError("CA key must have permission 0600")
        root_key = serialization.load_pem_private_key(root_key_path.read_bytes(), password=None)
        root = x509.load_pem_x509_certificate(root_path.read_bytes())
        if (
            root.public_key().public_numbers() != root_key.public_key().public_numbers()
            or not root.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
            or root.not_valid_after_utc < now + timedelta(days=366)
        ):
            raise ValueError("CA is mismatched, invalid or expires too soon; use a new directory")
    else:
        root_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Finstalgia Local Root CA")])
        root = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(root_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(
                x509.KeyUsage(False, False, False, False, False, True, True, False, False),
                critical=True,
            )
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(root_key.public_key()), False)
            .sign(root_key, hashes.SHA256())
        )
        write_private(
            root_key_path,
            root_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
        )
        write_private(root_path, root.public_bytes(serialization.Encoding.PEM))
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Finstalgia")])
    leaf = (
        x509.CertificateBuilder()
        .subject_name(leaf_name)
        .issuer_name(root.subject)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
        .add_extension(x509.SubjectAlternativeName(sans), False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False)
        .add_extension(
            x509.KeyUsage(True, False, True, False, False, False, False, False, False), True
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()), False
        )
        .sign(root_key, hashes.SHA256())
    )
    # Write temp files exclusively, then atomically replace only the renewable leaf/public CA.
    for name, data in {
        "server.key": leaf_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        "server.pem": leaf.public_bytes(serialization.Encoding.PEM),
        "ca.cer": root.public_bytes(serialization.Encoding.DER),
    }.items():
        temp = directory / (name + ".new")
        write_private(temp, data)
        temp.replace(directory / name)
    return fingerprint(root)


def tls_context(cert, key):
    cert, key = Path(cert), Path(key)
    if not cert.is_file() or not key.is_file():
        raise ValueError("TLS cert/key missing; run cert-init or supply --cert and --key")
    if key.stat().st_mode & 0o077:
        raise ValueError("TLS private key must have permission 0600")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.set_ciphers(CIPHERS)
    context.load_cert_chain(cert, key)
    return context
