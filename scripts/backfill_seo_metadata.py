"""
Backfill SEO metadata (category, description, keywords) for existing post markdown files.
"""

import argparse
import re
from pathlib import Path
from typing import List, Tuple

import yaml

from scripts.topic_utils import extract_named_entities, sanitize_topic_keywords

# Category inference rules based on keywords / text matching
CATEGORY_RULES: List[Tuple[str, re.Pattern[str]]] = [
    (
        "Verkehr",
        re.compile(
            r"\b(bvg|s-bahn|u-bahn|tram|straßenbahn|verkehr|bahn|rad|fahrrad|e-scooter|bus|auto|baustelle|flughafen)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Politik",
        re.compile(
            r"\b(politik|partei|spd|cdu|afd|grüne|linke|bundestag|senat|wegner|evers|wahl|regierung|beamte|gesetz|reform)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Stadtleben",
        re.compile(
            r"\b(miete|mieten|wohnung|wohnungen|bau|quartier|stadtteil|molkenmarkt|tempelhofer feld|wohngeld|grundsicherung|bunker|mauerpark)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Kultur",
        re.compile(
            r"\b(kultur|museum|kunst|musik|film|festival|csd|pop-inn|tour de france|dachpool|jugendclub|theater)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Wirtschaft",
        re.compile(
            r"\b(wirtschaft|tesla|preise|geld|it|itdz|zölle|unternehmen|firmen|gehalt|löhne|investition)\b",
            re.IGNORECASE,
        ),
    ),
]


def infer_category(title: str, text: str, topics: List[str]) -> str:
    """Infer news category from title, topics, and text content."""
    combined = f"{title} {' '.join(topics)} {text[:500]}"
    for category_name, pattern in CATEGORY_RULES:
        if pattern.search(combined):
            return category_name
    return "Nachrichten"


def clean_body_text_for_description(body: str) -> str:
    """Extract clean 1-2 sentence description from first markdown paragraph, removing HTML tags/buttons."""
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    for p in paragraphs:
        if p.startswith("#") or p.startswith("<script") or p.startswith("##"):
            continue
        # Remove HTML tags like <button ...>text</button> or <span>
        cleaned = re.sub(r"<button[^>]*>(.*?)</button>", r"\1", p)
        cleaned = re.sub(r"<[^>]+>", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if len(cleaned) > 20:
            # Truncate at 160 chars nicely at sentence boundary or space
            if len(cleaned) <= 160:
                return cleaned
            truncated = cleaned[:157]
            last_space = truncated.rfind(" ")
            if last_space > 100:
                return truncated[:last_space] + "..."
            return truncated + "..."
    return ""


def process_post_file(file_path: Path, dry_run: bool = False) -> bool:
    """Read post file, parse frontmatter, backfill SEO fields if missing, and write back."""
    content = file_path.read_text(encoding="utf-8")

    # Match YAML frontmatter between `---` markers
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", content, re.DOTALL)
    if not match:
        print(f"Skipping {file_path.name}: Invalid frontmatter structure")
        return False

    frontmatter_str, body_str = match.groups()
    try:
        data = yaml.safe_load(frontmatter_str) or {}
    except Exception as exc:
        print(f"Skipping {file_path.name}: Error parsing YAML ({exc})")
        return False

    title = str(data.get("title") or "")
    existing_topics = data.get("topics") or []
    if isinstance(existing_topics, str):
        existing_topics = [existing_topics]

    # 1. Backfill category
    if "category" not in data or not data["category"]:
        data["category"] = infer_category(title, body_str, existing_topics)

    # 2. Backfill description
    if "description" not in data or not data["description"]:
        data["description"] = clean_body_text_for_description(body_str)

    # 3. Backfill / enrich keywords with SpaCy NER
    clean_text = re.sub(r"<[^>]+>", " ", body_str)
    ner_entities = extract_named_entities(f"{title}\n{clean_text}")
    combined_raw_keywords = list(existing_topics) + ner_entities
    enriched_keywords = sanitize_topic_keywords(
        combined_raw_keywords,
        max_keywords=7,
        lowercase=False,
    )

    data["topics"] = enriched_keywords
    data["keywords"] = enriched_keywords

    # Re-serialize frontmatter
    new_yaml = yaml.dump(
        data,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=None,
    ).strip()

    new_content = f"---\n{new_yaml}\n---\n{body_str}"

    if dry_run:
        print(f"[DRY RUN] Would update: {file_path.name}")
        print(f"  Category: {data['category']}")
        print(f"  Description: {data['description']}")
        print(f"  Keywords: {data['keywords']}")
        return True

    file_path.write_text(new_content, encoding="utf-8")
    print(f"✅ Updated {file_path.name}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill SEO metadata (category, description, keywords) for existing post markdown files.",
    )
    parser.add_argument(
        "--posts-dir",
        default="output/_posts",
        help="Path to Jekyll _posts directory (default: output/_posts)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print changes without modifying files",
    )
    args = parser.parse_args()

    posts_dir = Path(args.posts_dir)
    if not posts_dir.exists():
        print(f"Error: Directory {posts_dir} does not exist")
        return

    post_files = sorted(posts_dir.glob("*.md"))
    print(f"Found {len(post_files)} articles in {posts_dir} (dry_run={args.dry_run})")

    updated_count = 0
    for file_path in post_files:
        if process_post_file(file_path, dry_run=args.dry_run):
            updated_count += 1

    print(f"\nDone! Processed {updated_count} / {len(post_files)} articles.")


if __name__ == "__main__":
    main()
