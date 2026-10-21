"""Render clearly labeled fictional previews of the real templates; never contact Jellyfin."""

import html
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs"


def main():
    environment = Environment(
        loader=FileSystemLoader(ROOT / "finstalgia/templates"),
        autoescape=select_autoescape(["html"]),
    )
    environment.globals["playable"] = {"Movie", "Episode", "Video"}
    titles = [
        "The Quiet Orbit",
        "Ocean After Hours",
        "A Map of Elsewhere",
        "Last Train North",
        "Small Signals",
        "The Long Weekend",
        "The Glass Garden",
        "Days in Amber",
        "Paper Satellites",
        "Every Blue Morning",
        "Night Crossing",
        "A Place to Begin",
    ]
    palettes = [
        ("#333451", "#cab4ed"),
        ("#173e48", "#a1dbcb"),
        ("#484535", "#dfd0a1"),
        ("#3d2f3c", "#e5adb4"),
        ("#223f52", "#a6c4dc"),
        ("#493a33", "#e7cbb2"),
    ]
    posters = OUTPUT / "posters"
    posters.mkdir(exist_ok=True)
    (posters / "player.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720">'
        '<rect width="1280" height="720" fill="#080b0f"/>'
        '<text x="640" y="360" text-anchor="middle" fill="#8e9aae" '
        'font-family="Arial,sans-serif" font-size="24">No media attached</text></svg>'
    )
    items = []
    for index, title in enumerate(titles):
        ident = f"{index + 1:032x}"
        background, accent = palettes[index % len(palettes)]
        circle_x, circle_y = 70 + index % 3 * 45, 100 + index % 4 * 22
        words = title.split()
        split = max(1, len(words) // 2)
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg"
width="240" height="360" viewBox="0 0 240 360">
<rect width="240" height="360" fill="{background}"/>
<circle cx="{circle_x}" cy="{circle_y}" r="69" fill="none" stroke="{accent}" stroke-width="1.4"/>
<circle cx="{240 - circle_x}" cy="{circle_y + 20}" r="46" fill="{accent}" opacity=".25"/>
<path d="M0 220 L240 {120 + index * 5} L240 240 L0 290Z" fill="{accent}" opacity=".12"/>
<path d="M22 22 H218 V338 H22Z" fill="none" stroke="{accent}" opacity=".35"/>
<text x="120" y="42" text-anchor="middle" fill="{accent}"
font-family="Arial,sans-serif" font-size="8" letter-spacing="3">A FICTIONAL FILM</text>
<text x="120" y="280" text-anchor="middle" fill="{accent}"
font-family="Georgia,serif" font-size="21">{html.escape(" ".join(words[:split]))}</text>
<text x="120" y="307" text-anchor="middle" fill="{accent}"
font-family="Georgia,serif" font-size="21">{html.escape(" ".join(words[split:]))}</text>
<text x="120" y="330" text-anchor="middle" fill="{accent}"
font-family="Arial,sans-serif" font-size="7" letter-spacing="2">
FINSTALGIA DESIGN PREVIEW</text></svg>'''
        (posters / f"{ident}.svg").write_text(svg)
        items.append(
            {
                "Id": ident,
                "Name": title,
                "Type": "Movie",
                "ProductionYear": 1999 + index,
                "RunTimeTicks": (92 + index * 3) * 600000000,
                "ImageTags": {"Primary": "fictional"},
            }
        )
    for mode in ("modern", "retro"):
        session = SimpleNamespace(token=True, csrf="STATIC-PREVIEW-NOT-A-SESSION", mode=mode)
        for player in (False, True):
            name = f"preview-{'player-' if player else ''}{mode}.html"
            page = environment.get_template("watch.html" if player else "browse.html").render(
                title="The Quiet Orbit" if player else "Movies",
                session=session,
                mode=mode,
                secure=True,
                request=SimpleNamespace(url=SimpleNamespace(path="/")),
                items=items,
                description="",
                page=0,
                total=len(items),
                size=24,
                page_url="/?",
                crumbs=[],
                grant=SimpleNamespace(item_id=items[0]["Id"], quality="720", ticket=None),
                media_url="",
            )
            page = page.replace('href="/static/style.css"', 'href="../finstalgia/static/style.css"')
            page = page.replace("/static/logo.svg", "../finstalgia/static/logo.svg")
            page = page.replace(
                '<video controls preload="none" src=""',
                '<video controls preload="none" poster="posters/player.svg"',
            )
            for item in items:
                page = page.replace("/art/" + item["Id"], "posters/" + item["Id"] + ".svg")
            banner = (
                '<aside class="notice warning">DESIGN PREVIEW · Fictional media · No playback. '
                '<a href="preview-modern.html">Modern library</a> · '
                '<a href="preview-retro.html">Retro library</a> · '
                '<a href="preview-player-modern.html">Modern player</a> · '
                '<a href="preview-player-retro.html">Retro player</a></aside>'
            )
            page = page.replace(
                '<main id="content" class="wrap">', '<main id="content" class="wrap">' + banner
            )
            page = page.replace('action="/mode"', 'action="#"').replace(
                'action="/logout"', 'action="#"'
            )
            (OUTPUT / name).write_text(
                "\n".join(line.rstrip() for line in page.splitlines()) + "\n"
            )
    print("Wrote four static design previews and twelve original SVG posters to docs/.")


if __name__ == "__main__":
    main()
