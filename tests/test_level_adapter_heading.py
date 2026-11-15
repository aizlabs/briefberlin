from scripts.level_adapter import strip_leading_heading


def test_strips_title_heading_at_start():
    content = "# Ein Croissant für 6,80 Euro\n\nIn Berlin kostet ein Croissant viel.\n\nZweiter Absatz."
    assert strip_leading_heading(content) == "In Berlin kostet ein Croissant viel.\n\nZweiter Absatz."


def test_strips_heading_after_leading_blank_lines_and_any_level():
    assert strip_leading_heading("\n\n## Titel\nErster Absatz.") == "Erster Absatz."


def test_keeps_body_without_heading_and_later_headings():
    content = "Erster Absatz.\n\n## Zwischentitel\n\nZweiter Absatz."
    assert strip_leading_heading(content) == content


def test_keeps_hash_that_is_not_a_heading():
    assert strip_leading_heading("#1 in Berlin: ein Absatz.") == "#1 in Berlin: ein Absatz."
