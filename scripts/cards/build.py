#!/usr/bin/env python3
"""Build the animated SVG cards used by README.md.

    python3 scripts/cards/build.py          # offline: uses live.json if present, else defaults
    python3 scripts/cards/build.py --live   # refresh pub.dev and GitHub numbers first

Every card is written twice, once per GitHub theme (assets/cards/<name>-light.svg and
-dark.svg), and README.md swaps between them with a <picture> element. Inter is
subset per card and embedded, so the cards render identically everywhere.

Requires: fonttools, brotli   (pip install fonttools brotli)
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import random
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parents[2]
FONT_SRC = ROOT / "scripts" / "cards" / "fonts" / "Inter-latin-variable.woff2"
OUT_DIR = ROOT / "assets" / "cards"
LIVE_FILE = ROOT / "scripts" / "cards" / "live.json"

# --------------------------------------------------------------------------- content

WIDE_PRODUCTS = {"hermes", "hashstudios"}

PRODUCTS = [
    # key, name, description, domain, href
    ("hermes", "Hermes", "Managed hosting for AI agents. One-click deploys to Telegram, Discord and Slack. Bootstrapped, with real customers.", "deploy-hermes.com", "https://deploy-hermes.com"),
    ("rentaikey", "Rent AI Key", "Rent real keyboard keys as time-slotted links. Yes, really.", "rentaikey.com", "https://rentaikey.com"),
    ("prism", "Prism", "Open-source Flutter wallpapers app. 300K+ installs since 2020.", "prismwalls.com", "https://github.com/Hash-Studios/Prism"),
    ("odin", "odin", "Open-source file sharing, AES-256 encrypted end to end.", "github.com/odinapp", "https://github.com/odinapp/odin"),
    ("pokerface", "Pokerface", "Hold'em odds and strategy on iOS. Banned near my friends.", "App Store", "https://apps.apple.com/app/pokerface/id6477531089"),
    ("hashstudios", "Hash Studios", "The studio I co-founded in college. Verified pub.dev publisher behind my open-source packages.", "hashstudios.in", "https://hashstudios.in"),
]

PACKAGES = [
    # key, pub.dev name, description
    ("ai_sdk_dart", "ai_sdk_dart", "Vercel AI SDK v6 for Dart. Streaming, tools and MCP."),
    ("ai_sdk_flutter_ui", "ai_sdk_flutter_ui", "Flutter controllers and widgets for streaming AI chat."),
    ("dart_tui", "dart_tui", "Elm-style terminal UIs for Dart. A Bubble Tea port."),
    ("dart_minify", "dart_minify", "Context packing and structured edits for Dart agents."),
    ("beui", "beui", "Spring-physics motion components. A beUI port."),
    ("flutter_floating_bottom_bar", "flutter_floating_bottom_bar", "A floating bottom bar that hides as you scroll."),
    ("async_wallpaper", "async_wallpaper", "Static and live wallpapers on Android, set off the UI thread."),
    ("secure_content", "secure_content", "Block screenshots and screen recording on iOS and Android."),
]

DEFAULT_LIVE = {
    "versions": {},
    "downloads": {},
    "prism_stars": 665,
    "contributions": 10688,
}


# --------------------------------------------------------------------------- tokens

THEMES = {
    "dark": dict(
        surface="#18181c",
        border_color="#ffffff", border_top=0.14, border_bottom=0.04,
        text="#f5f5f7", text2="rgba(235,235,245,0.62)", text3="rgba(235,235,245,0.34)",
        accent="#f5f5f7", accent_text="#f5f5f7", accent_soft="rgba(245,245,247,0.12)",
        tile="rgba(255,255,255,0.06)", tile2="rgba(255,255,255,0.11)", tile3="rgba(255,255,255,0.20)",
        ink="#0b0b12", on_accent="#1c1c1e",
        shadow=False,
    ),
    "light": dict(
        surface="#fbfbfd",
        border_color="#000000", border_top=0.06, border_bottom=0.10,
        text="#1c1c1e", text2="rgba(60,60,67,0.64)", text3="rgba(60,60,67,0.38)",
        accent="#1c1c1e", accent_text="#1c1c1e", accent_soft="rgba(28,28,30,0.08)",
        tile="rgba(28,28,30,0.05)", tile2="rgba(28,28,30,0.10)", tile3="rgba(28,28,30,0.18)",
        ink="#1c1c1e", on_accent="#fbfbfd",
        shadow=True,
    ),
}

FONT_STACK = "'Inter',-apple-system,BlinkMacSystemFont,'SF Pro Text','Segoe UI',system-ui,sans-serif"
INSET = 8
RADIUS = 20
# Cards are designed at these sizes and rendered at SCALE. GitHub shows the profile README in an
# 846px column, so the displayed grid is 840px: four 210px columns with 16px gutters.
SCALE = 0.85
GRID, WIDE, COL = 988, 494, 247


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --------------------------------------------------------------------------- fonts

class Fonts:
    """Static instances of the Inter variable font, measured and subset on demand."""

    def __init__(self, path: Path):
        self.path = path
        self._bytes: dict[int, bytes] = {}
        self._metrics: dict[int, tuple] = {}

    def _instance_bytes(self, weight: int) -> bytes:
        if weight not in self._bytes:
            vf = TTFont(self.path)
            inst = instancer.instantiateVariableFont(vf, {"wght": weight}, inplace=True)
            buf = io.BytesIO()
            inst.save(buf)
            self._bytes[weight] = buf.getvalue()
        return self._bytes[weight]

    def _metrics_for(self, weight: int):
        if weight not in self._metrics:
            f = TTFont(io.BytesIO(self._instance_bytes(weight)))
            self._metrics[weight] = (f.getBestCmap(), f["hmtx"], f["head"].unitsPerEm)
        return self._metrics[weight]

    def measure(self, text: str, weight: int, size: float, tracking: float = 0.0) -> float:
        cmap, hmtx, upm = self._metrics_for(weight)
        fallback = cmap[ord("?")]
        units = sum(hmtx[cmap.get(ord(ch), fallback)][0] for ch in text)
        return units * size / upm + tracking * max(len(text) - 1, 0)

    def digit_advance(self, weight: int, size: float) -> float:
        cmap, hmtx, upm = self._metrics_for(weight)
        return max(hmtx[cmap[ord(d)]][0] for d in "0123456789") * size / upm

    def face_css(self, weight: int, chars: str) -> str:
        f = TTFont(io.BytesIO(self._instance_bytes(weight)))
        opts = subset.Options()
        opts.flavor = "woff2"
        opts.desubroutinize = True
        opts.name_IDs = [1, 2]
        opts.notdef_outline = True
        s = subset.Subsetter(opts)
        s.populate(text=chars)
        s.subset(f)
        buf = io.BytesIO()
        f.save(buf)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return ("@font-face{font-family:'Inter';font-weight:%d;font-display:block;"
                "src:url(data:font/woff2;base64,%s) format('woff2')}" % (weight, b64))


FONTS = Fonts(FONT_SRC)


def wrap(text: str, weight: int, size: float, maxw: float, max_lines: int = 3) -> list[str]:
    """Greedy word wrap using the embedded font's metrics."""
    lines, cur = [], ""
    for word in text.split():
        cand = f"{cur} {word}".strip()
        if cur and FONTS.measure(cand, weight, size) > maxw:
            lines.append(cur)
            cur = word
        else:
            cur = cand
    if cur:
        lines.append(cur)
    assert len(lines) <= max_lines, f"copy too long for card: {text!r} -> {lines}"
    return lines


