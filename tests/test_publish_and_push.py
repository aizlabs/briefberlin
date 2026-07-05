import pytest

from scripts import publish_and_push


class CommandRunner:
    def __init__(self, responses):
        self.responses = list(responses)
        self.commands = []
        self.capture_output = []

    def __call__(self, command, *, capture_output=True):
        self.commands.append(list(command))
        self.capture_output.append(capture_output)
        if not self.responses:
            raise AssertionError(f"Unexpected command: {command}")
        return self.responses.pop(0)


def completed(returncode=0, stdout="", stderr=""):
    return publish_and_push.subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_parse_args_rejects_missing_sources():
    with pytest.raises(SystemExit):
        publish_and_push.parse_args([])


def test_dirty_worktree_exits_before_generation(monkeypatch, capsys):
    runner = CommandRunner([
        completed(stdout=" M scripts/prompts.py\n"),
    ])
    monkeypatch.setattr(publish_and_push, "run_command", runner)

    result = publish_and_push.main(["private-input/source-18.txt"])

    assert result == 1
    assert runner.commands == [["git", "status", "--porcelain"]]
    assert "worktree is not clean" in capsys.readouterr().err


def test_failed_publish_prevents_git_commit_and_push(monkeypatch):
    runner = CommandRunner([
        completed(),
        completed(returncode=1, stderr="pipeline failed\n"),
    ])
    monkeypatch.setattr(publish_and_push, "run_command", runner)

    result = publish_and_push.main(["private-input/source-18.txt"])

    assert result == 1
    assert runner.commands == [
        ["git", "status", "--porcelain"],
        ["uv", "run", "briefberlin-publish-source", "private-input/source-18.txt"],
    ]
    assert runner.capture_output == [True, False]


def test_successful_publish_with_no_post_changes_skips_commit_and_push(monkeypatch, capsys):
    runner = CommandRunner([
        completed(),
        completed(stdout="Generated A2 article\n"),
        completed(),
    ])
    monkeypatch.setattr(publish_and_push, "run_command", runner)

    result = publish_and_push.main(["private-input/source-18.txt"])

    assert result == 0
    assert runner.commands == [
        ["git", "status", "--porcelain"],
        ["uv", "run", "briefberlin-publish-source", "private-input/source-18.txt"],
        ["git", "status", "--porcelain", "--", "output/_posts"],
    ]
    assert runner.capture_output == [True, False, True]
    assert "nothing to commit" in capsys.readouterr().out


def test_successful_publish_stages_posts_commits_and_pushes(monkeypatch):
    runner = CommandRunner([
        completed(),
        completed(stdout="Generated A2 article\nGenerated B1 article\n"),
        completed(stdout="Generated A2 article\nGenerated B1 article\n"),
        completed(stdout="?? output/_posts/2026-07-02-test-a2.md\n"),
        completed(),
        completed(stdout="[main abc123] Generate articles\n"),
        completed(),
    ])
    monkeypatch.setattr(publish_and_push, "run_command", runner)

    result = publish_and_push.main([
        "--remote",
        "upstream",
        "--branch",
        "main",
        "private-input/source-18.txt",
        "private-input/source-19.txt",
    ])

    assert result == 0
    assert runner.commands[:5] == [
        ["git", "status", "--porcelain"],
        [
            "uv",
            "run",
            "briefberlin-publish-source",
            "private-input/source-18.txt",
        ],
        [
            "uv",
            "run",
            "briefberlin-publish-source",
            "private-input/source-19.txt",
        ],
        ["git", "status", "--porcelain", "--", "output/_posts"],
        ["git", "add", "output/_posts"],
    ]
    assert runner.commands[5][:3] == ["git", "commit", "-m"]
    assert runner.commands[5][3].startswith("Generate articles - ")
    assert runner.commands[6] == ["git", "push", "upstream", "main"]
    assert runner.capture_output == [True, False, False, True, True, True, True]


def test_publish_timestamp_is_forwarded_and_used_for_commit_message(monkeypatch):
    runner = CommandRunner([
        completed(),
        completed(stdout="Generated A2 article\nGenerated B1 article\n"),
        completed(stdout="Generated A2 article\nGenerated B1 article\n"),
        completed(stdout="?? output/_posts/2026-07-03-test-a2.md\n"),
        completed(),
        completed(stdout="[main abc123] Generate articles\n"),
        completed(),
    ])
    monkeypatch.setattr(publish_and_push, "run_command", runner)

    result = publish_and_push.main([
        "--publish-timestamp",
        "2026-07-03T09:00:00",
        "private-input/source-21.txt",
        "private-input/source-22.txt",
    ])

    assert result == 0
    assert runner.commands[1] == [
        "uv",
        "run",
        "briefberlin-publish-source",
        "--publish-timestamp",
        "2026-07-03T09:00:00",
        "private-input/source-21.txt",
    ]
    assert runner.commands[2] == [
        "uv",
        "run",
        "briefberlin-publish-source",
        "--publish-timestamp",
        "2026-07-03T09:00:00",
        "private-input/source-22.txt",
    ]
    assert runner.commands[5] == [
        "git",
        "commit",
        "-m",
        "Generate articles - 2026-07-03 09:00 UTC",
    ]
