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
import textwrap
import threading
import time
import unittest
from unittest.mock import MagicMock, call, patch
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

import farm.farm as farm_module
from farm.farm import (DEVICE_PORT, DEVICE_PROBE, Farm, FarmError, MODELS_PROBE,
                       describe_size, main, python_candidates)

# The three ways the finder reaches the network, held before any test patches them, so a test about
# the finder itself can put the real one back and fake only the socket under it.
REAL_CABLE = farm_module.host_addresses
REAL_RESPONDER = farm_module.udp_devices
REAL_CLIENT = farm_module.tiinyos_serving

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_manifest", ROOT / "scripts/check-manifest.py")
assert spec is not None and spec.loader is not None
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)

# Recorded from Jason's Tiiny on 2026-09-14: what the box really answers on its discovery page,
# and what it sends back to the responder token. The serial number is what makes one answer a box
# rather than an open port, and the address list is what lets one box register once with both of
# its planes.
TIINY_JSON = {"schema_version": "1", "device_name": "jason's Tiiny",
              "device_id": "8804fa89557e415f8055cf77d98c8ac8",
              "serial_number": "TNYM26072400300011Q", "hostname": "tiinyhost",
              "discovery_token": "GADGET_DISCOVER_V1", "transport": ["lan", "usb"],
              "service": {"instance_name": "jason's Tiiny", "dns_sd": "_gadget._tcp",
                          "http_port": 39218, "http_path": "/device.json",
                          "udp_discovery_port": 39217},
              "backend": {"scheme": "http", "port": 0, "path": "/"},
              "usb": {"interface": "usb0", "active": 1, "network": "172.17.7.176/30",
                      "device_ip": "172.17.7.177", "host_ip": "172.17.7.178"},
              "ipv4_addresses": [{"interface": "usb0", "address": "172.17.7.177"},
                                 {"interface": "wlan0", "address": "192.168.100.94"}]}
ON_THE_CABLE = {"serial": "TNYM26072400300011Q", "name": "jason's Tiiny",
                "address": "172.17.7.177", "via": "cable", "base": "http://172.17.7.177/v1",
                "interfaces": [{"interface": "usb0", "address": "172.17.7.177"}],
                "addresses": ["172.17.7.177"]}


