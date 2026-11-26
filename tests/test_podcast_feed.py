"""Exercise the feed template with an isolated Jekyll site and public fixture posts."""

import os
import shutil
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
import yaml

from scripts.validate_podcast_feed import validate_feed


def test_podcast_feed_rendering(tmp_path):
    site = Path("output").resolve()
    build_env = {**os.environ, "BUNDLE_GEMFILE": str(site / "Gemfile")}
    if (
        not shutil.which("bundle")
        or subprocess.run(
            ["bundle", "check"], cwd=site, env=build_env, capture_output=True
        ).returncode
    ):
        pytest.skip("Jekyll bundle is unavailable")

    src, dest = tmp_path / "src", tmp_path / "site"
    for subdir in ("_data", "_posts", "_translations", "_layouts"):
        (src / subdir).mkdir(parents=True)
    (src / "_layouts/post.html").write_text("{{ content }}")
    (src / "_layouts/default.html").write_text("{{ content }}")
    shutil.copy(site / "_data/podcast.yml", src / "_data/")
    shutil.copy(site / "podcast/b1.xml", src / "b1.xml")
    (src / "_config.yml").write_text(
        yaml.safe_dump(
            {
                "url": "https://briefberlin.de",
                "lang": "de",
                "collections": ["translations"],
                "publisher": {"name": "BriefBerlin", "email": "info@example.com"},
            }
        )
    )
    audio = {
        "url": "https://media.example.com/a.mp3",
        "mime_type": "audio/mpeg",
        "podcast_guid": "pilot-a",
        "size_bytes": 10,
    }

    def post(name, level="B1", collection="_posts", **fields):
        metadata = {"title": name, "level": level, "audio": audio, **fields}
        (src / collection / f"2024-01-02-{name}.md").write_text(
            "---\n" + yaml.safe_dump(metadata) + "---\nArtikeltext.\n"
        )

    def build():
        subprocess.run(
            ["bundle", "exec", "jekyll", "build", "--source", str(src), "--destination", str(dest)],
            check=True,
            cwd=site,
            env=build_env,
            capture_output=True,
            text=True,
        )
        feed = dest / "podcast/b1.xml"
        validate_feed(feed)
        return ET.parse(feed).findall("channel/item")

    post("eins", title="Garten & Park")
    post("zwei", audio=None)
    post("a2", level="A2")
    post("translation", collection="_translations")
    post("legacy", audio={"url": audio["url"]})
    items = build()
    assert [i.findtext("title") for i in items] == ["Garten & Park"]
    disclosure = yaml.safe_load((src / "_data/podcast.yml").read_text())["disclosure"]
    assert disclosure in items[0].findtext("description")
    assert disclosure in ET.parse(dest / "podcast/b1.xml").findtext("channel/description")
    assert all(disclosure not in p.read_text() for p in dest.rglob("*.html"))

    post("eins", title="Garten & Stadtpark")
    post(
        "zwei", audio={**audio, "url": "https://media.example.com/b.mp3", "podcast_guid": "pilot-b"}
    )
    items = build()
    assert {i.findtext("guid"): i.findtext("title") for i in items} == {
        "pilot-a": "Garten & Stadtpark",
        "pilot-b": "zwei",
    }
    assert len(build()) == 2
    feed_file = dest / "podcast/b1.xml"
    feed = ET.parse(feed_file)
    channel = feed.find("channel")
    channel.append(channel.find("item"))
    feed.write(feed_file)
    with pytest.raises(ValueError, match="Duplicate"):
        validate_feed(feed_file)
