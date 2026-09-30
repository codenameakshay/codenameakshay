#!/usr/bin/env python3
"""Focused regression checks for the profile card generator."""
import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import build
from fontTools.ttLib.tables import _h_e_a_d


def check_live_cache_and_refresh():
    with tempfile.TemporaryDirectory() as temp_dir:
        cache = Path(temp_dir) / "live.json"
        with patch.object(build, "LIVE_FILE", cache):
            first = build.load_live()
            first["versions"]["ai_sdk_dart"] = "9.9.9"
            assert "ai_sdk_dart" not in build.load_live()["versions"]

            cache.write_text(json.dumps({"versions": None, "downloads": {"ai_sdk_dart": "bad"}, "contributions": -1}))
            loaded = build.load_live()
            assert loaded["versions"] == {}
            assert loaded["downloads"] == {}
            assert loaded["contributions"] == build.DEFAULT_LIVE["contributions"]

            cache.write_text("not json")
            assert build.load_live() == {"versions": {}, "downloads": {}, "prism_stars": 665, "contributions": 10688}
            cache.write_bytes(b"\xff")
            assert build.load_live() == {"versions": {}, "downloads": {}, "prism_stars": 665, "contributions": 10688}
            cache.write_text("[]")
            assert build.load_live() == {"versions": {}, "downloads": {}, "prism_stars": 665, "contributions": 10688}

            cache.write_text(json.dumps({"versions": {"ai_sdk_dart": "2.0.0", "dart_tui": "1.0.0-" + "W" * 26}, "downloads": {"ai_sdk_dart": 12}}))
            def partial_fetch(url, headers=None):
                if url.endswith("/packages/ai_sdk_dart"):
                    return {"latest": {"version": "3.0.0"}}
                raise OSError("offline")

            with patch.object(build, "fetch_json", partial_fetch), patch.dict("os.environ", {}, clear=True):
                refreshed = build.refresh_live()
            assert refreshed["versions"] == {"ai_sdk_dart": "2.0.0"}
            assert refreshed["downloads"] == {"ai_sdk_dart": 12}
            assert refreshed["contributions"] == build.DEFAULT_LIVE["contributions"]
            assert json.loads(cache.read_text()) == refreshed

            def invalid_fetch(url, headers=None):
                if url.endswith("/score"):
                    return {"downloadCount30Days": -3}
                if "/packages/" in url:
                    return {"latest": {"version": "1.0.0-" + "W" * 26}}
                return {"stargazers_count": True}

            with patch.object(build, "fetch_json", invalid_fetch), patch.dict("os.environ", {}, clear=True):
                refreshed = build.refresh_live()
            assert refreshed["versions"] == {"ai_sdk_dart": "2.0.0"}
            assert refreshed["downloads"] == {"ai_sdk_dart": 12}
            assert refreshed["prism_stars"] == build.DEFAULT_LIVE["prism_stars"]

            graphql = {"data": {"user": {"contributionsCollection": {"contributionCalendar": {"totalContributions": None}}}}}
            with patch.object(build, "fetch_json", partial_fetch), patch.dict("os.environ", {"GITHUB_TOKEN": "test"}), \
                    patch.object(build.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(graphql).encode())):
                refreshed = build.refresh_live()
            assert refreshed["contributions"] == build.DEFAULT_LIVE["contributions"]

            cache.write_text(json.dumps({"versions": {"ai_sdk_dart": "2.0.0"}, "downloads": {"ai_sdk_dart": 12}}))
            before = cache.read_bytes()
            with patch.object(build, "fetch_json", partial_fetch), patch.dict("os.environ", {}, clear=True), \
                    patch.object(build.os, "replace", side_effect=OSError("disk failure")):
                try:
                    build.refresh_live()
                except OSError:
                    pass
                else:
                    raise AssertionError("cache replacement failure must propagate")
            assert cache.read_bytes() == before
            assert not list(cache.parent.glob("live.json.*.tmp"))


def check_reduced_motion_stat_value():
    svg = build.stat("light", "7", "stars", 0)
    assert 'style="transform:translateY(-748px);animation-delay:0.10s"' in svg
    assert '.roll7{animation-name:roll7}' in svg
    assert 'animation:none!important' in svg


def check_contribution_formatting():
    assert [build.fmt_contributions(n) for n in (0, 1, 499, 500, 10_688)] == ["0", "1", "499", "500+", "10,500+"]
    assert [build.fmt_thousands(n) for n in (0, 999, 1_000, 1_999, 10_000)] == ["0", "999", "1K+", "1K+", "10K+"]


def check_readme_stat_alts():
    with tempfile.TemporaryDirectory() as temp_dir:
        readme = Path(temp_dir) / "README.md"
        readme.write_text('<img alt="old downloads" src="assets/cards/stat-1-light.svg"><img alt="old stars" src="assets/cards/stat-2-light.svg"><img alt="keep" src="assets/cards/chip-x-light.svg">')
        with patch.object(build, "ROOT", Path(temp_dir)):
            build.sync_readme_stat_alts([("1M+", "downloads"), ("665", "GitHub stars on Prism")])
        assert readme.read_text() == '<img alt="1M+ downloads" src="assets/cards/stat-1-light.svg"><img alt="665 GitHub stars on Prism" src="assets/cards/stat-2-light.svg"><img alt="keep" src="assets/cards/chip-x-light.svg">'


def check_font_output_ignores_clock():
    with patch.object(_h_e_a_d, "timestampNow", return_value=1):
        first = build.Fonts(build.FONT_SRC).face_css(400, "A")
    with patch.object(_h_e_a_d, "timestampNow", return_value=2):
        second = build.Fonts(build.FONT_SRC).face_css(400, "A")
    assert first == second


def check_existing_copy_fits():
    for key, _, desc, _, _ in build.PRODUCTS:
        width = (build.WIDE if key in build.WIDE_PRODUCTS else build.COL) - 48
        assert all(build.FONTS.measure(line, 400, 13) <= width for line in build.wrap(desc, 400, 13, width, 2))
    for _, name, desc in build.PACKAGES:
        size = 14.0
        while build.FONTS.measure(name, 600, size, -0.2) > build.COL - 48:
            size -= 0.5
        assert build.FONTS.measure(name, 600, size, -0.2) <= build.COL - 48
        assert all(build.FONTS.measure(line, 400, 12) <= build.COL - 48 for line in build.wrap(desc, 400, 12, build.COL - 48, 2))


if __name__ == "__main__":
    check_live_cache_and_refresh()
    check_reduced_motion_stat_value()
    check_contribution_formatting()
    check_readme_stat_alts()
    check_font_output_ignores_clock()
    check_existing_copy_fits()
