"""The release-to-listing path, driven by a fake GitHub with a fake app repository.

Nothing here touches the network: every GitHub call and every archive download is
served from memory, so the poller, the pull request reuse and the measured
numbers are all checked offline.
"""
import base64
import contextlib
import copy
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from farm.farm import FarmError
from farm import release

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_manifest", ROOT / "scripts/check-manifest.py")
assert spec is not None and spec.loader is not None
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)

CATALOG = "Titanium-Devops/tiinyapp-farm"
APP_REPO = "maker/fake-app"
ARCHIVES = {
    "v0.1.0": gzip.compress(b"fake-app 0.1.0 source"),
    "v0.1.1": gzip.compress(b"fake-app 0.1.1 source, the one Tiiny 1.0 needs"),
    "v0.2.0": gzip.compress(b"fake-app 0.2.0 source"),
}
MANIFEST = {
    "id": "fake-app",
    "name": "Fake App",
    "pitch": "A stand-in app for the release path.",
    "description": "Two releases on GitHub and one manifest in the catalog.",
    "version": "0.1.0",
    "author": {"name": "A Maker", "url": "https://github.com/maker",
               "tiinyverse": "https://www.tiinyverse.com/users/39628b1e-e94e-4bd8-800e-5437d5336e1f"},
    "license": "MIT",
    "homepage": "https://github.com/maker/fake-app",
    "repo": "https://github.com/maker/fake-app",
    "screenshots": [],
    "release": {"url": "https://github.com/maker/fake-app/archive/refs/tags/v0.1.0.tar.gz",
                "sha256": hashlib.sha256(ARCHIVES["v0.1.0"]).hexdigest(),
                "size": len(ARCHIVES["v0.1.0"])},
    "entry": {"command": "python3 fake_app.py"},
    "requires": {"python": "3.9", "ports": [7788], "device": {"models": ["chat"], "npuUnits": 4}},
    "permissions": ["network", "device"],
    "tags": ["developer-tools"],
    "verified": False,
    "addedAt": "2026-09-12",
    "updatedAt": "2026-09-12",
}


def archive_url(tag):
    return "https://github.com/{}/archive/refs/tags/{}.tar.gz".format(APP_REPO, tag)


def asset_url(tag, name):
    return "https://github.com/{}/releases/download/{}/{}".format(APP_REPO, tag, name)


def github_release(tag, prerelease=False, draft=False, assets=()):
    return {"tag_name": tag, "prerelease": prerelease, "draft": draft,
            "assets": [{"name": name, "browser_download_url": asset_url(tag, name)} for name in assets],
            # Numbers a maker could put in release notes. The path must ignore them.
            "body": "sha256: " + "0" * 64}


