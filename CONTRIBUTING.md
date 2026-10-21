# Contributing

Install `python -m pip install -e '.[dev]'`, run `pytest -q`, `ruff check finstalgia tests tools` and `python -m compileall -q finstalgia`. Keep Python 3.10 compatibility. Use the CLI rather than a multi-worker ASGI launcher. Record Python/Jellyfin/browser versions with any test results.

Keep browser pages server rendered, usable without JavaScript, and economical on a 512 MiB iPad. No frontend build, CDN, external fonts, CSS grid/variables, modern browser APIs or framework runtime. Optional player enhancements use ES5 and XMLHttpRequest; the basic browsing/playback path remains usable without JavaScript. Preserve accessible labels, 44px tap targets, pagination and both Modern/Retro styles. Don't replace native video controls with a pretend custom player. Static preview titles and artwork must be fictional/original.

Use mocked accounts and media in tests; never ask for a real password or add tokens, certificates, keys, captured playlists or personal metadata. Keep authenticated state per user; never solve a cookie problem by opening media routes globally. Read SECURITY.md before changing auth, URL handling, TLS or the HLS proxy. Avoid implementation code from other repositories; requirements/API documentation research is welcome. The supplied user prototype is the implementation reference.

Test on an actual iPad before claiming compatibility. Report host checks, mocked checks, output codec verification and device playback separately using docs/DEVICE_CHECKLIST.md. No pushing, publishing or remote releases without the operator's explicit instruction. Before publishing, verify project/package name and trademark availability and provide a private vulnerability contact.