# --------------------------------------------------------------------------- card builder

class Card:
    def __init__(self, theme: str, w: int, h: int):
        self.t = THEMES[theme]
        self.theme = theme
        self.w, self.h = w, h
        self.parts: list[str] = []
        self.css: list[str] = []
        self.defs: list[str] = []
        self.chars: dict[int, set] = defaultdict(set)
        self._ids = 0

    # visible surface bounds
    @property
    def x0(self): return INSET
    @property
    def y0(self): return INSET
    @property
    def x1(self): return self.w - INSET
    @property
    def y1(self): return self.h - INSET

    def uid(self, prefix="i") -> str:
        self._ids += 1
        return f"{prefix}{self._ids}"

    def text(self, x, y, s, size, weight=400, fill=None, anchor="start", tracking=0.0, cls="", attrs=""):
        self.chars[weight].update(s)
        fill = fill or self.t["text"]
        ls = f' letter-spacing="{tracking}"' if tracking else ""
        c = f' class="{cls}"' if cls else ""
        self.parts.append(
            f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}"{ls}{c}{(" " + attrs) if attrs else ""}>{esc(s)}</text>'
        )

    def add(self, svg: str): self.parts.append(svg)
    def style(self, css: str):
        self.css.append(css.replace('$OUT', EASE_OUT).replace('$INOUT', EASE_INOUT).replace('$SPRING', EASE_SPRING))
    def define(self, svg: str): self.defs.append(svg)

    def clip(self, x, y, w, h, rx=0) -> str:
        cid = self.uid("clip")
        self.define(f'<clipPath id="{cid}"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}"/></clipPath>')
        return cid

    def render(self) -> str:
        t = self.t
        faces = "".join(FONTS.face_css(w, "".join(sorted(chars))) for w, chars in sorted(self.chars.items()))
        base_css = (
            "text{font-family:%s;-webkit-font-smoothing:antialiased}"
            "@media (prefers-reduced-motion:reduce){*{animation:none!important}}" % FONT_STACK
        )
        border = (
            f'<linearGradient id="bd" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{t["border_color"]}" stop-opacity="{t["border_top"]}"/>'
            f'<stop offset="1" stop-color="{t["border_color"]}" stop-opacity="{t["border_bottom"]}"/>'
            f'</linearGradient>'
        )
        shadow = ""
        filt = ""
        if t["shadow"]:
            shadow = ('<filter id="sh" x="-6%" y="-10%" width="112%" height="130%">'
                      '<feDropShadow dx="0" dy="5" stdDeviation="7" flood-color="#1c1c1e" flood-opacity="0.07"/></filter>')
            filt = ' filter="url(#sh)"'
        surface = (
            f'<rect x="{self.x0 + 0.5}" y="{self.y0 + 0.5}" width="{self.x1 - self.x0 - 1}" height="{self.y1 - self.y0 - 1}" '
            f'rx="{RADIUS}" fill="{t["surface"]}" stroke="url(#bd)"{filt}/>'
        )
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{round(self.w * SCALE)}" height="{round(self.h * SCALE)}" viewBox="0 0 {self.w} {self.h}">'
            f'<style><![CDATA[{faces}{base_css}{"".join(self.css)}]]></style>'
            f'<defs>{border}{shadow}{"".join(self.defs)}</defs>'
            f'{surface}{"".join(self.parts)}</svg>'
        )


# --------------------------------------------------------------------------- shared motion

EASE_OUT = "cubic-bezier(.16,1,.3,1)"
EASE_INOUT = "cubic-bezier(.65,0,.35,1)"
EASE_SPRING = "cubic-bezier(.34,1.4,.64,1)"


def rise_css(count: int, base_delay=0.05, step=0.1) -> str:
    css = ("@keyframes rise{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}"
           ".r{animation:rise .8s %s both}" % EASE_OUT)
    for i in range(count):
        css += ".r%d{animation-delay:%.2fs}" % (i + 1, base_delay + i * step)
    return css


# --------------------------------------------------------------------------- hero