class Hub:
    """A GitHub stand-in holding one catalog repository and one app repository."""

    def __init__(self, manifest=None, push=True, releases=None, login="maker", public_only=False):
        self.login = login
        self.push = push
        self.public_only = public_only
        self.branches = {(CATALOG, "main"): {"manifests/fake-app.json":
                                             release.serialize(manifest or MANIFEST)}}
        self.releases = list(releases if releases is not None else
                             [github_release("v0.1.0"), github_release("v0.1.1")])
        self.pulls = []
        self.forks = set()
        self.writes = []
        self.downloads = []

    # --- helpers -------------------------------------------------------
    @staticmethod
    def blob(text):
        body = text.encode("utf-8")
        return hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()

    def files(self, repo, branch):
        return self.branches.setdefault((repo, branch), {})

    def fail(self, url, code, message="failed"):
        return HTTPError(url, code, message, {}, io.BytesIO(json.dumps({"message": message}).encode()))

    def reply(self, payload):
        return io.BytesIO(json.dumps(payload).encode())

    # --- the urlopen the GitHub client is given -------------------------
    def open(self, request, timeout=None):
        method = request.get_method()
        parts = urlsplit(request.full_url)
        path, query = parts.path, parse_qs(parts.query)
        body = json.loads(request.data) if request.data else None
        credential = request.get_header("Authorization")
        if self.public_only and APP_REPO in path:
            if credential is not None:
                raise self.fail(request.full_url, 404, "Not Found")
        else:
            assert credential == "Bearer test-token", "every call is authenticated"
        if request.data:
            assert request.get_header("Content-type") == "application/json"
        payload = self.route(method, path, query, body, request.full_url)
        return io.BytesIO(json.dumps(payload).encode())

    def route(self, method, path, query, body, url):
        segments = [segment for segment in path.split("/") if segment]
        if path == "/user":
            return {"login": self.login}
        if segments[0] != "repos":
            raise self.fail(url, 404, "no such route")
        repo = "/".join(segments[1:3])
        rest = "/" + "/".join(segments[3:])
        if rest == "/":
            if repo not in (CATALOG, APP_REPO) and repo not in self.forks:
                raise self.fail(url, 404, "Not Found")
            return {"full_name": repo, "default_branch": "main",
                    "permissions": {"push": self.push or repo != CATALOG}}
        if rest == "/releases":
            return self.releases if repo == APP_REPO else []
        if rest == "/forks" and method == "POST":
            self.forks.add("{}/{}".format(self.login, repo.split("/")[1]))
            return {"full_name": "{}/{}".format(self.login, repo.split("/")[1])}
        if rest == "/merge-upstream" and method == "POST":
            return {"merge_type": "fast-forward"}
        if rest == "/contents/manifests":
            return [{"type": "file", "name": name.split("/")[-1]}
                    for name in sorted(self.files(repo, "main"))]
        if rest.startswith("/contents/manifests/"):
            name = rest[len("/contents/"):]
            branch = (query.get("ref") or [body.get("branch") if body else "main"])[0]
            files = self.files(repo, branch)
            if method == "GET":
                if name not in files:
                    raise self.fail(url, 404, "Not Found")
                return {"sha": self.blob(files[name]),
                        "content": base64.b64encode(files[name].encode("utf-8")).decode("ascii")}
            if method == "PUT":
                text = base64.b64decode(body["content"]).decode("utf-8")
                if name in files and body.get("sha") != self.blob(files[name]):
                    raise self.fail(url, 409, "does not match")
                files[name] = text
                self.writes.append((repo, branch, name, body["message"]))
                return {"content": {"sha": self.blob(text)}}
        if rest.startswith("/git/ref/heads/"):
            branch = rest[len("/git/ref/heads/"):]
            if (repo, branch) not in self.branches:
                raise self.fail(url, 404, "Not Found")
            return {"object": {"sha": "a" * 40}}
        if rest == "/git/refs" and method == "POST":
            branch = body["ref"][len("refs/heads/"):]
            if (repo, branch) in self.branches:
                raise self.fail(url, 422, "Reference already exists")
            self.branches[(repo, branch)] = dict(self.files(CATALOG, "main"))
            return {"ref": body["ref"]}
        if rest.startswith("/git/refs/heads/") and method == "PATCH":
            branch = rest[len("/git/refs/heads/"):]
            self.branches[(repo, branch)] = dict(self.files(CATALOG, "main"))
            return {"ref": "refs/heads/" + branch}
        if rest == "/pulls" and method == "GET":
            page = int(query.get("page", ["1"])[0])
            return [pull for pull in self.pulls if pull["state"] == "open"] if page == 1 else []
        if rest == "/pulls" and method == "POST":
            owner, _, branch = body["head"].rpartition(":")
            head_repo = "{}/{}".format(owner, repo.split("/")[1]) if owner else repo
            pull = {"number": len(self.pulls) + 1, "state": "open", "title": body["title"],
                    "body": body["body"], "base": {"ref": body["base"]},
                    "head": {"ref": branch, "repo": {"full_name": head_repo}},
                    "html_url": "https://github.com/{}/pull/{}".format(repo, len(self.pulls) + 1)}
            self.pulls.append(pull)
            return pull
        if rest.startswith("/pulls/") and method == "PATCH":
            pull = self.pulls[int(rest.split("/")[2]) - 1]
            pull.update({key: body[key] for key in ("title", "body") if key in body})
            return pull
        raise self.fail(url, 404, "unexpected route " + method + " " + path)

    # --- the archive downloader ----------------------------------------
    def download(self, url, timeout=None):
        self.downloads.append(url)
        for tag, data in ARCHIVES.items():
            if url in (archive_url(tag), asset_url(tag, "fake-app-" + tag[1:] + ".tar.gz")):
                return io.BytesIO(data)
        raise FarmError("HTTP 404 from github.com")

    def catalog(self):
        api = release.GitHub("test-token", opener=self.open)
        return release.Catalog(api, CATALOG)

    def listed(self, branch="main"):
        return json.loads(self.files(CATALOG, branch)["manifests/fake-app.json"])


