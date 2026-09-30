#!/usr/bin/env python3
"""Assert that README card markup matches build.py content and assets."""
from html.parser import HTMLParser
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
sys.path.insert(0, str(ROOT / "scripts" / "cards"))
import build as card_build


class Cards(HTMLParser):
    def __init__(self):
        super().__init__()
        self.href = None
        self.picture = None
        self.cards = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            self.href = attrs.get("href")
        elif tag == "picture":
            self.picture = {"href": self.href, "sources": [], "images": []}
        elif tag == "source" and self.picture is not None:
            self.picture["sources"].append(attrs)
        elif tag == "img" and self.picture is not None:
            self.picture["images"].append(attrs)

    def handle_endtag(self, tag):
        if tag == "picture":
            self.cards.append(self.picture)
            self.picture = None
        elif tag == "a":
            self.href = None


def main():
    products = card_build.PRODUCTS
    packages = card_build.PACKAGES
    live = card_build.load_live()
    installs = sum(live["downloads"].get(name, 0) for _, name, _ in card_build.PACKAGES)
    parser = Cards()
    parser.feed(README.read_text())

    expected = {
        "hero": ("https://www.akshaymaurya.com", None),
        "chip-portfolio": ("https://www.akshaymaurya.com", "Portfolio"),
        "chip-linkedin": ("https://www.linkedin.com/in/codenameakshay/", "LinkedIn"),
        "chip-x": ("https://x.com/codenameakshay", "X"),
        "chip-email": ("mailto:akshaymaurya3006@gmail.com", "Email"),
        "stat-1": ("https://www.producthunt.com/products/one4wall", "1M+ downloads on One4Wall"),
        "stat-2": ("https://github.com/Hash-Studios/Prism", f"{live['prism_stars']:,} GitHub stars on Prism"),
        "stat-3": ("https://github.com/codenameakshay", f"{card_build.fmt_contributions(live['contributions'])} contributions last year"),
        "stat-4": ("https://pub.dev/publishers/hashstudios.dev/packages", f"{card_build.fmt_thousands(installs)} pub.dev installs a month"),
    }
    expected["hero"] = (expected["hero"][0], "Akshay Maurya. Flutter and iOS by trade, AI by curiosity. Based in Bengaluru. Open to Flutter, iOS and AI-mobile roles. Building a fintech app at a stealth startup. Previously at CRED.")
    expected.update({
        f"product-{key}": (href, f"{name}. {desc}")
        for key, name, desc, _, href in products
    })
    expected.update({
        f"pkg-{key}": (f"https://pub.dev/packages/{name}", f"{name}. {desc}")
        for key, name, desc in packages
    })

    actual = {}
    for card in parser.cards:
        assert len(card["sources"]) == len(card["images"]) == 1, card
        source_attrs, image = card["sources"][0], card["images"][0]
        dark, light = source_attrs.get("srcset"), image.get("src")
        assert source_attrs.get("media") == "(prefers-color-scheme: dark)", card
        assert image.get("alt"), card
        if dark.startswith("https://") and light.startswith("https://"):
            continue
        assert dark and dark.endswith("-dark.svg"), card
        assert light and light.endswith("-light.svg"), card
        key = Path(light).name.removesuffix("-light.svg")
        assert Path(dark).name == f"{key}-dark.svg", card
        assert (ROOT / dark).is_file() and (ROOT / light).is_file(), card
        assert key not in actual, key
        actual[key] = (card["href"], image.get("alt"))

    assert actual == expected, {
        "missing": expected.keys() - actual.keys(),
        "extra": actual.keys() - expected.keys(),
        "mismatches": {
            key: (expected[key], actual.get(key))
            for key in expected.keys() & actual.keys()
            if expected[key] != actual[key]
        },
    }


if __name__ == "__main__":
    main()