def hero(theme: str) -> str:
    c = Card(theme, GRID, 260)
    t = c.t
    x = 40
    c.text(x, 88, "Akshay Maurya", 40, 700, t["text"], tracking=-1.4, cls="r r1")
    c.text(x, 120, "Flutter and iOS by trade, AI by curiosity. Based in Bengaluru.", 16, 400, t["text2"], cls="r r2")

    label = "Open to Flutter, iOS and AI-mobile roles"
    pw = FONTS.measure(label, 500, 13) + 28
    c.add(f'<g class="r r3"><rect x="{x}" y="146" width="{pw:.0f}" height="30" rx="15" fill="{t["accent_soft"]}"/>')
    c.text(x + 14, 166, label, 13, 500, t["accent_text"])
    c.add("</g>")
    c.text(x, 226, "Building a fintech app at a stealth startup. Previously at CRED.", 13, 500, t["text3"], cls="r r4")
    c.style(rise_css(4))

    # a phone filling a 7-day streak, then popping the reward badge: the kind of motion I shipped at CRED
    cx, top, pw_, ph = GRID - 184, 30, 124, 200
    screen = "#202024" if theme == "dark" else "#ececf0"
    c.add(f'<g class="phone"><rect x="{cx - pw_ / 2}" y="{top}" width="{pw_}" height="{ph}" rx="26" fill="{screen}" stroke="{t["tile3"]}"/>'
          f'<rect x="{cx - 18}" y="{top + 10}" width="36" height="8" rx="4" fill="{t["tile3"]}"/>')
    by = top + 66
    c.add(f'<circle cx="{cx}" cy="{by}" r="28" fill="{t["tile2"]}"/>'
          f'<circle class="burst" cx="{cx}" cy="{by}" r="28" fill="none" stroke="{t["accent"]}" stroke-width="2"/>'
          f'<g class="badge"><circle cx="{cx}" cy="{by}" r="28" fill="{t["accent"]}"/>'
          f'<path d="M{cx - 11},{by + 1} l7,7 l15,-15" fill="none" stroke="{t["on_accent"]}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/></g>')
    dy = top + 124
    c.style(".sd,.badge,.burst{transform-box:fill-box;transform-origin:center}.sd{animation:7s $SPRING infinite}")
    for i in range(7):
        dx = cx - 42 + i * 14
        c.add(f'<circle cx="{dx}" cy="{dy}" r="5" fill="{t["tile3"]}"/><circle class="sd sd{i}" cx="{dx}" cy="{dy}" r="5" fill="{t["accent"]}"/>')
        a = 8 + i * 6
        c.style("@keyframes sd%d{0%%,%d%%{transform:scale(0)}%d%%,88%%{transform:scale(1)}94%%,100%%{transform:scale(0)}}"
                ".sd%d{animation-name:sd%d}" % (i, a, a + 5, i, i))
    for i, bw in enumerate((76, 52)):
        c.add(f'<rect x="{cx - 38}" y="{dy + 24 + i * 14}" width="{bw}" height="7" rx="3.5" fill="{t["tile2"]}"/>')
    c.add("</g>")
    c.style(
        ".phone{animation:rise 1s $OUT both;animation-delay:.3s}"
        ".badge{animation:badge 7s $SPRING infinite}"
        "@keyframes badge{0%,50%{transform:scale(0)}58%,88%{transform:scale(1)}94%,100%{transform:scale(0)}}"
        ".burst{animation:burst 7s $OUT infinite}"
        "@keyframes burst{0%,52%{transform:scale(1);opacity:0}54%{opacity:1}72%,100%{transform:scale(1.8);opacity:0}}"
    )
    return c.render()


# --------------------------------------------------------------------------- proof tiles

def stat(theme: str, value: str, label: str, index: int) -> str:
    c = Card(theme, COL, 128)
    t = c.t
    size, weight = 34, 700
    x, y = 24, 70
    L = 44  # roll pitch
    colw = FONTS.digit_advance(weight, size)
    delay = 0.1 + index * 0.12
    col = 0
    c.style(".d{animation:1.5s %s both}" % EASE_OUT)
    for ch in value:
        if ch.isdigit():
            d = int(ch)
            cid = c.clip(x - 1, y - 30, colw + 2, 40)
            c.add(f'<g clip-path="url(#{cid})"><g class="d roll{d}" style="animation-delay:{delay + col * 0.09:.2f}s">')
            for i in range(20):
                c.text(x + colw / 2, y + i * L, str(i % 10), size, weight, t["text"], anchor="middle")
            c.add("</g></g>")
            c.style("@keyframes roll%d{from{transform:translateY(0)}to{transform:translateY(-%dpx)}}.roll%d{animation-name:roll%d}" % (d, (10 + d) * L, d, d))
            x += colw
            col += 1
        else:
            c.text(x, y, ch, size, weight, t["text"])
            x += FONTS.measure(ch, weight, size)
    c.text(24, 98, label, 13, 400, t["text2"])
    return c.render()


# --------------------------------------------------------------------------- product cards

def product_frame(c: Card, w: int, name: str, desc: str, domain: str):
    t = c.t
    c.text(24, 160, name, 18, 600, t["text"], tracking=-0.3)
    for i, line in enumerate(wrap(desc, 400, 13, w - 48, max_lines=2)):
        c.text(24, 183 + i * 17, line, 13, 400, t["text2"])
    c.text(w - 24, 238, domain, 11, 500, t["text3"], anchor="end")


def motif_area(c: Card, w: int, h: int = 108):
    """Returns (clip id, x, y, w, h) for the motif panel at the top of a card."""
    x, y, mw = 16, 16, w - 32
    cid = c.clip(x, y, mw, h, 14)
    return cid, x, y, mw, h


def panel(c: Card, w: int, fill: str | None = None):
    """Opens the clipped motif panel; the caller closes it with c.add("</g>")."""
    cid, x, y, mw, mh = motif_area(c, w)
    c.add(f'<g clip-path="url(#{cid})"><rect x="{x}" y="{y}" width="{mw}" height="{mh}" fill="{fill or c.t["tile"]}"/>')
    return x, y, mw, mh


def sheen(c: Card, gid: str):
    """A soft accent gradient for 'image' surfaces (wallpapers)."""
    hi = "#ffffff" if c.theme == "dark" else "#4a4a52"
    lo = "#8e8e96" if c.theme == "dark" else c.t["accent"]
    c.define(f'<linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="1">'
             f'<stop offset="0" stop-color="{hi}"/><stop offset="1" stop-color="{lo}"/></linearGradient>')
    return f"url(#{gid})"