def seen(records, blocked=False, moved=None, python=None):
    """What Farm.find_tiinys hands back: what answered, and under which interpreter."""
    return {"found": [dict(record) for record in records], "blocked": blocked,
            "python": python or sys.executable, "moved": moved}


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
        # farm device and farm doctor now look for a Tiiny, and a unit test must not reach the
        # network. Every test runs on a machine with no cable, nothing answering the broadcast and
        # no TiinyOS client; the tests about finding one put back whichever part they are about.
        self.no_tiinys = [patch("farm.farm.host_addresses", return_value=[]),
                          patch("farm.farm.udp_devices", return_value=([], 0)),
                          patch("farm.farm.tiinyos_serving", return_value=False)]
        for guard in self.no_tiinys:
            guard.start()
        self.make_release()

    def tearDown(self):
        try:
            for current in sorted(self.home.glob("*/current")):
                self.farm.stop(current.parent.name)
        finally:
            for guard in self.no_tiinys:
                guard.stop()
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

    def other_app(self, ident="other-app", version="0.1.0", install=False, notes=None, ports=None):
        """A second app in the same fake catalog, so the update list has more than one row."""
        manifest = copy.deepcopy(self.manifest)
        manifest.update(id=ident, name="Other app", version=version)
        if ports is not None:
            manifest["requires"]["ports"] = list(ports)
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

    def test_find_reads_every_cable_in_this_machine(self):
        with patch("farm.farm.host_addresses", return_value=["172.17.7.178"]), \
                patch("farm.farm.urlopen",
                      return_value=io.BytesIO(json.dumps(TIINY_JSON).encode())) as asked:
            found = self.farm.find_device()["found"]
        self.assertEqual(asked.call_args.args[0], "http://172.17.7.177:39218/device.json")
        self.assertEqual(asked.call_args.kwargs["timeout"], farm_module.FIND_TIMEOUT)
        self.assertEqual([record["serial"] for record in found], ["TNYM26072400300011Q"])
        printed = self.output.getvalue()
        self.assertIn("jason's Tiiny (TNYM26072400300011Q) at 172.17.7.177, over the cable,"
                      " base http://172.17.7.177/v1", printed)
        self.assertIn("Run farm device to save it.", printed)

    def test_find_asks_the_responder_and_so_finds_a_box_on_the_network(self):
        with patch("farm.farm.udp_devices", return_value=([("192.168.100.94", TIINY_JSON)], 0)) as asked:
            found = self.farm.find_device()["found"]
        self.assertEqual(asked.call_args.args[0], ["255.255.255.255"])
        self.assertEqual(found[0]["via"], "network")
        self.assertEqual(found[0]["base"], "http://192.168.100.94/v1")
        self.assertIn("jason's Tiiny (TNYM26072400300011Q) at 192.168.100.94, on this network,"
                      " base http://192.168.100.94/v1", self.output.getvalue())

    def test_find_folds_one_box_that_answers_on_both_planes_into_one_line(self):
        """Serial number, not address, is what says how many Tiinys are really there."""
        with patch("farm.farm.host_addresses", return_value=["172.17.7.178"]), \
                patch("farm.farm.urlopen",
                      return_value=io.BytesIO(json.dumps(TIINY_JSON).encode())), \
                patch("farm.farm.udp_devices",
                      return_value=([("172.17.7.177", TIINY_JSON),
                                     ("192.168.100.94", TIINY_JSON)], 0)):
            found = self.farm.find_device()["found"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["via"], "cable")
        self.assertEqual(found[0]["address"], "172.17.7.177")
        self.assertEqual(found[0]["addresses"], ["172.17.7.177", "192.168.100.94"])
        self.assertEqual(self.output.getvalue().count("TNYM26072400300011Q"), 1)

    def test_find_asks_the_tiinyos_client_only_when_nothing_else_answered(self):
        with patch("farm.farm.tiinyos_serving", return_value=True):
            found = self.farm.find_device()["found"]
        self.assertIsNone(found[0]["serial"])
        self.assertEqual(found[0]["via"], "TiinyOS client")
        self.assertEqual(found[0]["base"], "http://openai.api.tiiny/v1")
        self.assertIn("A Tiiny at openai.api.tiiny, through the TiinyOS client,"
                      " base http://openai.api.tiiny/v1", self.output.getvalue())
        with patch("farm.farm.udp_devices", return_value=([("192.168.100.94", TIINY_JSON)], 0)), \
                patch("farm.farm.tiinyos_serving", return_value=True) as skipped:
            self.farm.find_device()
        skipped.assert_not_called()

    def test_find_says_what_it_tried_and_how_to_type_it_in(self):
        self.assertEqual(self.farm.find_device()["found"], [])
        printed = self.output.getvalue()
        self.assertIn("No Tiiny answered. The farm looked on every USB cable in this machine,"
                      " on this network, and at the TiinyOS client on"
                      " http://openai.api.tiiny/v1.", printed)
        self.assertIn("then run: farm device --find", printed)
        self.assertIn("farm device --base http://<address>/v1 --key-stdin < key-file", printed)

    def test_a_machine_with_no_cable_finds_nothing_and_never_unplugs_one(self):
        """The cable is taken away at the bind step, which is the only thing that knows we have
        one. Everything else in the finder is the real code, over a socket that answers nothing."""
        empty = MagicMock()
        empty.bind.side_effect = OSError(errno.EADDRNOTAVAIL, "Can't assign requested address")
        empty.recvfrom.side_effect = farm_module.socket.timeout()
        with patch("farm.farm.host_addresses", REAL_CABLE), \
                patch("farm.farm.udp_devices", REAL_RESPONDER), \
                patch("farm.farm.tiinyos_serving", REAL_CLIENT), \
                patch("farm.farm.socket.socket", return_value=empty), \
                patch("farm.farm.urlopen", side_effect=OSError("nothing there")):
            answer = self.farm.find_device()
        self.assertEqual(answer, {"found": [], "blocked": False, "python": sys.executable,
                                  "moved": None})
        self.assertIn("No Tiiny answered.", self.output.getvalue())
        self.assertIn("--key-stdin < key-file", self.output.getvalue())

    def test_a_refused_python_is_never_reported_as_no_tiiny(self):
        """Jason, 2026-09-14: macOS grants the local network per binary. Last night miniconda got
        EHOSTUNREACH to the same Tiiny that Homebrew Python answered in milliseconds. Saying "no
        Tiiny" to that sends somebody to check a cable that was never the problem."""
        with patch("farm.farm.host_addresses", return_value=["172.17.7.178"]), \
                patch("farm.farm.python_candidates", return_value=[]), \
                patch("farm.farm.urlopen",
                      side_effect=URLError(OSError(errno.EHOSTUNREACH, "No route to host"))):
            answer = self.farm.find_device()
        self.assertEqual(answer["found"], [])
        self.assertTrue(answer["blocked"])
        self.assertIsNone(answer["moved"])
        printed = self.output.getvalue()
        self.assertIn(f"The farm cannot tell whether a Tiiny is there, because {sys.executable}"
                      " was refused your local network.", printed)
        self.assertIn("macOS is blocking this Python from your local network.", printed)
        self.assertNotIn("No Tiiny answered", printed)

    def test_a_refused_python_hands_the_search_to_one_that_is_not(self):
        """The same walk a failed start does, and the interpreter it lands on is saved."""
        other = "/opt/homebrew/bin/python3"
        reached = {"found": [dict(ON_THE_CABLE)], "errno": 0, "python": [3, 14]}
        blocked = {"found": [], "errno": errno.EHOSTUNREACH, "python": list(sys.version_info[:2])}
        with patch("farm.farm.host_addresses", return_value=["172.17.7.178"]), \
                patch("farm.farm.python_candidates", return_value=[other]), \
                patch.object(self.farm, "probed",
                             side_effect=lambda who, peers, budget=None:
                             reached if who == other else blocked) as asked:
            answer = self.farm.find_device()
        self.assertEqual([record["serial"] for record in answer["found"]],
                         ["TNYM26072400300011Q"])
        self.assertTrue(answer["blocked"])
        self.assertEqual(answer["moved"], other)
        self.assertEqual([held.args[0] for held in asked.call_args_list], [sys.executable, other])
        self.assertEqual(self.farm.settings()["python"], other)
        printed = self.output.getvalue()
        self.assertIn(f"{other} found it. The Python the farm was using cannot reach your local"
                      " network, so the farm will run apps with that one from now on, and has"
                      " saved it.", printed)
        self.assertIn("jason's Tiiny (TNYM26072400300011Q) at 172.17.7.177", printed)
        self.assertNotIn("No Tiiny answered", printed)

    def test_a_python_too_old_to_run_apps_does_not_win_the_walk(self):
        old = "/usr/bin/python3.8"
        found = {"found": [dict(ON_THE_CABLE)], "errno": 0, "python": [3, 8]}
        blocked = {"found": [], "errno": errno.EHOSTUNREACH, "python": list(sys.version_info[:2])}
        with patch("farm.farm.host_addresses", return_value=["172.17.7.178"]), \
                patch("farm.farm.python_candidates", return_value=[old]), \
                patch.object(self.farm, "probed",
                             side_effect=lambda who, peers, budget=None:
                             found if who == old else blocked):
            answer = self.farm.find_device()
        self.assertIsNone(answer["moved"])
        self.assertTrue(answer["blocked"])
        self.assertNotIn("python", self.farm.settings())

    def test_the_search_runs_under_the_python_the_farm_runs_apps_with(self):
        """The CLI and an app can be two binaries, and macOS grants them separately, so the answer
        that counts is the one from the binary that will be doing the reaching."""
        other = "/opt/homebrew/bin/python3"
        answer = json.dumps({"found": [dict(ON_THE_CABLE)], "errno": 0, "python": [3, 14]})
        done = subprocess.CompletedProcess([], 0, answer, "")
        with patch.object(self.farm, "app_python", return_value=other), \
                patch("farm.farm.host_addresses", return_value=["172.17.7.178"]), \
                patch("farm.farm.subprocess.run", return_value=done) as child:
            found = self.farm.find_device()["found"]
        self.assertEqual(child.call_args.args[0][0], other)
        self.assertEqual(child.call_args.args[0][1], "-c")
        self.assertEqual(child.call_args.args[0][2], farm_module.FIND_PROBE)
        self.assertEqual(json.loads(child.call_args.args[0][4]), ["172.17.7.177"])
        self.assertIsNotNone(child.call_args.kwargs["timeout"])
        self.assertEqual([record["serial"] for record in found], ["TNYM26072400300011Q"])

    def test_the_child_probe_source_runs_and_answers_in_json(self):
        """Nothing is plugged into a peer list of nothing, so the answer is empty, not a crash."""
        done = subprocess.run([sys.executable, "-c", farm_module.FIND_PROBE,
                               str(Path(farm_module.__file__).resolve().parents[1]), "[]", "0.5"],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        answer = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertEqual(answer["errno"], 0)
        self.assertIsInstance(answer["found"], list)
        self.assertEqual(tuple(answer["python"]), sys.version_info[:2])

    def test_a_child_that_will_not_run_is_an_empty_answer_not_a_crash(self):
        with patch.object(self.farm, "app_python", return_value="/no/such/python"), \
                patch("farm.farm.host_addresses", return_value=["172.17.7.178"]), \
                patch("farm.farm.python_candidates", return_value=[]):
            answer = self.farm.find_device()
        self.assertEqual(answer["found"], [])
        self.assertFalse(answer["blocked"])
        self.assertIn("No Tiiny answered.", self.output.getvalue())

    def test_the_discovery_page_says_why_it_heard_nothing(self):
        """A refused Python is told no; a box that is off says nothing at all. Only the errno
        tells them apart, so it comes back with the payload."""
        with patch("farm.farm.urlopen",
                   side_effect=URLError(OSError(errno.EHOSTUNREACH, "No route to host"))):
            self.assertEqual(farm_module.device_json("172.17.7.177"),
                             (None, errno.EHOSTUNREACH))
        with patch("farm.farm.urlopen", side_effect=farm_module.socket.timeout()):
            self.assertEqual(farm_module.device_json("172.17.7.177"), (None, 0))
        refused = MagicMock()
        refused.sendto.side_effect = OSError(errno.EHOSTUNREACH, "No route to host")
        with patch("farm.farm.socket.socket", return_value=refused):
            self.assertEqual(REAL_RESPONDER(["255.255.255.255"], timeout=0.25),
                             ([], errno.EHOSTUNREACH))

    def test_a_blocked_find_answers_a_machine_with_why(self):
        out = io.StringIO()
        with patch("farm.farm.Farm", return_value=self.farm), \
                patch("farm.farm.host_addresses", return_value=["172.17.7.178"]), \
                patch("farm.farm.python_candidates", return_value=[]), \
                patch("farm.farm.urlopen",
                      side_effect=URLError(OSError(errno.EHOSTUNREACH, "No route to host"))), \
                contextlib.redirect_stdout(out):
            self.assertEqual(main(["device", "--find", "--json", "--no-update-check"]), 1)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["found"], [])
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["blocked"])
        self.assertEqual(payload["python"], sys.executable)
        self.assertIsNone(payload["moved"])

    def test_no_probe_forks_this_process(self):
        """Measured on macOS 25.6 on 2026-09-14: once urllib has been through the macOS name and
        proxy path for a host it could not fetch, a forked child dies of SIGSEGV before it reaches
        exec, and subprocess forks whenever close_fds is on. Every probe asks for the spawn."""
        answer = subprocess.CompletedProcess([], 0, json.dumps({"errno": 0, "address": "",
                                                                "python": [3, 14]}), "")
        with patch("farm.farm.subprocess.run", return_value=answer) as child:
            self.farm.probe_device("172.17.7.177", "/opt/homebrew/bin/python3")
            self.farm.device_models({"base": "http://172.17.7.177/v1", "key": "not-a-real-key"},
                                    "/opt/homebrew/bin/python3")
            self.farm.probed("/opt/homebrew/bin/python3", ["172.17.7.177"], 1.0)
        self.assertEqual(len(child.call_args_list), 3)
        for held in child.call_args_list:
            self.assertFalse(held.kwargs["close_fds"])
            self.assertIsNotNone(held.kwargs["timeout"])

    def test_a_probe_still_answers_after_urllib_met_a_name_it_could_not_fetch(self):
        """The regression itself, with no hardware in it. Fetch a name that resolves nowhere the
        way the farm fetches, then ask another interpreter something and see whether it lived long
        enough to answer. Run in a child of its own, because the state it is about is the whole
        process's and would follow this one into every test after it."""
        source = textwrap.dedent("""
            import contextlib, subprocess, sys
            sys.path.insert(0, sys.argv[1])
            from farm.farm import run_probe, urlopen
            with contextlib.suppress(Exception):
                urlopen("http://farm-test.invalid/nothing", timeout=2).close()
            print(run_probe([sys.executable, "-c", "print(7)"], 30).returncode)
        """)
        done = subprocess.run([sys.executable, "-c", source, str(ROOT)],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.stdout.strip().splitlines()[-1], "0",
                         "a probe was killed before it could answer: " + done.stderr[-400:])

    def test_usb_peers_take_the_other_end_of_each_point_to_point_link(self):
        with patch("farm.farm.host_addresses",
                   return_value=["172.17.7.178", "172.17.9.1", "172.17.7.178"]):
            self.assertEqual(farm_module.usb_peers(), ["172.17.7.177", "172.17.9.2"])

    def test_the_base_url_takes_a_backend_port_at_its_word(self):
        """Firmware 1.0 serves the model API on port 80 behind a virtual host and says port 0 here,
        so the saved base carries no port unless a device.json names one."""
        self.assertEqual(farm_module.device_base(TIINY_JSON, "172.17.7.177"),
                         "http://172.17.7.177/v1")
        self.assertEqual(farm_module.device_base({}, "172.17.7.177"), "http://172.17.7.177/v1")
        self.assertEqual(farm_module.device_base({"backend": {"port": 80}}, "172.17.7.177"),
                         "http://172.17.7.177/v1")
        self.assertEqual(farm_module.device_base({"backend": {"port": 8800}}, "172.17.7.177"),
                         "http://172.17.7.177:8800/v1")

    def test_every_probe_in_the_finder_carries_a_timeout(self):
        """A filtered port does not refuse, it hangs, so a ceiling is the only thing that ends it."""
        with patch("farm.farm.urlopen", return_value=io.BytesIO(b"{}")) as page:
            self.assertEqual(farm_module.device_json("172.17.7.177", timeout=0.25), (None, 0))
        self.assertEqual(page.call_args.kwargs["timeout"], 0.25)
        with patch("farm.farm.urlopen", side_effect=OSError("nothing there")) as client:
            self.assertFalse(REAL_CLIENT(timeout=0.25))
        self.assertEqual(client.call_args.kwargs["timeout"], 0.25)
        quiet = MagicMock()
        quiet.recvfrom.side_effect = farm_module.socket.timeout()
        with patch("farm.farm.socket.socket", return_value=quiet):
            self.assertEqual(REAL_RESPONDER(["255.255.255.255"], timeout=0.25), ([], 0))
        self.assertTrue(quiet.settimeout.called)
        self.assertLessEqual(max(held.args[0] for held in quiet.settimeout.call_args_list), 0.25)
        quiet.close.assert_called_once_with()

    def test_the_search_shrinks_each_probe_to_what_is_left_of_the_budget(self):
        now = time.monotonic()
        self.assertEqual(farm_module._remaining(now + 10, 1.2), 1.2)
        self.assertEqual(farm_module._remaining(now - 5, 1.2), 0.05)

    def test_device_offers_the_one_thing_the_finder_saw(self):
        with patch.object(self.farm, "find_tiinys", return_value=seen([ON_THE_CABLE])), \
                patch.object(self.farm, "probe_device", return_value=(0, "172.17.7.177", (3, 14))), \
                patch("getpass.getpass", side_effect=["", "secret-value"]) as prompt:
            self.farm.device()
        self.assertEqual(prompt.call_args_list[0].args[0],
                         "Device base URL [http://172.17.7.177/v1] (hidden): ")
        saved = json.loads((self.home / "device.json").read_text())
        self.assertEqual(saved["base"], "http://172.17.7.177/v1")
        self.assertIn("Found jason's Tiiny (TNYM26072400300011Q) at 172.17.7.177, over the cable,"
                      " base http://172.17.7.177/v1", self.output.getvalue())
        self.assertNotIn("secret-value", self.output.getvalue())

    def test_device_takes_what_is_typed_over_what_was_found(self):
        with patch.object(self.farm, "find_tiinys", return_value=seen([ON_THE_CABLE])), \
                patch.object(self.farm, "probe_device", return_value=(0, "10.0.0.5", (3, 14))), \
                patch("getpass.getpass", side_effect=["http://10.0.0.5/v1", "secret-value"]):
            self.farm.device()
        self.assertEqual(json.loads((self.home / "device.json").read_text())["base"],
                         "http://10.0.0.5/v1")

    def test_device_numbers_them_when_more_than_one_answered(self):
        second = dict(ON_THE_CABLE, serial="TNYM26072400300012Q", name="the spare",
                      address="192.168.100.94", via="network", base="http://192.168.100.94/v1")
        with patch.object(self.farm, "find_tiinys", return_value=seen([ON_THE_CABLE, second])), \
                patch("farm.farm.ask_which", return_value=([1], "2")) as question, \
                patch.object(self.farm, "probe_device", return_value=(0, "192.168.100.94", (3, 14))), \
                patch("getpass.getpass", side_effect=["", "secret-value"]) as prompt:
            self.farm.device()
        self.assertEqual(question.call_args.args[1], 2)
        printed = self.output.getvalue()
        self.assertIn("1. jason's Tiiny (TNYM26072400300011Q) at 172.17.7.177, over the cable,",
                      printed)
        self.assertIn("2. the spare (TNYM26072400300012Q) at 192.168.100.94, on this network,",
                      printed)
        self.assertEqual(prompt.call_args_list[0].args[0],
                         "Device base URL [http://192.168.100.94/v1] (hidden): ")
        self.assertEqual(json.loads((self.home / "device.json").read_text())["base"],
                         "http://192.168.100.94/v1")

    def test_device_prompts_as_it_always_did_when_the_finder_falls_over(self):
        """Finding a Tiiny is a convenience on a command that has always worked by hand."""
        with patch.object(self.farm, "find_tiinys", side_effect=RuntimeError("finder exploded")), \
                patch("getpass.getpass",
                      side_effect=["http://example.test/v1", "secret-value"]) as prompt:
            self.farm.device()
        self.assertEqual(prompt.call_args_list[0].args[0], "Device base URL (hidden): ")
        self.assertNotIn("finder exploded", self.output.getvalue())
        self.assertEqual(json.loads((self.home / "device.json").read_text())["base"],
                         "http://example.test/v1")

    def test_a_scripted_device_never_goes_looking(self):
        with patch.object(self.farm, "find_tiinys") as never, patch.dict(os.environ):
            os.environ.pop("TIINY_BASE", None)
            os.environ.pop("TIINY_KEY", None)
            with patch("sys.stdin", io.StringIO("secret-value\n")):
                self.farm.device(base="http://example.test/v1", key_stdin=True)
        never.assert_not_called()

    def test_find_refuses_to_also_save(self):
        """Looking and saving are different jobs, and one command cannot quietly do one of them."""
        with patch.object(self.farm, "find_tiinys") as never:
            with self.assertRaises(FarmError) as refused:
                self.farm.device(base="http://example.test/v1", find=True)
        self.assertIn("looks and saves nothing", str(refused.exception))
        never.assert_not_called()
        with patch("farm.farm.Farm", return_value=self.farm):
            self.assertEqual(main(["device", "--find", "--key-stdin", "--no-update-check"]), 1)

    def test_the_cli_exits_one_when_the_find_answers_nothing(self):
        with patch("farm.farm.Farm", return_value=self.farm):
            self.assertEqual(main(["device", "--find", "--no-update-check"]), 1)
            with patch("farm.farm.udp_devices", return_value=([("192.168.100.94", TIINY_JSON)], 0)):
                self.assertEqual(main(["device", "--find", "--no-update-check"]), 0)

    def test_find_answers_a_machine_with_one_object(self):
        answer = io.StringIO()
        with patch("farm.farm.Farm", return_value=self.farm), \
                patch("farm.farm.udp_devices", return_value=([("192.168.100.94", TIINY_JSON)], 0)), \
                contextlib.redirect_stdout(answer):
            self.assertEqual(main(["device", "--find", "--json", "--no-update-check"]), 0)
        payload = json.loads(answer.getvalue())
        self.assertEqual(payload["command"], "device")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["found"], [{
            "serial": "TNYM26072400300011Q", "name": "jason's Tiiny",
            "address": "192.168.100.94", "via": "network", "base": "http://192.168.100.94/v1",
            "interfaces": [{"interface": "usb0", "address": "172.17.7.177"},
                           {"interface": "wlan0", "address": "192.168.100.94"}]}])
        empty = io.StringIO()
        with patch("farm.farm.Farm", return_value=self.farm), contextlib.redirect_stdout(empty):
            self.assertEqual(main(["device", "--find", "--json", "--no-update-check"]), 1)
        self.assertEqual(json.loads(empty.getvalue())["found"], [])

    def test_the_machine_answer_for_device_is_the_find_and_nothing_else(self):
        """Saving a key needs a prompt or standard input, and no --json command reads either."""
        answer = io.StringIO()
        with patch("farm.farm.Farm", return_value=self.farm), \
                patch("getpass.getpass", side_effect=AssertionError("asked for a key")), \
                contextlib.redirect_stdout(answer):
            self.assertEqual(main(["device", "--json", "--no-update-check"]), 1)
        self.assertIn("answers --find only", json.loads(answer.getvalue())["error"]["message"])

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
        start.assert_called_once_with('fake-app', port=43211, python=None)

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
        with patch("farm.farm.python_candidates", return_value=[]), \
                patch("farm.farm.urlopen",
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
        with patch.object(self.farm, "probe_device", side_effect=RuntimeError("probe exploded")):
            self.farm.start("fake-app")
        self.assertIn("Fake app is running.", self.output.getvalue())
        self.assertNotIn("probe exploded", self.output.getvalue())
        self.assertIsNotNone(self.farm.active("fake-app"))

    def test_device_says_when_macos_is_blocking_the_local_network(self):
        with patch("getpass.getpass", side_effect=["http://172.17.7.177/v1", "secret-value"]), \
                patch("farm.farm.python_candidates", return_value=[]), \
                patch("farm.farm.urlopen",
                      side_effect=URLError(OSError(errno.EHOSTUNREACH, "No route to host"))):
            self.farm.device()
        printed = self.output.getvalue()
        self.assertIn("Device settings saved.", printed)
        self.assertIn("macOS is blocking this Python from your local network.", printed)
        self.assertNotIn("secret-value", printed)

    def test_an_app_on_another_python_is_probed_with_that_python(self):
        """The CLI and the app can be two binaries, and macOS grants the local network one at a time."""
        answer = json.dumps({"errno": errno.EHOSTUNREACH, "address": "172.17.7.177", "python": [3, 13]})
        done = subprocess.CompletedProcess([], 0, answer, "")
        with patch("farm.farm.subprocess.run", return_value=done) as child:
            code, address, version = self.farm.probe_device("172.17.7.177", "/opt/conda/bin/python3")
        self.assertEqual(code, errno.EHOSTUNREACH)
        self.assertEqual(address, "172.17.7.177")
        self.assertEqual(version, (3, 13))
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

    def running_pair(self):
        """Two apps actually running, on ports nothing else here uses."""
        self.manifest["requires"]["ports"] = [7865]
        self.save_manifest()
        self.install()
        self.other_app(install=True, ports=[7866])
        with patch("farm.farm.socket.create_connection", side_effect=[
                ConnectionRefusedError(), contextlib.nullcontext(),
                ConnectionRefusedError(), contextlib.nullcontext()]):
            self.farm.start("fake-app")
            self.farm.start("other-app")

    def test_a_bare_stop_asks_which_of_the_running_apps_to_stop(self):
        """Jason, 2026-09-14: "Does it ask me which app I want to stop?\""""
        self.running_pair()
        with patch("farm.farm.interactive", return_value=True), \
                patch("builtins.input", return_value="2") as asked:
            self.farm.stop()
        printed = self.output.getvalue()
        self.assertIn("2 apps are running.", printed)
        self.assertIn("1. Fake app 0.1.0 on port 7865", printed)
        self.assertIn("2. Other app 0.1.0 on port 7866", printed)
        self.assertEqual(asked.call_args[0][0], 'Stop which? A number, "all", or Enter to leave them. ')
        self.assertIsNone(self.farm.active("other-app"))
        self.assertIsNotNone(self.farm.active("fake-app"))

    def test_a_bare_stop_takes_all_and_takes_enter_for_an_answer(self):
        self.running_pair()
        with patch("farm.farm.interactive", return_value=True), patch("builtins.input", return_value=""):
            self.farm.stop()
        self.assertIn("Left as they are.", self.output.getvalue())
        self.assertIsNotNone(self.farm.active("fake-app"))
        with patch("farm.farm.interactive", return_value=True), patch("builtins.input", return_value="all"):
            self.farm.stop()
        self.assertIsNone(self.farm.active("fake-app"))
        self.assertIsNone(self.farm.active("other-app"))

    def test_one_running_app_is_a_plain_question_not_a_list_of_one(self):
        self.manifest["requires"]["ports"] = [7867]
        self.save_manifest()
        self.install()
        with patch("farm.farm.socket.create_connection", side_effect=[
                ConnectionRefusedError(), contextlib.nullcontext()]):
            self.farm.start("fake-app")
        with patch("farm.farm.interactive", return_value=True), \
                patch("builtins.input", return_value="") as asked:
            self.farm.stop()
        self.assertEqual(asked.call_args[0][0], "Stop Fake app? [Y/n] ")
        self.assertNotIn("1. Fake app", self.output.getvalue())
        self.assertIsNone(self.farm.active("fake-app"))

    def test_one_running_app_answered_no_is_left_running(self):
        self.manifest["requires"]["ports"] = [7868]
        self.save_manifest()
        self.install()
        with patch("farm.farm.socket.create_connection", side_effect=[
                ConnectionRefusedError(), contextlib.nullcontext()]):
            self.farm.start("fake-app")
        with patch("farm.farm.interactive", return_value=True), patch("builtins.input", return_value="n"):
            self.farm.stop()
        self.assertIn("Left as it is.", self.output.getvalue())
        self.assertIsNotNone(self.farm.active("fake-app"))

    def test_a_bare_stop_with_nothing_running_says_so_in_one_line(self):
        self.install()
        with patch("builtins.input", side_effect=AssertionError("asked about nothing")):
            self.farm.stop()
        self.assertIn("Nothing is running.", self.output.getvalue())

    def test_a_bare_stop_in_a_script_prints_the_list_and_leaves(self):
        self.running_pair()
        with patch("farm.farm.interactive", return_value=False), \
                patch("builtins.input", side_effect=AssertionError("asked a script a question")):
            self.farm.stop()
        printed = self.output.getvalue()
        self.assertIn("1. Fake app 0.1.0 on port 7865", printed)
        self.assertIn("Nothing was stopped. Run: farm stop <id>, naming one of fake-app and other-app.",
                      printed)
        self.assertIsNotNone(self.farm.active("fake-app"))

    def test_a_bare_start_asks_which_installed_app_to_start(self):
        self.install()
        self.other_app(install=True)
        with patch("farm.farm.interactive", return_value=True), \
                patch("builtins.input", return_value="1") as asked:
            self.farm.start()
        printed = self.output.getvalue()
        self.assertIn("2 installed apps are ready to start.", printed)
        self.assertIn("1. Fake app 0.1.0", printed)
        self.assertIn("2. Other app 0.1.0", printed)
        self.assertEqual(asked.call_args[0][0], 'Start which? A number, "all", or Enter to leave them. ')
        self.assertIsNotNone(self.farm.active("fake-app"))
        self.assertIsNone(self.farm.active("other-app"))

    def test_one_app_to_start_is_a_plain_question(self):
        self.install()
        with patch("farm.farm.interactive", return_value=True), \
                patch("builtins.input", return_value="y") as asked:
            self.farm.start()
        self.assertEqual(asked.call_args[0][0], "Start Fake app? [Y/n] ")
        self.assertNotIn("1. Fake app", self.output.getvalue())
        self.assertIsNotNone(self.farm.active("fake-app"))

    def test_a_bare_start_leaves_a_running_app_and_a_library_off_the_list(self):
        self.install()
        library = self.other_app(ident="library-app")
        library.update(entry=None, tags=["library"])
        (self.catalog / "library-app.json").write_text(json.dumps(library))
        self.farm.install("library-app", yes=True)
        self.farm.start("fake-app")
        with patch("builtins.input", side_effect=AssertionError("asked about nothing")):
            self.farm.start()
        self.assertIn("Everything you have installed is already running.", self.output.getvalue())

    def test_a_bare_start_in_a_script_prints_the_list_and_leaves(self):
        self.install()
        self.other_app(install=True)
        with patch("farm.farm.interactive", return_value=False), \
                patch("builtins.input", side_effect=AssertionError("asked a script a question")):
            self.farm.start()
        printed = self.output.getvalue()
        self.assertIn("2. Other app 0.1.0", printed)
        self.assertIn("Nothing was started. Run: farm start <id>, naming one of fake-app and other-app.",
                      printed)
        self.assertIsNone(self.farm.active("fake-app"))

    def test_one_app_and_nobody_there_says_how_to_do_it_by_hand(self):
        self.install()
        with patch("farm.farm.interactive", return_value=False):
            self.farm.start()
        self.assertIn("Fake app is installed and not running. Run: farm start fake-app.",
                      self.output.getvalue())

    def test_an_answer_that_is_not_on_the_start_list_starts_nothing(self):
        self.install()
        self.other_app(install=True)
        with patch("farm.farm.interactive", return_value=True), patch("builtins.input", return_value="9"):
            self.farm.start()
        self.assertIn("There is no 9 in that list, so nothing was started.", self.output.getvalue())
        self.assertIsNone(self.farm.active("fake-app"))

    def test_a_port_with_no_app_named_is_refused(self):
        self.install()
        with self.assertRaisesRegex(FarmError, "farm start <id> --port N"):
            self.farm.start(port=7869)

    def test_the_cli_passes_a_bare_start_and_stop_through_to_the_choosers(self):
        with patch("farm.farm.Farm", return_value=self.farm), \
                patch.object(self.farm, "start") as start, patch.object(self.farm, "stop") as stop:
            self.assertEqual(main(["start"]), 0)
            self.assertEqual(main(["stop"]), 0)
        start.assert_called_once_with(None, port=None, python=None)
        stop.assert_called_once_with(None)

    def other_python(self, name="other-python3"):
        """A second interpreter for the farm to find, check and choose. What the farm launches is
        recorded by watch_the_launch, so this file never has to be something Windows, macOS and
        Linux can all execute: WinError 193 on windows-latest is what that cost."""
        path = self.root / (name + (".exe" if os.name == "nt" else ""))
        path.write_text("")
        path.chmod(0o755)
        return str(path)

    @contextlib.contextmanager
    def watch_the_launch(self):
        """Record the interpreter the farm launches an app with, and run the app with this one,
        so the app really starts, is really waited for, and is really stopped afterwards."""
        launched = []
        spawn = subprocess.Popen

        def record(command, *args, **kwargs):
            launched.append(command[0])
            return spawn([sys.executable, *command[1:]], *args, **kwargs)

        with patch("farm.farm.subprocess.Popen", side_effect=record):
            yield launched

    def answers_from(self, mapping):
        return lambda host, which: mapping[which]

    def test_a_python_that_cannot_reach_the_tiiny_is_swapped_for_one_that_can(self):
        """Jason, 2026-09-14: "How is an end user going to know that's an issue when they install
        it? They may not have you sitting there to fix it.\""""
        self.configure_device()
        self.install()
        other = self.other_python()
        answers = {sys.executable: (errno.EHOSTUNREACH, "172.17.7.177", (3, 14)),
                   other: (0, "172.17.7.177", (3, 14))}
        with self.watch_the_launch() as launched, \
                patch("farm.farm.python_candidates", return_value=[other]), \
                patch.object(self.farm, "probe_device", side_effect=self.answers_from(answers)):
            self.farm.start("fake-app")
        printed = self.output.getvalue()
        self.assertIn(f"This Python cannot reach your Tiiny, so the farm is running Fake app"
                      f" with {other} instead.", printed)
        self.assertIn("Fake app is running.", printed)
        self.assertNotIn("macOS is blocking", printed)
        self.assertEqual(launched, [other])  # the app was started with the Python the farm chose
        self.assertEqual(json.loads((self.home / "settings.json").read_text())["python"], other)

    def test_the_python_the_farm_settled_on_is_used_again_without_asking(self):
        self.configure_device()
        self.install()
        other = self.other_python()
        self.farm.save_setting("python", other)
        with self.watch_the_launch() as launched, \
                patch("farm.farm.python_candidates", side_effect=AssertionError("searched again")), \
                patch.object(self.farm, "probe_device", return_value=(0, "172.17.7.177", (3, 14))) as probe:
            self.farm.start("fake-app")
        self.assertEqual(probe.call_args.args[1], other)
        self.assertEqual(launched, [other])
        self.assertNotIn("This Python cannot reach", self.output.getvalue())

    def test_an_explicit_python_is_used_saved_and_never_second_guessed(self):
        self.configure_device()
        self.install()
        other = self.other_python()
        with self.watch_the_launch() as launched, \
                patch.object(self.farm, "probe_device", side_effect=AssertionError("probed a choice")):
            self.farm.start("fake-app", python=other)
        self.assertEqual(launched, [other])
        self.assertEqual(json.loads((self.home / "settings.json").read_text())["python"], other)
        self.assertNotIn("This Python cannot reach", self.output.getvalue())

    def test_a_python_that_is_not_there_is_refused_before_anything_starts(self):
        self.install()
        with self.assertRaisesRegex(FarmError, "no Python to run at"):
            self.farm.start("fake-app", python=str(self.root / "no-such-python"))
        self.assertIsNone(self.farm.active("fake-app"))

    def test_a_python_too_old_to_run_an_app_is_never_chosen(self):
        answers = {sys.executable: (errno.EHOSTUNREACH, "172.17.7.177", (3, 14)),
                   "/old/python3": (0, "172.17.7.177", (3, 8))}
        with patch("farm.farm.python_candidates", return_value=["/old/python3"]), \
                patch.object(self.farm, "probe_device", side_effect=self.answers_from(answers)):
            interpreter, moved, refused = self.farm.working_python(sys.executable, "http://172.17.7.177/v1")
        self.assertEqual(interpreter, sys.executable)
        self.assertIsNone(moved)
        self.assertTrue(refused)

    def test_a_tiiny_that_is_switched_off_never_moves_the_python(self):
        """Nothing answering is not the same as macOS refusing, and only one of them is fixable here."""
        answers = {sys.executable: (errno.ECONNREFUSED, "172.17.7.177", (3, 14))}
        with patch("farm.farm.python_candidates", side_effect=AssertionError("searched for a Python")), \
                patch.object(self.farm, "probe_device", side_effect=self.answers_from(answers)):
            interpreter, moved, refused = self.farm.working_python(sys.executable, "http://172.17.7.177/v1")
        self.assertEqual(interpreter, sys.executable)
        self.assertIsNone(moved)
        self.assertFalse(refused)

    def test_the_pythons_looked_for_are_the_known_places_then_path_without_repeats(self):
        suffix = ".exe" if os.name == "nt" else ""
        binaries = self.root / "bin"
        binaries.mkdir()
        real = binaries / ("python3.12" + suffix)
        real.write_text("")
        real.chmod(0o755)
        beside = binaries / ("python3-config" + suffix)  # not an interpreter on either platform
        beside.write_text("")
        beside.chmod(0o755)
        with patch.dict(os.environ, {"PATH": str(binaries)}), \
                patch("farm.farm.python_places", return_value=[str(real)]):
            self.assertEqual(python_candidates(skip=[]), [str(real)])
            self.assertEqual(python_candidates(skip=[str(real)]), [])

    @unittest.skipIf(os.name == "nt", "A symlink needs a privilege Windows runners do not grant")
    def test_two_names_for_one_python_are_listed_once(self):
        binaries = self.root / "bin"
        binaries.mkdir()
        real = binaries / "python3.12"
        real.write_text("")
        real.chmod(0o755)
        (binaries / "python3").symlink_to(real)
        with patch.dict(os.environ, {"PATH": str(binaries)}), \
                patch("farm.farm.python_places", return_value=[]):
            self.assertEqual(python_candidates(skip=[]), [str(binaries / "python3")])

    def test_the_pythons_looked_for_on_windows_are_the_windows_ones(self):
        """windows-latest has no /opt/homebrew, and its interpreters are all called python.exe."""
        root = self.root / "win"
        for made in ("Windows", "Program Files/Python312", "Local/Programs/Python/Python39",
                     "Local/Microsoft/WindowsApps"):
            (root / made).mkdir(parents=True)
        for made in ("Windows/py.exe", "Program Files/Python312/python.exe",
                     "Local/Programs/Python/Python39/python.exe",
                     "Local/Microsoft/WindowsApps/python.exe"):
            (root / made).write_text("")
        # Every place it looks has to come from this temporary tree, including the one a real
        # Windows runner sets and this test does not use, or the runner's own Pythons turn up.
        with patch("farm.farm.WINDOWS", True), patch.dict(os.environ, {
                "SystemRoot": str(root / "Windows"), "ProgramFiles": str(root / "Program Files"),
                "ProgramFiles(x86)": str(root / "nothing here"),
                "LOCALAPPDATA": str(root / "Local")}):
            found = farm_module.python_places()
        self.assertEqual(found, [str(root / "Windows/py.exe"),
                                 str(root / "Program Files/Python312/python.exe"),
                                 str(root / "Local/Programs/Python/Python39/python.exe"),
                                 str(root / "Local/Microsoft/WindowsApps/python.exe")])
        self.assertFalse(any("homebrew" in path for path in found))

    def test_the_windows_names_take_python_exe_and_leave_pythonw_alone(self):
        from farm.farm import PYTHON_NAMED
        for name in ("python.exe", "python3.exe", "python3.12.exe", "PYTHON3.EXE"):
            self.assertTrue(PYTHON_NAMED[True].fullmatch(name), name)
        for name in ("pythonw.exe", "python3-config.exe", "python3", "py.exe"):
            self.assertIsNone(PYTHON_NAMED[True].fullmatch(name), name)

    def test_doctor_passes_and_says_so(self):
        self.configure_device()
        self.install()
        with patch.object(self.farm, "probe_device", return_value=(0, "172.17.7.177", (3, 14))), \
                patch("farm.farm.python_candidates", return_value=[]), \
                patch.object(self.farm, "device_models", return_value=("ok", ["qwen3-4b", "whisper-tiny"])):
            self.assertTrue(self.farm.doctor())
        printed = self.output.getvalue()
        self.assertIn("running apps with " + sys.executable, printed)
        self.assertIn("The Tiiny on file is at http://172.17.7.177/v1.", printed)
        self.assertIn("Your Tiiny at 172.17.7.177 answered this Python in", printed)
        self.assertIn("The key on file is accepted by your Tiiny.", printed)
        self.assertIn("fake-app declares no port.", printed)
        self.assertIn("Your Tiiny lists 2 models: qwen3-4b and whisper-tiny.", printed)
        self.assertIn("Everything the farm checks is working.", printed)

    def test_doctor_fails_and_names_the_python_that_does_reach_it(self):
        self.configure_device()
        self.install()
        answers = {sys.executable: (errno.EHOSTUNREACH, "172.17.7.177", (3, 14)),
                   "/opt/homebrew/bin/python3": (0, "172.17.7.177", (3, 14))}
        with patch("farm.farm.python_candidates", return_value=["/opt/homebrew/bin/python3"]), \
                patch.object(self.farm, "probe_device", side_effect=self.answers_from(answers)):
            self.assertFalse(self.farm.doctor())
        printed = self.output.getvalue()
        self.assertIn("This Python cannot reach your Tiiny at 172.17.7.177, because macOS is"
                      " blocking it from your local network.", printed)
        self.assertIn("Other Pythons here: /opt/homebrew/bin/python3 reaches it.", printed)
        self.assertIn("farm start <id> --python /opt/homebrew/bin/python3", printed)
        self.assertIn("Something above needs attention", printed)

    def test_doctor_reports_a_refused_key_and_never_prints_it(self):
        self.configure_device()
        with patch.object(self.farm, "probe_device", return_value=(0, "172.17.7.177", (3, 14))), \
                patch("farm.farm.python_candidates", return_value=[]), \
                patch("farm.farm.urlopen",
                      side_effect=HTTPError("http://d/v1/models", 401, "no", {}, io.BytesIO(b"{}"))):
            self.assertFalse(self.farm.doctor())
        printed = self.output.getvalue()
        self.assertIn("Your Tiiny refused the key on file.", printed)
        self.assertIn("Fix: copy the key again from TiinyOS", printed)
        self.assertNotIn("device-key", printed)

    def test_doctor_says_when_something_else_holds_an_apps_port(self):
        self.configure_device()
        self.manifest["requires"]["ports"] = [43210]
        self.save_manifest()
        self.install()
        with patch.object(self.farm, "probe_device", return_value=(0, "172.17.7.177", (3, 14))), \
                patch("farm.farm.python_candidates", return_value=[]), \
                patch.object(self.farm, "device_models", return_value=("ok", ["qwen3-4b"])), \
                patch.object(self.farm, "tcp_ready", return_value=True):
            self.assertFalse(self.farm.doctor())
        printed = self.output.getvalue()
        self.assertIn("fake-app declares port 43210, and something else is holding it.", printed)
        self.assertIn("farm start fake-app --port N.", printed)

    def test_doctor_knows_an_app_is_holding_its_own_port(self):
        self.configure_device()
        self.manifest["requires"]["ports"] = [43210]
        self.save_manifest()
        self.install()
        with patch("farm.farm.socket.create_connection", side_effect=[
                ConnectionRefusedError(), contextlib.nullcontext()]), \
                patch.object(self.farm, "probe_device", return_value=(0, "172.17.7.177", (3, 14))), \
                patch("farm.farm.python_candidates", return_value=[]):
            self.farm.start("fake-app")
        with patch.object(self.farm, "probe_device", return_value=(0, "172.17.7.177", (3, 14))), \
                patch("farm.farm.python_candidates", return_value=[]), \
                patch.object(self.farm, "device_models", return_value=("ok", ["qwen3-4b"])), \
                patch.object(self.farm, "tcp_ready", return_value=True):
            self.assertTrue(self.farm.doctor())
        self.assertIn("fake-app declares port 43210, and fake-app itself is holding it.",
                      self.output.getvalue())

    def test_doctor_with_no_tiiny_on_file_and_none_in_sight_says_what_to_run(self):
        with patch.dict(os.environ), patch("farm.farm.python_candidates", return_value=[]):
            os.environ.pop("TIINY_BASE", None)
            self.assertFalse(self.farm.doctor())
        printed = self.output.getvalue()
        self.assertIn("No Tiiny is on file, and nothing answered on the cable, on this network,"
                      " or at the TiinyOS client.", printed)
        self.assertIn("Fix: switch the Tiiny on and plug the cable in, then run farm device"
                      " --find; or run farm device with the address and its API key.", printed)
        found = [note for note in self.farm.findings if note["check"] == "device"]
        self.assertEqual(found[0]["found"], [])

    def test_doctor_with_no_tiiny_on_file_names_the_one_it_can_see(self):
        """The person who has not run farm device yet is the least able to work out what to type,
        so doctor does the looking rather than telling them to go and look."""
        with patch.dict(os.environ), patch("farm.farm.python_candidates", return_value=[]), \
                patch.object(self.farm, "find_tiinys", return_value=seen([ON_THE_CABLE])):
            os.environ.pop("TIINY_BASE", None)
            self.assertFalse(self.farm.doctor())
        printed = self.output.getvalue()
        self.assertIn("No Tiiny is on file, so no app can reach one. The farm can see jason's"
                      " Tiiny (TNYM26072400300011Q) at 172.17.7.177, over the cable,"
                      " base http://172.17.7.177/v1.", printed)
        self.assertIn("Fix: run farm device, take http://172.17.7.177/v1 when it offers it,"
                      " and paste the key from TiinyOS, Settings, API Key.", printed)
        note = [row for row in self.farm.findings if row["check"] == "device"][0]
        self.assertEqual(note["found"], [{"serial": "TNYM26072400300011Q", "name": "jason's Tiiny",
                                          "address": "172.17.7.177", "via": "cable",
                                          "base": "http://172.17.7.177/v1"}])
        self.assertFalse(note["blocked"])
        self.assertIsNone(note["moved"])

    def test_doctor_says_a_refused_python_rather_than_an_absent_tiiny(self):
        with patch.dict(os.environ), patch("farm.farm.python_candidates", return_value=[]), \
                patch.object(self.farm, "find_tiinys",
                             return_value=seen([], blocked=True, python="/opt/conda/bin/python3")):
            os.environ.pop("TIINY_BASE", None)
            self.assertFalse(self.farm.doctor())
        printed = self.output.getvalue()
        self.assertIn("No Tiiny is on file, and the farm cannot tell whether one is there: macOS"
                      " refused /opt/conda/bin/python3 your local network.", printed)
        self.assertIn("Fix: System Settings, Privacy and Security, Local Network, turn on Python,"
                      " then run farm doctor again.", printed)
        self.assertNotIn("nothing answered on the cable", printed)
        note = [row for row in self.farm.findings if row["check"] == "device"][0]
        self.assertTrue(note["blocked"])
        self.assertEqual(note["python"], "/opt/conda/bin/python3")

    def test_doctor_says_which_python_had_to_do_the_looking(self):
        with patch.dict(os.environ), patch("farm.farm.python_candidates", return_value=[]), \
                patch.object(self.farm, "find_tiinys",
                             return_value=seen([ON_THE_CABLE], blocked=True,
                                               moved="/opt/homebrew/bin/python3",
                                               python="/opt/homebrew/bin/python3")):
            os.environ.pop("TIINY_BASE", None)
            self.assertFalse(self.farm.doctor())
        self.assertIn("It had to look with /opt/homebrew/bin/python3, because macOS refused the"
                      " Python it was using, and will run apps with that one from now on.",
                      self.output.getvalue())
        note = [row for row in self.farm.findings if row["check"] == "device"][0]
        self.assertEqual(note["moved"], "/opt/homebrew/bin/python3")

    def test_doctor_warns_when_the_only_answer_came_past_the_local_network(self):
        """The TiinyOS client is loopback, so it answers a Python macOS has refused. Saving that
        address without a word would set somebody up to watch every app fail."""
        client = {"serial": None, "name": None, "address": "openai.api.tiiny",
                  "via": "TiinyOS client", "base": "http://openai.api.tiiny/v1",
                  "interfaces": [], "addresses": []}
        with patch.dict(os.environ), patch("farm.farm.python_candidates", return_value=[]), \
                patch.object(self.farm, "find_tiinys",
                             return_value=seen([client], blocked=True,
                                               python="/opt/conda/bin/python3")):
            os.environ.pop("TIINY_BASE", None)
            self.assertFalse(self.farm.doctor())
        printed = self.output.getvalue()
        self.assertIn("The farm can see A Tiiny at openai.api.tiiny", printed)
        self.assertIn("macOS refused /opt/conda/bin/python3 your local network, so an app the farm"
                      " starts will not reach a Tiiny on the cable or on this network.", printed)
        self.assertIn("Fix: System Settings, Privacy and Security, Local Network, turn on Python,"
                      " then run farm doctor again.", printed)
        self.assertEqual([row["check"] for row in self.farm.findings if not row["ok"]],
                         ["device", "python"])

    def test_doctor_counts_them_when_more_than_one_answered(self):
        second = dict(ON_THE_CABLE, serial="TNYM26072400300012Q", name="the spare",
                      address="192.168.100.94", via="network", base="http://192.168.100.94/v1")
        with patch.dict(os.environ), patch("farm.farm.python_candidates", return_value=[]), \
                patch.object(self.farm, "find_tiinys", return_value=seen([ON_THE_CABLE, second])):
            os.environ.pop("TIINY_BASE", None)
            self.assertFalse(self.farm.doctor())
        self.assertIn("The farm can see 2 of them, the first jason's Tiiny", self.output.getvalue())

    def test_doctor_never_falls_over_because_the_finder_did(self):
        with patch.dict(os.environ), patch("farm.farm.python_candidates", return_value=[]), \
                patch.object(self.farm, "find_tiinys", side_effect=RuntimeError("finder exploded")):
            os.environ.pop("TIINY_BASE", None)
            self.assertFalse(self.farm.doctor())
        self.assertIn("No Tiiny is on file, and nothing answered", self.output.getvalue())
        self.assertNotIn("finder exploded", self.output.getvalue())

    def test_the_cli_exits_one_when_doctor_finds_something(self):
        with patch("farm.farm.Farm", return_value=self.farm):
            with patch.object(self.farm, "doctor", return_value=True):
                self.assertEqual(main(["doctor"]), 0)
            with patch.object(self.farm, "doctor", return_value=False):
                self.assertEqual(main(["doctor"]), 1)

    def test_the_key_is_checked_by_the_python_that_can_reach_the_tiiny(self):
        """Measured on this Mac: the device answered the chosen Python while the CLI's own Python
        was blocked, and asking from the wrong one called a good key bad."""
        answer = json.dumps({"state": "ok", "models": ["qwen3-8b"]})
        done = subprocess.CompletedProcess([], 0, answer, "")
        settings = {"base": "http://172.17.7.177/v1", "key": "device-key"}
        with patch("farm.farm.subprocess.run", return_value=done) as child:
            state, models = self.farm.device_models(settings, "/opt/homebrew/bin/python3")
        self.assertEqual((state, models), ("ok", ["qwen3-8b"]))
        self.assertEqual(child.call_args.args[0][0], "/opt/homebrew/bin/python3")
        self.assertNotIn("device-key", " ".join(child.call_args.args[0]))
        self.assertIn("device-key", child.call_args.kwargs["input"])

    def test_a_refused_key_is_never_answered_with_another_python(self):
        self.configure_device()
        answers = {sys.executable: (0, "172.17.7.177", (3, 14)),
                   "/opt/homebrew/bin/python3": (0, "172.17.7.177", (3, 14))}
        with patch("farm.farm.python_candidates", return_value=["/opt/homebrew/bin/python3"]), \
                patch.object(self.farm, "probe_device", side_effect=self.answers_from(answers)), \
                patch.object(self.farm, "device_models", return_value=("refused", [])):
            self.assertFalse(self.farm.doctor())
        printed = self.output.getvalue()
        self.assertIn("Your Tiiny refused the key on file.", printed)
        self.assertNotIn("--python /opt/homebrew/bin/python3", printed)

    def test_the_models_probe_source_runs_and_never_echoes_the_key(self):
        done = subprocess.run([sys.executable, "-c", MODELS_PROBE, "http://127.0.0.1:1/v1", "2.0"],
                              input="device-key\n", capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout.strip().splitlines()[-1])["state"], "unreachable")
        self.assertNotIn("device-key", done.stdout + done.stderr)

    def catalog_answer(self, cli="0.9.9", apps=()):
        return io.BytesIO(json.dumps({"cli": cli, "apps": list(apps)}).encode())

    def on_a_terminal(self):
        return patch.object(self.output, "isatty", return_value=True)

    def test_a_newer_farm_is_one_line_after_the_work(self):
        """Jason, 2026-09-14: "you're running at X and version XYZ is out.\""""
        with self.on_a_terminal(), patch("farm.farm._version", return_value="0.1.7"), \
                patch("farm.farm.urlopen", return_value=self.catalog_answer("0.1.9")) as asked:
            self.farm.update_notice()
        self.assertEqual(self.output.getvalue(),
                         "farm 0.1.9 is out and you are on 0.1.7. Run: farm self-update\n")
        self.assertEqual(asked.call_args.args[0].full_url, "https://tiinyapp.farm/catalog.json")

    def test_the_farm_you_are_running_says_nothing(self):
        for offered in ("0.1.7", "0.1.6", "", None, "later", ["0.2.0"]):
            with self.subTest(offered=offered), self.on_a_terminal(), \
                    patch("farm.farm._version", return_value="0.1.7"), \
                    patch("farm.farm.urlopen",
                          return_value=io.BytesIO(json.dumps({"cli": offered}).encode())):
                self.farm.update_notice()
                (self.home / "update-check.json").unlink()  # so the next one is looked up again
        self.assertEqual(self.output.getvalue(), "")

    def test_an_older_catalog_that_is_still_a_list_says_nothing(self):
        """A deploy in flight can still be serving the array this file used to be."""
        with self.on_a_terminal(), patch("farm.farm._version", return_value="0.1.7"), \
                patch("farm.farm.urlopen", return_value=io.BytesIO(b'[{"id": "fake-app"}]')):
            self.farm.update_notice()
        self.assertEqual(self.output.getvalue(), "")

    def test_a_script_is_never_told_about_a_new_farm(self):
        with patch("farm.farm._version", return_value="0.1.7"), \
                patch("farm.farm.urlopen", side_effect=AssertionError("asked in a script")):
            self.farm.update_notice()
        self.assertEqual(self.output.getvalue(), "")

    def test_the_check_can_be_turned_off_entirely(self):
        with patch.dict(os.environ, {"FARM_NO_UPDATE_CHECK": "1"}), self.on_a_terminal(), \
                patch("farm.farm._version", return_value="0.1.7"), \
                patch("farm.farm.urlopen", side_effect=AssertionError("asked anyway")):
            self.farm.update_notice()
        self.assertEqual(self.output.getvalue(), "")

    def test_the_cli_flag_turns_the_check_off_for_one_run(self):
        with patch("farm.farm.Farm", return_value=self.farm), \
                patch.object(self.farm, "list") as listing, \
                patch.object(self.farm, "update_notice") as notice:
            self.assertEqual(main(["--no-update-check", "list"]), 0)
            listing.assert_called_once_with()
            notice.assert_not_called()
            self.assertEqual(main(["list"]), 0)
            notice.assert_called_once_with()

    def test_the_cli_flag_is_taken_after_the_command_too(self):
        with patch("farm.farm.Farm", return_value=self.farm), \
                patch.object(self.farm, "list") as listing, \
                patch.object(self.farm, "update_notice") as notice:
            self.assertEqual(main(["list", "--no-update-check"]), 0)
            listing.assert_called_once_with()
            notice.assert_not_called()

    def test_a_command_that_failed_is_not_given_a_version_notice(self):
        errors = io.StringIO()
        with patch("farm.farm.Farm", return_value=self.farm), \
                patch.object(self.farm, "list", side_effect=FarmError("no catalog")), \
                patch.object(self.farm, "update_notice") as notice, \
                contextlib.redirect_stderr(errors):
            self.assertEqual(main(["list"]), 1)
        notice.assert_not_called()
        self.assertIn("no catalog", errors.getvalue())

    def test_the_catalog_is_asked_once_a_day_and_remembered_in_between(self):
        with self.on_a_terminal(), patch("farm.farm._version", return_value="0.1.7"), \
                patch("farm.farm.urlopen", return_value=self.catalog_answer("0.1.9")) as asked:
            self.farm.update_notice()
            self.farm.update_notice()
        self.assertEqual(asked.call_count, 1)
        self.assertEqual(self.output.getvalue().count("farm 0.1.9 is out"), 2)
        stamp = json.loads((self.home / "update-check.json").read_text())
        self.assertEqual(stamp["cli"], "0.1.9")
        with self.on_a_terminal(), patch("farm.farm._version", return_value="0.1.7"), \
                patch("farm.farm.urlopen", return_value=self.catalog_answer("0.2.0")) as asked:
            self.farm.offered_cli(now=stamp["checked"] + 24 * 60 * 60 + 1)
        asked.assert_called_once()

    def test_a_farm_that_cannot_reach_the_catalog_says_nothing_and_stops_asking(self):
        with self.on_a_terminal(), patch("farm.farm._version", return_value="0.1.7"), \
                patch("farm.farm.urlopen", side_effect=URLError("offline")) as asked:
            self.farm.update_notice()
            self.farm.update_notice()
        self.assertEqual(self.output.getvalue(), "")
        self.assertEqual(asked.call_count, 1)
        self.assertEqual(json.loads((self.home / "update-check.json").read_text())["cli"], "")

    def test_self_update_moves_the_farm_and_leaves_the_apps_alone(self):
        done = subprocess.CompletedProcess([], 0, "Successfully installed tiinyapp-farm-0.1.10\n", "")
        with patch("farm.farm.subprocess.run", return_value=done) as pip, \
                patch.object(self.farm, "installed_cli", return_value="0.1.10"), \
                patch("farm.farm._version", return_value="0.1.9"):
            self.farm.self_update()
        self.assertEqual(pip.call_args.args[0],
                         [sys.executable, "-m", "pip", "install", "--upgrade", "tiinyapp-farm"])
        printed = self.output.getvalue()
        self.assertIn("Successfully installed tiinyapp-farm-0.1.10", printed)
        self.assertIn("farm is now 0.1.10.", printed)
        self.assertIn("The next farm command you run is the new one.", printed)
        self.assertFalse((self.app / "current").exists())

    def test_self_update_uses_pipx_when_the_farm_lives_in_a_pipx_venv(self):
        done = subprocess.CompletedProcess([], 0, "upgraded package tiinyapp-farm from 0.1.9 to 0.1.10\n", "")
        with patch("farm.farm.sys.prefix", "/Users/someone/.local/pipx/venvs/tiinyapp-farm"), \
                patch("farm.farm.shutil.which", return_value="/opt/homebrew/bin/pipx"), \
                patch("farm.farm.subprocess.run", return_value=done) as upgrade, \
                patch.object(self.farm, "installed_cli", return_value="0.1.10"):
            self.farm.self_update()
        self.assertEqual(upgrade.call_args.args[0],
                         ["/opt/homebrew/bin/pipx", "upgrade", "tiinyapp-farm"])
        self.assertIn("farm is now 0.1.10.", self.output.getvalue())

    def test_an_upgrade_that_did_not_go_through_says_so_and_keeps_the_version(self):
        done = subprocess.CompletedProcess([], 1, "", "ERROR: Could not find a version\n")
        with patch("farm.farm.subprocess.run", return_value=done), \
                patch("farm.farm._version", return_value="0.1.9"):
            with self.assertRaisesRegex(FarmError, "still 0.1.9"):
                self.farm.self_update()
        self.assertIn("ERROR: Could not find a version", self.output.getvalue())

    def test_doctor_says_when_the_farm_itself_has_fallen_behind(self):
        self.configure_device()
        with patch("farm.farm._version", return_value="0.1.7"), \
                patch.object(self.farm, "offered_cli", return_value="0.1.9"), \
                patch.object(self.farm, "probe_device", return_value=(0, "172.17.7.177", (3, 14))), \
                patch("farm.farm.python_candidates", return_value=[]), \
                patch.object(self.farm, "device_models", return_value=("ok", ["qwen3-8b"])):
            self.assertTrue(self.farm.doctor())
        self.assertIn("farm 0.1.9 is out and you are on 0.1.7. Run: farm self-update",
                      self.output.getvalue())

    # --json: the same commands, answered to a machine. The shapes below are the ones
    # docs/site/11-agents.md documents, so a change here is a change to that page.

    def json_cli(self, *args):
        """One --json command through main(), keeping the prose out of the test's own output."""
        answer, prose = io.StringIO(), io.StringIO()
        with patch("farm.farm.Farm", return_value=self.farm), \
                contextlib.redirect_stdout(answer), contextlib.redirect_stderr(prose):
            code = main([*args, "--json"])
        return code, json.loads(answer.getvalue()), prose.getvalue()

    def test_json_list_carries_the_state_of_every_installed_app_and_the_catalog(self):
        self.install()
        self.other_app(version="0.2.0")
        code, payload, _ = self.json_cli("list")
        self.assertEqual((code, payload["command"]), (0, "list"))
        self.assertEqual(payload["installed"], [{"id": "fake-app", "name": "Fake app",
                                                 "version": "0.1.0", "pitch": self.manifest["pitch"],
                                                 "running": False, "updateAvailable": None}])
        catalog = {row["id"]: row for row in payload["catalog"]}
        self.assertEqual(sorted(catalog), ["fake-app", "other-app"])
        self.assertEqual(catalog["fake-app"]["installed"], "0.1.0")
        self.assertEqual(catalog["other-app"]["installed"], None)
        self.assertEqual(catalog["other-app"]["release"], "ready")

    def test_json_list_says_which_release_a_catalog_entry_has(self):
        del self.manifest["release"]
        self.save_manifest()
        self.assertEqual(self.json_cli("list")[1]["catalog"][0]["release"], "none")
        self.make_release()
        self.manifest["release"]["sha256"] = "pending"
        self.save_manifest()
        self.assertEqual(self.json_cli("list")[1]["catalog"][0]["release"], "pending")

    def test_json_install_answers_with_the_version_the_path_and_what_it_declares(self):
        code, payload, prose = self.json_cli("install", "fake-app", "-y")
        self.assertEqual((code, payload["installed"]), (0, True))
        self.assertEqual(payload["command"], "install")
        self.assertEqual(payload["version"], "0.1.0")
        self.assertEqual(payload["path"], str(self.app / "0.1.0"))
        self.assertFalse(payload["library"])
        self.assertEqual(payload["permissions"], self.manifest["permissions"])
        self.assertIn("Ready.", prose)
        self.assertEqual((self.app / "current").read_text().strip(), "0.1.0")

    def test_json_install_never_asks_and_says_so_without_yes(self):
        with patch("builtins.input", side_effect=AssertionError("asked a question")):
            code, payload, _ = self.json_cli("install", "fake-app")
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"]["command"], "install")
        self.assertIn("--yes", payload["error"]["message"])
        self.assertFalse((self.app / "current").exists())

    def test_json_start_status_and_stop_carry_the_port_the_link_and_the_log(self):
        self.manifest["requires"]["ports"] = [7861]
        self.save_manifest()
        self.install()
        with patch("farm.farm.socket.create_connection", side_effect=[
                ConnectionRefusedError(), contextlib.nullcontext()]):
            code, started, _ = self.json_cli("start", "fake-app")
        self.assertEqual((code, started["running"], started["already"]), (0, True, False))
        self.assertEqual(started["ports"], [7861])
        self.assertEqual(started["port"], 7861)
        self.assertEqual(started["url"], "http://localhost:7861")
        self.assertEqual(started["log"], str(self.app / "farm.log"))
        self.assertEqual(started["pid"], self.farm.active("fake-app"))
        row = self.json_cli("status")[1]["running"][0]
        self.assertEqual(row["id"], "fake-app")
        self.assertEqual((row["pid"], row["port"], row["url"]), (started["pid"], 7861, started["url"]))
        self.assertEqual((row["version"], row["installed"]), ("0.1.0", "0.1.0"))
        self.assertEqual((row["restartToUpdate"], row["health"], row["updateAvailable"]),
                         (False, None, None))
        self.assertGreaterEqual(row["uptime"], 0)
        self.assertEqual(self.json_cli("start", "fake-app")[1]["already"], True)
        code, stopped, _ = self.json_cli("stop", "fake-app")
        self.assertEqual((code, stopped), (0, {"command": "stop", "id": "fake-app", "stopped": True}))
        self.assertEqual(self.json_cli("stop", "fake-app")[1]["stopped"], False)
        self.assertEqual(self.json_cli("status")[1], {"command": "status", "running": []})

    def test_json_start_and_stop_with_no_id_name_the_apps_instead_of_asking(self):
        self.install()
        self.other_app(install=True)
        with patch("builtins.input", side_effect=AssertionError("asked a question")):
            code, payload, _ = self.json_cli("start")
            self.assertEqual(code, 1)
            self.assertEqual(payload["error"]["message"],
                             "Run: farm start <id>, naming one of fake-app and other-app.")
            self.assertEqual(self.json_cli("stop")[1]["error"]["message"], "Nothing is running.")

    def test_json_check_lists_what_is_newer_and_all_takes_it(self):
        self.install()
        self.assertEqual(self.json_cli("check")[1],
                         {"command": "check", "updates": [], "unreachable": [], "updated": []})
        self.make_release("0.2.0")
        self.manifest["release"]["notes"] = "Faster starts."
        self.save_manifest()
        code, payload, _ = self.json_cli("check")
        self.assertEqual((code, payload["updated"]), (0, []))
        self.assertEqual(payload["updates"], [{"id": "fake-app", "name": "Fake app",
                                               "installed": "0.1.0", "available": "0.2.0",
                                               "notes": "Faster starts.",
                                               "updatedAt": self.manifest["updatedAt"]}])
        self.assertEqual(self.json_cli("check", "--all")[1]["updated"], ["fake-app"])
        self.assertEqual((self.app / "current").read_text().strip(), "0.2.0")

    def test_json_update_says_what_moved_and_what_did_not(self):
        self.install()
        code, payload, _ = self.json_cli("update", "fake-app")
        self.assertEqual((code, payload["updated"]), (0, False))
        self.assertEqual((payload["previous"], payload["version"], payload["available"]),
                         ("0.1.0", "0.1.0", None))
        self.make_release("0.2.0")
        code, payload, _ = self.json_cli("update", "fake-app")
        self.assertEqual((code, payload["updated"], payload["running"]), (0, True, False))
        self.assertEqual((payload["previous"], payload["version"], payload["available"]),
                         ("0.1.0", "0.2.0", "0.2.0"))

    def test_json_doctor_carries_every_line_it_prints_with_its_fix(self):
        self.configure_device()
        self.install()
        with patch.object(self.farm, "probe_device", return_value=(0, "172.17.7.177", (3, 14))), \
                patch("farm.farm.python_candidates", return_value=[]), \
                patch.object(self.farm, "device_models", return_value=("refused", [])):
            code, payload, prose = self.json_cli("doctor")
        self.assertEqual((code, payload["ok"]), (1, False))
        for finding in payload["findings"]:
            self.assertIn(finding["message"], prose)
            if finding["fix"]:
                self.assertIn("Fix: " + finding["fix"], prose)
        found = {finding["check"]: finding for finding in payload["findings"]}
        self.assertEqual(found["device"]["ok"], True)
        self.assertEqual(found["device"]["address"], "172.17.7.177")
        self.assertEqual(found["key"]["ok"], False)
        self.assertEqual(found["key"]["fix"],
                         "copy the key again from TiinyOS, Settings, API Key, then run farm device.")
        self.assertEqual(found["app"], {"check": "app", "ok": True, "fix": None, "id": "fake-app",
                                        "message": "fake-app declares no port."})
        self.assertNotIn("device-key", json.dumps(payload))

    def test_json_doctor_names_the_app_and_the_port_something_else_is_holding(self):
        self.configure_device()
        self.manifest["requires"]["ports"] = [43210]
        self.save_manifest()
        self.install()
        with patch.object(self.farm, "probe_device", return_value=(0, "172.17.7.177", (3, 14))), \
                patch("farm.farm.python_candidates", return_value=[]), \
                patch.object(self.farm, "device_models", return_value=("ok", ["qwen3-4b"])), \
                patch.object(self.farm, "tcp_ready", return_value=True):
            code, payload, _ = self.json_cli("doctor")
        held = next(f for f in payload["findings"] if f["check"] == "port")
        self.assertEqual((code, payload["ok"], held["ok"]), (1, False, False))
        self.assertEqual((held["id"], held["port"]), ("fake-app", 43210))
        self.assertEqual(held["fix"], "stop whatever has it, or put the app somewhere else:"
                                      " farm start fake-app --port N.")
        self.assertEqual(next(f for f in payload["findings"] if f["check"] == "models")["models"],
                         ["qwen3-4b"])

    def test_json_errors_use_the_sentence_a_person_would_see(self):
        code, payload, _ = self.json_cli("start", "fake-app")
        self.assertEqual((code, payload), (1, {"error": {"command": "start", "id": "fake-app",
                                                         "message": "fake-app is not installed."}}))
        self.assertEqual(self.json_cli("install", "Upper", "-y")[1]["error"]["message"],
                         "Invalid app id; use lowercase letters, digits and dashes (not tiiny).")

    def test_json_puts_one_object_on_stdout_and_the_prose_on_standard_error(self):
        env = os.environ | {"HOME": str(self.root), "USERPROFILE": str(self.root),
                            "FARM_CATALOG": str(self.catalog)}
        command = [sys.executable, str(ROOT / "farm/farm.py")]
        done = subprocess.run(command + ["install", "fake-app", "--json", "-y"],
                              env=env, text=True, capture_output=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["version"], "0.1.0")
        self.assertEqual(done.stdout.count("\n"), 1)
        self.assertIn("Ready. Run: farm start fake-app", done.stderr)
        done = subprocess.run(command + ["list", "--json"], env=env, text=True,
                              capture_output=True, timeout=60)
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        self.assertEqual([row["id"] for row in json.loads(done.stdout)["installed"]], ["fake-app"])

    @contextlib.contextmanager
    def catalog_offering(self, version):
        """A local site whose catalog.json publishes this farm version, so the update notice
        has something to say. The live site is never asked anything by a test."""
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                raw = json.dumps({"cli": version, "apps": []}).encode()
                self.send_response(200 if self.path == "/catalog.json" else 404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def through_a_terminal(self, arguments, origin):
        """One farm command whose standard output really is a terminal, and what reached it.

        The other on_a_terminal above patches this test's own stdout; this one gives a child
        process a real one, which is the only way to see what a person would see."""
        import pty
        primary, secondary = pty.openpty()
        env = os.environ | {"HOME": str(self.root), "USERPROFILE": str(self.root),
                            "FARM_CATALOG": str(self.catalog), "FARM_API_ORIGIN": origin}
        env.pop("FARM_NO_UPDATE_CHECK", None)
        written = []
        def drain():
            while True:
                try:
                    chunk = os.read(primary, 65536)
                except OSError:
                    return
                if not chunk:
                    return
                written.append(chunk)
        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        try:
            done = subprocess.run([sys.executable, str(ROOT / "farm/farm.py"), *arguments],
                                  env=env, stdout=secondary, stderr=subprocess.PIPE, timeout=60)
        finally:
            os.close(secondary)
            reader.join(10)
            os.close(primary)
        return done, b"".join(written).decode().replace("\r\n", "\n")

    @unittest.skipIf(os.name == "nt", "pseudo-terminals are POSIX")
    def test_a_terminal_asking_for_json_is_given_json_and_no_update_notice(self):
        """Jason's farm says when a newer farm is out. That line is for a person, so it never
        lands in the middle of an answer meant for a machine, terminal or not."""
        self.install()
        stamp = self.root / ".tiinyapps/update-check.json"
        with self.catalog_offering("99.0.0") as origin:
            done, answered = self.through_a_terminal(["list", "--json"], origin)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual([row["id"] for row in json.loads(answered)["installed"]], ["fake-app"])
            self.assertNotIn("is out and you are on", answered)
            # It did not even look: nothing asked the site, so nothing was remembered.
            self.assertFalse(stamp.exists())
            # The same command without --json is where a person gets told.
            done, said = self.through_a_terminal(["list"], origin)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn(f"farm 99.0.0 is out and you are on {farm_module._version()}."
                          " Run: farm self-update", said)
            self.assertTrue(stamp.exists())
