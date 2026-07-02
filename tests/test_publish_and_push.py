import pytest

from scripts import publish_and_push


class CommandRunner:
    def __init__(self, responses):
        self.responses = list(responses)
        self.commands = []

    def __call__(self, command):
        self.commands.append(list(command))
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
    assert "nothing to commit" in capsys.readouterr().out


def test_successful_publish_stages_posts_commits_and_pushes(monkeypatch):
    runner = CommandRunner([
        completed(),
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
    assert runner.commands[:4] == [
        ["git", "status", "--porcelain"],
        [
            "uv",
            "run",
            "briefberlin-publish-source",
            "private-input/source-18.txt",
            "private-input/source-19.txt",
        ],
        ["git", "status", "--porcelain", "--", "output/_posts"],
        ["git", "add", "output/_posts"],
    ]
    assert runner.commands[4][:3] == ["git", "commit", "-m"]
    assert runner.commands[4][3].startswith("Generate articles - ")
    assert runner.commands[5] == ["git", "push", "upstream", "main"]
