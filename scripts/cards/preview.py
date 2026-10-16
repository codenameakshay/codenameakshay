#!/usr/bin/env python3
"""Render a self-contained HTML preview of the README card layout for one theme.

    python3 scripts/cards/preview.py dark  > preview-dark.html
    python3 scripts/cards/preview.py light > preview-light.html

The page mimics GitHub's profile README column (880px, markdown-body colours) and
inlines every SVG as a data URI, so it can be opened anywhere with animations playing.
"""
import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CARDS = ROOT / "assets" / "cards"

theme = sys.argv[1] if len(sys.argv) > 1 else "dark"
bg, fg, muted, line = ("#0d1117", "#f0f6fc", "#9198a1", "#3d444d") if theme == "dark" else ("#ffffff", "#1f2328", "#59636e", "#d1d9e0")


def img(name: str, width: int, href: str = "#") -> str:
    svg = (CARDS / f"{name}-{theme}.svg").read_bytes()
    uri = "data:image/svg+xml;base64," + base64.b64encode(svg).decode()
    return f'<a href="{href}"><img src="{uri}" width="{width}" alt="{name}"></a>'


rows = [
    img("hero", 840),
    "".join(img(f"chip-{n}", 0) for n in ("portfolio", "linkedin", "x", "email")),
    "".join(img(f"stat-{i}", 210) for i in (1, 2, 3, 4)),
    "<h2>Products</h2>",
    img("product-hermes", 420) + img("product-rentaikey", 210) + img("product-prism", 210),
    img("product-odin", 210) + img("product-pokerface", 210) + img("product-hashstudios", 420),
    "<h2>Packages</h2>",
    "".join(img(f"pkg-{k}", 210) for k in ("ai_sdk_dart", "ai_sdk_flutter_ui", "dart_tui", "dart_minify")),
    "".join(img(f"pkg-{k}", 210) for k in ("beui", "flutter_floating_bottom_bar", "async_wallpaper", "secure_content")),
]

# chips have their intrinsic width; drop the width attribute for them
html_rows = "\n".join(f"<p>{r}</p>" if not r.startswith("<h2") else r for r in rows).replace(' width="0"', "")

print(f"""<!doctype html><meta charset="utf-8"><title>README preview ({theme})</title>
<style>
body{{margin:0;background:{bg};color:{fg};font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans",Helvetica,Arial,sans-serif}}
.wrap{{width:846px;margin:0 auto;padding:32px 0}}
p{{margin:0 0 8px}} img{{max-width:100%;vertical-align:top}}
h2{{font-size:24px;font-weight:600;padding-bottom:.3em;border-bottom:1px solid {line};margin:24px 0 16px}}
a{{color:#4493f8;text-decoration:none}} ul{{padding-left:2em;margin:0 0 16px}}
</style>
<div class="wrap">
{html_rows}
</div>""")
