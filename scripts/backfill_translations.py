"""Backfill reader-language translations for already-published German posts.

Built and tested, but NOT run as part of shipping the feature: the existing
archive stays German-only until someone explicitly asks for it. Adding a new
language later is the same command with ``--lang``.

Unlike backfill_seo_metadata.py, this appends the ``translations:`` block to the
frontmatter TEXTUALLY instead of round-tripping the whole mapping through
yaml.dump. Re-dumping reflows quoting and the nested ``audio:`` mapping, which
would produce a no-op diff across every post the publisher wrote by hand.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import yaml

from scripts.config import load_config
from scripts.glossary_sections import split_at_glossary_heading
from scripts.logger import setup_logger
from scripts.models import AdaptedArticle, VocabularyItem
from scripts.text_utils import strip_article_ui_markup
from scripts.translator import ArticleTranslator

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
GLOSSARY_JSON_RE = re.compile(
    r'<script[^>]*class="article-glossary-data"[^>]*>(.*?)</script>',
    re.DOTALL,
)
GLOSSARY_ROW_RE = re.compile(r"^-\s+\*\*(?P<term>.+?)\*\*\s+-\s+(?P<rest>.+)$")


def load_post(path: Path) -> Optional[Tuple[str, Dict[str, Any], str]]:
    """Return ``(frontmatter_text, parsed_frontmatter, body)`` or None."""
    match = FRONTMATTER_RE.match(path.read_text(encoding="utf-8"))
    if not match:
        return None
    frontmatter_str, body = match.groups()
    try:
        data = yaml.safe_load(frontmatter_str) or {}
    except Exception:
        return None
    return frontmatter_str, data, body


def recover_vocabulary(body: str, glossary_headings: Sequence[str]) -> List[VocabularyItem]:
    """Recover the visible glossary.

    The embedded JSON payload is authoritative because it carries
    ``defaultGlossary``. Older posts predate it, so fall back to parsing the
    rendered ``## Vokabeln`` list.
    """
    match = GLOSSARY_JSON_RE.search(body)
    if match:
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            payload = []
        items = [
            VocabularyItem(
                term=row.get("term", ""),
                english=row.get("english", ""),
                explanation=row.get("explanation", ""),
                default_glossary=bool(row.get("defaultGlossary")),
            )
            for row in payload
            if row.get("term")
        ]
        if items:
            return items

    _, glossary_md = split_at_glossary_heading(body, glossary_headings)
    items = []
    for line in glossary_md.splitlines():
        row = GLOSSARY_ROW_RE.match(line.strip())
        if not row:
            continue
        parts = [p.strip() for p in row.group("rest").split(" - ", 1)]
        items.append(
            VocabularyItem(
                term=row.group("term").strip(),
                english=parts[0] if parts else "",
                explanation=parts[1] if len(parts) > 1 else "",
                default_glossary=True,
            )
        )
    return items


def recover_article(data: Dict[str, Any], body: str, glossary_headings: Sequence[str]) -> AdaptedArticle:
    """Rebuild the AdaptedArticle the translator needs from a published post."""
    prose, _ = split_at_glossary_heading(body, glossary_headings)
    vocabulary = recover_vocabulary(body, glossary_headings)
    return AdaptedArticle(
        title=str(data.get("title") or ""),
        content=strip_article_ui_markup(prose),
        summary=str(data.get("summary") or data.get("description") or ""),
        reading_time=int(data.get("reading_time") or 2),
        level=str(data.get("level") or "B1"),
        vocabulary=[item for item in vocabulary if item.default_glossary],
        translation_hints=vocabulary,
        author=data.get("author"),
        category=data.get("category"),
        description=data.get("description"),
        # Audio MUST be carried over: translated pages deliberately keep the German
        # track so the reader can listen in German while reading their own
        # language. Dropping it here silently removes the player from every
        # backfilled translation.
        audio=data.get("audio") or None,
    )


def post_ref(path: Path) -> str:
    """Jekyll's `:title` for this post: filename stem minus the date prefix."""
    return re.sub(r"[^a-z0-9]+", "-", path.stem[11:].lower()).strip("-")


def missing_languages(
    translations_dir: Path,
    ref: str,
    wanted: Sequence[str],
    overwrite: bool,
) -> List[str]:
    if overwrite:
        return list(wanted)
    return [code for code in wanted if not (translations_dir / ref / f"{code}.md").exists()]


def append_translations_block(frontmatter_str: str, urls: Dict[str, str]) -> str:
    """Append (or replace) the translations mapping, leaving all other bytes alone."""
    without = re.sub(r"(?ms)^translations:\n(?:[ \t]+.*\n?)*", "", frontmatter_str).rstrip("\n")
    block = "\n".join(["translations:", *(f"  {c}: {u}" for c, u in urls.items())])
    return f"{without}\n{block}"


