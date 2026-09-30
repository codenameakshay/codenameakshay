#!/usr/bin/env python3
"""Run the workflow commit step against a local push race."""
import os
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "refresh-readme.yml"


def run(command, cwd, *, check=True, env=None):
    return subprocess.run(
        command, cwd=cwd, check=check, text=True, capture_output=True, env=env
    )


def git(repo: Path, *args: str) -> str:
    return run(["git", *args], repo).stdout.strip()


def step_script(title: str) -> str:
    lines = WORKFLOW.read_text().splitlines()
    step = lines.index(f"      - name: {title}")
    for line in lines[step + 1 :]:
        if line.startswith("        run: "):
            if line != "        run: |":
                return line.removeprefix("        run: ")
            break
    start = lines.index("        run: |", step) + 1
    block = []
    for line in lines[start:]:
        if line and not line.startswith("          "):
            break
        block.append(line[10:] if line.startswith("          ") else "")
    return textwrap.dedent("\n".join(block))


def check_push_race(malformed: bool = False, always_race: bool = False) -> None:
    branch = "feature/readme"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        origin = root / "origin.git"
        git(root, "init", "--bare", str(origin))

        seed = root / "seed"
        git(root, "init", str(seed))
        git(seed, "checkout", "-b", branch)
        git(seed, "config", "user.name", "test")
        git(seed, "config", "user.email", "test@example.com")
        (seed / "README.md").write_text(
            "# Profile\n\n<!-- BLOG-POST-LIST:START -->\n"
            "<!-- BLOG-POST-LIST:END -->\n\n<img alt=\"old stats\">\n\n"
            "<!-- other -->\n<!-- /other -->\n"
        )
        (seed / "scripts/cards").mkdir(parents=True)
        (seed / "assets/cards").mkdir(parents=True)
        (seed / "scripts/cards/build.py").write_text("old generator\n")
        (seed / "scripts/cards/live.json").write_text('{"value": "old"}\n')
        (seed / "assets/cards/card.svg").write_text("old card\n")
        git(seed, "add", ".")
        git(seed, "commit", "-m", "initial")
        git(seed, "remote", "add", "origin", str(origin))
        git(seed, "push", "-u", "origin", branch)

        cards = root / "cards"
        git(root, "clone", "--branch", branch, str(origin), str(cards))
        git(cards, "config", "user.name", "test")
        git(cards, "config", "user.email", "test@example.com")
        (cards / "README.md").write_text(
            "# Profile\n\n<!-- BLOG-POST-LIST:START -->\n- new post\n"
            "<!-- BLOG-POST-LIST:END -->\n\n<img alt=\"old stats\">\n\n"
            "<!-- other -->\n<!-- /other -->\n"
        )
        (cards / "assets/cards/card.svg").write_text("built by old generator\n")
        (cards / "scripts/cards/live.json").write_text('{"value": "fresh"}\n')

        race = root / "race"
        git(root, "clone", "--branch", branch, str(origin), str(race))
        git(race, "config", "user.name", "test")
        git(race, "config", "user.email", "test@example.com")
        shim = root / "bin"
        shim.mkdir()
        marker = root / "race-pushed"
        real_git = shutil.which("git")
        shim.joinpath("git").write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = push ] && [ \"$2\" = origin ] && "
            f"{{ [ ! -e \"{marker}\" ] || [ \"$RACE_EVERY_PUSH\" = yes ]; }}; then\n"
            f"  touch \"{marker}\"\n"
            f"  \"{real_git}\" -C \"{race}\" fetch origin {branch}\n"
            f"  \"{real_git}\" -C \"{race}\" reset --hard origin/{branch}\n"
            "  if [ \"$MALFORMED_RACE\" = yes ]; then\n"
            f"    sed '/<!-- BLOG-POST-LIST:END -->/d;s/<!-- other -->/concurrent update\\n<!-- other -->/' "
            f"\"{race}/README.md\" > \"{race}/README.next\"\n"
            "  else\n"
            f"    sed 's/<!-- other -->/concurrent update\\n<!-- other -->/' "
            f"\"{race}/README.md\" > \"{race}/README.next\"\n"
            "  fi\n"
            f"  mv \"{race}/README.next\" \"{race}/README.md\"\n"
            f"  printf 'new generator\\n' > \"{race}/scripts/cards/build.py\"\n"
            f"  printf '{{\"value\": \"concurrent cache\"}}\\n' > \"{race}/scripts/cards/live.json\"\n"
            f"  printf 'concurrent card\\n' > \"{race}/assets/cards/card.svg\"\n"
            f"  \"{real_git}\" -C \"{race}\" add README.md scripts/cards/build.py scripts/cards/live.json assets/cards/card.svg\n"
            f"  \"{real_git}\" -C \"{race}\" commit -m 'concurrent refresh'\n"
            f"  \"{real_git}\" -C \"{race}\" push origin {branch}\n"
            "fi\n"
            f"exec \"{real_git}\" \"$@\"\n"
        )
        shim.joinpath("git").chmod(0o755)
        python = shim / "python"
        python.write_text(
            "#!/bin/sh\n"
            "printf 'built with %s' \"$(cat scripts/cards/build.py)\" "
            "> assets/cards/card.svg\n"
            "printf 'built\\n' >> \"$BUILD_LOG\"\n"
            "sed 's/old stats/new stats/' README.md > README.next\n"
            "mv README.next README.md\n"
        )
        python.chmod(0o755)
        build_log = root / "build-log"
        result = run(
            ["bash", "-e", "-c", step_script("Commit refreshed cards")],
            cards,
            check=not malformed and not always_race,
            env={
                **os.environ,
                "PATH": f"{shim}:{os.environ['PATH']}",
                "GITHUB_REF_NAME": branch,
                "GITHUB_REF": f"refs/heads/{branch}",
                "BLOG_STEP_OUTCOME": "success",
                "MALFORMED_RACE": "yes" if malformed else "no",
                "RACE_EVERY_PUSH": "yes" if always_race else "no",
                "BUILD_LOG": str(build_log),
                "RUNNER_TEMP": str(root),
            },
        )

        readme = git(origin, "show", f"refs/heads/{branch}:README.md")
        if malformed:
            assert result.returncode != 0
            assert "new post" not in readme and "new stats" not in readme
            assert git(origin, "rev-list", "--count", branch) == "2"
            return
        if always_race:
            assert result.returncode != 0
            assert git(origin, "rev-list", "--count", branch) == "4"
            assert "new post" not in readme
            assert git(origin, "show", f"refs/heads/{branch}:assets/cards/card.svg") == "concurrent card"
            assert build_log.read_text().splitlines() == ["built", "built"]
            return
        card = git(origin, "show", f"refs/heads/{branch}:assets/cards/card.svg")
        assert "new post" in readme and "concurrent update" in readme
        assert "new stats" in readme
        assert card == "built with new generator"
        live = git(origin, "show", f"refs/heads/{branch}:scripts/cards/live.json")
        assert live == '{"value": "concurrent cache"}', live
        assert build_log.read_text().splitlines() == ["built"]


