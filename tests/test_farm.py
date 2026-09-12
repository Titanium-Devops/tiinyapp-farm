import contextlib
import copy
from email.parser import BytesParser
from email.policy import default as email_policy
import getpass
import hashlib
from http.client import BadStatusLine, IncompleteRead
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from farm.farm import Farm, FarmError, main

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_manifest", ROOT / "scripts/check-manifest.py")
assert spec is not None and spec.loader is not None
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)

FAKE_APP = '''import json, os, signal, time
from pathlib import Path
root = Path(os.environ["FARM_DATA_DIR"])
root.joinpath("environment.json").write_text(json.dumps({k: os.environ.get(k) for k in
    ("FARM_DATA_DIR", "TIINY_DATA_DIR", "ONELANE_DIR", "TIINY_BASE", "TIINY_KEY", "TIINY_HOST")}))
print("ready", flush=True)
signal.signal(signal.SIGINT, lambda *_: exit(0))
while True: time.sleep(0.1)
'''


class FarmAPIHandler(BaseHTTPRequestHandler):
    requests = None

    def reply(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def record(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.requests.append((self.command, self.path, dict(self.headers), body))
        return body

    def do_POST(self):
        self.record()
        if self.path == "/api/media":
            self.reply({"url": f"/media/{len([r for r in self.requests if r[1] == '/api/media'])}.png"}, 201)
        elif self.path == "/api/seeds":
            self.reply({"id": "tiny-tool", "prUrl": "https://github.test/pull/9", "statusUrl": "/account/"}, 201)
        else:
            self.reply({"error": "not found"}, 404)

    def do_PUT(self):
        self.record()
        self.reply({"id": "tiny-tool", "prUrl": "https://github.test/pull/10", "statusUrl": "/account/"})

    def do_GET(self):
        self.record()
        if self.path == "/api/seeds/mine":
            self.reply({"seeds": [{"id": "tiny-tool", "state": "awaiting review",
                                    "checks": [{"name": "Manifest checks", "status": "success"}],
                                    "reviews": ["APPROVED"]}]})
        else:
            self.reply({"error": "not found"}, 404)

    def log_message(self, *args):
        pass


@contextlib.contextmanager
def fake_farm_api():
    requests = []
    handler = type("BoundFarmAPIHandler", (FarmAPIHandler,), {"requests": requests})
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    except PermissionError:
        # Some test sandboxes prohibit even loopback binds. Keep the same request-level
        # fake so archive and HTTP contract coverage remains available there.
        def open_request(request, timeout=60):
            path = urlsplit(request.full_url).path
            method = request.get_method()
            headers = {key.title(): value for key, value in request.header_items()}
            requests.append((method, path, headers, request.data or b""))
            if path == "/api/media":
                payload = {"url": f"/media/{len([r for r in requests if r[1] == '/api/media'])}.png"}
            elif path == "/api/seeds/mine":
                payload = {"seeds": [{"id": "tiny-tool", "state": "awaiting review",
                                      "checks": [{"name": "Manifest checks", "status": "success"}],
                                      "reviews": ["APPROVED"]}]}
            else:
                payload = {"id": "tiny-tool", "prUrl": "https://github.test/pull/9",
                           "statusUrl": "/account/"}
            return io.BytesIO(json.dumps(payload).encode())

        with patch("farm.farm.urlopen", side_effect=open_request):
            yield "http://farm.test", requests
        return
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def multipart_parts(headers, body):
    message = BytesParser(policy=email_policy).parsebytes(
        ("Content-Type: " + headers["Content-Type"] + "\r\nMIME-Version: 1.0\r\n\r\n").encode() + body)
    return {part.get_param("name", header="content-disposition"):
            (part.get_filename(), part.get_payload(decode=True)) for part in message.iter_parts()}


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / "manifests/titanium-tiiny-bot.json").read_text())
        self.manifest["release"]["sha256"] = "pending"
        self.manifest["description"] = "Release pending publication."

    def test_catalog_manifests(self):
        paths = sorted((ROOT / "manifests").glob("*.json"))
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(path=path.name):
                validator.check_manifest(json.loads(path.read_text()), allow_pending=True)

    def test_pending_requires_explicit_flag(self):
        with self.assertRaisesRegex(ValueError, "allow-pending"):
            validator.check_manifest(self.manifest)
        self.manifest["release"]["sha256"] = "a" * 64
        validator.check_manifest(self.manifest)

    def test_sprouting_manifest_still_requires_other_fields(self):
        del self.manifest['release']
        self.manifest['description'] = 'A seed taking shape.'
        validator.check_manifest(self.manifest)
        for field in ('entry', 'version', 'requires', 'author'):
            with self.subTest(field=field):
                manifest = copy.deepcopy(self.manifest)
                del manifest[field]
                with self.assertRaises(ValueError):
                    validator.check_manifest(manifest)
        for release in (None, {}, {'url': 'https://example.com/seed.tar.gz'}):
            with self.subTest(release=release), self.assertRaises(ValueError):
                validator.check_manifest(dict(self.manifest, release=release))

    def test_validator_cli(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "pending.json"
            self.manifest["description"] = "Release pending publication."
            path.write_text(json.dumps(self.manifest))
            command = [sys.executable, str(ROOT / "scripts/check-manifest.py"), str(path)]
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 1)
            self.assertEqual(subprocess.run(command + ["--allow-pending"], capture_output=True).returncode, 0)

    def test_invalid_manifest_fields(self):
        cases = [("id", "tiiny"), ("id", "../oops"), ("id", "Upper"), ("id", "valid-id\n"), ("pitch", "line\n"),
                 ("version", "1.2"), ("version", "01.2.3"), ("version", "1.2.3\n"),
                 ("pitch", "two\nlines"), ("verified", "yes"),
                 ("addedAt", "2026-02-30"), ("updatedAt", "yesterday"),
                 ("homepage", "https://"), ("permissions", ["shell"]),
                 ("permissions", ["files", "files"]), ("entry", {"python": "lite"}),
                 ("entry", {"python": "lite", "args": [], "command": "oops"})]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                manifest = copy.deepcopy(self.manifest)
                manifest[key] = value
                with self.assertRaises(ValueError):
                    validator.check_manifest(manifest, allow_pending=True)

    def test_required_unknown_types_and_ranges(self):
        changes = [lambda m: m.pop("author"), lambda m: m.update(unexpected=True),
                   lambda m: m["requires"].update(ports=[True]),
                   lambda m: m["requires"].update(ports=[65536]),
                   lambda m: m["requires"]["device"].update(npuUnits=-1),
                   lambda m: m["release"].update(size=True),
                   lambda m: m["release"].update(sha256="broken"),
                   lambda m: m.update(entry=None)]
        for change in changes:
            manifest = copy.deepcopy(self.manifest)
            change(manifest)
            with self.assertRaises(ValueError):
                validator.check_manifest(manifest, allow_pending=True)

    def test_pending_must_be_explained(self):
        self.manifest["description"] = "No release explanation."
        with self.assertRaisesRegex(ValueError, "explain"):
            validator.check_manifest(self.manifest, allow_pending=True)


