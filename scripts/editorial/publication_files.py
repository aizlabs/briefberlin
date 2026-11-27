"""Story-scoped Jekyll artifact validation and Git plumbing for the host publisher."""

import hashlib
import html
import os
import re
import subprocess
import unicodedata
from datetime import datetime
from pathlib import Path

import yaml

from scripts.publisher import PUBLICATION_ZONE, format_publication_date

POST = re.compile(r"output/_posts/\d{4}-\d{2}-\d{2}-([a-z0-9]+(?:-[a-z0-9]+)*)-(a2|b1)\.md")
LANG = re.compile(r"[a-z]{2,3}(?:-[A-Za-z0-9]+)*")
MAX_FILES = 128
MAX_SIZE = 2_000_000


def git(tree, *args, timeout=90, pass_fds=()):
    result = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=tree,
                            capture_output=True, timeout=timeout, pass_fds=pass_fds,
                            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if result.returncode:
        # Remote diagnostics can contain credential-bearing URLs.
        raise ValueError(f"git {args[0]} failed (exit {result.returncode})")
    return result.stdout


def names(data):
    return set(data.decode().rstrip("\0").split("\0")) if data else set()


def changes(tree):
    tracked = names(git(tree, "diff", "--name-only", "-z", "HEAD", "--"))
    untracked = names(git(tree, "ls-files", "--others", "--exclude-standard", "-z"))
    paths = tracked | untracked
    if len(paths) > MAX_FILES:
        raise ValueError("too many changed files in publication workspace")
    return paths


def read_artifact(tree, path):
    file = tree / path
    if (not path.startswith("output/") or file.resolve() != file or not file.is_file()
            or file.stat().st_size > MAX_SIZE or file.stat().st_mode & 0o111):
        raise ValueError("public artifact must be a bounded regular, non-executable file")
    return file.read_bytes()


def front(data):
    chunks = data.decode().split("---\n", 2)
    if len(chunks) != 3 or chunks[0] or not isinstance(fields := yaml.safe_load(chunks[1]), dict):
        raise ValueError("invalid article front matter")
    if any(k in fields for k in ("permalink", "slug", "published", "layout")):
        raise ValueError("unexpected canonical or rendering override")
    return fields


def artifacts(tree: Path, story: str):
    paths = changes(tree)
    files = {path: read_artifact(tree, path) for path in paths}
    editions, posts, allowed = {}, {}, set()
    for path, data in files.items():
        match = POST.fullmatch(path)
        if not match:
            continue
        fields = front(data)
        level = match[2].upper()
        if (fields.get("story") != story or fields.get("level") != level or level in editions
                or fields.get("lang", "de") != "de" or fields.get("sources")):
            raise ValueError("wrong story, level, language, sources or duplicate edition")
        ref = Path(path).stem[11:]
        canonical = f"/articles/{ref}/"
        links = fields.get("translations", {"de": canonical})
        if not isinstance(links, dict) or links.get("de") != canonical:
            raise ValueError("invalid German translation backlink")
        for lang, url in links.items():
            if lang == "de":
                continue
            translation = f"output/_translations/{ref}/{lang}.md"
            if not LANG.fullmatch(lang) or url != canonical + lang + "/" or translation not in files:
                raise ValueError("missing or misdirected translation")
            head = front(files[translation])
            if (head.get("ref"), head.get("lang"), head.get("level"), head.get("translations")) != (
                    ref, lang, level, links) or head.get("story", story) != story:
                raise ValueError("translation metadata belongs to another edition")
            allowed.add(translation)
        editions[level], posts[level] = canonical, path
        allowed.add(path)
    if set(editions) != {"A2", "B1"}:
        raise ValueError("one A2 and one B1 German post required")
    record = f"output/_data/story_illustrations/{story}.yml"
    if record in files:
        visuals = yaml.safe_load(files[record]).get("visuals")
        if not isinstance(visuals, list) or not 1 <= len(visuals) <= 3:
            raise ValueError("invalid illustration record")
        allowed.add(record)
        for index, visual in enumerate(visuals, 1):
            stem = story if index == 1 else f"{story}-{index}"
            location = visual["path"]
            if location not in {f"/assets/images/stories/{stem}.{ext}" for ext in ("svg", "webp")}:
                raise ValueError("wrong story illustration")
            allowed.add("output" + location)
    if allowed != paths:
        raise ValueError("unexpected changes or missing story assets")
    # Generated stories can only add files. Existing artifacts and canonical routes
    # (including older dated filenames) are owned by their original publication.
    existing = names(git(tree, "ls-tree", "-r", "-z", "--name-only", "HEAD", "output"))
    if paths & existing or any(
        Path(path).stem[11:] in {Path(p).stem[11:] for p in posts.values()}
        for path in existing if "/_posts/" in path and path.endswith(".md")
    ):
        raise ValueError("artifact or edition URL already exists in base commit")
    return {"story_id": story, "editions": editions,
            "files": {path: hashlib.sha256(data).hexdigest() for path, data in files.items()}}, posts


