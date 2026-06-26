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