def sibling_map(translations_dir: Path, ref: str, order: Sequence[str]) -> Dict[str, str]:
    """Full `code -> url` map for a ref, read from what is actually on disk.

    An incremental run only translates the MISSING languages, so the article's
    own `translations` list covers just those. Building the map from it would
    drop every previously generated language out of the German post's selector
    and leave the pre-existing sibling documents advertising a stale, smaller
    set - breaking hreflang reciprocity with no error anywhere.
    """
    present = {path.stem for path in (translations_dir / ref).glob("*.md")}
    urls = {"de": f"/articles/{ref}/"}
    for code in order:
        if code in present:
            urls[code] = f"/articles/{ref}/{code}/"
    # Any language on disk that is no longer configured still exists as a page,
    # so it must stay reachable.
    for code in sorted(present - set(order)):
        urls[code] = f"/articles/{ref}/{code}/"
    return urls


def rewrite_sibling_maps(translations_dir: Path, ref: str, urls: Dict[str, str]) -> int:
    """Rewrite the translations block in every sibling doc so all 8 agree."""
    rewritten = 0
    for path in sorted((translations_dir / ref).glob("*.md")):
        match = FRONTMATTER_RE.match(path.read_text(encoding="utf-8"))
        if not match:
            continue
        frontmatter_str, body = match.groups()
        updated = append_translations_block(frontmatter_str, urls)
        path.write_text(f"---\n{updated}\n---\n{body}", encoding="utf-8")
        rewritten += 1
    return rewritten


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--posts-dir", default="output/_posts")
    parser.add_argument("--translations-dir", default=None,
                        help="Defaults to translations.output_path from config.")
    parser.add_argument("--lang", action="append", default=None,
                        help="Restrict to this language code. Repeatable.")
    parser.add_argument("--level", action="append", choices=["A2", "B1"], default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--model", default=None, help="Override the translation model.")
    parser.add_argument("--environment", default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_config(args.environment or "local")
    logger = setup_logger(config.logging or {"name": "backfill-translations"}, "backfill-translations")

    if args.model:
        config.translations.model = args.model
    config.translations.enabled = True

    translations_dir = Path(args.translations_dir or config.translations.output_path)
    posts_dir = Path(args.posts_dir)
    glossary_headings = config.language.glossary_headings()

    from scripts.publisher import Publisher

    translator = ArticleTranslator(config, logger)
    publisher = Publisher(config, logger, dry_run=args.dry_run)

    paths = sorted(posts_dir.glob("*.md"))
    processed = 0

    for path in paths:
        if args.limit is not None and processed >= args.limit:
            break

        loaded = load_post(path)
        if loaded is None:
            logger.warning("Skipping %s: unparseable frontmatter", path.name)
            continue
        frontmatter_str, data, body = loaded

        if args.level and str(data.get("level")) not in args.level:
            continue

        ref = post_ref(path)
        configured = [lang.code for lang in config.translations.for_level(str(data.get("level") or "B1"))]
        wanted = [c for c in configured if not args.lang or c in args.lang]
        todo = missing_languages(translations_dir, ref, wanted, args.overwrite)
        if not todo:
            continue

        processed += 1
        logger.info("[%s] %s -> %s", processed, path.name, ", ".join(todo))
        if args.dry_run:
            continue

        article = recover_article(data, body, glossary_headings)
        # Restrict this run to the languages actually missing.
        original = config.translations.languages
        config.translations.languages = [lang for lang in original if lang.code in todo]
        try:
            article = translator.translate_article(article)
        finally:
            config.translations.languages = original

        if not article.translations:
            logger.error("No translations produced for %s", path.name)
            continue

        publisher.translations_dir = translations_dir
        # Reuse the publisher so backfilled files are byte-compatible with
        # pipeline-generated ones.
        target = translations_dir / ref
        target.mkdir(parents=True, exist_ok=True)
        from datetime import datetime

        stamp = data.get("date")
        timestamp = stamp if isinstance(stamp, datetime) else datetime.now()
        for translation in article.translations:
            (target / f"{translation.lang}.md").write_text(
                publisher._generate_translation_markdown(article, translation, timestamp, ref),
                encoding="utf-8",
            )

        # Derive the map from what is on disk, not from this run's subset, so an
        # incremental backfill keeps previously generated languages reachable.
        urls = sibling_map(translations_dir, ref, [lang.code for lang in original])
        new_frontmatter = append_translations_block(frontmatter_str, urls)
        path.write_text(f"---\n{new_frontmatter}\n---\n{body}", encoding="utf-8")
        # All siblings must advertise the identical set or hreflang stops being
        # reciprocal and Google discards the cluster.
        rewrite_sibling_maps(translations_dir, ref, urls)

    logger.info("Backfill complete: %d posts processed", processed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
