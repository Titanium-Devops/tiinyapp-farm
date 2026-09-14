import contextlib
import copy
from email.parser import BytesParser
from email.policy import default as email_policy
import errno
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
from unittest.mock import call, patch
from urllib.error import URLError
from urllib.parse import urlsplit

from farm.farm import DEVICE_PORT, DEVICE_PROBE, Farm, FarmError, describe_size, main

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

    def test_catalog_manifests_say_how_each_app_takes_its_port(self):
        """Read from each app's own source at its released tag on 2026-09-13."""
        expected = {'titanium-tiiny-bot': {'argv': '--port'},  # lite/server.py: --port
                    'tiiny-bench': {'argv': '--serve'},        # bench.py: --serve [PORT], default 8425
                    'story-lantern': {'env': 'PORT'},          # lantern.py: PORT, default 8420
                    'onelane': None}                           # a library with no port at all
        for ident, takes in expected.items():
            with self.subTest(app=ident):
                manifest = json.loads((ROOT / f'manifests/{ident}.json').read_text())
                self.assertEqual(manifest['port'], takes)

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
                 ("entry", {"python": "lite", "args": [], "command": "oops"}),
                 ("port", {}), ("port", {"argv": "--port", "env": "PORT"}), ("port", "PORT"),
                 ("port", {"env": "2PORT"}), ("port", {"argv": "port"})]
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

    def test_an_open_page_needs_a_declared_port(self):
        """The link farm start offers has to have a port to live on."""
        self.manifest["release"]["sha256"] = "a" * 64
        self.manifest["open"] = "/chat"
        validator.check_manifest(self.manifest)
        del self.manifest["health"]
        self.manifest["requires"]["ports"] = []
        with self.assertRaisesRegex(ValueError, r"\$\.open"):
            validator.check_manifest(self.manifest)

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
        said = io.StringIO()
        with patch("farm.farm.getpass.getpass", return_value=self.TOKEN), contextlib.redirect_stdout(said):
            farm.login()
        self.assertEqual(said.getvalue().strip(), "Farm token saved.")
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
        self.manifest.pop("port", None)  # The app the other tests use takes the default, TIINYAPP_PORT.
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

    def other_app(self, ident="other-app", version="0.1.0", install=False, notes=None):
        """A second app in the same fake catalog, so the update list has more than one row."""
        manifest = copy.deepcopy(self.manifest)
        manifest.update(id=ident, name="Other app", version=version)
        archive = self.catalog / f"{ident}-{version}.tar.gz"
        payload = FAKE_APP.encode()
        with tarfile.open(archive, "w:gz") as tar:
            info = tarfile.TarInfo(f"{ident}-{version}/fake.py")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        manifest["release"] = {"url": archive.as_uri(),
                               "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                               "size": archive.stat().st_size}
        if notes is not None:
            manifest["release"]["notes"] = notes
        (self.catalog / f"{ident}.json").write_text(json.dumps(manifest))
        if install:
            self.farm.install(ident, yes=True)
        return manifest

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
        self.assertIn("It can reach your microphone, your files, the network and your Tiiny.",
                      self.output.getvalue())
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
        """Every row carries the name, the version, the one-line summary and, once installed, whether it runs."""
        self.install()
        self.farm.list()
        printed = self.output.getvalue()
        self.assertIn("Installed:", printed)
        self.assertIn("Catalog:", printed)
        self.assertIn("  fake-app 0.1.0 Fake app [stopped] - " + self.manifest["pitch"], printed)
        self.assertIn("  fake-app 0.1.0 Fake app - " + self.manifest["pitch"], printed)

    def test_list_says_which_installed_app_is_running(self):
        self.install()
        self.farm.start("fake-app")
        self.farm.list()
        self.assertIn("  fake-app 0.1.0 Fake app [running] - ", self.output.getvalue())

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
        # The adapter carries data paths only; PORT comes from the manifest port field at start.
        self.assertEqual(env.get("PORT"), os.environ.get("PORT"))

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
        self.assertIn('Fake app is running.', self.output.getvalue())

    def test_busy_port_moves_a_movable_app_up_and_says_so(self):
        """Jason, 2026-09-14: the archiver held 8430 and farm start should have stepped off it."""
        self.manifest['requires']['ports'] = [43210]
        self.save_manifest()
        self.make_release(code='import os\nprint("port=" + os.environ["TIINYAPP_PORT"], flush=True)\n' + FAKE_APP)
        self.install()
        with patch('farm.farm.socket.create_connection', side_effect=[
                contextlib.nullcontext(), ConnectionRefusedError(), contextlib.nullcontext()]):
            self.farm.start('fake-app')
        self.assertIn('Port 43210 was busy, so it started on 43211.', self.output.getvalue())
        self.assertIn('Open http://localhost:43211', self.output.getvalue())
        self.wait_for(lambda: 'port=43211' in (self.app / 'farm.log').read_text())

    def test_busy_port_never_launches_or_claims_started(self):
        self.manifest['requires']['ports'] = [43210]
        self.manifest['port'] = None
        self.save_manifest()
        self.install()
        with patch('farm.farm.socket.create_connection', return_value=contextlib.nullcontext()):
            with patch('farm.farm.subprocess.Popen') as spawn:
                with self.assertRaisesRegex(FarmError, 'already in use'):
                    self.farm.start('fake-app')
        spawn.assert_not_called()
        self.assertNotIn('is running', self.output.getvalue())
        self.assertFalse((self.app / 'farm.pid').exists())

    def test_a_mistyped_app_id_leaves_no_lock_behind(self):
        """farm start nope used to drop a lock file in your home directory for ever."""
        # start and remove refuse an unknown app; stop reports it is not running.
        for command in ("start", "stop", "remove"):
            with contextlib.suppress(FarmError):
                getattr(self.farm, command)("never-installed")
        self.assertIn("not running", self.output.getvalue())
        leftovers = sorted(q.name for q in (self.home / ".locks").glob("*.lock"))
        self.assertEqual(leftovers, [])

    def test_an_installed_app_keeps_its_lock(self):
        self.install()
        self.farm.stop("fake-app")
        self.assertTrue((self.home / ".locks/fake-app.lock").exists())

    def test_busy_port_refusal_does_not_quote_an_older_run(self):
        """A refused port launches nothing, so farm.log still holds the run before it."""
        self.manifest['requires']['ports'] = [43210]
        self.manifest['port'] = None
        self.save_manifest()
        self.install()
        self.app.mkdir(parents=True, exist_ok=True)
        (self.app / 'farm.log').write_text('Traceback from a run that ended yesterday\n')
        with patch('farm.farm.socket.create_connection', return_value=contextlib.nullcontext()):
            with self.assertRaisesRegex(FarmError, 'already in use') as error:
                self.farm.start('fake-app')
        self.assertNotIn('yesterday', str(error.exception))

    def test_timeout_names_a_port_override_the_app_ignored(self):
        """An app that ignores TIINYAPP_PORT binds its own port and looks like a hang."""
        self.manifest['requires']['ports'] = [43210]
        self.save_manifest()
        self.install()
        ready = {43210: True, 43211: False}

        def connect(address, *_args, **_kwargs):
            if ready.get(address[1]):
                return contextlib.nullcontext()
            raise ConnectionRefusedError()

        with patch('farm.farm.socket.create_connection', side_effect=connect):
            with patch('farm.farm.START_TIMEOUT', 0.5):
                with self.assertRaisesRegex(FarmError, 'timed out') as error:
                    self.farm.start('fake-app', port=43211)
        message = str(error.exception)
        self.assertIn('never opened 43211', message)
        self.assertIn('43210', message)
        self.assertIn('TIINYAPP_PORT', message)

    def test_failed_start_points_at_farm_device_when_the_app_needs_one(self):
        """Story Lantern dies on a missing device; the log says nothing about farm device."""
        self.manifest['requires']['device'] = {'models': ['chat'], 'npuUnits': 1}
        self.make_release(code='raise SystemExit(1)\n')
        self.install()
        with self.assertRaises(FarmError) as error:
            self.farm.start('fake-app')
        self.assertIn('run farm device', str(error.exception))

    def test_failed_start_stays_quiet_about_a_device_that_is_configured(self):
        self.manifest['requires']['device'] = {'models': ['chat'], 'npuUnits': 1}
        self.make_release(code='raise SystemExit(1)\n')
        self.install()
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / 'device.json').write_text(json.dumps({'base': 'http://d/v1', 'key': 'k'}))
        with self.assertRaises(FarmError) as error:
            self.farm.start('fake-app')
        self.assertNotIn('run farm device', str(error.exception))

    def test_status_header_names_the_status_column(self):
        """The row ends with a status word, not a bare version."""
        self.install()
        self.farm.start('fake-app')
        self.farm.status()
        printed = self.output.getvalue()
        self.assertIn('APP PID PORT LINK UPTIME STATUS', printed)
        self.assertIn('running 0.1.0', printed)

    def test_install_prompt_describes_requirements_in_words(self):
        """The first thing a stranger reads should not be a JSON blob."""
        self.manifest['requires'] = {'python': '3.9', 'ports': [7788],
                                     'device': {'models': ['chat', 'tts'], 'npuUnits': 57}}
        self.save_manifest()
        self.install()
        printed = self.output.getvalue()
        self.assertIn('Needs: Python 3.9 or newer, port 7788, your Tiiny, for chat, tts, 57 NPU units',
                      printed)
        self.assertNotIn('npuUnits', printed)

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
        self.assertNotIn('is running', self.output.getvalue())

    def test_delayed_exit_is_not_success(self):
        self.manifest['requires']['ports'] = [43210]
        self.make_release(code='import time\ntime.sleep(0.3)\nprint("bind failed", flush=True)\nraise SystemExit(2)\n')
        self.install()
        with patch('farm.farm.socket.create_connection', side_effect=ConnectionRefusedError()):
            with self.assertRaisesRegex(FarmError, 'bind failed'):
                self.farm.start('fake-app')
        self.assertNotIn('is running', self.output.getvalue())
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
        self.assertNotIn('is running', result.stdout)
        self.assertFalse((self.app / 'farm.pid').exists())

    def start_with_port_field(self, ident, takes, args, port=None, ports=(7788,), code=None):
        """Start one app whose manifest says how it takes its port, and return its log."""
        self.install()
        manifest = copy.deepcopy(self.manifest)
        manifest['id'] = ident
        manifest['entry']['args'] = list(args)
        manifest['requires']['ports'] = list(ports)
        if takes is not False:
            manifest['port'] = takes
        root = self.app / '0.1.0'
        root.joinpath('fake.py').write_text(code or 'import os, sys\nprint(sys.argv[1:], flush=True)\n' + FAKE_APP)
        with patch.object(self.farm, 'installed', return_value=(root, manifest)), \
                patch.object(self.farm, 'app_dir', return_value=self.app), \
                patch('farm.farm.socket.create_connection', side_effect=[
                    ConnectionRefusedError(), contextlib.nullcontext()]):
            self.farm.start(ident, port=port)
        self.wait_for(lambda: 'ready' in (self.app / 'farm.log').read_text())
        return (self.app / 'farm.log').read_text()

    def test_argv_port_field_replaces_the_number_in_the_entry(self):
        """Lite's shape: the manifest already carries --port 7788."""
        log = self.start_with_port_field('titanium-tiiny-bot', {'argv': '--port'},
                                         ['--port', '7788'], port=7790)
        self.assertIn("['--port', '7790']", log)

    def test_argv_port_field_replaces_an_attached_number(self):
        log = self.start_with_port_field('titanium-tiiny-bot', {'argv': '--port'},
                                         ['--port=7788'], port=7790)
        self.assertIn("['--port=7790']", log)

    def test_argv_port_field_adds_the_number_when_the_entry_has_none(self):
        """TiinyBench's shape: --serve takes an optional port and the entry leaves it off."""
        log = self.start_with_port_field('tiiny-bench', {'argv': '--serve'}, ['--serve'],
                                         port=7790, ports=(8425,))
        self.assertIn("['--serve', '7790']", log)

    def test_argv_port_field_adds_the_flag_the_entry_left_out(self):
        log = self.start_with_port_field('tiiny-bench', {'argv': '--serve'}, ['--quiet'],
                                         port=7790, ports=(8425,))
        self.assertIn("['--quiet', '--serve', '7790']", log)

    def test_env_port_field_uses_the_name_the_manifest_gives(self):
        """Story Lantern's shape: the app reads PORT."""
        log = self.start_with_port_field(
            'story-lantern', {'env': 'PORT'}, [], port=7790, ports=(8420,),
            code='import os, sys\nprint(os.environ["PORT"], os.environ["TIINYAPP_PORT"], flush=True)\n' + FAKE_APP)
        self.assertIn('7790 7790', log)

    def test_a_manifest_with_no_port_field_gets_tiinyapp_port_alone(self):
        with patch.dict(os.environ, {'PORT': 'left alone'}):
            log = self.start_with_port_field(
                'fake-app', False, [], port=7790,
                code='import os, sys\nprint(os.environ["TIINYAPP_PORT"], os.environ["PORT"], flush=True)\n' + FAKE_APP)
        self.assertIn('7790 left alone', log)

    def test_a_fixed_port_refuses_to_be_moved(self):
        self.manifest['port'] = None
        self.manifest['requires']['ports'] = [8425]
        self.save_manifest()
        self.install()
        with self.assertRaises(FarmError) as error:
            self.farm.start('fake-app', port=7790)
        self.assertEqual(str(error.exception),
                         'fake-app runs on port 8425 only and cannot be moved, so start it without --port.')

    def test_a_fixed_port_in_use_is_not_told_to_use_port(self):
        self.manifest['port'] = None
        self.manifest['requires']['ports'] = [8425]
        self.save_manifest()
        self.install()
        with patch('farm.farm.socket.create_connection', return_value=contextlib.nullcontext()):
            with self.assertRaises(FarmError) as error:
                self.farm.start('fake-app')
        self.assertEqual(str(error.exception),
                         'Port 8425 is already in use, and fake-app cannot be moved off it.')
        self.assertNotIn('--port', str(error.exception))

    def test_a_movable_port_in_use_still_offers_port(self):
        self.manifest['requires']['ports'] = [8420]
        self.save_manifest()
        self.install()
        with patch('farm.farm.socket.create_connection', return_value=contextlib.nullcontext()):
            with self.assertRaises(FarmError) as error:
                self.farm.start('fake-app')
        self.assertEqual(str(error.exception),
                         'Port 8420 is already in use and nothing above it up to 8470 is free; use farm start fake-app --port N.')

    def test_invalid_port_fields_are_refused(self):
        from farm.farm import validate_manifest
        for takes in ({}, {'argv': '--port', 'env': 'PORT'}, {'argv': ''}, {'argv': 'port'},
                      {'env': '2PORT'}, {'env': ''}, {'flag': '--port'}, '--port', 7788, True):
            manifest = copy.deepcopy(self.manifest)
            manifest['port'] = takes
            with self.subTest(port=takes), self.assertRaises(FarmError):
                validate_manifest(manifest, 'fake-app')
        for takes in (None, {'argv': '--port'}, {'argv': '-p'}, {'env': 'TIINYAPP_PORT'}):
            manifest = copy.deepcopy(self.manifest)
            manifest['port'] = takes
            with self.subTest(port=takes):
                validate_manifest(manifest, 'fake-app')

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

        # The trickle is far longer than the deadline, so returning early proves the
        # CLI did not wait for it even when a busy machine adds a tenth of a second.
        def slow_response(*args, **kwargs):
            time.sleep(5)
            return io.BytesIO(b'{"version":"0.1.0"}')

        with patch('farm.farm.socket.create_connection', side_effect=ConnectionRefusedError()), \
                patch('farm.farm.urlopen', side_effect=slow_response), \
                patch('farm.farm.START_TIMEOUT', 0.25):
            started = time.monotonic()
            with self.assertRaisesRegex(FarmError, 'timed out'):
                self.farm.start('fake-app')
            self.assertLess(time.monotonic() - started, 1.0)
        self.assertFalse((self.app / 'farm.pid').exists())

    def test_install_tells_a_person_what_it_is_installing(self):
        """Jason, 2026-09-14: "It works, I guess, but it's very simplistic and not very telling.\""""
        self.install()
        printed = self.output.getvalue()
        self.assertIn("Looking up fake-app in the catalog.", printed)
        self.assertIn("Fake app 0.1.0", printed)
        self.assertIn(self.manifest["pitch"], printed)
        self.assertIn("Made by Titanium Computing. The farm has reviewed it.", printed)
        self.assertIn("Downloading " + describe_size(self.manifest["release"]["size"]), printed)
        self.assertNotIn("Downloading 0 bytes", printed)
        self.assertIn("The download matches the checksum the catalog lists.", printed)
        self.assertIn(f"Unpacking it into {self.app / '0.1.0'}.", printed)
        self.assertIn("Ready. Run: farm start fake-app", printed)
        self.assertLess(printed.index("Fake app 0.1.0"), printed.index("Downloading "))

    def test_install_names_the_download_size_a_person_can_picture(self):
        for size, said in ((480188, "480 KB"), (2349344, "2.3 MB"), (900, "900 bytes"), (0, "0 bytes")):
            with self.subTest(size=size):
                self.assertEqual(describe_size(size), said)

    def test_install_says_when_nobody_is_named_and_nothing_was_reviewed(self):
        del self.manifest["author"]
        self.manifest["verified"] = False
        self.save_manifest()
        self.install()
        self.assertIn("Its maker is not named in the catalog. The farm has not reviewed it yet.",
                      self.output.getvalue())

    def test_start_ends_with_the_link_the_pitch_and_how_to_stop_it(self):
        """The line a person wants is the link, not a process ID."""
        self.manifest["requires"]["ports"] = [43210]
        self.save_manifest()
        self.install()
        with patch("farm.farm.socket.create_connection", side_effect=[
                ConnectionRefusedError(), contextlib.nullcontext()]):
            self.farm.start("fake-app")
        said = self.output.getvalue().split("Fake app is running.")[1]
        self.assertIn("Open http://localhost:43210\n", said)
        self.assertIn(self.manifest["pitch"], said)
        self.assertIn("Stop it with: farm stop fake-app", said)
        self.assertIn(f"Log: {self.app / 'farm.log'}", said)
        self.assertLess(said.index("Open http://localhost:43210"), said.index("Stop it with"))
        self.assertLess(said.index("Stop it with"), said.index("Log: "))
        self.assertNotIn((self.app / "farm.pid").read_text().strip(), said)

    def test_an_app_already_running_is_told_where_to_open_it(self):
        self.manifest["requires"]["ports"] = [43210]
        self.save_manifest()
        self.install()
        with patch("farm.farm.socket.create_connection", side_effect=[
                ConnectionRefusedError(), contextlib.nullcontext()]):
            self.farm.start("fake-app")
        self.farm.start("fake-app")
        self.assertIn("Fake app is already running.", self.output.getvalue())
        self.assertEqual(self.output.getvalue().count("Open http://localhost:43210"), 2)

    def test_status_shows_a_link_for_every_running_app(self):
        self.manifest["requires"]["ports"] = [43210]
        self.save_manifest()
        self.install()
        with patch("farm.farm.socket.create_connection", side_effect=[
                ConnectionRefusedError(), contextlib.nullcontext()]):
            self.farm.start("fake-app")
        self.farm.status()
        self.assertIn("APP PID PORT LINK UPTIME STATUS", self.output.getvalue())
        self.assertRegex(self.output.getvalue(),
                         r"fake-app \d+ 43210 http://localhost:43210 \d+s running 0\.1\.0")

    def test_the_open_field_names_the_first_page_and_a_health_probe_is_not_one(self):
        self.manifest["requires"]["ports"] = [43210]
        self.manifest["health"] = "/api/health"
        self.manifest["open"] = "/chat"
        self.save_manifest()
        self.install()
        with patch("farm.farm.socket.create_connection", side_effect=ConnectionRefusedError()), \
                patch("farm.farm.urlopen", side_effect=lambda *a, **k: io.BytesIO(b'{"version":"0.1.0"}')):
            self.farm.start("fake-app")
        self.assertIn("Open http://localhost:43210/chat", self.output.getvalue())
        self.assertNotIn("localhost:43210/api/health", self.output.getvalue())

    def test_invalid_open_pages_are_refused(self):
        from farm.farm import validate_manifest
        self.manifest["requires"]["ports"] = [43210]
        for page in ("https://example.com", "//example.com", "/bad?q=x", "/bad\npath", True, "chat", ""):
            manifest = copy.deepcopy(self.manifest)
            manifest["open"] = page
            with self.subTest(open=page), self.assertRaises(FarmError):
                validate_manifest(manifest, "fake-app")
        for page in ("/", "/chat", "/ui/index.html"):
            manifest = copy.deepcopy(self.manifest)
            manifest["open"] = page
            with self.subTest(open=page):
                validate_manifest(manifest, "fake-app")
        without_a_port = copy.deepcopy(self.manifest)
        without_a_port["requires"]["ports"] = []
        without_a_port["open"] = "/chat"
        with self.assertRaises(FarmError):
            validate_manifest(without_a_port, "fake-app")

    def test_a_library_says_what_to_import_instead_of_a_command(self):
        self.manifest.update(entry=None, tags=["library"])
        self.make_release(members=[("fake-0.1.0/fake-app.py", b"# a library\n", None)])
        self.install()
        printed = self.output.getvalue()
        self.assertIn("Ready. Fake app is a library, so there is nothing to start.", printed)
        self.assertIn(f"Copy fake-app.py out of {self.app / '0.1.0'} into your own app", printed)
        self.assertNotIn("farm start", printed)

    def test_a_library_with_no_file_of_its_own_name_points_at_its_directory(self):
        self.manifest.update(entry=None, tags=["library"])
        self.make_release(members=[("fake-0.1.0/inner/thing.py", b"# a library\n", None)])
        self.install()
        self.assertIn(f"Its files are in {self.app / '0.1.0'}; import what you need from there.",
                      self.output.getvalue())

    def test_device_names_the_apps_that_will_use_it_and_how_to_try_one(self):
        self.install()
        with patch("getpass.getpass", side_effect=["http://example.test/v1", "secret-value"]):
            self.farm.device()
        printed = self.output.getvalue()
        self.assertIn("These installed apps will use it: fake-app.", printed)
        self.assertIn("Try it now: farm start fake-app", printed)
        self.assertNotIn("secret-value", printed)

    def test_device_with_nothing_installed_points_at_the_catalog(self):
        with patch("getpass.getpass", side_effect=["http://example.test/v1", "secret-value"]):
            self.farm.device()
        self.assertIn("No app you have installed uses your Tiiny yet.", self.output.getvalue())

    def test_no_consumer_line_carries_a_word_only_a_maker_needs(self):
        """Jason, 2026-09-14: no pids in the headline, no argv, no manifest on a consumer line."""
        self.manifest["requires"]["ports"] = [43210]
        self.save_manifest()
        self.install()
        with patch("farm.farm.socket.create_connection", side_effect=[
                ConnectionRefusedError(), contextlib.nullcontext()]):
            self.farm.start("fake-app")
        self.farm.status()
        self.farm.list()
        for word in ("argv", "manifest", "Manifest", "pid "):
            with self.subTest(word=word):
                self.assertNotIn(word, self.output.getvalue())

    def configure_device(self, base="http://172.17.7.177/v1"):
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "device.json").write_text(json.dumps({"base": base, "key": "device-key"}))

    def test_a_blocked_local_network_is_named_after_a_start(self):
        """Jason, 2026-09-14: under miniconda Python the app saw nothing on the LAN at all, while
        the same code under Homebrew Python found his Tiiny in 5 ms."""
        self.configure_device()
        self.install()
        with patch("farm.farm.urlopen",
                   side_effect=URLError(OSError(errno.EHOSTUNREACH, "No route to host"))) as probe:
            self.farm.start("fake-app")
        printed = self.output.getvalue()
        self.assertIn("Fake app is running.", printed)
        self.assertIn("macOS is blocking this Python from your local network.", printed)
        self.assertIn("System Settings, Privacy and Security, Local Network, turn on Python,"
                      " then farm stop and farm start again.", printed)
        self.assertEqual(probe.call_args.args[0], f"http://172.17.7.177:{DEVICE_PORT}/device.json")

    def test_a_tiiny_that_answers_says_nothing_about_privacy(self):
        self.configure_device()
        self.install()
        with patch("farm.farm.urlopen", return_value=io.BytesIO(b'{"name":"tiiny"}')):
            self.farm.start("fake-app")
        self.assertNotIn("macOS is blocking", self.output.getvalue())

    def test_a_refused_connection_is_not_a_blocked_network(self):
        """A Tiiny that is switched off refuses the connection; privacy never enters into it."""
        self.configure_device()
        self.install()
        with patch("farm.farm.urlopen",
                   side_effect=URLError(OSError(errno.ECONNREFUSED, "Connection refused"))):
            self.farm.start("fake-app")
        self.assertNotIn("macOS is blocking", self.output.getvalue())

    def test_an_address_off_the_local_network_is_never_blamed_on_privacy(self):
        self.configure_device("http://93.184.216.34/v1")
        self.install()
        with patch("farm.farm.urlopen",
                   side_effect=URLError(OSError(errno.EHOSTUNREACH, "No route to host"))):
            self.farm.start("fake-app")
        self.assertNotIn("macOS is blocking", self.output.getvalue())

    def test_no_device_configured_is_never_probed(self):
        self.install()
        with patch.dict(os.environ), patch("farm.farm.urlopen",
                                           side_effect=AssertionError("probed with no device")) as probe:
            os.environ.pop("TIINY_BASE", None)
            self.farm.start("fake-app")
        probe.assert_not_called()
        self.assertIn("Fake app is running.", self.output.getvalue())

    def test_a_probe_that_breaks_never_fails_the_start(self):
        self.configure_device()
        self.install()
        with patch.object(self.farm, "probe_local_network", side_effect=RuntimeError("probe exploded")):
            self.farm.start("fake-app")
        self.assertIn("Fake app is running.", self.output.getvalue())
        self.assertNotIn("probe exploded", self.output.getvalue())
        self.assertIsNotNone(self.farm.active("fake-app"))

    def test_device_says_when_macos_is_blocking_the_local_network(self):
        with patch("getpass.getpass", side_effect=["http://172.17.7.177/v1", "secret-value"]), \
                patch("farm.farm.urlopen",
                      side_effect=URLError(OSError(errno.EHOSTUNREACH, "No route to host"))):
            self.farm.device()
        printed = self.output.getvalue()
        self.assertIn("Device settings saved.", printed)
        self.assertIn("macOS is blocking this Python from your local network.", printed)
        self.assertNotIn("secret-value", printed)

    def test_an_app_on_another_python_is_probed_with_that_python(self):
        """The CLI and the app can be two binaries, and macOS grants the local network one at a time."""
        answer = json.dumps({"errno": errno.EHOSTUNREACH, "address": "172.17.7.177"})
        done = subprocess.CompletedProcess([], 0, answer, "")
        with patch("farm.farm.subprocess.run", return_value=done) as child:
            refused, address = self.farm.probe_local_network("172.17.7.177", "/opt/conda/bin/python3")
        self.assertTrue(refused)
        self.assertEqual(address, "172.17.7.177")
        self.assertEqual(child.call_args.args[0][0], "/opt/conda/bin/python3")
        self.assertEqual(child.call_args.args[0][3], "172.17.7.177")

    def test_the_probe_source_runs_and_answers_in_json(self):
        """Nothing listens on the device port here, so the answer is a refusal, not a block."""
        done = subprocess.run([sys.executable, "-c", DEVICE_PROBE, "127.0.0.1", str(DEVICE_PORT), "2.0"],
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        answer = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertEqual(answer["address"], "127.0.0.1")
        self.assertNotEqual(answer["errno"], errno.EHOSTUNREACH)

    def test_update_with_no_id_lists_the_one_app_that_has_a_newer_version(self):
        """Jason, 2026-09-14: "'Check updates' would come back with a list of all the apps that have been updated.\""""
        self.install()
        self.make_release("0.1.1")
        with patch("farm.farm.interactive", return_value=False):
            self.farm.update()
        printed = self.output.getvalue()
        self.assertIn("Looking up the app you have installed in the catalog.", printed)
        self.assertIn("1. Fake app 0.1.0, 0.1.1 is out", printed)
        self.assertNotIn("2. Other app", printed)

    def test_update_with_no_id_numbers_every_app_that_has_one(self):
        self.install()
        self.other_app(install=True)
        self.make_release("0.1.1")
        self.other_app(version="0.1.2")
        with patch("farm.farm.interactive", return_value=False):
            self.farm.update()
        printed = self.output.getvalue()
        self.assertIn("Looking up all 2 apps you have installed in the catalog.", printed)
        self.assertIn("1. Fake app 0.1.0, 0.1.1 is out", printed)
        self.assertIn("2. Other app 0.1.0, 0.1.2 is out", printed)

    def test_nothing_newer_says_so_in_one_line_and_asks_nothing(self):
        self.install()
        self.other_app(install=True)
        with patch("builtins.input", side_effect=AssertionError("asked about nothing")):
            self.farm.update()
        printed = self.output.getvalue()
        self.assertIn("Everything you have installed is the newest the catalog has.", printed)
        self.assertNotIn("1. ", printed)

    def test_a_number_updates_the_app_on_that_row_and_leaves_the_rest(self):
        self.install()
        self.other_app(install=True)
        self.make_release("0.1.1")
        self.other_app(version="0.1.2")
        with patch("farm.farm.interactive", return_value=True), patch("builtins.input", return_value="2") as asked:
            self.farm.update()
        self.assertEqual(asked.call_args[0][0], 'Update which? A number, "all", or Enter to leave them. ')
        self.assertEqual((self.home / "other-app/current").read_text().strip(), "0.1.2")
        self.assertEqual((self.app / "current").read_text().strip(), "0.1.0")

    def test_all_updates_each_one_in_order(self):
        self.install()
        self.other_app(install=True)
        self.make_release("0.1.1")
        self.other_app(version="0.1.2")
        with patch("farm.farm.interactive", return_value=True), patch("builtins.input", return_value="all"):
            self.farm.update()
        self.assertEqual((self.app / "current").read_text().strip(), "0.1.1")
        self.assertEqual((self.home / "other-app/current").read_text().strip(), "0.1.2")
        printed = self.output.getvalue()
        self.assertLess(printed.index("Looking up fake-app in the catalog."),
                        printed.index("Looking up other-app in the catalog."))

    def test_enter_leaves_them_all_alone(self):
        self.install()
        self.make_release("0.1.1")
        with patch("farm.farm.interactive", return_value=True), patch("builtins.input", return_value=""):
            self.farm.update()
        self.assertIn("Left as they are.", self.output.getvalue())
        self.assertEqual((self.app / "current").read_text().strip(), "0.1.0")

    def test_an_answer_that_is_not_on_the_list_updates_nothing(self):
        self.install()
        self.make_release("0.1.1")
        with patch("farm.farm.interactive", return_value=True), patch("builtins.input", return_value="9"):
            self.farm.update()
        self.assertIn("There is no 9 in that list, so nothing was updated.", self.output.getvalue())
        self.assertEqual((self.app / "current").read_text().strip(), "0.1.0")

    def test_a_script_is_given_the_list_and_is_never_asked_a_question(self):
        self.install()
        self.make_release("0.1.1")
        with patch("farm.farm.interactive", return_value=False), \
                patch("builtins.input", side_effect=AssertionError("asked a script a question")):
            self.farm.update()
        printed = self.output.getvalue()
        self.assertIn("1. Fake app 0.1.0, 0.1.1 is out", printed)
        self.assertIn("Nothing was updated. Run: farm update <id> to take one,"
                      " or farm update --all to take them all.", printed)
        self.assertEqual((self.app / "current").read_text().strip(), "0.1.0")

    def test_all_and_yes_take_everything_newer_without_asking(self):
        for flags in ({"everything": True}, {"yes": True}):
            with self.subTest(**flags):
                self.install()
                self.make_release("0.1.1")
                with patch("builtins.input", side_effect=AssertionError("asked with a flag set")):
                    self.farm.update(**flags)
                self.assertEqual((self.app / "current").read_text().strip(), "0.1.1")
                self.farm.remove("fake-app", purge=True)
                self.make_release("0.1.0")

    def test_update_one_app_asks_before_it_takes_it(self):
        self.install()
        self.make_release("0.1.1")
        with patch("builtins.input", return_value="y") as asked:
            self.farm.update("fake-app")
        self.assertEqual(asked.call_args[0][0],
                         "Fake app 0.1.0 is installed and 0.1.1 is out. Update it? [Y/n] ")
        self.assertEqual((self.app / "current").read_text().strip(), "0.1.1")

    def test_the_question_defaults_to_yes_so_enter_takes_it(self):
        self.install()
        self.make_release("0.1.1")
        with patch("builtins.input", return_value=""):
            self.farm.update("fake-app")
        self.assertEqual((self.app / "current").read_text().strip(), "0.1.1")

    def test_no_leaves_the_installed_version_alone(self):
        self.install()
        self.make_release("0.1.1")
        with patch("builtins.input", return_value="n"), \
                patch.object(self.farm, "download", side_effect=AssertionError("downloaded after no")):
            self.farm.update("fake-app")
        self.assertIn("Left as it is.", self.output.getvalue())
        self.assertEqual((self.app / "current").read_text().strip(), "0.1.0")

    def test_yes_skips_the_question_and_says_the_data_is_kept(self):
        self.install()
        (self.app / "data/keep.txt").write_text("precious")
        self.make_release("0.1.1")
        with patch("builtins.input", side_effect=AssertionError("asked with --yes")):
            self.farm.update("fake-app", yes=True)
        printed = self.output.getvalue()
        self.assertIn(f"Your data in {self.app / 'data'} is kept.", printed)
        self.assertIn("Ready. Run: farm start fake-app", printed)
        self.assertEqual((self.app / "data/keep.txt").read_text(), "precious")
        self.assertEqual((self.app / "current").read_text().strip(), "0.1.1")

    def test_an_app_already_current_says_so_in_one_line(self):
        self.install()
        with patch("builtins.input", side_effect=AssertionError("asked about nothing")), \
                patch.object(self.farm, "download", side_effect=AssertionError("downloaded nothing new")):
            self.farm.update("fake-app")
        self.assertIn("Fake app 0.1.0 is installed, and that is the newest the catalog has.",
                      self.output.getvalue())

    def test_a_running_app_is_stopped_updated_and_started_again_on_its_port(self):
        self.manifest["requires"]["ports"] = [7861]
        self.save_manifest()
        self.install()
        ready = [ConnectionRefusedError(), contextlib.nullcontext(),
                 ConnectionRefusedError(), contextlib.nullcontext()]
        with patch("farm.farm.socket.create_connection", side_effect=ready):
            self.farm.start("fake-app")
            first = self.farm.active("fake-app")
            self.make_release("0.1.1", code=FAKE_APP + "# version two\n")
            self.farm.update("fake-app", yes=True)
        printed = self.output.getvalue()
        self.assertIn("Fake app is running on port 7861, so the farm stops it and starts it again on 7861.", printed)
        self.assertEqual((self.app / "current").read_text().strip(), "0.1.1")
        self.assertIsNotNone(self.farm.active("fake-app"))
        self.assertNotEqual(self.farm.active("fake-app"), first)
        self.assertEqual(json.loads((self.app / "process.json").read_text())["ports"], [7861])
        after = printed.split("Your data in")[1]
        self.assertIn("Open http://localhost:7861", after)
        self.assertNotIn("Ready. Run: farm start fake-app", after)

    def test_status_row_carries_an_available_update(self):
        self.manifest["requires"]["ports"] = [7862]
        self.save_manifest()
        self.install()
        with patch("farm.farm.socket.create_connection", side_effect=[
                ConnectionRefusedError(), contextlib.nullcontext()]):
            self.farm.start("fake-app")
        self.make_release("0.1.1")
        self.farm.status()
        self.assertRegex(self.output.getvalue(), r"running 0\.1\.0, update available: 0\.1\.1")

    def test_list_row_carries_an_available_update(self):
        self.install()
        self.make_release("0.1.1")
        self.farm.list()
        self.assertIn("  fake-app 0.1.0 Fake app [stopped, update available: 0.1.1] - ",
                      self.output.getvalue())

    def test_start_says_in_one_line_when_a_newer_version_is_out(self):
        self.manifest["requires"]["ports"] = [7863]
        self.save_manifest()
        self.install()
        self.make_release("0.1.1")
        with patch("farm.farm.socket.create_connection", side_effect=[
                ConnectionRefusedError(), contextlib.nullcontext()]):
            self.farm.start("fake-app")
        said = self.output.getvalue().split("Fake app is running.")[1]
        self.assertIn("Open http://localhost:7863\nVersion 0.1.1 is out. Run: farm update fake-app\n", said)

    def test_start_stays_quiet_when_nothing_newer_is_out(self):
        self.manifest["requires"]["ports"] = [7864]
        self.save_manifest()
        self.install()
        with patch("farm.farm.socket.create_connection", side_effect=[
                ConnectionRefusedError(), contextlib.nullcontext()]):
            self.farm.start("fake-app")
        self.assertNotIn("is out. Run: farm update", self.output.getvalue())

    def test_a_release_note_is_the_reason_on_the_row(self):
        self.install()
        self.make_release("0.1.1")
        self.manifest["release"]["notes"] = "Faster startup and a fix for the chat page"
        self.manifest["updatedAt"] = "2026-09-14"
        self.save_manifest()
        with patch("farm.farm.interactive", return_value=False):
            self.farm.update()
        self.assertIn("1. Fake app 0.1.0, 0.1.1 is out. Faster startup and a fix for the chat page.",
                      self.output.getvalue())

    def test_without_a_note_the_row_carries_the_day_the_catalog_changed(self):
        self.install()
        self.make_release("0.1.1")
        self.manifest["updatedAt"] = "2026-09-14"
        self.save_manifest()
        with patch("farm.farm.interactive", return_value=False):
            self.farm.update()
        self.assertIn("1. Fake app 0.1.0, 0.1.1 is out, dated 2026-09-14.", self.output.getvalue())

    def test_a_catalog_that_cannot_be_read_is_named_rather_than_hidden(self):
        self.install()
        self.other_app(install=True)
        self.make_release("0.1.1")
        (self.catalog / "other-app.json").unlink()
        with patch("farm.farm.interactive", return_value=False):
            self.farm.update()
        printed = self.output.getvalue()
        self.assertIn("1. Fake app 0.1.0, 0.1.1 is out", printed)
        self.assertIn("The catalog had nothing to say about other-app.", printed)

    def test_a_pending_release_is_never_offered_as_an_update(self):
        self.install()
        self.make_release("0.1.1")
        self.manifest["release"]["sha256"] = "pending"
        self.save_manifest()
        self.farm.update()
        self.assertIn("Everything you have installed is the newest the catalog has.", self.output.getvalue())

    def test_nothing_installed_points_at_the_catalog(self):
        self.farm.update()
        self.assertIn("Nothing is installed yet. Run: farm list to see what the catalog has.",
                      self.output.getvalue())

    def test_check_and_update_are_the_same_command(self):
        with patch("farm.farm.Farm", return_value=self.farm), patch.object(self.farm, "update") as update:
            for argv in (["check"], ["update"], ["update", "fake-app", "--yes"], ["update", "--all"],
                         ["check", "--all"]):
                self.assertEqual(main(argv), 0, argv)
        self.assertEqual(update.call_args_list,
                         [call(None, yes=False, everything=False),
                          call(None, yes=False, everything=False),
                          call("fake-app", yes=True, everything=False),
                          call(None, yes=False, everything=True),
                          call(None, yes=False, everything=True)])

    def test_cli_check_lists_what_is_newer_without_asking(self):
        self.install()
        self.make_release("0.1.1")
        env = os.environ | {"HOME": str(self.root), "USERPROFILE": str(self.root),
                            "FARM_CATALOG": str(self.catalog)}
        result = subprocess.run([sys.executable, str(ROOT / "farm/farm.py"), "check"],
                                env=env, text=True, capture_output=True,
                                stdin=subprocess.DEVNULL, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1. Fake app 0.1.0, 0.1.1 is out", result.stdout)
        self.assertEqual((self.app / "current").read_text().strip(), "0.1.0")

    def test_a_newer_catalog_entry_with_no_release_is_not_offered_as_one(self):
        self.install()
        self.make_release("0.1.1")
        del self.manifest["release"]
        self.save_manifest()
        with patch("builtins.input", side_effect=AssertionError("asked about a seed")):
            self.farm.update("fake-app")
        self.assertIn("Fake app 0.1.1 is in the catalog with no release to install yet.",
                      self.output.getvalue())
        self.assertEqual((self.app / "current").read_text().strip(), "0.1.0")

    def test_an_advisory_lookup_never_waits_as_long_as_an_install(self):
        """An unreachable catalog must not stall farm start, farm status or farm list."""
        from farm.farm import ADVISORY_TIMEOUT
        self.install()
        farm = Farm(self.home, "https://catalog.invalid/manifests/")
        with patch("farm.farm.open_url", side_effect=URLError("unreachable")) as opened:
            self.assertEqual(farm.newer_version("fake-app", self.manifest), "")
        self.assertEqual(opened.call_args.kwargs["timeout"], ADVISORY_TIMEOUT)
        self.assertLess(ADVISORY_TIMEOUT, 30)

    def test_end_of_input_at_the_question_leaves_everything_alone(self):
        """Windows calls NUL a terminal, so a script reaches the question even with no one there."""
        self.install()
        self.make_release("0.1.1")
        with patch("farm.farm.interactive", return_value=True), \
                patch("builtins.input", side_effect=EOFError()):
            self.farm.update()
        printed = self.output.getvalue()
        self.assertIn("1. Fake app 0.1.0, 0.1.1 is out", printed)
        self.assertIn("Nothing was updated. Run: farm update <id> to take one,"
                      " or farm update --all to take them all.", printed)
        self.assertEqual((self.app / "current").read_text().strip(), "0.1.0")

    def test_the_cli_exits_zero_when_the_question_reaches_end_of_input(self):
        """What CI caught on Windows: the run must not end as a cancellation."""
        self.install()
        self.make_release("0.1.1")
        with patch("farm.farm.Farm", return_value=self.farm), \
                patch("farm.farm.interactive", return_value=True), \
                patch("builtins.input", side_effect=EOFError()):
            self.assertEqual(main(["check"]), 0)
        self.assertNotIn("Cancelled.", self.output.getvalue())