def run(hub, ident="fake-app", **kwargs):
    catalog = hub.catalog()
    kwargs.setdefault("opener", hub.download)
    kwargs.setdefault("day", "2026-09-13")
    return release.check(catalog, ident, **kwargs)


class PollerTests(unittest.TestCase):
    def test_one_pull_request_for_a_newer_release_with_measured_numbers(self):
        hub = Hub()
        outcome = run(hub)
        self.assertEqual(outcome.status, "found")
        self.assertEqual(outcome.message, "v0.1.1 found, checks running, a maintainer will review it")
        self.assertEqual(len(hub.pulls), 1)
        self.assertEqual(hub.pulls[0]["head"]["ref"], "farm-release/fake-app")
        self.assertEqual(hub.pulls[0]["base"]["ref"], "main")
        written = json.loads(hub.files(CATALOG, "farm-release/fake-app")["manifests/fake-app.json"])
        self.assertEqual(written["version"], "0.1.1")
        self.assertEqual(written["updatedAt"], "2026-09-13")
        self.assertEqual(written["release"]["url"], archive_url("v0.1.1"))
        self.assertEqual(written["release"]["sha256"], hashlib.sha256(ARCHIVES["v0.1.1"]).hexdigest())
        self.assertEqual(written["release"]["size"], len(ARCHIVES["v0.1.1"]))
        self.assertEqual(hub.downloads, [archive_url("v0.1.1")])
        # main is untouched until a maintainer merges.
        self.assertEqual(hub.listed()["version"], "0.1.0")

    def test_maker_supplied_numbers_are_never_copied(self):
        hub = Hub(releases=[github_release("v0.1.0"), github_release("v0.1.1")])
        written = run(hub).manifest
        self.assertNotEqual(written["release"]["sha256"], "0" * 64)
        self.assertEqual(written["release"]["sha256"], hashlib.sha256(ARCHIVES["v0.1.1"]).hexdigest())

    def test_the_bumped_manifest_still_passes_the_submission_schema(self):
        written = run(Hub()).manifest
        validator.check_manifest(written)

    def test_a_listed_release_opens_nothing(self):
        manifest = copy.deepcopy(MANIFEST)
        manifest["version"] = "0.1.1"
        manifest["release"] = {"url": archive_url("v0.1.1"),
                               "sha256": hashlib.sha256(ARCHIVES["v0.1.1"]).hexdigest(),
                               "size": len(ARCHIVES["v0.1.1"])}
        hub = Hub(manifest=manifest)
        outcome = run(hub)
        self.assertEqual(outcome.status, "listed")
        self.assertEqual(outcome.message, "already listed at v0.1.1")
        self.assertEqual(hub.pulls, [])
        self.assertEqual(hub.downloads, [])

    def test_no_newer_release_says_so_in_the_makers_words(self):
        hub = Hub(releases=[github_release("v0.1.0")])
        manifest = copy.deepcopy(MANIFEST)
        manifest["version"] = "0.1.1"
        hub.branches[(CATALOG, "main")]["manifests/fake-app.json"] = release.serialize(manifest)
        outcome = run(hub)
        self.assertEqual(outcome.status, "none")
        self.assertEqual(outcome.message, "no release newer than v0.1.1 on GitHub")
        self.assertEqual(hub.pulls, [])

    def test_a_repository_with_no_releases_at_all(self):
        hub = Hub(releases=[])
        self.assertEqual(run(hub).message, "no release newer than v0.1.0 on GitHub")
        self.assertEqual(hub.pulls, [])

    def test_manual_updates_and_a_missing_repo_are_left_alone(self):
        manual = copy.deepcopy(MANIFEST)
        manual["updates"] = "manual"
        hub = Hub(manifest=manual)
        self.assertEqual(run(hub).status, "manual")
        self.assertEqual(hub.pulls, [])
        without = copy.deepcopy(MANIFEST)
        del without["repo"]
        hub = Hub(manifest=without)
        self.assertEqual(run(hub).status, "untracked")
        self.assertEqual(hub.pulls, [])

    def test_prereleases_and_drafts_are_skipped_unless_the_manifest_opts_in(self):
        releases = [github_release("v0.1.0"), github_release("v0.2.0", prerelease=True),
                    github_release("v0.3.0", draft=True), github_release("v0.1.1-rc.1")]
        self.assertEqual(run(Hub(releases=releases)).message, "already listed at v0.1.0")
        opted = copy.deepcopy(MANIFEST)
        opted["prereleases"] = True
        hub = Hub(manifest=opted, releases=releases)
        outcome = run(hub)
        self.assertEqual(outcome.version, "0.2.0")
        self.assertEqual(hub.downloads, [archive_url("v0.2.0")])
        # A draft is never a candidate, even when prereleases are allowed.
        self.assertNotIn("0.3.0", outcome.message)

    def test_a_second_run_reuses_the_open_pull_request_instead_of_stacking(self):
        hub = Hub()
        first = run(hub)
        second = run(hub)
        self.assertEqual(len(hub.pulls), 1)
        self.assertEqual(second.pr, first.pr)
        self.assertTrue(first.opened)
        self.assertFalse(second.opened)
        self.assertEqual(len(hub.writes), 1, "an unchanged branch is not rewritten")

    def test_a_newer_release_refreshes_the_same_pull_request(self):
        hub = Hub()
        first = run(hub)
        hub.releases.append(github_release("v0.2.0"))
        second = run(hub)
        self.assertEqual(len(hub.pulls), 1)
        self.assertEqual(second.pr, first.pr)
        self.assertEqual(second.version, "0.2.0")
        self.assertIn("0.2.0", hub.pulls[0]["title"])
        self.assertEqual(json.loads(hub.files(CATALOG, "farm-release/fake-app")
                                    ["manifests/fake-app.json"])["version"], "0.2.0")

    def test_a_closed_pull_request_does_not_block_the_next_one(self):
        hub = Hub()
        run(hub)
        hub.pulls[0]["state"] = "closed"
        hub.releases.append(github_release("v0.2.0"))
        run(hub)
        self.assertEqual(len(hub.pulls), 2)
        self.assertEqual([pull["state"] for pull in hub.pulls], ["closed", "open"])

    def test_the_pull_request_says_where_the_numbers_came_from(self):
        hub = Hub()
        outcome = run(hub)
        pull = hub.pulls[0]
        self.assertEqual(pull["title"], "Fake App 0.1.1")
        self.assertIn(hashlib.sha256(ARCHIVES["v0.1.1"]).hexdigest(), pull["body"])
        self.assertIn(str(len(ARCHIVES["v0.1.1"])) + " bytes", pull["body"])
        self.assertIn("measured by downloading that archive here", pull["body"])
        self.assertIn("the farm's release poller", pull["body"])
        self.assertNotIn("—", pull["body"] + pull["title"] + outcome.message)

    def test_dry_run_measures_without_opening_anything(self):
        hub = Hub()
        outcome = run(hub, submit=False)
        self.assertEqual(outcome.status, "found")
        self.assertIsNone(outcome.pr)
        self.assertEqual(hub.pulls, [])

    def test_an_asset_release_keeps_the_asset_shape_and_a_source_release_keeps_its_own(self):
        packaged = copy.deepcopy(MANIFEST)
        packaged["release"]["url"] = asset_url("v0.1.0", "fake-app-0.1.0.tar.gz")
        hub = Hub(manifest=packaged, releases=[github_release("v0.1.0", assets=["fake-app-0.1.0.tar.gz"]),
                                               github_release("v0.1.1", assets=["fake-app-0.1.1.tar.gz"])])
        self.assertEqual(run(hub).manifest["release"]["url"], asset_url("v0.1.1", "fake-app-0.1.1.tar.gz"))
        hub = Hub()
        self.assertEqual(run(hub).manifest["release"]["url"], archive_url("v0.1.1"))

    def test_a_release_without_the_expected_asset_is_reported_not_guessed(self):
        packaged = copy.deepcopy(MANIFEST)
        packaged["release"]["url"] = asset_url("v0.1.0", "fake-app-0.1.0.tar.gz")
        hub = Hub(manifest=packaged, releases=[
            github_release("v0.1.0", assets=["fake-app-0.1.0.tar.gz"]),
            github_release("v0.1.1", assets=["one.tar.gz", "two.tar.gz"])])
        with self.assertRaisesRegex(FarmError, "no tar.gz asset named fake-app-0.1.1.tar.gz"):
            run(hub)
        self.assertEqual(hub.pulls, [])

    def test_a_download_that_is_not_a_gzip_archive_is_refused(self):
        hub = Hub()
        with patch.object(hub, "download", lambda url, timeout=None: io.BytesIO(b"<html>404</html>")):
            with self.assertRaisesRegex(FarmError, "did not return a gzip archive"):
                run(hub)
        self.assertEqual(hub.pulls, [])

    def test_a_repository_the_farm_app_cannot_read_is_asked_for_without_a_credential(self):
        hub = Hub(public_only=True)
        outcome = run(hub)
        self.assertEqual(outcome.status, "found")
        self.assertEqual(len(hub.pulls), 1)

    def test_a_maker_without_push_access_opens_the_request_from_a_fork(self):
        hub = Hub(push=False)
        catalog = hub.catalog()
        where = catalog.use_fork("maker")
        self.assertEqual(where, "maker/tiinyapp-farm")
        outcome = release.check(catalog, "fake-app", opener=hub.download, day="2026-09-13",
                                opened_by="a maker running farm release")
        self.assertEqual(outcome.status, "found")
        self.assertEqual(hub.pulls[0]["head"]["ref"], "farm-release/fake-app")
        self.assertEqual(hub.pulls[0]["head"]["repo"]["full_name"], "maker/tiinyapp-farm")
        self.assertEqual(hub.writes[0][0], "maker/tiinyapp-farm")
        self.assertIn("a maker running farm release", hub.pulls[0]["body"])

    def test_a_maintainer_writes_the_branch_on_the_catalog_itself(self):
        hub = Hub(push=True)
        catalog = hub.catalog()
        self.assertEqual(catalog.use_fork("webdevtodayjason"), CATALOG)
        release.check(catalog, "fake-app", opener=hub.download, day="2026-09-13")
        self.assertEqual(hub.writes[0][0], CATALOG)
        self.assertEqual(hub.forks, set())


