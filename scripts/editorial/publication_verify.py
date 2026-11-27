"""Read-only remote and Pages verification. Unknown outcomes always retain the fence."""

import json
import re
import subprocess
from html.parser import HTMLParser
from urllib.request import Request, urlopen

from . import publication_host as host
from .publication_files import git, verify_commit

SITE = "https://briefberlin.de"
GITHUB_REPO = "aizlabs/briefberlin"
SHA = re.compile(r"[a-f0-9]{40}(?:[a-f0-9]{24})?")


def public(path):
    url = SITE + path
    with urlopen(Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "BriefBerlin verifier"}),
                 timeout=15) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError("canonical page or deployment marker redirected")
        data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise ValueError("public response too large")
        return data.decode()


def api(path):
    result = subprocess.run(["gh", "api", f"repos/{GITHUB_REPO}/{path}"], capture_output=True,
                            text=True, timeout=30)
    if result.returncode:
        raise ValueError("GitHub deployment API unavailable")
    return json.loads(result.stdout)


class Identity(HTMLParser):
    def __init__(self):
        super().__init__()
        self.articles = []
        self.canonicals = []

    def handle_starttag(self, tag, attrs):
        item = dict(attrs)
        if tag == "article" and "data-briefberlin-story" in item:
            self.articles.append((item["data-briefberlin-story"], item.get("data-briefberlin-level")))
        if tag == "link" and "canonical" in item.get("rel", "").lower().split():
            self.canonicals.append(item.get("href"))


def verify(tree, expected, manifest):
    remote = host.fetch()
    deployed = public("/briefberlin-deployment.txt").strip()
    if not SHA.fullmatch(deployed):
        raise ValueError("no deployed commit identity")
    git(tree, "merge-base", "--is-ancestor", expected, deployed)
    git(tree, "merge-base", "--is-ancestor", deployed, remote)
    verify_commit(tree, expected, manifest, delta=True)
    verify_commit(tree, deployed, manifest)
    deployments = api("deployments?environment=github-pages&sha=" + deployed + "&per_page=10")
    if not any(d.get("sha") == deployed and d.get("environment") == "github-pages"
               and type(d.get("id")) is int and any(
                   status.get("state") == "success" for status in api(f"deployments/{d['id']}/statuses")
               ) for d in deployments):
        raise ValueError("successful Pages deployment missing for served commit")
    for level, path in manifest["editions"].items():
        page = Identity()
        page.feed(public(path))
        if page.articles != [(manifest["story_id"], level)] or page.canonicals != [SITE + path]:
            raise ValueError("canonical page identity mismatch")
    if public("/briefberlin-deployment.txt").strip() != deployed:
        raise ValueError("Pages deployment changed during verification")
    return f"verified main {remote}, Pages {deployed}, manifest and both canonical identities"
