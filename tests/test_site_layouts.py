import re
from pathlib import Path


def test_post_layout_does_not_render_audio_voice_label():
    # The player markup now lives in a shared include so the German post layout
    # and the translation layout cannot drift. post.html must still pull it in,
    # and the rendered markup is asserted against the include.
    post_layout = Path("output/_layouts/post.html").read_text(encoding="utf-8")
    assert "{% include article-audio.html t=t %}" in post_layout

    layout = Path("output/_includes/article-audio.html").read_text(encoding="utf-8")

    assert "<audio controls preload=\"metadata\"" in layout
    assert "article-audio__player" in layout
    assert "article-audio__waveform" in layout
    assert "article-audio__skip-back" in layout
    assert "article-audio__skip-forward" in layout
    # The German strings themselves now live in _data/ui-briefberlin.yml so the
    # translation layout can localize them; the de block must keep them verbatim.
    ui_text = Path("output/_data/ui-briefberlin.yml").read_text(encoding="utf-8")
    assert "10 Sekunden zurück" in ui_text
    assert "10 Sekunden vor" in ui_text
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
    # The deck is set in the site's news serif - the same face and role as
    # .story__deck on the front page - and stays larger than body copy.
    assert "font-family: var(--serif);" in styles
    assert "--serif: \"Newsreader\"" in styles


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


def test_language_selector_links_stay_keyboard_reachable_without_js():
    """Regression guard: tabindex="-1" on every link meant a keyboard user with
    JavaScript unavailable could open the selector but never reach a language.
    The arrow-key handling is an enhancement on top of working tab navigation."""
    include = Path("output/_includes/language-selector.html").read_text(encoding="utf-8")
    # Strip Liquid comments: they document these very anti-patterns by name, so
    # asserting against the raw file would match the explanation, not the markup.
    markup = re.sub(r"\{%-?\s*comment\s*-?%\}.*?\{%-?\s*endcomment\s*-?%\}", "", include, flags=re.S)

    assert "tabindex" not in markup
    # Plain links, not a listbox: options in a listbox must not be individually
    # tabbable, so the roles and the required tab order contradicted each other.
    assert 'role="listbox"' not in markup
    assert 'role="option"' not in markup
    assert 'aria-current="true"' in markup


def test_language_selector_degrades_without_javascript():
    include = Path("output/_includes/language-selector.html").read_text(encoding="utf-8")

    # Native disclosure: opens and reports state with zero JS.
    assert "<details class=\"language-selector\"" in include
    assert "<summary class=\"language-selector__toggle\"" in include
    # A search field that cannot filter is worse than none, so it ships hidden
    # and is revealed by the script on init.
    assert 'class="language-selector__search" hidden' in include


def test_audio_resume_does_not_build_a_selector_from_the_stored_rate():
    """Regression guard: an invalid attribute selector threw inside the restore
    path, aborting before audio.play() and killing the resume feature."""
    script = Path("output/assets/js/language-selector.js").read_text(encoding="utf-8")

    assert "data-speed= + state.rate" not in script
    assert 'getAttribute("data-speed")' in script
    # Restoring position/rate must never be able to prevent playback resuming.
    assert "resumePlayback()" in script
