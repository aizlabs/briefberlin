"""Opt-in private generation history stored beside the first source input."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4


class GenerationTrace:
    """Append each completed stage immediately so interrupted runs retain their history."""

    def __init__(self, source_paths: Sequence[Path], run_id: str):
        first_source = source_paths[0]
        self.path = first_source.parent / (
            f"{first_source.name}.{uuid4().hex}.generation-trace.jsonl"
        )
        # Exclusive creation and owner-only permissions; never overwrite an earlier run.
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        self.record("run_started", run_id=run_id, sources=[str(p) for p in source_paths])

    def record(self, event: str, **data: Any) -> None:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **data,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