def hermes_motif(c: Card, w: int):
    t = c.t
    x, y, mw, mh = panel(c, w)
    # press deploy, then the agent goes live on each channel in turn
    bx, by = x + 28, y + 40
    c.add(f'<g class="btn"><rect x="{bx}" y="{by}" width="96" height="28" rx="14" fill="{t["accent"]}"/>')
    c.text(bx + 48, by + 18.5, "Deploy", 12, 600, t["on_accent"], anchor="middle")
    c.add("</g>")
    sx, sy = bx + 96, by + 14
    px = x + mw - 150
    c.style(".ln{animation:7s $INOUT infinite}.on{animation:7s $OUT infinite}")
    for i, name in enumerate(("Telegram", "Discord", "Slack")):
        py = y + 14 + i * 28
        cy = py + 12
        c.add(f'<path class="ln ln{i}" d="M{sx},{sy} C{sx + 70},{sy} {px - 70},{cy} {px},{cy}" fill="none" stroke="{t["text3"]}" '
              f'stroke-width="1.5" pathLength="1" stroke-dasharray="1" stroke-dashoffset="1"/>')
        c.add(f'<rect x="{px}" y="{py}" width="122" height="24" rx="12" fill="{t["tile2"]}"/>')
        c.text(px + 61, py + 16, name, 11, 500, t["text2"], anchor="middle")
        c.add(f'<g class="on on{i}"><rect x="{px}" y="{py}" width="122" height="24" rx="12" fill="{t["accent"]}"/>')
        c.text(px + 61, py + 16, name, 11, 600, t["on_accent"], anchor="middle")
        c.add("</g>")
        a = 12 + i * 8
        c.style("@keyframes ln%d{0%%,%d%%{stroke-dashoffset:1;opacity:1}%d%%,86%%{stroke-dashoffset:0;opacity:1}94%%,100%%{stroke-dashoffset:0;opacity:0}}"
                ".ln%d{animation-name:ln%d}" % (i, a, a + 12, i, i))
        c.style("@keyframes on%d{0%%,%d%%{opacity:0}%d%%,86%%{opacity:1}94%%,100%%{opacity:0}}"
                ".on%d{animation-name:on%d}" % (i, a + 11, a + 15, i, i))
    c.add("</g>")
    c.style(
        ".btn{transform-box:fill-box;transform-origin:center;animation:press 7s $SPRING infinite}"
        "@keyframes press{0%,5%{transform:scale(1)}8%{transform:scale(.9)}14%,100%{transform:scale(1)}}"
    )


def rentaikey_motif(c: Card, w: int):
    t = c.t
    x, y, mw, mh = panel(c, w)
    kw, kh, gap = 28, 24, 6
    bx = x + (mw - (6 * kw + 5 * gap)) / 2
    rented = {(0, 2): 0, (1, 4): 1, (2, 1): 2}
    c.style(".key{animation:6s $OUT infinite}")
    for r in range(3):
        for k in range(6):
            kx, ky = bx + k * (kw + gap), y + 16 + r * 30
            c.add(f'<rect x="{kx}" y="{ky}" width="{kw}" height="{kh}" rx="6" fill="{t["tile2"]}"/>')
            if (r, k) in rented:
                i = rented[(r, k)]
                ax, ay = kx + kw / 2, ky + kh / 2
                c.add(f'<g class="key key{i}"><rect x="{kx}" y="{ky}" width="{kw}" height="{kh}" rx="6" fill="{t["accent"]}"/>'
                      f'<path d="M{ax - 4},{ay + 4} L{ax + 4},{ay - 4} M{ax - 1},{ay - 4} L{ax + 4},{ay - 4} L{ax + 4},{ay + 1}" '
                      f'fill="none" stroke="{t["on_accent"]}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></g>')
                a = 10 + i * 18
                c.style("@keyframes key%d{0%%,%d%%{opacity:0;transform:none}%d%%{opacity:1;transform:translateY(2px)}%d%%,84%%{opacity:1;transform:none}92%%,100%%{opacity:0}}"
                        ".key%d{animation-name:key%d}" % (i, a, a + 2, a + 6, i, i))
    c.add("</g>")


def prism_motif(c: Card, w: int):
    t = c.t
    x, y, mw, mh = panel(c, w)
    art = sheen(c, "wp")
    tw, th, gap = 56, 72, 10
    bx = x + (mw - (3 * tw + 2 * gap)) / 2
    period = 3 * (th + gap)
    fills = [t["tile2"], art, t["tile3"]]
    for col in range(3):
        c.add(f'<g class="col col{col}">')
        for i in range(6):
            fill = fills[(i + col) % 3]
            c.add(f'<rect x="{bx + col * (tw + gap)}" y="{y - 20 - col * 26 + i * (th + gap)}" width="{tw}" height="{th}" rx="10" fill="{fill}"/>')
        c.add("</g>")
    c.add("</g>")
    c.style(
        ".col{animation:scroll 14s linear infinite}.col1{animation-direction:reverse}"
        "@keyframes scroll{from{transform:translateY(0)}to{transform:translateY(-%dpx)}}" % period
    )


