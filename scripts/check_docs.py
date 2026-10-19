#!/usr/bin/env python3
"""Validate the docs, the agent instructions, and the Tripo commands they contain.

Checks:
  1. Relative links and images in every Markdown file resolve (including #anchors).
  2. AGENTS.md and each pipeline guide contain at least one mermaid diagram.
  3. Every `tripo make "..."` line in a fenced code block is valid as a dry run.
  4. Every text job in art/manifests/*.yaml is valid as a dry run.

The dry runs make no network calls, spend no credits, and need no API key.
Pass --no-tripo to skip checks 3 and 4 when the tripo CLI is not installed.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "node_modules", ".godot", "tripo-out"}
MERMAID_REQUIRED = [
    "AGENTS.md",
    "docs/character-pipeline.md",
    "docs/environment-pipeline.md",
]
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".glb", ".gltf", ".fbx", ".obj"}
LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)\)")
FENCE_RE = re.compile(r"^(\s*)(```|~~~)")

errors: list[str] = []


def fail(message: str) -> None:
    errors.append(message)
    print(f"ERROR: {message}")


def markdown_files() -> list[Path]:
    return sorted(
        p
        for p in ROOT.rglob("*.md")
        if not SKIP_DIRS.intersection(p.relative_to(ROOT).parts)
    )


def slugify(heading: str) -> str:
    """GitHub-style heading anchor."""
    text = re.sub(r"`", "", heading.strip().lower())
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"\s", "-", text)


def split_fences(text: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Return (prose lines outside fences, [(info string, body)] for each fence)."""
    prose: list[str] = []
    blocks: list[tuple[str, str]] = []
    fence: str | None = None
    info = ""
    body: list[str] = []
    for line in text.splitlines():
        m = FENCE_RE.match(line)
        if m and fence is None:
            fence = m.group(2)
            info = line.strip()[len(fence):].strip()
            body = []
        elif m and fence is not None and m.group(2) == fence:
            blocks.append((info, "\n".join(body)))
            fence = None
        elif fence is not None:
            body.append(line)
        else:
            prose.append(line)
    if fence is not None:
        blocks.append((info, "\n".join(body)))
    return prose, blocks


def anchors_of(path: Path, cache: dict[Path, set[str]]) -> set[str]:
    if path not in cache:
        prose, _ = split_fences(path.read_text(encoding="utf-8"))
        found: set[str] = set()
        counts: dict[str, int] = {}
        for line in prose:
            m = re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line)
            if not m:
                continue
            slug = slugify(m.group(1))
            n = counts.get(slug, 0)
            counts[slug] = n + 1
            found.add(slug if n == 0 else f"{slug}-{n}")
        cache[path] = found
    return cache[path]


def check_links(files: list[Path]) -> None:
    cache: dict[Path, set[str]] = {}
    for md in files:
        prose, _ = split_fences(md.read_text(encoding="utf-8"))
        rel = md.relative_to(ROOT)
        for line in prose:
            for target in LINK_RE.findall(line):
                if re.match(r"^[a-z][a-z0-9+.-]*:", target):  # http:, https:, mailto:
                    continue
                file_part, _, anchor = target.partition("#")
                dest = md if not file_part else (md.parent / file_part).resolve()
                if not dest.exists():
                    fail(f"{rel}: broken link target '{target}'")
                    continue
                if anchor and dest.suffix == ".md" and anchor not in anchors_of(dest, cache):
                    fail(f"{rel}: missing anchor '#{anchor}' in {dest.relative_to(ROOT)}")


def check_mermaid() -> None:
    for name in MERMAID_REQUIRED:
        path = ROOT / name
        if not path.exists():
            fail(f"{name}: required file is missing")
            continue
        _, blocks = split_fences(path.read_text(encoding="utf-8"))
        if not any(info.split()[:1] == ["mermaid"] for info, _ in blocks):
            fail(f"{name}: expected at least one ```mermaid diagram")


def tripo_dry_run(args: list[str], label: str) -> None:
    """Run `tripo make <args> --dry-run --json --yes` and require a valid plan."""
    cleaned: list[str] = []
    skip_next = False
    for arg in args:
        if skip_next:
            skip_next = False
        elif arg in {"--dry-run", "--json", "--yes"}:
            continue
        elif arg in {"-o", "--out"}:
            skip_next = True
        else:
            cleaned.append(arg)
    cmd = ["tripo", "make", *cleaned, "--dry-run", "--json", "--yes"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    try:
        plan = json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        fail(f"{label}: tripo gave no JSON plan (exit {proc.returncode}): {proc.stderr.strip()[:200]}")
        return
    if proc.returncode != 0 or not plan.get("valid"):
        fail(f"{label}: invalid tripo plan: {plan.get('errors')}")
        return
    for warning in plan.get("warnings", []):
        if "removed" in warning or "adjusted" in warning:
            print(f"WARN:  {label}: {warning}")


def doc_tripo_commands(files: list[Path]) -> list[tuple[str, list[str]]]:
    found: list[tuple[str, list[str]]] = []
    for md in files:
        _, blocks = split_fences(md.read_text(encoding="utf-8"))
        for info, body in blocks:
            if info.split()[:1] not in (["bash"], ["sh"], ["shell"]):
                continue
            joined = re.sub(r"\\\n\s*", " ", body)
            for line in joined.splitlines():
                line = line.strip()
                if line.startswith('tripo make "'):
                    found.append((f"{md.relative_to(ROOT)}", shlex.split(line)[2:]))
    return found


def manifest_jobs() -> list[tuple[str, list[str]]]:
    try:
        import yaml
    except ImportError:
        fail("PyYAML is required to check manifests: pip install pyyaml")
        return []
    found: list[tuple[str, list[str]]] = []
    for manifest in sorted((ROOT / "art" / "manifests").glob("*.yaml")):
        data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        defaults = data.get("defaults", {})
        jobs = data.get("jobs")
        rel = manifest.relative_to(ROOT)
        if not isinstance(jobs, list) or not jobs:
            fail(f"{rel}: 'jobs' must be a non-empty list")
            continue
        for index, job in enumerate(jobs, start=1):
            merged = {**defaults, **job}
            label = f"{rel} job {index} ({merged.get('name', '?')})"
            text = merged.get("input")
            if not isinstance(text, str) or Path(text).suffix.lower() in IMAGE_EXTS:
                continue  # image/model inputs cannot be planned without the file
            args = [text]
            if "for" in merged:
                args += ["--for", str(merged["for"])]
            if "then" in merged:
                args += ["--then", str(merged["then"])]
            for key, value in (merged.get("params") or {}).items():
                value = json.dumps(value) if not isinstance(value, str) else value
                args += ["-p", f"{key}={value}"]
            found.append((label, args))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-tripo", action="store_true", help="skip tripo dry-run checks")
    opts = parser.parse_args()

    files = markdown_files()
    print(f"Checking {len(files)} Markdown files")
    check_links(files)
    check_mermaid()

    if not opts.no_tripo:
        if shutil.which("tripo") is None:
            fail("tripo CLI not found on PATH (npm install -g tripo-cli, or use --no-tripo)")
        else:
            commands = doc_tripo_commands(files) + manifest_jobs()
            if not commands:
                fail("no tripo commands found to validate; docs lost their examples?")
            for label, args in commands:
                tripo_dry_run(args, label)
            print(f"Dry-ran {len(commands)} tripo commands")

    if errors:
        print(f"\n{len(errors)} problem(s) found")
        return 1
    print("All checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
