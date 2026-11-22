"""Rewrite ``description:`` of already-published posts and translations as search snippets.

Applies :func:`scripts.seo_description.finalize_seo_description` (names Berlin in the
page language, fits a search result) to every German post and every translation.
No LLM call: the transformation is deterministic, so A2/B1 posts that share one
German description stay paired (level-switch.html, language-edition.html).

Only the ``description`` entry is replaced; the rest of the front matter and the
body are left byte-identical.

    uv run python -m scripts.backfill_seo_descriptions --dry-run
    uv run python -m scripts.backfill_seo_descriptions
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import List, Optional, Tuple

import yaml

from scripts.seo_description import finalize_seo_description

_FRONTMATTER = re.compile(r"\A---\n(.*?\n)---\n", re.DOTALL)
# A description key plus any indented continuation lines (YAML-folded plain scalars).
_DESCRIPTION_ENTRY = re.compile(r"^description:.*\n(?:[ \t]+.*\n)*", re.MULTILINE)
# Only the ASCII "..." that backfill_seo_metadata wrote; "…" is our own word-boundary
# cut and must survive a second run.
_TRAILING_ELLIPSIS = re.compile(r"\s*\.\.\.\s*$")
_SENTENCE_END = re.compile(r"[.!?](?=\s)")


def drop_truncated_tail(text: str) -> str:
    """Remove an unfinished last sentence that backfill_seo_metadata cut with "...".

    Keeps the text unchanged when there is no complete sentence to fall back to.
    """
    if not _TRAILING_ELLIPSIS.search(text):
        return text
    stem = _TRAILING_ELLIPSIS.sub("", text)
    ends = [m.end() for m in _SENTENCE_END.finditer(stem + " ")]
    if not ends:
        return text
    return stem[: ends[-1]].strip()


def _yaml_quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def rewrite_description(content: str, lang: str) -> Optional[Tuple[str, str, str]]:
    """Return ``(new_content, old, new)`` or None when nothing changes."""
    match = _FRONTMATTER.match(content)
    if not match:
        return None
    frontmatter = match.group(1)
    data = yaml.safe_load(frontmatter) or {}
    old = data.get("description")
    if not isinstance(old, str) or not old.strip():
        return None
    if not data.get("level"):
        # Site announcements (e.g. the welcome post) are not news stories.
        return None

    new = finalize_seo_description(drop_truncated_tail(old), lang)
    if new == re.sub(r"\s+", " ", old).strip():
        return None

    entry = _DESCRIPTION_ENTRY.search(frontmatter)
    if not entry:
        return None
    new_frontmatter = (
        frontmatter[: entry.start()]
        + f"description: {_yaml_quote(new)}\n"
        + frontmatter[entry.end():]
    )
    if (yaml.safe_load(new_frontmatter) or {}).get("description") != new:
        raise ValueError("description rewrite did not round-trip")
    return content[: match.start(1)] + new_frontmatter + content[match.end(1):], old, new


def collect_files(output_dir: Path, posts_lang: str) -> List[Tuple[Path, str]]:
    files = [(path, posts_lang) for path in sorted((output_dir / "_posts").glob("*.md"))]
    files += [
        (path, path.stem) for path in sorted((output_dir / "_translations").glob("*/*.md"))
    ]
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", default="output", help="Jekyll site root")
    parser.add_argument("--posts-lang", default="de", help="Language of _posts")
    parser.add_argument("--dry-run", action="store_true", help="Print changes only")
    args = parser.parse_args()

    files = collect_files(Path(args.output_dir), args.posts_lang)
    changed = 0
    for path, lang in files:
        content = path.read_text(encoding="utf-8")
        result = rewrite_description(content, lang)
        if result is None:
            continue
        new_content, old, new = result
        changed += 1
        if args.dry_run:
            print(f"[{lang}] {path.relative_to(args.output_dir)}\n  - {old}\n  + {new}")
        else:
            path.write_text(new_content, encoding="utf-8")

    verb = "Would update" if args.dry_run else "Updated"
    print(f"{verb} {changed} of {len(files)} files")


if __name__ == "__main__":
    main()