def source_urls(text):
    return {u.rstrip(".,;:!?)]}’”'") for u in re.findall(r"""https?://[^\s<>"']+""", html.unescape(text))}


def protect_text(public, source, directory=None):
    """Catch source addresses and long contiguous passages, permitting short factual quotations."""
    public = html.unescape(public)
    if any(u in public for u in source_urls(source)) or any(
        p in public for p in (".source.txt", "private-input/", "input/private/", ".publisher/")
    ) or (directory and str(directory) in public):
        raise ValueError("private evidence URL or path in public content")

    def tokens(text):
        return re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text).casefold())

    # Frozen automatic evidence includes JSON-escaped quotes and line breaks.
    words = tokens(source.replace(r"\n", " ").replace(r"\t", " "))
    width = 16
    runs = {tuple(words[i:i + width]) for i in range(len(words) - width + 1)}
    words = tokens(public)
    if any(tuple(words[i:i + width]) in runs for i in range(len(words) - width + 1)):
        raise ValueError("extended verbatim private evidence passage in public content")


def ensure_private(tree, manifest, source):
    for path in manifest["files"]:
        raw = read_artifact(tree, path)
        protect_text(raw.decode(errors="ignore" if path.endswith(".webp") else "strict"), source, tree)


def check_story_in_base(tree, story_id):
    # Narrow by literal id, then inspect the actual YAML field. Git grep exits 1 for no match.
    result = subprocess.run(["git", "grep", "-l", "-z", "-F", "-e", story_id, "HEAD", "--",
                             "output/_posts/*.md"], cwd=tree, capture_output=True, timeout=60)
    if result.returncode not in (0, 1):
        raise ValueError("unable to inspect current main for the story identity")
    for object_name in names(result.stdout):
        data = git(tree, "show", object_name).decode().split("---\n", 2)
        if len(data) == 3 and (yaml.safe_load(data[1]) or {}).get("story") == story_id:
            raise ValueError("story identifier already present on main")


def restamp(tree, manifest, posts, when=None):
    # Preserve the :title slug and all reciprocal translation/media URLs across midnight.
    when = (when or datetime.now(PUBLICATION_ZONE)).astimezone(PUBLICATION_ZONE)
    stamp = format_publication_date(when)
    for path in manifest["files"]:
        if path not in posts.values() and not path.startswith("output/_translations/"):
            continue
        src = tree / path
        _, header, body = src.read_text().split("---\n", 2)
        header, count = re.subn(r"^date:[^\n]*$", "date: " + stamp, header, flags=re.M)
        if count != 1:
            raise ValueError("missing or duplicate publication date")
        dest = src.with_name(when.strftime("%Y-%m-%d") + src.name[10:]) if path in posts.values() else src
        if dest != src and dest.exists():
            raise ValueError("restamped filename collision")
        dest.write_text("---\n" + header + "---\n" + body)
        if dest != src:
            src.unlink()


def verify_commit(tree, commit, manifest, *, delta=False):
    files = manifest["files"]
    if delta:
        lines = git(tree, "diff-tree", "--no-commit-id", "-r", "--name-status", "-z",
                    "--no-renames", commit + "^", commit).decode().rstrip("\0").split("\0")
        if (len(lines) != 2 * len(files) or set(lines[::2]) != {"A"}
                or set(lines[1::2]) != set(files)):
            raise ValueError("committed delta differs from publication manifest")
    for path, digest in files.items():
        entry = git(tree, "ls-tree", "-z", commit, "--", path)
        if not entry.startswith(b"100644 blob ") or hashlib.sha256(git(tree, "show", commit + ":" + path)).hexdigest() != digest:
            raise ValueError("commit lacks expected regular blob")