class CommandTests(unittest.TestCase):
    def test_the_poller_checks_every_listed_app_and_reports_each_one(self):
        hub = Hub()
        poller = importlib.util.spec_from_file_location("poll_releases", ROOT / "scripts/poll-releases.py")
        module = importlib.util.module_from_spec(poller)
        poller.loader.exec_module(module)
        said = io.StringIO()
        with patch.dict("os.environ", {"GITHUB_TOKEN": "test-token"}, clear=False), \
                patch("farm.release.urlopen", hub.open), patch("farm.release.open_url", hub.download), \
                contextlib.redirect_stdout(said):
            code = module.main([])
        self.assertEqual(code, 0)
        self.assertIn("fake-app: v0.1.1 found, checks running, a maintainer will review it", said.getvalue())
        self.assertIn("https://github.com/{}/pull/1".format(CATALOG), said.getvalue())
        self.assertEqual(len(hub.pulls), 1)

    def test_the_poller_reports_an_app_it_could_not_check_and_fails_the_run(self):
        broken = copy.deepcopy(MANIFEST)
        broken["repo"] = "https://gitlab.example.com/maker/fake-app"
        hub = Hub(manifest=broken)
        poller = importlib.util.spec_from_file_location("poll_releases", ROOT / "scripts/poll-releases.py")
        module = importlib.util.module_from_spec(poller)
        poller.loader.exec_module(module)
        said, problem = io.StringIO(), io.StringIO()
        with patch.dict("os.environ", {"GITHUB_TOKEN": "test-token"}, clear=False), \
                patch("farm.release.urlopen", hub.open), patch("farm.release.open_url", hub.download), \
                contextlib.redirect_stdout(said), contextlib.redirect_stderr(problem):
            code = module.main([])
        self.assertEqual(code, 1)
        self.assertIn("could not be checked", said.getvalue())
        self.assertIn("fake-app", problem.getvalue())

    def test_farm_release_resolves_the_app_from_farm_json_and_prints_the_pull_request(self):
        import tempfile
        from farm.farm import Farm
        hub = Hub()
        with tempfile.TemporaryDirectory(prefix="farm-release-test-") as temporary:
            project = Path(temporary)
            project.joinpath("farm.json").write_text(json.dumps({"id": "fake-app"}))
            said = io.StringIO()
            with patch("farm.release.urlopen", hub.open), patch("farm.release.open_url", hub.download), \
                    patch("farm.release.gh_token", return_value="test-token"), \
                    contextlib.redirect_stdout(said):
                Farm(project).release(project=project)
        self.assertIn("fake-app: v0.1.1 found, checks running, a maintainer will review it", said.getvalue())
        self.assertIn("Pull request: https://github.com/{}/pull/1".format(CATALOG), said.getvalue())
        self.assertEqual(len(hub.pulls), 1)

    def test_farm_release_needs_an_app_name_when_there_is_no_farm_json(self):
        import tempfile
        from farm.farm import Farm
        with tempfile.TemporaryDirectory(prefix="farm-release-test-") as temporary:
            with self.assertRaisesRegex(FarmError, "Name the app"):
                Farm(Path(temporary)).release(project=Path(temporary))

    def test_gh_is_the_only_credential_farm_release_asks_for(self):
        with patch("farm.release.subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(FarmError, "gh auth login"):
                release.gh_token()


class SchemaTests(unittest.TestCase):
    def test_the_schema_rejects_an_unknown_updates_value(self):
        manifest = copy.deepcopy(MANIFEST)
        manifest["updates"] = "hourly"
        with self.assertRaisesRegex(ValueError, "updates"):
            validator.check_manifest(manifest)

    def test_the_schema_accepts_the_two_tracking_fields_and_their_defaults(self):
        manifest = copy.deepcopy(MANIFEST)
        validator.check_manifest(manifest)
        self.assertNotIn("updates", manifest)
        for value in ("auto", "manual"):
            manifest["updates"] = value
            validator.check_manifest(manifest)
        manifest["prereleases"] = True
        validator.check_manifest(manifest)
        manifest["prereleases"] = "yes"
        with self.assertRaisesRegex(ValueError, "prereleases"):
            validator.check_manifest(manifest)

    def test_the_schema_still_refuses_unknown_properties(self):
        manifest = copy.deepcopy(MANIFEST)
        manifest["updatePolicy"] = "auto"
        with self.assertRaises(ValueError):
            validator.check_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