def odin_motif(c: Card, w: int):
    t = c.t
    x, y, mw, mh = panel(c, w)
    # laptop -> phone, locked in transit
    lx, ly = x + 22, y + 28
    c.add(f'<rect x="{lx}" y="{ly}" width="64" height="44" rx="5" fill="{t["tile2"]}"/>'
          f'<rect x="{lx - 8}" y="{ly + 46}" width="80" height="6" rx="3" fill="{t["tile3"]}"/>')
    phx, phy = x + mw - 58, y + 22
    c.add(f'<rect x="{phx}" y="{phy}" width="36" height="62" rx="8" fill="{t["tile2"]}"/>'
          f'<rect class="rcv" x="{phx}" y="{phy}" width="36" height="62" rx="8" fill="{t["accent_soft"]}" stroke="{t["accent"]}" stroke-width="1.5"/>')
    c.add(f'<line x1="{lx + 70}" y1="{y + 52}" x2="{phx - 6}" y2="{y + 52}" stroke="{t["text3"]}" stroke-width="1.5" stroke-dasharray="2 5" stroke-linecap="round"/>')
    fx, fy = lx + 23, ly + 10
    dx = (phx + 9) - fx
    c.add(f'<g class="file"><rect x="{fx}" y="{fy}" width="18" height="24" rx="3" fill="{t["accent"]}"/>'
          f'<g class="lk"><rect x="{fx + 4}" y="{fy + 12}" width="10" height="8" rx="1.5" fill="{t["on_accent"]}"/>'
          f'<path d="M{fx + 6},{fy + 12} v-3 a3,3 0 0 1 6,0 v3" fill="none" stroke="{t["on_accent"]}" stroke-width="1.6"/></g></g>')
    c.add("</g>")
    c.style(
        ".file{animation:send 5s $INOUT infinite}"
        "@keyframes send{0%%,15%%{transform:none;opacity:1}65%%{transform:translateX(%dpx);opacity:1}74%%,100%%{transform:translateX(%dpx);opacity:0}}" % (dx, dx) +
        ".lk{animation:lk 5s linear infinite}"
        "@keyframes lk{0%,20%{opacity:0}28%,58%{opacity:1}64%,100%{opacity:0}}"
        ".rcv{animation:rcv 5s $OUT infinite}"
        "@keyframes rcv{0%,63%{opacity:0}70%,90%{opacity:1}100%{opacity:0}}"
    )


def pokerface_motif(c: Card, w: int):
    t = c.t
    x, y, mw, mh = panel(c, w)
    face = "#2a2a30" if c.theme == "dark" else "#ffffff"
    c.style(".cd{animation:6s $OUT infinite}")
    for i, (rank, ang) in enumerate((("A", -8), ("K", 8))):
        cx = x + 58 + i * 34
        c.add(f'<g transform="translate({cx},{y + 56}) rotate({ang})"><g class="cd cd{i}">'
              f'<rect x="-20" y="-28" width="40" height="56" rx="6" fill="{face}" stroke="{t["tile3"]}"/>')
        c.text(-11, -9, rank, 15, 700, t["text"])
        c.add(f'<circle cx="0" cy="8" r="6" fill="{t["accent"]}"/></g></g>')
        a = 8 + i * 8
        c.style("@keyframes cd%d{0%%,%d%%{opacity:0;transform:translateY(-70px)}%d%%,86%%{opacity:1;transform:none}94%%,100%%{opacity:0;transform:none}}"
                ".cd%d{animation-name:cd%d}" % (i, a, a + 14, i, i))
    ox = x + mw - 34
    c.add('<g class="odds">')
    c.text(ox, y + 58, "67%", 24, 700, t["accent_text"], anchor="end", tracking=-0.6)
    c.text(ox, y + 76, "to win", 11, 500, t["text3"], anchor="end")
    c.add("</g></g>")
    c.style(
        ".odds{animation:odds 6s $OUT infinite}"
        "@keyframes odds{0%,36%{opacity:0;transform:translateY(8px)}46%,86%{opacity:1;transform:none}94%,100%{opacity:0}}"
    )


def product(theme: str, key: str, name: str, desc: str, domain: str, wide: bool = False) -> str:
    w = WIDE if wide else COL
    c = Card(theme, w, 256)
    {"hermes": hermes_motif, "rentaikey": rentaikey_motif, "prism": prism_motif,
     "odin": odin_motif, "pokerface": pokerface_motif, "hashstudios": hash_motif}[key](c, w)
    product_frame(c, w, name, desc, domain)
    return c.render()


def hash_motif(c: Card, w: int):
    t = c.t
    cid, x, y, mw, mh = motif_area(c, w)
    c.add(f'<g clip-path="url(#{cid})"><rect x="{x}" y="{y}" width="{mw}" height="{mh}" fill="{t["tile"]}"/>')
    ox, oy = x + 36, y + 24
    strokes = [(ox + 16, oy + 2, ox + 12, oy + 58), (ox + 40, oy + 2, ox + 36, oy + 58),
               (ox + 2, oy + 22, ox + 54, oy + 22), (ox - 2, oy + 40, ox + 50, oy + 40)]
    c.style(".hs{animation:hash 7s $OUT infinite}")
    for i, (x1, y1, x2, y2) in enumerate(strokes):
        c.add(f'<line class="hs h{i}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{t["accent"]}" stroke-width="7" stroke-linecap="round" stroke-dasharray="70" stroke-dashoffset="75"/>')
        c.style(".h%d{animation-delay:%.2fs}" % (i, i * 0.18))
    c.style("@keyframes hash{0%{stroke-dashoffset:75;opacity:1}18%,80%{stroke-dashoffset:0;opacity:1}90%,100%{stroke-dashoffset:0;opacity:0}}")
    # three app tiles: the studio's output, shipping one after another
    c.style(".tl{transform-box:fill-box;transform-origin:center;animation:pop 7s $SPRING infinite}")
    for i, fill in enumerate((t["tile3"], t["tile2"], t["accent"])):
        tx = x + 150 + i * 64
        c.add(f'<g class="tl t{i}"><rect x="{tx}" y="{y + 30}" width="48" height="48" rx="13" fill="{fill}"/></g>')
        c.style(".t%d{animation-delay:%.2fs}" % (i, 0.9 + i * 0.28))
    c.style("@keyframes pop{0%{transform:scale(0);opacity:0}12%,78%{transform:scale(1);opacity:1}88%,100%{transform:scale(0);opacity:0}}")
    c.add("</g>")


# --------------------------------------------------------------------------- package cards

def pkg_area(c: Card):
    x, y, w, h = 16, 16, COL - 32, 84
    cid = c.clip(x, y, w, h, 12)
    c.add(f'<g clip-path="url(#{cid})"><rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{c.t["tile"]}"/>')
    return x, y, w, h


