#!/usr/bin/env python3
"""Turn a maker's published GitHub release into a catalog bump pull request.

The hourly poller (scripts/poll-releases.py) and `farm release` both run this
module, so a maker gets the same answer whichever one they use. Every number
written into a manifest is measured here from the bytes GitHub serves; a
checksum or size from release notes is never trusted.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import json
import re
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .farm import FarmError, MAX_DOWNLOAD, VERSION, _version, app_id, open_url

FARM_REPO = "Titanium-Devops/tiinyapp-farm"
GITHUB_API = "https://api.github.com"
BRANCH_PREFIX = "farm-release/"
TAG = re.compile(r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
REPO_URL = re.compile(r"https://github\.com/([A-Za-z0-9][A-Za-z0-9._-]*)/([A-Za-z0-9][A-Za-z0-9._-]*?)(?:\.git)?/?\Z")
ARCHIVE_URL = re.compile(r"https://github\.com/[^/]+/[^/]+/archive/refs/tags/(.+)\.tar\.gz\Z")
ASSET_URL = re.compile(r"https://github\.com/[^/]+/[^/]+/releases/download/([^/]+)/(.+)\Z")


def today():
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def serialize(manifest):
    """The catalog's on-disk shape: two-space JSON, unescaped text, one newline."""
    return json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"


