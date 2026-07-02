"""One-command public article generation with uploaded website audio."""

from __future__ import annotations

import argparse
import os
import sys
from argparse import Namespace
from typing import Sequence

from scripts.manual_pipeline import run_manual_pipeline

STANDARD_AUDIO_ENV = {
    "AUDIO_PROVIDER": "openai",
    "AUDIO_VOICE": "alloy",
    "AUDIO_FORMAT": "mp3",
    "AUDIO_PUBLIC_BASE_URL": "https://media.briefberlin.de",
    "AUDIO_S3_BUCKET": "briefberlin-audio-prod",
    "AUDIO_S3_REGION": "eu-central-1",
    "AUDIO_S3_PREFIX": "articles",
}


def apply_audio_defaults() -> None:
    """Enable website-ready audio while preserving explicit delivery overrides."""
    os.environ["AUDIO_ENABLED"] = "true"
    os.environ["AUDIO_UPLOAD_ENABLED"] = "true"
    for key, value in STANDARD_AUDIO_ENV.items():
        os.environ.setdefault(key, value)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate A2/B1 learner posts from private source files and upload audio.",
    )
    parser.add_argument(
        "sources",
        nargs="+",
        help="Private input files under private-input/, input/private/, or named *.source.txt",
    )
    parser.add_argument(
        "--environment",
        default=None,
        help="Configuration environment to load. Defaults to ENVIRONMENT or local.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        apply_audio_defaults()
        return run_manual_pipeline(
            Namespace(
                sources=args.sources,
                level=["A2", "B1"],
                environment=args.environment,
                dry_run=False,
            )
        )
    except Exception as exc:
        print(f"Publish-source pipeline failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