def check_failed_blog_restore() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        origin = root / "origin.git"
        git(root, "init", "--bare", str(origin))
        seed = root / "seed"
        git(root, "init", str(seed))
        git(seed, "checkout", "-b", "feature/readme")
        git(seed, "config", "user.name", "test")
        git(seed, "config", "user.email", "test@example.com")
        (seed / "README.md").write_text("saved writing list\n<img alt=\"old stats\">\n")
        git(seed, "add", "README.md")
        git(seed, "commit", "-m", "initial")
        git(seed, "remote", "add", "origin", str(origin))
        git(seed, "push", "-u", "origin", "feature/readme")
        repo = root / "work"
        git(root, "clone", "--branch", "feature/readme", str(origin), str(repo))
        git(repo, "config", "user.name", "test")
        git(repo, "config", "user.email", "test@example.com")
        readme = repo / "README.md"
        readme.write_text("partial writing list\n")
        git(repo, "add", "README.md")
        run(["bash", "-e", "-c", step_script("Discard partial writing list update")], repo)
        assert "saved writing list" in readme.read_text()
        readme.write_text(readme.read_text().replace("old stats", "new stats"))
        (repo / "assets/cards").mkdir(parents=True)
        (repo / "scripts/cards").mkdir(parents=True)
        (repo / "assets/cards/card.svg").write_text("new card\n")
        (repo / "scripts/cards/live.json").write_text('{"value": "new"}\n')
        run(
            ["bash", "-e", "-c", step_script("Commit refreshed cards")],
            repo,
            env={
                **os.environ,
                "GITHUB_REF_NAME": "feature/readme",
                "GITHUB_REF": "refs/heads/feature/readme",
                "BLOG_STEP_OUTCOME": "failure",
                "RUNNER_TEMP": str(root),
                "BUILD_LOG": str(root / "unused-build-log"),
            },
        )
        published = git(origin, "show", "refs/heads/feature/readme:README.md")
        assert "saved writing list" in published and "new stats" in published
        assert "partial writing list" not in published


if __name__ == "__main__":
    check_push_race()
    check_push_race(malformed=True)
    check_push_race(always_race=True)
    check_failed_blog_restore()
    print("workflow push race, rebuild, and blog failure checks passed")
