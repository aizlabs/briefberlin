"""Both levels of one news item carry the same `story` id, so the homepage can pair them."""

from datetime import datetime

import pytest

from scripts.manual_pipeline import make_story_id
from scripts.models import AdaptedArticle
from scripts.publisher import Publisher

TIMESTAMP = datetime(2026, 11, 7, 16, 13, 6)


def _article(level: str, title: str, story: str | None) -> AdaptedArticle:
    return AdaptedArticle(
        title=title,
        content="Erster Absatz über das Stadtbad.\n\nZweiter Absatz über die Folgen.",
        summary="Das Stadtbad hat wieder Probleme.",
        reading_time=2,
        level=level,
        category="Stadtleben",
        author="clara-becker",
        story=story,
    )


@pytest.fixture
def publisher(base_config, mock_logger, tmp_path) -> Publisher:
    base_config.output = {"path": str(tmp_path / "_posts"), "default_author": "clara-becker"}
    base_config.translations.output_path = str(tmp_path / "_translations")
    return Publisher(base_config, mock_logger)


def test_story_id_is_readable_and_stable():
    story = make_story_id("Probleme im Stadtbad Schöneberg", TIMESTAMP)
    assert story == "20261107-161306-probleme-im-stadtbad-schoeneberg"
    assert make_story_id("Probleme im Stadtbad Schöneberg", TIMESTAMP) == story


def test_story_id_has_no_trailing_hyphen_when_cut():
    story = make_story_id("Ein sehr langer Titel über viele Dinge in Berlin und Brandenburg", TIMESTAMP)
    assert not story.endswith("-")
    assert len(story) <= 16 + 40


def test_both_levels_get_the_same_story_line(publisher, tmp_path):
    story = make_story_id("Probleme im Stadtbad Schöneberg", TIMESTAMP)
    a2 = _article("A2", "Probleme im Stadtbad Schöneberg", story)
    b1 = _article("B1", "Stadtbad Schöneberg hat kurz nach Sanierung wieder Probleme", story)
    publisher.save_article(a2, timestamp=TIMESTAMP)
    publisher.save_article(b1, timestamp=TIMESTAMP)

    posts = sorted((tmp_path / "_posts").glob("*.md"))
    assert len(posts) == 2
    for post in posts:
        assert f'story: "{story}"\n' in post.read_text("utf-8")


def test_posts_without_a_story_id_have_no_story_line(publisher, tmp_path):
    publisher.save_article(_article("A2", "Ohne Story", None), timestamp=TIMESTAMP)
    post = next((tmp_path / "_posts").glob("*.md"))
    assert "\nstory:" not in post.read_text("utf-8")
