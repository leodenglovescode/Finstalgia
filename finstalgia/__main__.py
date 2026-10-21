import argparse
import logging
import os
import sys

from .config import Config
from .tls import cert_init, fingerprint, tls_context


def main(argv=None):
    parser = argparse.ArgumentParser(description="Finstalgia — app-free Jellyfin for older iPads")
    sub = parser.add_subparsers(dest="command", required=True)
    cert = sub.add_parser(
        "cert-init", help="Create/reuse private CA and renew a 365-day server cert"
    )
    cert.add_argument("--ip", action="append", default=[])
    cert.add_argument("--dns", action="append", default=[])
    cert.add_argument("--config-dir")
    info = sub.add_parser("cert-info", help="Print public root CA SHA-256 fingerprint")
    info.add_argument("--config-dir")
    serve = sub.add_parser("serve", help="Run a single-process LAN bridge")
    for command in (serve, cert, info):
        env = command.add_mutually_exclusive_group()
        env.add_argument("--env-file", help="Use this .env file instead of ./.env")
        env.add_argument("--no-env-file", action="store_true", help="Ignore .env files")
    protocol = serve.add_mutually_exclusive_group()
    protocol.add_argument("--http", action="store_true")
    protocol.add_argument("--https", action="store_true")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--cert")
    serve.add_argument("--key")
    serve.add_argument("--config-dir")
    serve.add_argument("--workers", type=int, default=1, help="Must be 1: in-memory sessions")
    args = parser.parse_args(argv)
    try:
        extra = {"config_dir": args.config_dir} if args.config_dir else {}
        if args.command == "serve":
            if args.http or args.https:
                extra["https"] = args.https
            if args.host is not None:
                extra["host"] = args.host
            if args.port is not None:
                extra["port"] = args.port
        config = Config.from_env(
            env_file=args.env_file, load_env_file=not args.no_env_file, **extra
        )
        if args.command == "cert-init":
            value = cert_init(config.config_dir, args.ip, args.dns)
            print(f"Public CA: {config.config_dir / 'ca.cer'}\nSHA-256: {value}")
            print("Verify this fingerprint over a trusted channel before installing the CA.")
            return
        if args.command == "cert-info":
            from cryptography import x509

            root = x509.load_der_x509_certificate((config.config_dir / "ca.cer").read_bytes())
            print("SHA-256:", fingerprint(root))
            return
        if args.workers != 1 or int(os.getenv("WEB_CONCURRENCY", "1")) != 1:
            parser.error("Finstalgia requires exactly one worker; sessions are process-local")
        if bool(args.cert) != bool(args.key):
            parser.error("Supply both --cert and --key")
        if not config.https and (args.cert or args.key):
            parser.error("--cert and --key require --https")
        import uvicorn

        from .app import create_app

        port = config.port or (18443 if config.https else 18095)
        if not 1 <= port <= 65535:
            parser.error("Port must be between 1 and 65535")
        # No URL/request-body logs: media tickets and credentials must never be recorded.
        for name in ("httpx", "httpcore"):
            logging.getLogger(name).setLevel(logging.CRITICAL)
        server_config = uvicorn.Config(
            create_app(config),
            host=config.host,
            port=port,
            workers=1,
            access_log=False,
            proxy_headers=False,
            limit_concurrency=64,
            timeout_keep_alive=5,
            server_header=False,
            log_level="warning",
        )
        server_config.load()
        if config.https:
            server_config.ssl = tls_context(
                args.cert or config.config_dir / "server.pem",
                args.key or config.config_dir / "server.key",
            )
        print(f"Finstalgia: {'https' if config.https else 'http'}://{config.host}:{port}")
        if not config.https:
            print("WARNING: HTTP sends passwords and sessions unencrypted. Prefer HTTPS.")
        uvicorn.Server(server_config).run()
    except KeyboardInterrupt:
        pass
    except (ValueError, OSError):
        # Do not echo exception strings: they may contain operator secrets or paths.
        print(
            "Configuration/certificate error. Check URL, lifetimes, SANs "
            "and protected cert/key files.",
            file=sys.stderr,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
