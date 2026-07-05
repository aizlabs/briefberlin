"""Generate public posts from private sources, then commit and push them."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from typing import Sequence

POSTS_PATH = "output/_posts"


def parse_publish_timestamp(value: str | None) -> datetime | None:
    """Parse an optional ISO publish timestamp for commit messages."""
    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            "--publish-timestamp must be an ISO date or datetime, "
            "for example 2026-07-03 or 2026-07-03T09:00:00"
        ) from exc


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate public learner posts, commit output/_posts, and push them.",
    )
    parser.add_argument(
        "sources",
        nargs="+",
        help="Private input files. Each source is published as its own A2/B1 article set.",
    )
    parser.add_argument(
        "--remote",
        default="origin",
        help="Git remote to push to. Defaults to origin.",
    )
    parser.add_argument(
        "--branch",
        default="main",
        help="Git branch to push. Defaults to main.",
    )
    parser.add_argument(
        "--publish-timestamp",
        default=None,
        help=(
            "Forward an ISO post/audio timestamp to briefberlin-publish-source, "
            "for example 2026-07-03 or 2026-07-03T09:00:00."
        ),
    )
    return parser.parse_args(argv)


def run_command(
    command: Sequence[str],
    *,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, text=True, capture_output=capture_output)


def git_status(pathspec: str | None = None) -> str:
    command = ["git", "status", "--porcelain"]
    if pathspec:
        command.extend(["--", pathspec])
    result = run_command(command)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git status failed")
    return result.stdout.strip()


def print_command_output(result: subprocess.CompletedProcess[str]) -> None:
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    publish_timestamp = parse_publish_timestamp(args.publish_timestamp)

    dirty_status = git_status()
    if dirty_status:
        print(
            "Refusing to publish because the worktree is not clean:\n"
            f"{dirty_status}",
            file=sys.stderr,
        )
        return 1

    for source in args.sources:
        print(f"Publishing source: {source}")
        publish_command = ["uv", "run", "briefberlin-publish-source"]
        if args.publish_timestamp:
            publish_command.extend(["--publish-timestamp", args.publish_timestamp])
        publish_command.append(source)
        publish_result = run_command(publish_command, capture_output=False)
        if publish_result.returncode != 0:
            return publish_result.returncode

    posts_status = git_status(POSTS_PATH)
    if not posts_status:
        print(f"No generated post changes found under {POSTS_PATH}; nothing to commit.")
        return 0

    add_result = run_command(["git", "add", POSTS_PATH])
    print_command_output(add_result)
    if add_result.returncode != 0:
        return add_result.returncode

    timestamp_datetime = publish_timestamp or datetime.now(timezone.utc)
    if timestamp_datetime.tzinfo is None:
        timestamp_datetime = timestamp_datetime.replace(tzinfo=timezone.utc)
    timestamp = timestamp_datetime.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    commit_result = run_command(["git", "commit", "-m", f"Generate articles - {timestamp}"])
    print_command_output(commit_result)
    if commit_result.returncode != 0:
        return commit_result.returncode

    push_result = run_command(["git", "push", args.remote, args.branch])
    print_command_output(push_result)
    return push_result.returncode


if __name__ == "__main__":
    sys.exit(main())
