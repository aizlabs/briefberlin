"""Send the waiting BriefBerlin posts to the user's Telegram chat, as readable text.

Runs inside the briefberlin venv. Uses the repo's own post parser, so the text is
exactly what the posts contain. Sends through bb_tg (Telegram Bot API, see there why).
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from bb_tg import TARGET, send, send_photo

from scripts.publish_telegram_channel import parse_jekyll_post

LIMIT = 3800


def render(path: Path) -> list[str]:
    post = parse_jekyll_post(path, ["Vokabeln"])
    head = f"**{post.title}**\n_{post.level} · {post.reading_time} min_"
    blocks = [head, *post.paragraphs]
    if post.vocabulary_lines:
        vocab = [line[2:] if line.startswith("- ") else line for line in post.vocabulary_lines]
        blocks.append("**Vokabeln**\n" + "\n".join(f"• {v}" for v in vocab))
    messages, current = [], ""
    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) > LIMIT and current:
            messages.append(current)
            current = block
        else:
            current = candidate
    if current:
        messages.append(current)
    return messages


def story_images(paths: list[str]) -> list[tuple[Path, str]]:
    """Images recorded for the stories of the waiting posts, in reading order."""
    seen, images = set(), []
    for raw in paths:
        head = Path(raw).read_text(encoding="utf-8").split("---\n", 2)
        story = (yaml.safe_load(head[1]) or {}).get("story") if len(head) == 3 else None
        record = Path(f"output/_data/story_illustrations/{story}.yml")
        if not story or story in seen or not record.exists():
            continue
        seen.add(story)
        for visual in (yaml.safe_load(record.read_text(encoding="utf-8")) or {}).get("visuals", []):
            image = Path("output") / str(visual.get("path", "")).lstrip("/")
            if image.suffix == ".webp" and image.exists():
                images.append((image, str(visual.get("alt", ""))))
    return images


def main(paths: list[str]) -> int:
    if not Path(TARGET).exists():
        print("ERROR: no Telegram chat configured for previews")
        return 4
    sent = 0
    for image, alt in story_images(paths):
        try:
            send_photo(str(image), f"Image: {alt}")
        except (OSError, RuntimeError) as err:
            print(f"WARNING: could not send image {image.name}: {err}")
            continue
        sent += 1
    for raw in sorted(paths, key=lambda p: (not p.endswith("-a2.md"), p)):
        for text in render(Path(raw)):
            try:
                send(text, markdown=True)
            except (OSError, RuntimeError) as err:
                print(f"ERROR: Telegram send failed after {sent} messages: {err}")
                return 5
            sent += 1
    print(f"PREVIEW SENT: {sent} messages for {len(paths)} articles")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
