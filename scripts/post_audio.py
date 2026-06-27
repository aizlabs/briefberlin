"""Generate website audio for an existing public Jekyll post."""

from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Sequence

import yaml

from scripts.audio_pipeline import AudioPipeline
from scripts.config import load_config
from scripts.models import AdaptedArticle, AudioAsset, VocabularyItem

POSTS_DIR = Path("output/_posts")
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", flags=re.S)
EMPHASIS_RE = re.compile(r"\*\*(.+?)\*\*")
VOCABULARY_ITEM_RE = re.compile(r"- \*\*(.+?)\*\* - (.+?)(?: - (.+))?$")


def split_frontmatter(markdown: str) -> tuple[dict, str]:
    """Split a Jekyll Markdown post into parsed YAML front matter and body."""
    match = FRONTMATTER_RE.match(markdown)
    if not match:
        raise ValueError("Post must start with YAML front matter")
    return yaml.safe_load(match.group(1)) or {}, match.group(2)


def is_public_post_path(path: Path) -> bool:
    """Return whether a path is inside the public generated posts directory."""
    posts_dir = (Path.cwd() / POSTS_DIR).resolve()
    try:
        path.resolve().relative_to(posts_dir)
    except ValueError:
        return False
    return True


def extract_article_content(body: str) -> str:
    """Extract public article prose, excluding vocabulary and footer blocks."""
    content = body.split("## Vokabeln", 1)[0]
    content = content.split("\n---\n", 1)[0]
    return content.strip()


def extract_vocabulary(body: str) -> list[VocabularyItem]:
    """Extract structured vocabulary items from the public Markdown vocabulary section."""
    if "## Vokabeln" not in body:
        return []

    _, vocabulary_section = body.split("## Vokabeln", 1)
    items: list[VocabularyItem] = []
    for line in vocabulary_section.splitlines():
        match = VOCABULARY_ITEM_RE.match(line.strip())
        if not match:
            continue
        term, english, explanation = match.groups()
        items.append(
            VocabularyItem(
                term=term.strip(),
                english=english.strip(),
                explanation=(explanation or "").strip(),
            )
        )
    return items


def first_sentence(text: str) -> str:
    """Return a public-text fallback summary when the post has no summary field."""
    compact = re.sub(r"\s+", " ", EMPHASIS_RE.sub(r"\1", text).replace("*", "")).strip()
    match = re.match(r"(.+?[.!?])(?:\s|$)", compact)
    return match.group(1) if match else compact[:250]


def coerce_post_datetime(value: object) -> datetime:
    """Normalize a YAML date value from Jekyll front matter."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    raise ValueError("Post front matter must include a Jekyll datetime")


def build_article_from_post(path: Path) -> tuple[AdaptedArticle, datetime, dict, str]:
    """Build an AdaptedArticle from public post Markdown."""
    if not is_public_post_path(path):
        raise ValueError("Audio generation only accepts posts under output/_posts")

    raw = path.read_text(encoding="utf-8")
    frontmatter, body = split_frontmatter(raw)
    content = extract_article_content(body)
    if not content:
        raise ValueError("Post body does not contain article content")

    timestamp = coerce_post_datetime(frontmatter.get("date"))
    article = AdaptedArticle(
        title=str(frontmatter["title"]),
        content=content,
        summary=str(frontmatter.get("summary") or first_sentence(content)),
        reading_time=int(frontmatter.get("reading_time") or 1),
        vocabulary=extract_vocabulary(body),
        level=str(frontmatter["level"]),
        sources=[],
        audio=AudioAsset(**frontmatter["audio"]) if isinstance(frontmatter.get("audio"), dict) else None,
    )
    return article, timestamp, frontmatter, body


def render_frontmatter(frontmatter: dict, body: str) -> str:
    """Render updated front matter and preserve the Markdown body as-is."""
    rendered = yaml.safe_dump(
        frontmatter,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).strip()
    return f"---\n{rendered}\n---\n{body}"


def update_post_audio(path: Path, audio: AudioAsset, frontmatter: dict, body: str) -> None:
    """Write public audio metadata into a post's front matter."""
    frontmatter["audio"] = {
        "url": audio.url,
        "format": audio.format,
        "mime_type": audio.mime_type,
        "provider": audio.provider,
        "voice": audio.voice,
    }
    path.write_text(render_frontmatter(frontmatter, body), encoding="utf-8")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate website audio for an existing public post under output/_posts.",
    )
    parser.add_argument("post", help="Public Jekyll post Markdown file under output/_posts")
    parser.add_argument("--environment", default="local", help="Config environment to load")
    parser.add_argument("--upload", action="store_true", help="Upload generated audio to S3")
    parser.add_argument("--provider", default=None, help="Audio provider override")
    parser.add_argument("--voice", default=None, help="TTS voice override")
    parser.add_argument("--format", default=None, choices=["mp3", "m4a", "wav"], help="Audio format override")
    parser.add_argument("--public-base-url", default=None, help="Public media base URL override")
    parser.add_argument("--s3-bucket", default=None, help="S3 bucket override")
    parser.add_argument("--s3-region", default=None, help="S3 region override")
    parser.add_argument("--s3-prefix", default=None, help="S3 key prefix override")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        post_path = Path(args.post).expanduser()
        article, timestamp, frontmatter, body = build_article_from_post(post_path)

        config = load_config(args.environment)
        config.audio.enabled = True
        config.audio.upload_enabled = bool(args.upload)
        if args.provider:
            config.audio.provider = args.provider
        if args.voice:
            config.audio.voice = args.voice
        if args.format:
            config.audio.format = args.format
        if args.public_base_url:
            config.audio.public_base_url = args.public_base_url
        if args.s3_bucket:
            config.audio.s3.bucket = args.s3_bucket
        if args.s3_region:
            config.audio.s3.region = args.s3_region
        if args.s3_prefix:
            config.audio.s3.prefix = args.s3_prefix

        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        logger = logging.getLogger("briefberlin.post-audio")
        prepared = AudioPipeline(config, logger).prepare_for_publish(article, timestamp=timestamp)

        if not prepared.audio:
            raise RuntimeError("Audio pipeline completed without audio metadata")
        if args.upload and not prepared.audio.url:
            raise RuntimeError("Audio upload was requested but no public audio URL was produced")

        if prepared.audio.url:
            update_post_audio(post_path, prepared.audio, frontmatter, body)
            print(f"Updated post audio: {post_path}")
        else:
            print("Generated local audio without updating post front matter because --upload was not set.")

        print(f"Storage key: {prepared.audio.storage_key}")
        print(f"Local audio: {prepared.audio.local_audio_path}")
        if prepared.audio.url:
            print(f"Public URL: {prepared.audio.url}")
        return 0
    except Exception as exc:
        print(f"Post audio generation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
