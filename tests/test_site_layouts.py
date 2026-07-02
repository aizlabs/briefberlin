from pathlib import Path


def test_post_layout_does_not_render_audio_voice_label():
    layout = Path("output/_layouts/post.html").read_text(encoding="utf-8")

    assert "<audio controls preload=\"metadata\"" in layout
    assert "article-audio__player" in layout
    assert "article-audio__waveform" in layout
    assert "article-audio__skip-back" in layout
    assert "10 Sekunden zurück" in layout
    assert "article-audio__skip-forward" in layout
    assert "10 Sekunden vor" in layout
    assert 'data-speed="0.5"' in layout
    assert 'data-speed="0.75"' in layout
    assert 'data-speed="1"' in layout
    assert ">Escuchar<" not in layout
    assert "article-audio__download" not in layout
    assert "Descargar audio" not in layout
    assert "Voz:" not in layout
    assert "page.audio.voice" not in layout


def test_head_includes_interactive_glossary_script():
    head = Path("output/_includes/head/custom.html").read_text(encoding="utf-8")

    assert "/assets/js/glossary-popup.js" in head


def test_interactive_glossary_reuses_existing_vocabulary_section():
    script = Path("output/assets/js/glossary-popup.js").read_text(encoding="utf-8")

    assert 'heading.id === "vokabeln"' in script
    assert 'text.startsWith("vokabeln ")' in script
    assert 'sibling.tagName !== "H2"' in script


def test_interactive_glossary_toggles_vocabulary_terms():
    script = Path("output/assets/js/glossary-popup.js").read_text(encoding="utf-8")

    assert "selectedTerms" in script
    assert "const locale = glossaryLocale(pageContent)" in script
    assert "function addToGlossary(pageContent, item, selectedTerms, locale)" in script
    assert "function removeFromGlossary(pageContent, item, selectedTerms, locale)" in script
    assert "setArticleTermSelected(pageContent, item, true)" in script
    assert "setArticleTermSelected(pageContent, item, false)" in script
    assert "Aus Vokabelliste entfernen" in script
    assert "Zur Vokabelliste hinzufügen" in script
    assert "addButton.disabled = false" in script


def test_selected_glossary_terms_are_bold_not_underlined():
    styles = Path("output/assets/css/custom.css").read_text(encoding="utf-8")

    assert ".article-term--default" in styles
    assert "border-bottom-color: transparent" in styles
    assert "font-weight: 700" in styles
