"""Build provider-neutral synchronized-text sidecars for the website player."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from scripts.models import AudioWordCue, SpeechBlock, SpeechScript

_SENTENCE_PATTERN = re.compile(r"[^.!?…]+(?:[.!?…]+|$)")


def build_timing_sidecar(
    script: SpeechScript,
    cues: list[AudioWordCue],
    *,
    provider: str,
    model: str,
    voice: str,
) -> dict[str, Any]:
    """Convert global provider cues into stable per-visible-block offsets."""
    blocks = [_serialize_block(block) for block in script.blocks]
    serialized_cues: list[dict[str, Any]] = []
    for cue in cues:
        block = _containing_block(script.blocks, cue)
        if block is None:
            continue
        local_start = cue.text_start - block.text_start
        local_end = cue.text_end - block.text_start
        sentence_id = _sentence_id_for_offset(block.text, local_start)
        serialized_cues.append(
            {
                "text": cue.text,
                "start": round(cue.start_seconds, 6),
                "end": round(cue.end_seconds, 6),
                "block_id": block.id,
                "block_kind": block.kind,
                "text_start": local_start,
                "text_end": local_end,
                "sentence_id": sentence_id,
            }
        )

    return {
        "version": 1,
        "granularity": "word",
        "narration_sha256": hashlib.sha256(script.narration.encode("utf-8")).hexdigest(),
        "provider": provider,
        "model": model,
        "voice": voice,
        "blocks": blocks,
        "cues": serialized_cues,
    }


def _serialize_block(block: SpeechBlock) -> dict[str, Any]:
    sentences = []
    for index, match in enumerate(_SENTENCE_PATTERN.finditer(block.text)):
        start, end = match.span()
        while start < end and block.text[start].isspace():
            start += 1
        while end > start and block.text[end - 1].isspace():
            end -= 1
        if start < end:
            sentences.append({"id": index, "text_start": start, "text_end": end})
    return {"id": block.id, "kind": block.kind, "text": block.text, "sentences": sentences}


def _containing_block(
    blocks: list[SpeechBlock],
    cue: AudioWordCue,
) -> SpeechBlock | None:
    for block in blocks:
        if cue.text_start >= block.text_start and cue.text_end <= block.text_end:
            return block
    return None


def _sentence_id_for_offset(text: str, offset: int) -> int | None:
    for index, match in enumerate(_SENTENCE_PATTERN.finditer(text)):
        if match.start() <= offset < match.end():
            return index
    return None