def m_ai_sdk(c: Card):
    t = c.t
    x, y, w, h = pkg_area(c)
    # tokens stream in; the provider underneath keeps changing, the code doesn't
    lines = [[34, 22, 40, 28], [26, 44, 30], [38, 24]]
    n = sum(len(l) for l in lines)
    c.style(".wd{animation:5s steps(1) infinite}")
    i = 0
    for row, words in enumerate(lines):
        wx = x + 18
        for ww in words:
            c.add(f'<rect class="wd w{i}" x="{wx}" y="{y + 16 + row * 16}" width="{ww}" height="7" rx="3.5" fill="{t["text3"]}"/>')
            a = 4 + i * 7
            c.style("@keyframes w%d{0%%,%d%%{opacity:0}%d%%,86%%{opacity:1}87%%,100%%{opacity:0}}.w%d{animation-name:w%d}" % (i, a, a + 1, i, i))
            wx += ww + 6
            i += 1
    assert i == n
    c.style(".pv{animation:15s steps(1) infinite;opacity:0}")
    for j, name in enumerate(("openai", "anthropic", "google")):
        c.text(x + w - 14, y + h - 12, name, 10, 600, t["accent_text"], anchor="end", cls=f"pv pv{j}")
        lo, hi = j * 33.33, (j + 1) * 33.33
        c.style("@keyframes pv%d{0%%{opacity:0}%.2f%%{opacity:1}%.2f%%,100%%{opacity:0}}.pv%d{animation-name:pv%d}" % (j, lo, hi, j, j))
    c.add("</g>")


def m_flutter_ui(c: Card):
    t = c.t
    x, y, w, h = pkg_area(c)
    c.add(f'<rect class="ub" x="{x + w - 104}" y="{y + 28}" width="90" height="18" rx="9" fill="{t["accent"]}"/>')
    c.add(f'<g class="typing"><rect x="{x + 14}" y="{y + 54}" width="44" height="20" rx="10" fill="{t["tile2"]}"/>')
    c.style(".dt{animation:dot .9s $INOUT infinite alternate}"
            "@keyframes dot{from{transform:translateY(2px)}to{transform:translateY(-2px)}}")
    for i in range(3):
        c.add(f'<circle class="dt" cx="{x + 26 + i * 10}" cy="{y + 64}" r="2.5" fill="{t["text3"]}" style="animation-delay:{i * 0.15:.2f}s"/>')
    c.add("</g>")
    c.add(f'<g class="ab"><rect x="{x + 14}" y="{y + 52}" width="130" height="24" rx="10" fill="{t["tile3"]}"/>'
          f'<rect x="{x + 24}" y="{y + 58}" width="96" height="4.5" rx="2.25" fill="{t["text3"]}"/>'
          f'<rect x="{x + 24}" y="{y + 66}" width="64" height="4.5" rx="2.25" fill="{t["text3"]}"/></g>')
    c.add("</g>")
    c.style(
        ".ub,.ab,.typing{animation:6s $OUT infinite}"
        ".ub{animation-name:ub}.typing{animation-name:typing}.ab{animation-name:ab}"
        "@keyframes ub{0%,4%{opacity:0;transform:translateY(8px)}12%,86%{opacity:1;transform:none}94%,100%{opacity:0}}"
        "@keyframes typing{0%,20%{opacity:0}26%,50%{opacity:1}54%,100%{opacity:0}}"
        "@keyframes ab{0%,52%{opacity:0;transform:translateY(8px)}60%,86%{opacity:1;transform:none}94%,100%{opacity:0}}"
    )


def m_dart_tui(c: Card):
    t = c.t
    x, y, w, h = pkg_area(c)
    for i in range(3):
        c.add(f'<circle cx="{x + 14 + i * 10}" cy="{y + 12}" r="3" fill="{t["tile3"]}"/>')
    c.add(f'<g class="cur"><rect x="{x + 12}" y="{y + 22}" width="{w - 24}" height="14" rx="4" fill="{t["accent_soft"]}"/>'
          f'<path d="M{x + 20},{y + 25} l6,4 l-6,4 z" fill="{t["accent"]}"/></g>')
    for i, rw in enumerate((96, 72, 118, 60)):
        c.add(f'<rect x="{x + 34}" y="{y + 26 + i * 14}" width="{rw}" height="6" rx="3" fill="{t["text3"]}"/>')
    c.add("</g>")
    c.style(
        ".cur{animation:cur 5s $INOUT infinite}"
        "@keyframes cur{0%,18%{transform:none}25%,43%{transform:translateY(14px)}50%,68%{transform:translateY(28px)}75%,93%{transform:translateY(42px)}100%{transform:none}}"
    )


def m_dart_minify(c: Card):
    t = c.t
    x, y, w, h = pkg_area(c)
    # six lines of context in, three that matter out
    widths = (120, 80, 140, 60, 100, 90)
    keep = {0: 0, 2: 1, 5: 2}
    c.style(".cl{animation:5s $INOUT infinite}")
    for i, lw in enumerate(widths):
        ly = y + 12 + i * 11
        c.add(f'<rect class="cl cl{i}" x="{x + 20}" y="{ly}" width="{lw}" height="6" rx="3" fill="{t["text3"]}"/>')
        if i in keep:
            dy = (keep[i] - i) * 11
            c.style("@keyframes cl%d{0%%,32%%{transform:none;fill:%s}48%%,84%%{transform:translateY(%dpx);fill:%s}96%%,100%%{transform:none;fill:%s}}"
                    % (i, t["text3"], dy, t["accent"], t["text3"]))
        else:
            c.style("@keyframes cl%d{0%%,16%%{opacity:1}30%%,86%%{opacity:0}96%%,100%%{opacity:1}}" % i)
        c.style(".cl%d{animation-name:cl%d}" % (i, i))
    c.add("</g>")