class GitHub:
    """The slice of GitHub's REST API the release path uses."""

    def __init__(self, token, api=GITHUB_API, opener=None):
        if not token:
            raise FarmError("No GitHub token. Sign in with gh auth login, or set GITHUB_TOKEN.")
        self.token = token
        self.api = api.rstrip("/")
        self.opener = opener or urlopen
        self.calls = []

    def __call__(self, method, path, body=None, allow=()):
        self.calls.append((method, path))
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {**({"Authorization": "Bearer " + self.token} if self.token else {}),
                   "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "tiinyapp-farm/" + _version()}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(self.api + path, data=data, headers=headers, method=method)
        try:
            with self.opener(request, timeout=60) as response:
                raw = response.read(8 * 1024 * 1024)
        except HTTPError as error:
            with error:
                if error.code in allow:
                    return None
                detail = ""
                try:
                    detail = str(json.loads(error.read(65536)).get("message", ""))[:200]
                except Exception:  # the body is optional and may be anything
                    pass
            raise FarmError(f"GitHub answered {error.code} for {method} {path}"
                            + (": " + detail if detail else "")) from None
        except URLError as error:
            raise FarmError(f"Could not reach GitHub: {error.reason}") from None
        return json.loads(raw) if raw.strip() else {}

    def public(self):
        """The same client with no credential, for a maker's own public repository."""
        clone = GitHub.__new__(GitHub)
        clone.token, clone.api, clone.opener, clone.calls = None, self.api, self.opener, self.calls
        return clone

    def paged(self, path):
        items = []
        for page in range(1, 11):
            joiner = "&" if "?" in path else "?"
            batch = self("GET", "{}{}per_page=100&page={}".format(path, joiner, page))
            if not isinstance(batch, list) or not batch:
                break
            items.extend(batch)
            if len(batch) < 100:
                break
        return items


def gh_token():
    """The maker's own GitHub login, read from the gh CLI they already use."""
    try:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        raise FarmError("The gh command is not available. Install GitHub CLI and run gh auth login.") from None
    token = result.stdout.strip()
    if result.returncode != 0 or not token:
        raise FarmError("gh is not signed in. Run gh auth login, then try again.")
    return token


def gh_login(api):
    user = api("GET", "/user")
    login = user.get("login") if isinstance(user, dict) else None
    if not isinstance(login, str) or not login:
        raise FarmError("GitHub did not say who you are signed in as.")
    return login


def parse_tag(tag):
    found = TAG.fullmatch(tag.strip()) if isinstance(tag, str) else None
    return tuple(int(part) for part in found.groups()) if found else None


def parse_version(version):
    found = VERSION.fullmatch(version) if isinstance(version, str) else None
    return tuple(int(part) for part in found.groups()) if found else None


def repo_path(url):
    found = REPO_URL.fullmatch(url.strip()) if isinstance(url, str) else None
    if not found:
        raise FarmError("Release tracking needs a github.com repository URL in the manifest.")
    return found.group(1) + "/" + found.group(2)


def pick_release(releases, prereleases=False):
    """The highest three-number tag GitHub has published, drafts always excluded."""
    best = None
    for release in releases if isinstance(releases, list) else []:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        if release.get("prerelease") and not prereleases:
            continue
        version = parse_tag(release.get("tag_name", ""))
        if version is None:
            continue
        if best is None or version > best[0]:
            best = (version, release)
    return best if best else (None, None)


def tarball_assets(release):
    return [asset for asset in release.get("assets", []) or []
            if isinstance(asset, dict) and isinstance(asset.get("browser_download_url"), str)
            and isinstance(asset.get("name"), str) and asset["name"].endswith((".tar.gz", ".tgz"))]


def pick_url(manifest, repo, release, old_version, new_version):
    """Keep the kind of archive the listing already serves: source or built asset."""
    current = manifest.get("release", {}).get("url", "") if isinstance(manifest.get("release"), dict) else ""
    assets = tarball_assets(release)
    source = "https://github.com/{}/archive/refs/tags/{}.tar.gz".format(repo, quote(release["tag_name"], safe=""))
    if not current:
        return assets[0]["browser_download_url"] if len(assets) == 1 else source
    if ARCHIVE_URL.fullmatch(current):
        return source
    found = ASSET_URL.fullmatch(current)
    if not found:
        raise FarmError("The listed archive is not a GitHub release asset or source archive, "
                        "so this app needs a hand-written update.")
    wanted = found.group(2).replace(old_version, new_version) if old_version else ""
    for asset in assets:
        if asset["name"] == wanted:
            return asset["browser_download_url"]
    if len(assets) == 1:
        return assets[0]["browser_download_url"]
    raise FarmError("Release {} has no tar.gz asset named {}.".format(release["tag_name"], wanted or "(unknown)"))


def measure(url, opener=None):
    """Download the archive and report its own checksum and exact size."""
    opener = opener or open_url
    digest = hashlib.sha256()
    size = 0
    first = b""
    with opener(url) as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            if len(first) < 2:
                first = (first + chunk)[:2]
            size += len(chunk)
            if size > MAX_DOWNLOAD:
                raise FarmError("The release archive exceeds the 512 MiB limit.")
            digest.update(chunk)
    if first[:2] != b"\x1f\x8b":
        raise FarmError("That release link did not return a gzip archive.")
    return digest.hexdigest(), size


def bumped(manifest, version, url, sha256, size, day=None):
    updated = json.loads(json.dumps(manifest))
    release = updated.get("release") if isinstance(updated.get("release"), dict) else {}
    updated["version"] = version
    updated["release"] = dict(release, url=url, sha256=sha256, size=size)
    updated["updatedAt"] = day or today()
    return updated


class Outcome:
    """What a check found, in the words the maker reads."""

    def __init__(self, status, message, version=None, manifest=None, pr=None):
        self.status = status
        self.opened = False
        self.message = message
        self.version = version
        self.manifest = manifest
        self.pr = pr

    def __repr__(self):
        return "Outcome({!r}, {!r}, version={!r}, pr={!r})".format(
            self.status, self.message, self.version, self.pr)


def releases(api, repo):
    """A maker's repository is public and the farm app is not installed on it, so a
    credential that GitHub refuses there is dropped rather than reported as a failure."""
    path = "/repos/{}/releases".format(repo)
    try:
        return api.paged(path)
    except FarmError:
        return api.public().paged(path)


def plan(api, manifest, opener=None, day=None):
    """Compare the listing with GitHub and measure the new archive if there is one."""
    listed = manifest.get("version")
    if manifest.get("updates") == "manual":
        return Outcome("manual", "this app is set to manual updates, so the farm leaves its version alone", listed)
    if not manifest.get("repo"):
        return Outcome("untracked", "this app has no GitHub repository in its manifest", listed)
    repo = repo_path(manifest["repo"])
    version, release = pick_release(releases(api, repo), prereleases=manifest.get("prereleases") is True)
    current = parse_version(listed) or (0, 0, 0)
    if version is None or version < current:
        return Outcome("none", "no release newer than v{} on GitHub".format(listed), listed)
    if version == current:
        return Outcome("listed", "already listed at v{}".format(listed), listed)
    tag = ".".join(str(part) for part in version)
    url = pick_url(manifest, repo, release, listed, tag)
    checksum, size = measure(url, opener)
    return Outcome("found", "v{} found, checks running, a maintainer will review it".format(tag), tag,
                   manifest=bumped(manifest, tag, url, checksum, size, day), pr=None)


class Catalog:
    """The farm repository, written through whichever repo the actor may push to."""

    def __init__(self, api, repo=FARM_REPO):
        self.api = api
        self.repo = repo
        self.head_repo = repo
        self._base = None

    @property
    def base(self):
        if self._base is None:
            self._base = self.api("GET", "/repos/" + self.repo).get("default_branch") or "main"
        return self._base

    def ids(self):
        entries = self.api("GET", "/repos/{}/contents/manifests".format(self.repo))
        return sorted(entry["name"][:-5] for entry in entries
                      if isinstance(entry, dict) and entry.get("type") == "file"
                      and str(entry.get("name", "")).endswith(".json"))

    def manifest(self, ident, repo=None, ref=None):
        """The manifest as the repository holds it, with the blob sha needed to write it."""
        path = "/repos/{}/contents/manifests/{}.json".format(repo or self.repo, app_id(ident))
        if ref:
            path += "?ref=" + quote(ref, safe="")
        found = self.api("GET", path, allow=(404,))
        if found is None:
            return None, None
        try:
            content = base64.b64decode(found["content"].encode("ascii"))
            return json.loads(content), found["sha"]
        except (KeyError, ValueError, TypeError):
            raise FarmError("The catalog manifest for {} could not be read.".format(ident)) from None

    def use_fork(self, login):
        """A maker without push access opens the pull request from their own fork."""
        repository = self.api("GET", "/repos/" + self.repo)
        self._base = repository.get("default_branch") or "main"
        if (repository.get("permissions") or {}).get("push"):
            self.head_repo = self.repo
            return self.head_repo
        name = self.repo.split("/")[1]
        fork = "{}/{}".format(login, name)
        if self.api("GET", "/repos/" + fork, allow=(404,)) is None:
            self.api("POST", "/repos/{}/forks".format(self.repo))
            for _ in range(30):
                if self.api("GET", "/repos/" + fork, allow=(404,)) is not None:
                    break
                time.sleep(2)
            else:
                raise FarmError("GitHub is still making your fork of the catalog. Try again in a minute.")
        self.api("POST", "/repos/{}/merge-upstream".format(fork), {"branch": self.base}, allow=(409, 422))
        self.head_repo = fork
        return fork

    def open_pulls(self):
        return self.api.paged("/repos/{}/pulls?state=open".format(self.repo))

    def pull_for(self, branch):
        for pull in self.open_pulls():
            head = pull.get("head") or {}
            if head.get("ref") != branch:
                continue
            if ((head.get("repo") or {}).get("full_name") or self.repo) == self.head_repo:
                return pull
        return None

    def reset_branch(self, branch, sha):
        created = self.api("POST", "/repos/{}/git/refs".format(self.head_repo),
                           {"ref": "refs/heads/" + branch, "sha": sha}, allow=(422,))
        if created is None:
            self.api("PATCH", "/repos/{}/git/refs/heads/{}".format(self.head_repo, quote(branch, safe="/")),
                     {"sha": sha, "force": True})

    def write(self, ident, text, branch, message, sha=None):
        body = {"message": message, "branch": branch,
                "content": base64.b64encode(text.encode("utf-8")).decode("ascii")}
        if sha:
            body["sha"] = sha
        self.api("PUT", "/repos/{}/contents/manifests/{}.json".format(self.head_repo, app_id(ident)), body)

    def submit(self, ident, manifest, source, title, body, message):
        """Open one pull request per app, reusing the open one instead of stacking."""
        branch = BRANCH_PREFIX + app_id(ident)
        text = serialize(manifest)
        existing = self.pull_for(branch)
        if existing:
            current, sha = self.manifest(ident, repo=self.head_repo, ref=branch)
            if current is not None and serialize(current) == text:
                return existing["html_url"], False
            self.write(ident, text, branch, message, sha)
            self.api("PATCH", "/repos/{}/pulls/{}".format(self.repo, existing["number"]),
                     {"title": title, "body": body})
            return existing["html_url"], True
        head = self.api("GET", "/repos/{}/git/ref/heads/{}".format(self.repo, quote(self.base, safe="/")))
        self.reset_branch(branch, head["object"]["sha"])
        _, sha = self.manifest(ident, repo=self.head_repo, ref=branch)
        self.write(ident, text, branch, message, sha or source)
        reference = branch if self.head_repo == self.repo else self.head_repo.split("/")[0] + ":" + branch
        pull = self.api("POST", "/repos/{}/pulls".format(self.repo),
                        {"title": title, "body": body, "head": reference, "base": self.base,
                         "maintainer_can_modify": True})
        return pull["html_url"], True


def wording(manifest, outcome, opened_by):
    name = manifest.get("name") or manifest["id"]
    release = outcome.manifest["release"]
    title = "{} {}".format(name, outcome.version)
    body = ("{} published v{} and the catalog still listed {}.\n\n"
            "url: {}\nsha256: {}\nsize: {} bytes\n\n"
            "The checksum and the size were measured by downloading that archive here, not read "
            "from the release notes. Opened by {}.\n").format(
        manifest.get("repo", "The repository"), outcome.version, manifest["version"],
        release["url"], release["sha256"], release["size"], opened_by)
    message = ("{} {}\n\nRelease url, sha256 and size measured from the published archive.\n\n"
               "Confidence: high\nScope-risk: narrow\nTested: Archive downloaded, hashed and sized\n"
               "Not-tested: Awaiting CI and maintainer review\n").format(name, outcome.version)
    return title, body, message


def check(catalog, ident, opener=None, day=None, opened_by="the farm's release poller", submit=True):
    """One app, end to end: compare, measure, and open or refresh its bump pull request."""
    manifest, source = catalog.manifest(ident)
    if manifest is None:
        raise FarmError("{} is not in the catalog.".format(ident))
    outcome = plan(catalog.api, manifest, opener=opener, day=day)
    if outcome.status != "found" or not submit:
        return outcome
    title, body, message = wording(manifest, outcome, opened_by)
    outcome.pr, outcome.opened = catalog.submit(ident, outcome.manifest, source, title, body, message)
    return outcome
