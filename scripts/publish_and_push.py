"""Generate public posts from private sources, then commit and push them."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

POSTS_PATH = "output/_posts"
TRANSLATIONS_PATH = "output/_translations"
# Both must be staged: translations are written on every run and would otherwise
# be regenerated forever and never pushed.
PUBLISH_PATHS = [POSTS_PATH, TRANSLATIONS_PATH]


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


def git_status(pathspec: str | Sequence[str] | None = None) -> str:
    command = ["git", "status", "--porcelain"]
    if pathspec:
        paths = [pathspec] if isinstance(pathspec, str) else list(pathspec)
        command.extend(["--", *paths])
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
    configured = bool(os.environ.get("BRIEFBERLIN_EDITORIAL_DB"))
    if configured and args.branch in {"main", "refs/heads/main"}:
        from scripts.editorial.publication_cli import main as publisher

        if args.remote != "origin" or args.publish_timestamp or len(args.sources) != 1:
            print("Editorial host publication uses origin/main, one approved draft and the live clock.", file=sys.stderr)
            return 2
        return publisher(["manual", "stage", str(Path(args.sources[0]).resolve())])
    push_target = args.branch
    if configured:
        # Never accept refspecs, pseudo refs, remote helpers or option injection on this host.
        if (args.remote != "origin" or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9/_.-]*", args.branch)
                or args.branch.startswith("refs/") or args.branch == "HEAD"
                or run_command(["git", "check-ref-format", "refs/heads/" + args.branch]).returncode):
            print("Use a literal test branch name on origin, or the manual main workflow.", file=sys.stderr)
            return 2
        ref = "refs/heads/" + args.branch
        if run_command(["git", "symbolic-ref", "-q", "HEAD"]).stdout.strip() != ref:
            print("Check out the independent test branch before generating.", file=sys.stderr)
            return 2
        push_target = f"{ref}:{ref}"
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

    posts_status = git_status(PUBLISH_PATHS)
    if not posts_status:
        print(
            "No generated post changes found under "
            f"{' or '.join(PUBLISH_PATHS)}; nothing to commit."
        )
        return 0

    add_result = run_command(["git", "add", *PUBLISH_PATHS])
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

    push_result = run_command(["git", "push", args.remote, push_target])
    print_command_output(push_result)
    return push_result.returncode


if __name__ == "__main__":
    sys.exit(main())