def m_beui(c: Card):
    t = c.t
    x, y, w, h = pkg_area(c)
    knob = "#f5f5f7" if c.theme == "dark" else "#ffffff"
    tx, ty = x + w / 2 - 36, y + h / 2 - 18
    c.add(f'<rect x="{tx}" y="{ty}" width="72" height="36" rx="18" fill="{t["tile3"]}"/>'
          f'<rect class="trk" x="{tx}" y="{ty}" width="72" height="36" rx="18" fill="{t["accent"]}"/>'
          f'<circle class="knob" cx="{tx + 18}" cy="{ty + 18}" r="14" fill="{knob}" stroke="{t["tile3"]}"/>')
    c.add("</g>")
    c.style(
        ".knob{animation:knob 4s $SPRING infinite}"
        "@keyframes knob{0%,20%{transform:none}40%,70%{transform:translateX(36px)}90%,100%{transform:none}}"
        ".trk{animation:trk 4s $INOUT infinite}"
        "@keyframes trk{0%,22%{opacity:0}36%,72%{opacity:1}86%,100%{opacity:0}}"
    )


def m_floating_bar(c: Card):
    t = c.t
    x, y, w, h = pkg_area(c)
    c.add('<g class="feed">')
    for i in range(8):
        c.add(f'<rect x="{x + 20}" y="{y + 10 + i * 22}" width="{w - 40}" height="14" rx="5" fill="{t["tile2"]}"/>')
    c.add("</g>")
    bw = 110
    bx, by = x + (w - bw) / 2, y + h - 30
    c.add(f'<g class="bar"><rect x="{bx}" y="{by}" width="{bw}" height="22" rx="11" fill="{t["accent"]}"/>')
    for i in range(3):
        c.add(f'<circle cx="{bx + 30 + i * 25}" cy="{by + 11}" r="3.5" fill="{t["on_accent"]}" fill-opacity="{.9 - i * .3:.1f}"/>')
    c.add("</g></g>")
    c.style(
        ".feed{animation:feed 6s $INOUT infinite}"
        "@keyframes feed{0%,10%{transform:none}45%,55%{transform:translateY(-66px)}90%,100%{transform:none}}"
        ".bar{animation:bar 6s $INOUT infinite}"
        "@keyframes bar{0%,12%{transform:none}24%,58%{transform:translateY(40px)}70%,100%{transform:none}}"
    )


def m_async_wallpaper(c: Card):
    t = c.t
    x, y, w, h = pkg_area(c)
    art = sheen(c, "wg")
    px, py = x + w / 2 - 58, y + 8
    c.add(f'<rect x="{px}" y="{py}" width="44" height="68" rx="9" fill="{t["tile3"]}"/>'
          f'<rect class="wall" x="{px}" y="{py}" width="44" height="68" rx="9" fill="{art}"/>')
    # the spinner keeps turning: setting the wallpaper never blocks the UI thread
    sx, sy = x + w / 2 + 40, y + h / 2
    c.add(f'<circle cx="{sx}" cy="{sy}" r="12" fill="none" stroke="{t["tile3"]}" stroke-width="3"/>'
          f'<circle class="spin" cx="{sx}" cy="{sy}" r="12" fill="none" stroke="{t["accent"]}" stroke-width="3" stroke-linecap="round" stroke-dasharray="20 56"/>')
    c.add("</g>")
    c.style(
        ".wall{animation:wall 5s $INOUT infinite}"
        "@keyframes wall{0%,30%{opacity:0}45%,80%{opacity:1}95%,100%{opacity:0}}"
        ".spin{transform-box:fill-box;transform-origin:center;animation:turn 1.1s linear infinite}"
        "@keyframes turn{to{transform:rotate(360deg)}}"
    )


def m_secure(c: Card):
    t = c.t
    x, y, w, h = pkg_area(c)
    sx, sy, sw, sh = x + (w - 84) / 2, y + 12, 84, 60
    c.add(f'<rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="8" fill="{t["tile2"]}"/>')
    for i, lw in enumerate((56, 40, 48)):
        c.add(f'<rect x="{sx + 12}" y="{sy + 14 + i * 12}" width="{lw}" height="6" rx="3" fill="{t["accent"] if i == 0 else t["text3"]}"/>')
    # viewfinder corners: someone tries a screenshot
    k = 9
    corners = [(sx - 5, sy - 5, 1, 1), (sx + sw + 5, sy - 5, -1, 1), (sx - 5, sy + sh + 5, 1, -1), (sx + sw + 5, sy + sh + 5, -1, -1)]
    c.add('<g class="vf">' + "".join(
        f'<path d="M{cx},{cy + k * dy} v{-k * dy} h{k * dx}" fill="none" stroke="{t["accent"]}" stroke-width="1.8" stroke-linecap="round"/>'
        for cx, cy, dx, dy in corners) + "</g>")
    c.add(f'<rect class="flash" x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="8" fill="#ffffff"/>')
    lx, ly = sx + sw / 2, sy + sh / 2
    c.add(f'<g class="shield"><rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="8" fill="{t["text"]}"/>'
          f'<rect x="{lx - 8}" y="{ly - 3}" width="16" height="12" rx="2.5" fill="{t["surface"]}"/>'
          f'<path d="M{lx - 5},{ly - 3} v-3 a5,5 0 0 1 10,0 v3" fill="none" stroke="{t["surface"]}" stroke-width="2.2"/></g>')
    c.add("</g>")
    c.style(
        ".vf{animation:vf 6s $OUT infinite}"
        "@keyframes vf{0%,10%{opacity:0;transform:scale(1.04)}20%,34%{opacity:1;transform:none}40%,100%{opacity:0}}"
        ".vf{transform-box:fill-box;transform-origin:center}"
        ".flash{animation:flash 6s linear infinite}"
        "@keyframes flash{0%,33%{opacity:0}35%{opacity:.8}40%,100%{opacity:0}}"
        ".shield{animation:shield 6s $OUT infinite}"
        "@keyframes shield{0%,35%{opacity:0}40%,82%{opacity:1}92%,100%{opacity:0}}"
    )


