import contextlib
import copy
import getpass
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch

from farm.farm import Farm, FarmError, main

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_manifest", ROOT / "scripts/check-manifest.py")
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


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / "manifests/titanium-tiiny-bot.json").read_text())

    def test_three_catalog_manifests(self):
        paths = sorted((ROOT / "manifests").glob("*.json"))
        self.assertEqual(len(paths), 3)
        for path in paths:
            with self.subTest(path=path.name):
                validator.check_manifest(json.loads(path.read_text()), allow_pending=True)

    def test_pending_requires_explicit_flag(self):
        with self.assertRaisesRegex(ValueError, "allow-pending"):
            validator.check_manifest(self.manifest)
        self.manifest["release"]["sha256"] = "a" * 64
        validator.check_manifest(self.manifest)

    def test_validator_cli(self):
        path = ROOT / "manifests/titanium-tiiny-bot.json"
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


class FarmTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="farm-test-")
        self.root = Path(self.temp.name)
        self.home = self.root / "tinyapps"
        self.catalog = self.root / "catalog"
        self.catalog.mkdir()
        self.farm = Farm(self.home, self.catalog)
        self.app = self.home / "fake-app"
        self.manifest = json.loads((ROOT / "manifests/titanium-tiiny-bot.json").read_text())
        self.manifest.update(id="fake-app", name="Fake app", version="0.1.0",
                             entry={"python": "fake", "args": []})
        self.manifest["requires"]["ports"] = [43210]
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
        for name, kind in [("../../escape", None), ("/absolute", None),
                           ("fake/symlink", tarfile.SYMTYPE), ("fake/hardlink", tarfile.LNKTYPE),
                           ("fake/fifo", tarfile.FIFOTYPE)]:
            with self.subTest(name=name):
                self.make_release(members=[(name, b"x", kind)])
                with self.assertRaisesRegex(FarmError, "Unsafe archive"):
                    self.install()
                self.assertFalse((self.app / "current").exists())
        self.assertFalse((self.root / "escape").exists())

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
        self.assertIn(f"fake-app {pid} 43210", self.output.getvalue())
        self.assertNotIn("private-key", self.output.getvalue())
        self.farm.start("fake-app")
        self.assertEqual(int((self.app / "farm.pid").read_text()), pid)
        self.farm.stop("fake-app")
        self.assertIsNone(self.farm.active("fake-app"))
        self.assertFalse((self.app / "farm.pid").exists())

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
        with patch("farm.farm.os.killpg") as kill:
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
        self.assertEqual(config.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(config.read_text())["key"], "secret-value")
        self.assertNotIn("secret-value", self.output.getvalue())
        config.chmod(0o644)
        with patch("getpass.getpass", side_effect=["http://example.test/v1", "new-secret"]):
            self.farm.device()
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
        env = os.environ | {"HOME": str(self.root), "FARM_CATALOG": str(self.catalog)}
        result = subprocess.run([sys.executable, str(ROOT / "farm/farm.py"), "install", "fake-app", "--yes"],
                                env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([sys.executable, str(ROOT / "farm/farm.py"), "list"],
                                env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("fake-app", result.stdout)

    def test_cli_errors_do_not_echo_keys(self):
        errors = io.StringIO()
        with patch("farm.farm.Farm.device", side_effect=ValueError("contains-secret-key")):
            with contextlib.redirect_stderr(errors):
                self.assertEqual(main(["device"]), 1)
        self.assertNotIn("contains-secret-key", errors.getvalue())
