"""Check the rendered BriefBerlin podcast feed before uploading a Pages build."""

import sys
from pathlib import Path
from xml.etree import ElementTree as ET

ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"


def validate_feed(path: Path) -> None:
    rss = ET.parse(path).getroot()
    channel = rss.find("channel")
    if rss.tag != "rss" or rss.get("version") != "2.0" or channel is None:
        raise ValueError("Expected an RSS 2.0 channel")
    for tag in (
        "title",
        "link",
        "description",
        "language",
        ITUNES + "author",
        ITUNES + "explicit",
        ITUNES + "owner/" + ITUNES + "email",
    ):
        if not channel.findtext(tag, "").strip():
            raise ValueError(f"Missing channel field {tag}")
    cover = channel.find(ITUNES + "image")
    category = channel.find(ITUNES + "category")
    if cover is None or not cover.get("href", "").startswith("https://"):
        raise ValueError("Missing HTTPS cover URL")
    if category is None or not category.get("text"):
        raise ValueError("Missing podcast category")

    items = channel.findall("item")
    if not items:
        raise ValueError("Feed has no episodes")
    guids: set[str] = set()
    urls: set[str] = set()
    for item in items:
        for tag in ("title", "link", "description", "pubDate", "guid"):
            if not item.findtext(tag, "").strip():
                raise ValueError(f"Missing episode field {tag}")
        guid = item.findtext("guid", "").strip()
        enclosure = item.find("enclosure")
        if enclosure is None or enclosure.get("type") != "audio/mpeg":
            raise ValueError(f"Missing MP3 enclosure for {guid}")
        url = enclosure.get("url", "")
        if not url.startswith("https://") or int(enclosure.get("length", "0")) <= 0:
            raise ValueError(f"Invalid enclosure for {guid}")
        if guid in guids or url in urls:
            raise ValueError(f"Duplicate GUID or enclosure for {guid}")
        guids.add(guid)
        urls.add(url)


if __name__ == "__main__":
    validate_feed(Path(sys.argv[1]))
