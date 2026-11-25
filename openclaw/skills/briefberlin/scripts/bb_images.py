"""Story illustrations for the waiting BriefBerlin posts (OpenClaw bot).

Runs inside the briefberlin venv from the repo root, like bb_preview.py.

  bb_images.py stories POST...                       print each waiting story's public text
  bb_images.py add STORY FILE ALT [CAPTION] -- POST... attach an image to a waiting story
  bb_images.py illustrate STORY PROMPT ALT -- POST...  generate one image with OpenAI and attach it
  bb_images.py list POST...                           print the visuals of the waiting stories

Only the public post text is printed. Images are validated (WebP or SVG, size and
dimensions) before they are copied to output/assets/images/stories/ and recorded in
output/_data/story_illustrations/<story>.yml, the files the post layout reads.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import yaml
from dotenv import dotenv_values

from scripts.publish_telegram_channel import parse_jekyll_post

IMAGE_DIR = Path("output/assets/images/stories")
DATA_DIR = Path("output/_data/story_illustrations")
MAX_VISUALS = 3
MAX_BYTES = 800_000
MIN_WIDTH = 800
STORY_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[a-z0-9-]+$")
# Same settings as the published story images: 1280x720 WebP, medium quality.
IMAGE_REQUEST = {
    "model": "gpt-image-2",
    "size": "1280x720",
    "quality": "medium",
    "output_format": "webp",
    "output_compression": 80,
    "n": 1,
}
# gpt-image-2 list prices per 1M tokens (text input, image output), for the cost line only.
PRICE_IN, PRICE_OUT = 5.0, 30.0


def front_matter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    parts = text.split("---\n", 2)
    return yaml.safe_load(parts[1]) or {} if len(parts) == 3 else {}


def stories_of(posts: list[str]) -> dict[str, list[Path]]:
    grouped: dict[str, list[Path]] = {}
    for raw in posts:
        story = str(front_matter(Path(raw)).get("story") or "")
        if STORY_RE.match(story):
            grouped.setdefault(story, []).append(Path(raw))
    return grouped


def load_record(story: str) -> dict:
    path = DATA_DIR / f"{story}.yml"
    if not path.exists():
        return {"visuals": []}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data.setdefault("visuals", [])
    return data


def webp_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    chunk = data[12:16]
    if chunk == b"VP8X":
        return 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
    if chunk == b"VP8 ":
        return int.from_bytes(data[26:28], "little") & 0x3FFF, int.from_bytes(data[28:30], "little") & 0x3FFF
    if chunk == b"VP8L":
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return None


def check_image(src: Path) -> str:
    """Returns the file extension to use, or raises ValueError with the reason."""
    if not src.is_file():
        raise ValueError(f"file not found: {src}")
    data = src.read_bytes()
    if len(data) > MAX_BYTES:
        raise ValueError(f"file is {len(data) // 1000} KB; keep it under {MAX_BYTES // 1000} KB "
                         "(generate WebP at 1280x720 with outputCompression around 80)")
    size = webp_size(data)
    if size:
        width, height = size
        if width < MIN_WIDTH or width <= height:
            raise ValueError(f"image is {width}x{height}; it must be landscape and at least {MIN_WIDTH} px wide")
        return "webp"
    text = data[:200_000].decode("utf-8", "replace")
    if "<svg" in text[:2000]:
        if re.search(r"<script|\son\w+\s*=|xlink:href\s*=\s*\"https?:|href\s*=\s*\"https?:", text, re.I):
            raise ValueError("SVG contains scripts, event handlers or external links")
        return "svg"
    raise ValueError("only WebP (from the image tool, outputFormat webp) or SVG files are accepted")


def cmd_stories(posts: list[str]) -> int:
    grouped = stories_of(posts)
    if not grouped:
        print("ERROR: the waiting posts have no story id")
        return 3
    for story, paths in grouped.items():
        visuals = load_record(story)["visuals"]
        print(f"STORY {story}  ({len(visuals)} visual(s) already, max {MAX_VISUALS})")
        for path in sorted(paths, key=lambda p: (not p.name.endswith("-a2.md"), p.name)):
            post = parse_jekyll_post(path, ["Vokabeln"])
            summary = front_matter(path).get("summary") or ""
            print(f"\n[{post.level}] {post.title}\n{summary}\n")
            print("\n\n".join(post.paragraphs))
        print()
    return 0


def cmd_add(story: str, src: str, alt: str, caption: str, posts: list[str]) -> int:
    grouped = stories_of(posts)
    if story not in grouped:
        print(f"ERROR: {story} is not one of the waiting stories: {', '.join(grouped) or 'none'}")
        return 3
    alt = alt.strip()
    if not 5 <= len(alt) <= 200:
        print("ERROR: alt text must be one German sentence of 5-200 characters")
        return 2
    try:
        ext = check_image(Path(src))
    except ValueError as err:
        print(f"ERROR: {err}")
        return 2
    record = load_record(story)
    if len(record["visuals"]) >= MAX_VISUALS:
        print(f"ERROR: {story} already has {MAX_VISUALS} visuals")
        return 3
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    n = len(record["visuals"])
    name = f"{story}.{ext}" if n == 0 else f"{story}-{n + 1}.{ext}"
    shutil.copyfile(src, IMAGE_DIR / name)
    visual = {"path": f"/assets/images/stories/{name}", "alt": alt}
    if caption.strip():
        visual["caption"] = caption.strip()
    record["visuals"].append(visual)
    (DATA_DIR / f"{story}.yml").write_text(
        yaml.safe_dump(record, allow_unicode=True, sort_keys=False, indent=2), encoding="utf-8"
    )
    print(f"IMAGE ADDED: {visual['path']} ({len(record['visuals'])} visual(s) for {story})")
    return 0


def openai_image(prompt: str, out: Path) -> str:
    """Generates one image into `out`; returns a short usage/cost note. Raises RuntimeError."""
    key = os.environ.get("OPENAI_API_KEY") or dotenv_values(".env").get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set in the repo .env")
    if "no text" not in prompt.lower():
        prompt = prompt.rstrip(". ") + ". No text, no logos."
    body = json.dumps({**IMAGE_REQUEST, "prompt": prompt}).encode()
    last = ""
    for _attempt in range(2):
        request = urllib.request.Request(
            "https://api.openai.com/v1/images/generations",
            data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=240) as response:
                result = json.load(response)
            break
        except urllib.error.HTTPError as err:
            try:
                last = json.load(err).get("error", {}).get("message", "")
            except ValueError:
                last = ""
            last = f"OpenAI HTTP {err.code}: {last}"
            if err.code < 500:
                raise RuntimeError(last) from None
        except (urllib.error.URLError, TimeoutError) as err:
            last = f"OpenAI unreachable: {getattr(err, 'reason', err)}"
    else:
        raise RuntimeError(last)
    out.write_bytes(base64.b64decode(result["data"][0]["b64_json"]))
    usage = result.get("usage") or {}
    tin, tout = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
    return f"{tin} in / {tout} out tokens, about ${(tin * PRICE_IN + tout * PRICE_OUT) / 1e6:.3f}"


def cmd_illustrate(story: str, prompt: str, alt: str, posts: list[str]) -> int:
    if story not in stories_of(posts):
        print(f"ERROR: {story} is not one of the waiting stories")
        return 3
    if not 5 <= len(alt.strip()) <= 200:
        print("ERROR: alt text must be one German sentence of 5-200 characters")
        return 2
    if len(prompt.strip()) < 20:
        print("ERROR: the prompt is too short; describe the scene, medium and light")
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "image.webp"
        try:
            note = openai_image(prompt.strip(), out)
        except RuntimeError as err:
            print(f"ERROR: image generation failed: {err}")
            return 5
        print(f"IMAGE GENERATED: gpt-image-2 medium 1280x720 ({note})")
        return cmd_add(story, str(out), alt, "", posts)


def cmd_list(posts: list[str]) -> int:
    for story in stories_of(posts):
        for visual in load_record(story)["visuals"]:
            print(f"{story}\t{visual['path']}\t{visual.get('alt', '')}")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    command, rest = argv[0], argv[1:]
    if command == "stories":
        return cmd_stories(rest)
    if command == "list":
        return cmd_list(rest)
    if command == "illustrate" and "--" in rest:
        i = rest.index("--")
        if i == 3:
            return cmd_illustrate(rest[0], rest[1], rest[2], rest[i + 1:])
    if command == "add" and "--" in rest:
        i = rest.index("--")
        head, posts = rest[:i], rest[i + 1:]
        if len(head) in (3, 4):
            story, src, alt = head[:3]
            return cmd_add(story, src, alt, head[3] if len(head) == 4 else "", posts)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
