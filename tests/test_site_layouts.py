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
    assert "data-timings-url" in layout
    assert "data-highlight-context" in layout


def test_post_layout_renders_editorial_summary():
    layout = Path("output/_layouts/post.html").read_text(encoding="utf-8")
    styles = Path("output/assets/css/custom.css").read_text(encoding="utf-8")

    assert "{% if page.summary %}" in layout
    assert 'class="article-summary"' in layout
    assert 'class="article-summary" itemprop=' not in layout
    assert "{{ page.summary | escape }}" in layout
    assert ".article-summary {" in styles
    assert 'font-family: Georgia, "Times New Roman", serif;' in styles
    assert "font-size: 1rem;" in styles


def test_audio_player_supports_optional_synchronized_highlighting():
    script = Path("output/assets/js/audio-player.js").read_text(encoding="utf-8")
    styles = Path("output/assets/css/custom.css").read_text(encoding="utf-8")

    assert "initTextHighlighting" in script
    assert "root.dataset.timingsUrl" in script
    assert "textMatchesBlock" in script
    assert 'page.querySelector(".article-summary")' in script
    assert 'block.kind === "summary"' in script
    assert "trimEnd()" in script
    assert 'root.dataset.highlightContext === "paragraph"' in script
    assert "article-audio-word" in script
    assert "activeContextKey" in script
    assert "clearActiveWord" in script
    assert "contextCueAt" in script
    assert "if (!audio.paused && !audio.ended)" in script
    assert ".article-audio-word.is-active-context" in styles
    assert ".article-audio-word.is-active-word" in styles
    assert ".is-active-audio-paragraph" in styles


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
