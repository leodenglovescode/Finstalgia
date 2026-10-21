"""Check a running loopback HTTP/HTTPS bridge without Jellyfin credentials."""

import argparse
import socket
import ssl
from urllib.error import URLError
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ca", required=True, help="Public PEM CA for the local HTTPS server")
    parser.add_argument("--http-port", type=int, default=18095)
    parser.add_argument("--https-port", type=int, default=18443)
    args = parser.parse_args()
    context = ssl.create_default_context(cafile=args.ca)
    for port, secure in [(args.http_port, False), (args.https_port, True)]:
        scheme = "https" if secure else "http"
        with urlopen(
            f"{scheme}://127.0.0.1:{port}/login", context=context if secure else None, timeout=5
        ) as response:
            text = response.read(65536).decode()
            assert response.status == 200 and "Jellyfin username" in text
            assert ("HTTP connection" in text) is not secure
            cookie = response.headers.get("Set-Cookie", "")
            assert "HttpOnly" in cookie and ("Secure" in cookie) is secure
            print(scheme.upper(), "login and cookie settings: passed")
    try:
        urlopen(f"https://127.0.0.1:{args.https_port}/login", timeout=5)
    except URLError as exc:
        assert isinstance(exc.reason, ssl.SSLCertVerificationError)
        print("Unknown CA rejected by system trust: passed")
    else:
        raise AssertionError("Expected unknown private CA to fail system trust")
    context.maximum_version = ssl.TLSVersion.TLSv1_2
    with socket.create_connection(("127.0.0.1", args.https_port), timeout=5) as raw:
        with context.wrap_socket(raw, server_hostname="127.0.0.1") as tls:
            assert tls.version() == "TLSv1.2" and "ECDHE-RSA" in tls.cipher()[0]
            print("Verified TLS 1.2 RSA handshake:", tls.cipher()[0])
    try:
        with socket.create_connection(("127.0.0.1", args.https_port), timeout=5) as raw:
            context.wrap_socket(raw, server_hostname="wrong.invalid")
    except ssl.SSLCertVerificationError:
        print("Incorrect SAN rejected: passed")
    else:
        raise AssertionError("Expected SAN mismatch to fail")


if __name__ == "__main__":
    main()