PKG_MOTIFS = {
    "ai_sdk_dart": m_ai_sdk, "ai_sdk_flutter_ui": m_flutter_ui, "dart_tui": m_dart_tui,
    "dart_minify": m_dart_minify, "beui": m_beui, "flutter_floating_bottom_bar": m_floating_bar,
    "async_wallpaper": m_async_wallpaper, "secure_content": m_secure,
}


def package(theme: str, key: str, name: str, desc: str, version: str | None) -> str:
    c = Card(theme, COL, 196)
    t = c.t
    PKG_MOTIFS[key](c)
    size = 14.0
    while FONTS.measure(name, 600, size, -0.2) > COL - 48:  # long package names shrink to fit
        size -= 0.5
    c.text(24, 128, name, size, 600, t["text"], tracking=-0.2)
    if version:
        label = "v" + version
        pw = FONTS.measure(label, 500, 10) + 14
        right = COL - 22
        c.add(f'<rect x="{right - pw:.1f}" y="22" width="{pw:.1f}" height="18" rx="9" fill="{t["surface"]}" fill-opacity=".92"/>')
        c.text(right - pw / 2, 34.5, label, 10, 500, t["text3"], anchor="middle")
    for i, line in enumerate(wrap(desc, 400, 12, COL - 48, max_lines=2)):
        c.text(24, 149 + i * 17, line, 12, 400, t["text2"])
    return c.render()


# --------------------------------------------------------------------------- link chips

def chip(theme: str, label: str, primary: bool = False) -> str:
    tw = FONTS.measure(label, 500, 13)
    w = int(tw + 40 + 2 * INSET)
    c = Card(theme, w, 36 + 2 * INSET)
    t = c.t
    # chips are flat pills, not cards: cover the surface with the pill fill
    fill = t["accent"] if primary else t["tile"]
    color = t["on_accent"] if primary else t["text"]
    c.add(f'<rect x="{INSET}" y="{INSET}" width="{w - 2 * INSET}" height="36" rx="18" fill="{t["surface"]}"/>'
          f'<rect x="{INSET}" y="{INSET}" width="{w - 2 * INSET}" height="36" rx="18" fill="{fill}"/>')
    c.text(w / 2, INSET + 23, label, 13, 500, color, anchor="middle")
    return c.render()


# --------------------------------------------------------------------------- live data

def fetch_json(url: str, headers: dict | None = None):
    req = urllib.request.Request(url, headers={"User-Agent": "profile-cards", **(headers or {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def refresh_live() -> dict:
    live = load_live()  # start from the last good numbers; a failed fetch keeps them
    for _, name, _ in PACKAGES:
        try:
            live["versions"][name] = fetch_json(f"https://pub.dev/api/packages/{name}")["latest"]["version"]
            live["downloads"][name] = fetch_json(f"https://pub.dev/api/packages/{name}/score")["downloadCount30Days"]
        except Exception as e:  # keep going; a stale number beats a broken build
            print(f"warn: pub.dev {name}: {e}", file=sys.stderr)
    token = os.environ.get("GITHUB_TOKEN")
    gh_headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        live["prism_stars"] = fetch_json("https://api.github.com/repos/Hash-Studios/Prism", gh_headers)["stargazers_count"]
    except Exception as e:
        print(f"warn: prism stars: {e}", file=sys.stderr)
    if token:
        try:
            q = {"query": '{ user(login:"codenameakshay"){ contributionsCollection { contributionCalendar { totalContributions } } } }'}
            req = urllib.request.Request("https://api.github.com/graphql", data=json.dumps(q).encode(),
                                         headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": "profile-cards"})
            with urllib.request.urlopen(req, timeout=20) as r:
                live["contributions"] = json.load(r)["data"]["user"]["contributionsCollection"]["contributionCalendar"]["totalContributions"]
        except Exception as e:
            print(f"warn: contributions: {e}", file=sys.stderr)
    LIVE_FILE.write_text(json.dumps(live, indent=2) + "\n")
    return live


def load_live() -> dict:
    live = json.loads(json.dumps(DEFAULT_LIVE))  # deep copy: refresh_live mutates the nested dicts
    if LIVE_FILE.exists():
        live.update(json.loads(LIVE_FILE.read_text()))
    return live


def fmt_contributions(n: int) -> str:
    return f"{(n // 500) * 500:,}+"


# --------------------------------------------------------------------------- main

def fmt_thousands(n: int) -> str:
    return f"{n // 1000}K+" if n >= 1000 else str(n)


CHIPS = (("Portfolio", False), ("LinkedIn", False), ("X", False), ("Email", True))


def build(live: dict):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    written = []

    def out(name: str, theme: str, svg: str):
        p = OUT_DIR / f"{name}-{theme}.svg"
        p.write_text(svg)
        written.append((p.name, len(svg)))

    installs = sum(live["downloads"].get(name, 0) for _, name, _ in PACKAGES)
    for theme in THEMES:
        out("hero", theme, hero(theme))
        stats = [
            ("1M+", "downloads on One4Wall"),
            (f"{live['prism_stars']:,}", "GitHub stars on Prism"),
            (fmt_contributions(live["contributions"]), "contributions last year"),
            (fmt_thousands(installs), "pub.dev installs a month"),
        ]
        for i, (value, label) in enumerate(stats):
            out(f"stat-{i + 1}", theme, stat(theme, value, label, i))
        for key, name, desc, domain, _ in PRODUCTS:
            out(f"product-{key}", theme, product(theme, key, name, desc, domain, wide=(key in WIDE_PRODUCTS)))
        for key, name, desc in PACKAGES:
            out(f"pkg-{key}", theme, package(theme, key, name, desc, live["versions"].get(name)))
        for label, primary in CHIPS:
            out(f"chip-{label.lower()}", theme, chip(theme, label, primary))
    return written


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="refresh pub.dev and GitHub numbers first")
    args = ap.parse_args()
    live = refresh_live() if args.live else load_live()
    files = build(live)
    total = sum(n for _, n in files)
    print(f"wrote {len(files)} files, {total / 1024:.0f} KB total")
    for name, n in files:
        if n > 120_000:
            print(f"  large: {name} {n / 1024:.0f} KB")