class PublishTests(unittest.TestCase):
    TOKEN = "farm_" + "a" * 40

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="farm-publish-test-")
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.project.joinpath("farm.json").write_text(json.dumps({
            "id": "tiny-tool", "name": "Tiny Tool", "pitch": "Does one useful thing",
            "description": "A complete description.", "version": "0.1.0", "license": "MIT",
            "category": "developer-tools", "entry": None, "permissions": ["network"],
            "links": {"repo": "https://example.org/source"},
            "media": {"icon": "icon.png", "screenshots": ["screen.jpg"]},
        }))
        self.project.joinpath("app.py").write_text("print('hello')\n")
        self.project.joinpath("icon.png").write_bytes(b"png")
        self.project.joinpath("screen.jpg").write_bytes(b"jpeg")
        for excluded in (".git", "node_modules", "__pycache__", ".venv"):
            folder = self.project / excluded
            folder.mkdir()
            folder.joinpath("secret.txt").write_text("excluded")

    def tearDown(self):
        self.temporary.cleanup()

    def test_login_saves_private_token_and_token_priority(self):
        farm = Farm(self.root / "config", api_origin="http://example.test")
        with patch("farm.farm.getpass.getpass", return_value=self.TOKEN):
            farm.login()
        token_path = self.root / "config/token"
        self.assertEqual(token_path.read_text().strip(), self.TOKEN)
        if os.name != "nt":
            self.assertEqual(token_path.stat().st_mode & 0o777, 0o600)
        other = "farm_" + "b" * 40
        with patch.dict(os.environ, {"FARM_TOKEN": other}):
            self.assertEqual(farm.token(), other)
            self.assertEqual(farm.token(self.TOKEN), self.TOKEN)

    def test_publish_rejects_unknown_manifest_fields_and_invalid_shapes(self):
        farm = Farm(self.root / "config", api_origin="http://example.test")
        original = json.loads(self.project.joinpath("farm.json").read_text())
        cases = [dict(original, unexpected=True), dict(original, category="tools"),
                 dict(original, entry={"python": "bad-module", "args": []}),
                 dict(original, media={"gallery": ["screen.jpg"]})]
        for manifest in cases:
            with self.subTest(manifest=manifest):
                self.project.joinpath("farm.json").write_text(json.dumps(manifest))
                with self.assertRaises(FarmError):
                    farm.publish(self.project, token=self.TOKEN)
        self.project.joinpath("farm.json").write_text(json.dumps(original))

    def test_publish_uploads_media_and_packs_project(self):
        output = io.StringIO()
        with fake_farm_api() as (origin, requests), contextlib.redirect_stdout(output):
            Farm(self.root / "config", api_origin=origin).publish(self.project, token=self.TOKEN)
        self.assertEqual([(method, path) for method, path, _, _ in requests],
                         [("POST", "/api/media"), ("POST", "/api/media"), ("POST", "/api/seeds")])
        self.assertTrue(all(headers["Authorization"] == "Bearer " + self.TOKEN for _, _, headers, _ in requests))
        parts = multipart_parts(requests[-1][2], requests[-1][3])
        self.assertEqual(parts["archive"][0], "tiny-tool-0.1.0.tar.gz")
        self.assertEqual(parts["tags"][1], b"developer-tools")
        self.assertEqual(json.loads(parts["media"][1]), {"icon": "/media/1.png", "gallery": ["/media/2.png"]})
        with tarfile.open(fileobj=io.BytesIO(parts["archive"][1]), mode="r:gz") as archive:
            names = archive.getnames()
        self.assertIn("app.py", names)
        self.assertIn("farm.json", names)
        self.assertFalse(any(part in name.split("/") for name in names for part in (".git", "node_modules", "__pycache__", ".venv")))
        self.assertIn("Pull request: https://github.test/pull/9", output.getvalue())
        self.assertIn("Your apps: " + origin + "/account/", output.getvalue())

    def test_update_and_remote_status(self):
        output = io.StringIO()
        with fake_farm_api() as (origin, requests), contextlib.redirect_stdout(output):
            farm = Farm(self.root / "config", api_origin=origin)
            farm.publish(self.project, token=self.TOKEN, update=True)
            farm.submission_status("tiny-tool", token=self.TOKEN)
        self.assertIn(("PUT", "/api/seeds/tiny-tool"), [(method, path) for method, path, _, _ in requests])
        self.assertIn(("GET", "/api/seeds/mine"), [(method, path) for method, path, _, _ in requests])
        self.assertIn("tiny-tool: awaiting review", output.getvalue())
        self.assertIn("Manifest checks: success", output.getvalue())
        self.assertIn("Review: approved", output.getvalue())

    def test_publish_refuses_oversize_file_before_network(self):
        self.project.joinpath("large.bin").write_bytes(b"123456")
        farm = Farm(self.root / "config", api_origin="http://127.0.0.1:1")
        with patch("farm.farm.MAX_PUBLISH", 5), self.assertRaisesRegex(FarmError, "exceeds 50 MB"):
            farm.publish(self.project, token=self.TOKEN)


class FarmTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="farm-test-")
        self.root = Path(self.temp.name)
        self.home = self.root / "tiinyapps"
        self.catalog = self.root / "catalog"
        self.catalog.mkdir()
        self.farm = Farm(self.home, self.catalog)
        self.app = self.home / "fake-app"
        self.manifest = json.loads((ROOT / "manifests/titanium-tiiny-bot.json").read_text())
        self.manifest.update(id="fake-app", name="Fake app", version="0.1.0",
                             entry={"python": "fake", "args": []})
        self.manifest["requires"]["python"] = "3.9"
        self.manifest["requires"]["ports"] = []
        self.manifest.pop("health", None)
        self.output = io.StringIO()
        self.redirect = contextlib.redirect_stdout(self.output)
        self.redirect.__enter__()
        self.make_release()

    def tearDown(self):
        try:
            self.farm.stop("fake-app")
        finally:
            self.redirect.__exit__(None, None, None)
            self.temp.cleanup()

    def make_release(self, version="0.1.0", code=FAKE_APP, members=None, wrapper=True):
        self.manifest["version"] = version
        archive = self.catalog / f"fake-{version}.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            if members is None:
                members = [(f"fake-{version}/fake.py" if wrapper else "fake.py", code.encode(), None)]
            for name, payload, kind in members:
                info = tarfile.TarInfo(name)
                if kind is not None:
                    info.type = kind
                    info.linkname = "/tmp/farm-should-never-write"
                else:
                    info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload) if kind is None else None)
        self.manifest["release"] = {"url": archive.as_uri(),
                                    "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                                    "size": archive.stat().st_size}
        self.save_manifest()
        return archive

    def save_manifest(self):
        (self.catalog / "fake-app.json").write_text(json.dumps(self.manifest))

    def install(self):
        self.farm.install("fake-app", yes=True)

    def wait_for(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.02)
        self.fail("Timed out waiting for app evidence")

    def test_local_catalog_install(self):
        self.install()
        self.assertEqual((self.app / "current").read_text().strip(), "0.1.0")
        self.assertTrue((self.app / "0.1.0/fake.py").is_file())
        self.assertTrue((self.app / "data").is_dir())
        self.assertEqual(json.loads((self.app / "launcher.json").read_text())["entry"], self.manifest["entry"])
        self.assertFalse((self.app / "farm.pid").exists())

    def test_sprouting_seed_lists_but_refuses_install_without_download(self):
        del self.manifest['release']
        self.save_manifest()
        self.farm.list()
        self.assertIn('fake-app 0.1.0', self.output.getvalue())
        self.assertIn('[No release yet]', self.output.getvalue())
        with patch.object(self.farm, 'download') as download:
            with self.assertRaisesRegex(FarmError, 'has no release'):
                self.install()
        download.assert_not_called()
        self.assertFalse((self.app / 'current').exists())

    def test_explicit_invalid_release_is_not_sprouting(self):
        for release in (None, {}):
            self.manifest['release'] = release
            self.save_manifest()
            with self.subTest(release=release), self.assertRaisesRegex(FarmError, 'release URL'):
                self.farm.list()

    def test_install_prompt_once_and_decline(self):
        with patch("builtins.input", return_value="n") as prompt:
            self.farm.install("fake-app")
        prompt.assert_called_once()
        self.assertFalse((self.app / "current").exists())
        with patch("builtins.input", return_value="yes") as prompt:
            self.farm.install("fake-app")
        prompt.assert_called_once()
        self.assertIn("Permissions:", self.output.getvalue())
        self.assertIn("Needs:", self.output.getvalue())

    def test_bad_checksum_never_unpacks(self):
        self.manifest["release"]["sha256"] = "0" * 64
        self.save_manifest()
        with patch.object(self.farm, "unpack", side_effect=AssertionError("unpack called")):
            with self.assertRaisesRegex(FarmError, "Checksum mismatch"):
                self.install()
        self.assertFalse(self.app.exists())

    def test_bad_size_refused(self):
        self.manifest["release"]["size"] += 1
        self.save_manifest()
        with self.assertRaisesRegex(FarmError, "size"):
            self.install()

    def test_pending_cannot_be_installed(self):
        self.manifest["release"]["sha256"] = "pending"
        self.save_manifest()
        with self.assertRaisesRegex(FarmError, "pending"):
            self.install()

    def test_archive_traversal_and_links_refused(self):
        for name, kind in [("../../escape", None), ("/absolute", None), ("C:/escape", None), ("file:stream", None),
                           ("fake/symlink", tarfile.SYMTYPE), ("fake/hardlink", tarfile.LNKTYPE),
                           ("fake/fifo", tarfile.FIFOTYPE)]:
            with self.subTest(name=name):
                self.make_release(members=[(name, b"x", kind)])
                with self.assertRaisesRegex(FarmError, "Unsafe archive"):
                    self.install()
                self.assertFalse((self.app / "current").exists())
        self.assertFalse((self.root / "escape").exists())

    def test_windows_archive_path_aliases_are_refused(self):
        for name in (".. /escape", "NUL", "folder/con.txt", "name."):
            with self.subTest(name=name):
                archive = self.make_release(members=[(name, b"x", None)])
                destination = self.root / "unpacked"
                destination.mkdir(exist_ok=True)
                with patch("farm.farm.WINDOWS", True), self.assertRaisesRegex(FarmError, "Unsafe archive"):
                    Farm.unpack(archive, destination, self.manifest["entry"])

    def test_archive_limit(self):
        with patch("farm.farm.MAX_UNPACKED", 1):
            with self.assertRaisesRegex(FarmError, "extraction limits"):
                self.install()

    def test_flat_archive(self):
        self.make_release(wrapper=False)
        self.install()
        self.assertTrue((self.app / "0.1.0/fake.py").exists())

    def test_bare_package_archive(self):
        self.manifest["entry"] = {"python": "lite", "args": []}
        self.make_release(members=[("lite/__main__.py", FAKE_APP.encode(), None)])
        self.install()
        self.assertTrue((self.app / "0.1.0/lite/__main__.py").exists())

    def test_start_status_stop_and_environment(self):
        self.install()
        (self.home / "device.json").write_text(json.dumps({"base": "http://example.test:8800/v1", "key": "private-key"}))
        self.farm.start("fake-app")
        pid = int((self.app / "farm.pid").read_text())
        self.assertEqual(self.farm.active("fake-app"), pid)
        self.wait_for(lambda: "ready" in (self.app / "farm.log").read_text())
        env = json.loads((self.app / "data/environment.json").read_text())
        self.assertEqual(env["TIINY_DATA_DIR"], str(self.app / "data"))
        self.assertEqual(env["TIINY_BASE"], "http://example.test:8800/v1")
        self.assertEqual(env["TIINY_HOST"], "example.test")
        self.assertEqual(env["TIINY_KEY"], "private-key")
        self.assertEqual(env["ONELANE_DIR"], str(self.home / ".onelane"))
        self.farm.status()
        self.assertIn(f"fake-app {pid} -", self.output.getvalue())
        self.assertNotIn("private-key", self.output.getvalue())
        self.farm.start("fake-app")
        self.assertEqual(int((self.app / "farm.pid").read_text()), pid)
        self.farm.stop("fake-app")
        self.assertIsNone(self.farm.active("fake-app"))
        self.assertFalse((self.app / "farm.pid").exists())

    @unittest.skipIf(os.name == "nt", "Windows terminate does not send POSIX signals")
    def test_sigkill_after_five_seconds(self):
        code = FAKE_APP.replace('signal.signal(signal.SIGINT, lambda *_: exit(0))',
                                'signal.signal(signal.SIGINT, signal.SIG_IGN)')
        self.make_release(code=code)
        self.install()
        self.farm.start("fake-app")
        self.wait_for(lambda: (self.app / "data/environment.json").exists())
        start = time.monotonic()
        self.farm.stop("fake-app")
        self.assertGreaterEqual(time.monotonic() - start, 5)
        self.assertLess(time.monotonic() - start, 8)
        self.assertIsNone(self.farm.active("fake-app"))

    def test_failed_start_cleans_pid(self):
        self.make_release(code="raise SystemExit(2)\n")
        self.install()
        with self.assertRaisesRegex(FarmError, "exited at startup"):
            self.farm.start("fake-app")
        self.assertFalse((self.app / "farm.pid").exists())

    def test_stale_pid_does_not_signal_unrelated_process(self):
        self.install()
        (self.app / "farm.pid").write_text(str(os.getpid()))
        with patch("farm.farm.os.killpg", create=True) as kill:
            self.farm.stop("fake-app")
        kill.assert_not_called()
        self.assertFalse((self.app / "farm.pid").exists())

    def test_update_keeps_data_and_old_release(self):
        self.install()
        data = self.app / "data/keep.txt"
        data.write_text("precious")
        self.farm.start("fake-app")
        self.make_release("0.1.1", code=FAKE_APP + "# version two\n")
        self.farm.install("fake-app", yes=True, update=True)
        self.assertEqual(data.read_text(), "precious")
        self.assertEqual((self.app / "current").read_text().strip(), "0.1.1")
        self.assertTrue((self.app / "0.1.0/fake.py").exists())
        self.assertIsNone(self.farm.active("fake-app"))
        self.farm.start("fake-app")
        self.assertIsNotNone(self.farm.active("fake-app"))

    def test_failed_update_keeps_running_app(self):
        self.install()
        self.farm.start("fake-app")
        pid = self.farm.active("fake-app")
        self.make_release("0.1.1")
        self.manifest["release"]["sha256"] = "0" * 64
        self.save_manifest()
        with self.assertRaisesRegex(FarmError, "Checksum"):
            self.farm.install("fake-app", yes=True, update=True)
        self.assertEqual(self.farm.active("fake-app"), pid)
        self.assertEqual((self.app / "current").read_text().strip(), "0.1.0")

    def test_same_or_older_version_does_not_install(self):
        self.install()
        with patch.object(self.farm, "download", side_effect=AssertionError("download called")):
            self.farm.install("fake-app", yes=True, update=True)
            self.manifest["version"] = "0.0.9"
            self.save_manifest()
            self.farm.install("fake-app", yes=True, update=True)
        self.assertEqual((self.app / "current").read_text().strip(), "0.1.0")

    def test_remove_keeps_data_then_purge(self):
        self.install()
        (self.app / "data/keep.txt").write_text("precious")
        self.farm.start("fake-app")
        self.farm.remove("fake-app")
        self.assertEqual(list(self.app.iterdir()), [self.app / "data"])
        self.assertEqual((self.app / "data/keep.txt").read_text(), "precious")
        self.farm.remove("fake-app", purge=True)
        self.assertFalse(self.app.exists())

    def test_reinstall_preserves_retained_data(self):
        self.install()
        (self.app / "data/keep.txt").write_text("precious")
        self.farm.remove("fake-app")
        self.install()
        self.assertEqual((self.app / "data/keep.txt").read_text(), "precious")

    def test_library_installs_but_will_not_start(self):
        self.manifest.update(entry=None, tags=["library"])
        self.save_manifest()
        self.install()
        with self.assertRaisesRegex(FarmError, "library"):
            self.farm.start("fake-app")

    def test_command_entry(self):
        self.manifest["entry"] = {"command": "python3 fake.py"}
        self.save_manifest()
        self.install()
        self.farm.start("fake-app")
        self.assertIsNotNone(self.farm.active("fake-app"))

    def test_catalog_list(self):
        self.install()
        self.farm.list()
        self.assertIn("Installed:", self.output.getvalue())
        self.assertIn("Catalog:", self.output.getvalue())
        self.assertIn("fake-app 0.1.0", self.output.getvalue())

    def test_device_config_hidden_and_private(self):
        with patch("getpass.getpass", side_effect=["http://example.test/v1", "secret-value"]) as prompt:
            self.farm.device()
        self.assertEqual(prompt.call_count, 2)
        config = self.home / "device.json"
        if os.name != "nt":
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(config.read_text())["key"], "secret-value")
        self.assertNotIn("secret-value", self.output.getvalue())
        config.chmod(0o644)
        with patch("getpass.getpass", side_effect=["http://example.test/v1", "new-secret"]):
            self.farm.device()
        if os.name != "nt":
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)

    def test_device_refuses_echo_fallback(self):
        def unsafe(prompt):
            import warnings
            warnings.warn("Cannot control echo", getpass.GetPassWarning)
            self.fail("Echo fallback reached")
        with patch("getpass.getpass", side_effect=unsafe):
            with self.assertRaises(getpass.GetPassWarning):
                self.farm.device()
        self.assertFalse((self.home / "device.json").exists())

    def test_story_lantern_adapter(self):
        self.app.mkdir(parents=True)
        env = self.farm.environment("fake-app", self.manifest)
        self.assertNotIn("LANTERN_HOME", {k: v for k, v in env.items() if k == "LANTERN_HOME"})
        story = json.loads((ROOT / "manifests/story-lantern.json").read_text())
        (self.home / "story-lantern").mkdir()
        env = self.farm.environment("story-lantern", story)
        self.assertEqual(env["LANTERN_HOME"], str(self.home / "story-lantern/data"))
        self.assertEqual(env["PORT"], "8420")

    def test_removing_library_preserves_shared_lock_directory(self):
        self.install()
        self.farm.environment("fake-app", self.manifest)
        shared = self.home / ".onelane/device.lock"
        shared.write_text("shared inode")
        inode = shared.stat().st_ino
        library = self.home / "onelane"
        library.mkdir()
        (library / "data").mkdir()
        self.farm.remove("onelane", purge=True)
        self.assertEqual(shared.stat().st_ino, inode)

    @unittest.skipIf(os.name == "nt", "POSIX fork/process group behavior")
    def test_stop_kills_forked_child_after_leader_exits(self):
        code = """import os, signal, time
from pathlib import Path
if os.fork() == 0:
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    Path(os.environ['FARM_DATA_DIR'], 'child-ready').touch()
    while True: time.sleep(0.1)
signal.signal(signal.SIGINT, lambda *_: exit(0))
while True: time.sleep(0.1)
"""
        self.make_release(code=code)
        self.install()
        self.farm.start("fake-app")
        self.wait_for(lambda: (self.app / "data/child-ready").exists())
        self.farm.stop("fake-app")
        self.assertIsNone(self.farm.active("fake-app"))

    def test_id_and_manifest_mismatch_refused(self):
        with self.assertRaises(FarmError):
            self.farm.install("../escape", yes=True)
        self.manifest["id"] = "different-app"
        self.save_manifest()
        with self.assertRaisesRegex(FarmError, "does not match"):
            self.install()

    def test_cli_local_catalog(self):
        env = os.environ | {"HOME": str(self.root), "USERPROFILE": str(self.root), "FARM_CATALOG": str(self.catalog)}
        result = subprocess.run([sys.executable, str(ROOT / "farm/farm.py"), "install", "fake-app", "--yes"],
                                env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([sys.executable, str(ROOT / "farm/farm.py"), "list"],
                                env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("fake-app", result.stdout)

    def test_separate_cli_start_status_stop(self):
        self.install()
        env = dict(os.environ, HOME=str(self.root), USERPROFILE=str(self.root))
        command = [sys.executable, str(ROOT / "farm/farm.py")]
        for args in (["start", "fake-app"], ["status"], ["stop", "fake-app"]):
            result = subprocess.run(command + args, env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            if args == ["status"]:
                self.assertIn("fake-app", result.stdout)
                self.assertIn("running 0.1.0", result.stdout)
        self.assertIsNone(self.farm.active("fake-app"))

    @unittest.skipUnless(os.name == "nt", "Windows process creation identity")
    def test_windows_reused_pid_is_not_terminated(self):
        from farm.farm import WindowsProcess
        self.install()
        with WindowsProcess(os.getpid()) as process:
            identity = process.identity
        (self.app / "farm.pid").write_text(str(os.getpid()))
        (self.app / "process.json").write_text(json.dumps({"identity": identity + 1}))
        with patch.object(WindowsProcess, "terminate") as terminate:
            self.farm.stop("fake-app")
        terminate.assert_not_called()

    def test_local_catalog_file_uri(self):
        farm = Farm(self.home, self.catalog.as_uri())
        self.assertEqual(farm.manifest("fake-app")["id"], "fake-app")

    def test_windows_lock_uses_same_byte_and_releases(self):
        from farm.farm import file_lock
        from unittest.mock import Mock
        backend = Mock(LK_NBLCK=2, LK_UNLCK=0)
        offsets = []
        with (self.root / "byte.lock").open("a+b") as lock:
            backend.locking.side_effect = lambda *args: offsets.append(lock.tell())
            with patch("farm.farm.WINDOWS", True), patch.dict(sys.modules, msvcrt=backend):
                with self.assertRaisesRegex(RuntimeError, "test"):
                    with file_lock(lock):
                        raise RuntimeError("test")
        self.assertEqual(offsets, [0, 0])
        self.assertEqual([call.args[1:] for call in backend.locking.call_args_list], [(2, 1), (0, 1)])

    def test_windows_private_mode_is_best_effort(self):
        from farm.farm import private_mode
        with patch("farm.farm.WINDOWS", True), patch.object(Path, "chmod", side_effect=PermissionError):
            private_mode(self.root / "settings")
        with patch("farm.farm.WINDOWS", False), patch.object(Path, "chmod", side_effect=PermissionError):
            with self.assertRaises(PermissionError):
                private_mode(self.root / "settings")

    def test_default_device_path_and_legacy_read(self):
        with patch("farm.farm.Path.home", return_value=self.root):
            farm = Farm(catalog=self.catalog)
        self.assertEqual(farm.config_home, self.root / ".tiinyapps")
        self.install()
        self.home.joinpath("device.json").write_text(json.dumps({"base": "http://legacy.test/v1", "key": "old"}))
        self.assertEqual(farm.environment("fake-app", self.manifest)["TIINY_KEY"], "old")
        with patch.dict(os.environ, {"TIINY_KEY": "new"}):
            farm.device(base="http://new.test/v1")
        self.assertEqual(farm.environment("fake-app", self.manifest)["TIINY_KEY"], "new")
        self.assertTrue((self.root / ".tiinyapps/device.json").exists())

    def test_cli_errors_do_not_echo_keys(self):
        errors = io.StringIO()
        with patch("farm.farm.Farm.device", side_effect=ValueError("contains-secret-key")):
            with contextlib.redirect_stderr(errors):
                self.assertEqual(main(["device"]), 1)
        self.assertNotIn("contains-secret-key", errors.getvalue())

    def test_start_waits_for_declared_tcp_port(self):
        self.manifest['requires']['ports'] = [43210]
        self.save_manifest()
        self.install()
        with patch('farm.farm.socket.create_connection', side_effect=[
                ConnectionRefusedError(), ConnectionRefusedError(), contextlib.nullcontext()]) as connect:
            self.farm.start('fake-app')
        self.assertEqual(connect.call_count, 3)
        self.assertIn('Started fake-app', self.output.getvalue())

    def test_busy_port_never_launches_or_claims_started(self):
        self.manifest['requires']['ports'] = [43210]
        self.save_manifest()
        self.install()
        with patch('farm.farm.socket.create_connection', return_value=contextlib.nullcontext()):
            with patch('farm.farm.subprocess.Popen') as spawn:
                with self.assertRaisesRegex(FarmError, 'already in use'):
                    self.farm.start('fake-app')
        spawn.assert_not_called()
        self.assertNotIn('Started', self.output.getvalue())
        self.assertFalse((self.app / 'farm.pid').exists())

    def test_start_timeout_reports_last_ten_log_lines_and_cleans_up(self):
        self.manifest['requires']['ports'] = [43210]
        self.make_release(code='\n'.join(f'print("line-{i}", flush=True)' for i in range(20)) + '\n' + FAKE_APP)
        self.install()
        with patch('farm.farm.socket.create_connection', side_effect=ConnectionRefusedError()):
            with patch('farm.farm.START_TIMEOUT', 0.5):
                with self.assertRaisesRegex(FarmError, 'timed out') as error:
                    self.farm.start('fake-app')
        self.assertIn('line-19', str(error.exception))
        self.assertNotIn('line-9\n', str(error.exception))
        self.assertEqual(len(str(error.exception).splitlines()[1:]), 10)
        self.assertIsNone(self.farm.active('fake-app'))
        self.assertFalse((self.app / 'process.json').exists())
        self.assertNotIn('Started', self.output.getvalue())

    def test_delayed_exit_is_not_success(self):
        self.manifest['requires']['ports'] = [43210]
        self.make_release(code='import time\ntime.sleep(0.3)\nprint("bind failed", flush=True)\nraise SystemExit(2)\n')
        self.install()
        with patch('farm.farm.socket.create_connection', side_effect=ConnectionRefusedError()):
            with self.assertRaisesRegex(FarmError, 'bind failed'):
                self.farm.start('fake-app')
        self.assertNotIn('Started', self.output.getvalue())
        self.assertFalse((self.app / 'farm.pid').exists())

    def test_health_retries_and_status_uses_live_version_and_override(self):
        self.manifest['requires']['ports'] = [43210]
        self.manifest['health'] = '/api/health'
        self.save_manifest()
        self.install()
        with patch('farm.farm.socket.create_connection', side_effect=ConnectionRefusedError()):
            with patch('farm.farm.urlopen', side_effect=[
                    OSError(), io.BytesIO(b'{"version":"0.1.0"}')]) as request:
                self.farm.start('fake-app', port=43211)
        self.assertEqual(request.call_args.args[0], 'http://127.0.0.1:43211/api/health')
        info = json.loads((self.app / 'process.json').read_text())
        self.assertEqual(info['ports'], [43211])
        with patch('farm.farm.urlopen', return_value=io.BytesIO(b'{"version":"0.0.9"}')):
            self.farm.status()
        self.assertIn('43211', self.output.getvalue())
        self.assertIn('running 0.0.9, installed 0.1.0: restart to update', self.output.getvalue())
        with patch('farm.farm.urlopen', side_effect=OSError()):
            self.farm.status()
        self.assertIn('health unavailable', self.output.getvalue())

    def test_port_override_reaches_child(self):
        self.make_release(code='import os\nprint("port=" + os.environ["TIINYAPP_PORT"], flush=True)\n' + FAKE_APP)
        self.install()
        with patch('farm.farm.socket.create_connection', side_effect=[
                ConnectionRefusedError(), contextlib.nullcontext()]):
            self.farm.start('fake-app', port=43211)
        self.wait_for(lambda: 'port=43211' in (self.app / 'farm.log').read_text())

    def test_invalid_port_and_health_are_rejected(self):
        from farm.farm import validate_manifest
        for port in (0, -1, 65536, True):
            with self.subTest(port=port), self.assertRaises(FarmError):
                self.farm.start('fake-app', port=port)
        for health in ('https://example.com', '//example.com', '/bad?key=x', '/bad\npath', True):
            manifest = copy.deepcopy(self.manifest)
            manifest['health'] = health
            with self.subTest(health=health), self.assertRaises(FarmError):
                validate_manifest(manifest, 'fake-app')

    def test_start_cli_failure_exits_one_with_log_tail(self):
        self.make_release(code='print("startup exploded", flush=True)\nraise SystemExit(2)\n')
        self.install()
        result = subprocess.run([sys.executable, str(ROOT / 'farm/farm.py'), 'start', 'fake-app'],
                                env=os.environ | {'HOME': str(self.root), 'USERPROFILE': str(self.root)}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('startup exploded', result.stderr)
        self.assertNotIn('Started', result.stdout)
        self.assertFalse((self.app / 'farm.pid').exists())

    def test_lite_override_replaces_manifest_argument_and_sets_both_env_vars(self):
        self.install()
        lite = copy.deepcopy(self.manifest)
        lite['id'] = 'titanium-tiiny-bot'
        lite['entry']['args'] = ['--port', '7788']
        lite['requires']['ports'] = [7788]
        root = self.app / '0.1.0'
        root.joinpath('fake.py').write_text('import os, sys\nprint(sys.argv[1:])\n'
                                          'print(os.environ["TIINYAPP_PORT"], os.environ["TIINY_PORT"])\n' + FAKE_APP)
        with patch.object(self.farm, 'installed', return_value=(root, lite)), \
                patch.object(self.farm, 'app_dir', return_value=self.app), \
                patch('farm.farm.socket.create_connection', side_effect=[
                    ConnectionRefusedError(), contextlib.nullcontext()]):
            self.farm.start('titanium-tiiny-bot', port=7790)
        self.wait_for(lambda: 'ready' in (self.app / 'farm.log').read_text())
        self.assertIn("['--port', '7790']", (self.app / 'farm.log').read_text())
        self.assertIn('7790 7790', (self.app / 'farm.log').read_text())

    def test_cli_port_option_dispatches_to_start(self):
        with patch('farm.farm.Farm', return_value=self.farm), patch.object(self.farm, 'start') as start:
            self.assertEqual(main(['start', 'fake-app', '--port', '43211']), 0)
        start.assert_called_once_with('fake-app', port=43211)

    def test_status_legacy_record_uses_manifest_health(self):
        self.install()
        self.farm.start('fake-app')
        installed = self.app / '0.1.0/.farm-manifest.json'
        manifest = json.loads(installed.read_text())
        manifest.update(health='/api/health')
        manifest['requires']['ports'] = [43210]
        installed.write_text(json.dumps(manifest))
        info = json.loads((self.app / 'process.json').read_text())
        info.pop('health', None)
        info['ports'] = [43211]
        (self.app / 'process.json').write_text(json.dumps(info))
        with patch('farm.farm.urlopen', return_value=io.BytesIO(b'{"version":"0.0.9"}')):
            self.farm.status()
        self.assertIn('running 0.0.9, installed 0.1.0: restart to update', self.output.getvalue())

    def test_health_invalid_responses_are_not_ready(self):
        for body in (b'bad json', b'[]', b'{"ok":false}', b'{"version":'):
            with self.subTest(body=body), patch('farm.farm.urlopen', return_value=io.BytesIO(body)):
                self.assertIsNone(self.farm.health(43210, '/api/health'))

    def test_all_declared_ports_must_be_ready(self):
        self.manifest['requires']['ports'] = [43210, 43211]
        self.save_manifest()
        self.install()
        calls = []

        def probe(address, timeout):
            calls.append(address[1])
            if len(calls) <= 2 or (len(calls) == 4):
                raise ConnectionRefusedError()
            return contextlib.nullcontext()

        with patch('farm.farm.socket.create_connection', side_effect=probe):
            self.farm.start('fake-app')
        self.assertEqual(calls, [43210, 43211, 43210, 43211, 43210, 43211])

    def test_broken_http_response_retries_instead_of_crashing(self):
        for error in (BadStatusLine("bad status"), IncompleteRead(b"partial")):
            with self.subTest(error=error), patch('farm.farm.urlopen', side_effect=error):
                self.assertIsNone(self.farm.health(43210, '/api/health'))

    def test_startup_log_tail_preserves_ten_long_lines(self):
        self.install()
        lines = [str(i) + ':' + 'x' * 8000 for i in range(15)]
        (self.app / 'farm.log').write_text('\n'.join(lines) + '\n')
        error = self.farm.startup_error(self.app, 'failed')
        self.assertEqual(str(error).splitlines()[1:], lines[-10:])

    def test_health_trickling_response_cannot_exceed_readiness_deadline(self):
        self.manifest['requires']['ports'] = [43210]
        self.manifest['health'] = '/api/health'
        self.save_manifest()
        self.install()

        def slow_response(*args, **kwargs):
            time.sleep(0.5)
            return io.BytesIO(b'{"version":"0.1.0"}')

        with patch('farm.farm.socket.create_connection', side_effect=ConnectionRefusedError()), \
                patch('farm.farm.urlopen', side_effect=slow_response), \
                patch('farm.farm.START_TIMEOUT', 0.25):
            started = time.monotonic()
            with self.assertRaisesRegex(FarmError, 'timed out'):
                self.farm.start('fake-app')
            self.assertLess(time.monotonic() - started, 0.45)
        self.assertFalse((self.app / 'farm.pid').exists())
