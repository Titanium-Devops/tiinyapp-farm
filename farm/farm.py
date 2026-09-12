#!/usr/bin/env python3
"""Install and run tinyapp.farm apps. Python 3.11+, standard library, POSIX."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import getpass
import hashlib
from html.parser import HTMLParser
from http.client import HTTPException
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import threading
from urllib.parse import unquote, urlsplit
from urllib.request import urlopen
import warnings

CATALOG = "https://tinyapp.farm/manifests/"
ID = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
START_TIMEOUT = 10.0
MAX_DOWNLOAD = 512 * 1024 * 1024
MAX_UNPACKED = 2 * 1024 * 1024 * 1024


class FarmError(Exception):
    pass


def app_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value) or value == "tiiny":
        raise FarmError("Invalid app id; use lowercase letters, digits and dashes (not tiiny).")
    return value


def atomic_write(path, text, mode=0o600):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=".farm-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            os.fchmod(out.fileno(), mode)
            out.write(text)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_manifest(manifest, ident):
    """Check all fields the installer consumes; catalog CI uses the full schema."""
    if not isinstance(manifest, dict) or manifest.get("id") != app_id(ident):
        raise FarmError("Catalog manifest id does not match the requested app.")
    version = manifest.get("version")
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise FarmError("Manifest version must be three nonnegative numbers.")
    for field in ("name", "pitch", "description"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            raise FarmError(f"Manifest needs {field}.")
    release = manifest.get("release")
    if not isinstance(release, dict) or not isinstance(release.get("url"), str) or not release["url"]:
        raise FarmError("Manifest needs a release URL.")
    sha = release.get("sha256")
    if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{64}|pending", sha):
        raise FarmError("Invalid release checksum.")
    if type(release.get("size")) is not int or release["size"] < 0:  # noqa: E721 - JSON integers exclude booleans.
        raise FarmError("Invalid release size.")
    permissions = manifest.get("permissions")
    if not isinstance(permissions, list) or any(p not in ("microphone", "files", "network", "device") for p in permissions):
        raise FarmError("Invalid permissions.")
    requires = manifest.get("requires")
    if not isinstance(requires, dict) or not isinstance(requires.get("ports"), list):
        raise FarmError("Manifest needs its requirements and ports.")
    if any(type(p) is not int or not 1 <= p <= 65535 for p in requires["ports"]):  # noqa: E721 - JSON integers exclude booleans.
        raise FarmError("Invalid port.")
    health = manifest.get("health")
    if "health" in manifest and (not isinstance(health, str)
                               or not re.fullmatch(r"/[A-Za-z0-9_./-]+", health)
                               or health.startswith("//") or not requires["ports"]):
        raise FarmError("Health must be a local HTTP path with a declared port.")
    py = requires.get("python")
    if py is not None and (not isinstance(py, str) or not re.fullmatch(r"[0-9]+\.[0-9]+", py)):
        raise FarmError("Invalid Python requirement.")
    device = requires.get("device")
    if (not isinstance(device, dict) or not isinstance(device.get("models"), list)
            or any(not isinstance(m, str) or not m for m in device["models"])
            or type(device.get("npuUnits")) is not int or device["npuUnits"] < 0):  # noqa: E721 - JSON integers exclude booleans.
        raise FarmError("Invalid device requirements.")
    entry = manifest.get("entry", False)
    if entry is None:
        if "library" not in manifest.get("tags", []):
            raise FarmError("A null entry must be tagged library.")
    elif isinstance(entry, dict) and set(entry) == {"python", "args"}:
        if (not isinstance(entry["python"], str)
                or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*", entry["python"])
                or not isinstance(entry["args"], list)
                or any(not isinstance(a, str) for a in entry["args"])):
            raise FarmError("Invalid Python entry.")
    elif isinstance(entry, dict) and set(entry) == {"command"} and isinstance(entry["command"], str):
        if not shlex.split(entry["command"]):
            raise FarmError("Empty command entry.")
    else:
        raise FarmError("Invalid app entry.")
    return manifest


class CatalogLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            name = Path(unquote(urlsplit(dict(attrs).get("href", "")).path)).name
            if name.endswith(".json") and ID.fullmatch(name[:-5]) and name != "index.json":
                self.ids.add(app_id(name[:-5]))


class Farm:
    def __init__(self, home=None, catalog=None):
        self.home = Path(home) if home is not None else Path.home() / "tinyapps"
        self.catalog = str(catalog or os.environ.get("FARM_CATALOG", CATALOG))
        parsed = urlsplit(self.catalog)
        self.local_catalog = (Path(unquote(parsed.path)) if parsed.scheme == "file"
                              else Path(self.catalog).expanduser() if not parsed.scheme else None)

    def app_dir(self, ident):
        path = self.home / app_id(ident)
        if path.is_symlink():
            raise FarmError("App directory must not be a symlink.")
        return path

    @contextmanager
    def guard(self, ident):
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        locks = self.home / ".locks"
        locks.mkdir(exist_ok=True, mode=0o700)
        with (locks / (app_id(ident) + ".lock")).open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def manifest(self, ident):
        ident = app_id(ident)
        if self.local_catalog is not None:
            result = read_json(self.local_catalog / (ident + ".json"))
        else:
            with urlopen(self.catalog.rstrip("/") + "/" + ident + ".json", timeout=30) as response:
                data = response.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024:
                raise FarmError("Manifest exceeds 1 MiB.")
            result = json.loads(data)
        return validate_manifest(result, ident)

    def installed(self, ident):
        app = self.app_dir(ident)
        try:
            version = (app / "current").read_text().strip()
        except FileNotFoundError:
            raise FarmError(f"{ident} is not installed.") from None
        if not VERSION.fullmatch(version):
            raise FarmError("Invalid current version record.")
        root = app / version
        if root.is_symlink():
            raise FarmError("Version directory must not be a symlink.")
        manifest = validate_manifest(read_json(root / ".farm-manifest.json"), ident)
        if manifest["version"] != version:
            raise FarmError("Installed version metadata does not match current.")
        return root, manifest

    def catalog_ids(self):
        if self.local_catalog is not None:
            return sorted(app_id(p.stem) for p in self.local_catalog.glob("*.json") if p.name != "index.json")
        with urlopen(self.catalog.rstrip("/") + "/", timeout=30) as response:
            raw = response.read(2 * 1024 * 1024).decode("utf-8")
        if raw.lstrip().startswith("["):
            entries = json.loads(raw)
            return sorted({app_id(x if isinstance(x, str) else x["id"]) for x in entries})
        parser = CatalogLinks()
        parser.feed(raw)
        if not parser.ids:
            raise FarmError("Catalog must serve a JSON array of ids or links to manifest JSON files.")
        return sorted(parser.ids)

    def list(self):
        print("Installed:")
        for current in sorted(self.home.glob("*/current")):
            _, manifest = self.installed(current.parent.name)
            print(f"  {manifest['id']} {manifest['version']} — {manifest['name']}")
        print("Catalog:")
        for ident in self.catalog_ids():
            manifest = self.manifest(ident)
            draft = " [release pending]" if manifest["release"]["sha256"] == "pending" else ""
            print(f"  {ident} {manifest['version']} — {manifest['pitch']}{draft}")

    def download(self, release, destination):
        location = release["url"]
        parsed = urlsplit(location)
        if self.local_catalog is not None and not parsed.scheme:
            source = (self.local_catalog / location).open("rb")
        elif parsed.scheme == "file" and self.local_catalog is not None:
            source = Path(unquote(parsed.path)).open("rb")
        elif parsed.scheme in ("http", "https"):
            source = urlopen(location, timeout=30)
        else:
            raise FarmError("Release must use HTTP(S); local archives require a local catalog.")
        digest = hashlib.sha256()
        size = 0
        with source, destination.open("wb") as out:
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_DOWNLOAD:
                    raise FarmError("Archive exceeds the 512 MiB download limit.")
                digest.update(chunk)
                out.write(chunk)
        if digest.hexdigest() != release["sha256"]:
            raise FarmError("Checksum mismatch; archive was not unpacked or run.")
        if size != release["size"]:
            raise FarmError("Archive size does not match the manifest.")

    @staticmethod
    def unpack(archive, destination, entry):
        size = 0
        count = 0
        with tarfile.open(archive, "r:*") as tar:
            for member in tar:
                count += 1
                parts = PurePosixPath(member.name).parts
                if (member.name.startswith("/") or ".." in parts or "\\" in member.name
                        or not (member.isfile() or member.isdir())):
                    raise FarmError("Unsafe archive member; paths, links and special files are refused.")
                size += member.size
                if size > MAX_UNPACKED or count > 100000:
                    raise FarmError("Archive exceeds extraction limits.")
                if not parts:
                    if member.isdir():
                        continue
                    raise FarmError("Invalid archive member.")
                target = destination.joinpath(*parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source = tar.extractfile(member)
                    if source is None:
                        raise FarmError("Archive file has no content stream.")
                    with source, target.open("xb") as out:
                        shutil.copyfileobj(source, out)
                    target.chmod(0o755 if member.mode & 0o111 else 0o644)
        children = list(destination.iterdir())
        if not children:
            raise FarmError("Empty release archive.")
        # GitHub tarballs have a single wrapper; a bare Python package is already a root.
        module = entry.get("python", "").split(".")[0] if entry else ""
        if len(children) == 1 and children[0].is_dir() and children[0].name != module:
            return children[0]
        return destination

    def install(self, ident, yes=False, update=False):
        with self.guard(ident):
            manifest = self.manifest(ident)
            app = self.app_dir(ident)
            if update:
                _, previous = self.installed(ident)
                if tuple(map(int, manifest["version"].split("."))) <= tuple(map(int, previous["version"].split("."))):
                    print(f"{ident} is up to date; no downgrade performed.")
                    return
            elif (app / "current").exists():
                raise FarmError(f"{ident} is already installed; use farm update.")
            release = manifest["release"]
            if release["sha256"] == "pending":
                raise FarmError("Release checksum is pending; this catalog draft cannot be installed.")
            py = manifest["requires"].get("python", "3.11")
            if tuple(map(int, py.split("."))) > sys.version_info[:2]:
                raise FarmError(f"This app needs Python {py} or newer.")
            print(f"{manifest['name']} {manifest['version']}\n{manifest['pitch']}")
            print("Permissions: " + ", ".join(manifest["permissions"]))
            print("Needs: " + json.dumps(manifest["requires"], sort_keys=True))
            if not yes and input("Install this release? [y/N] ").strip().lower() not in ("y", "yes"):
                print("Cancelled.")
                return
            # Stage and verify before touching the installed version or stopping an app.
            with tempfile.TemporaryDirectory(prefix=".install-", dir=self.home) as temporary:
                stage = Path(temporary)
                archive = stage / "release.tar"
                self.download(release, archive)
                content = stage / "content"
                content.mkdir()
                root = self.unpack(archive, content, manifest["entry"])
                atomic_write(root / ".farm-manifest.json", json.dumps(manifest, indent=2) + "\n")
                app.mkdir(exist_ok=True, mode=0o700)
                destination = app / manifest["version"]
                if destination.exists():
                    raise FarmError("Version directory already exists; refusing to overwrite it.")
                if update:
                    self._stop(ident)
                (app / "data").mkdir(exist_ok=True, mode=0o700)
                if (app / "data").is_symlink():
                    raise FarmError("Data directory must not be a symlink.")
                os.replace(root, destination)
                atomic_write(app / "launcher.json", json.dumps({"id": ident, "entry": manifest["entry"]}) + "\n")
                atomic_write(app / "current", manifest["version"] + "\n")
            print(f"Installed {ident} {manifest['version']}. " +
                  ("Library only; copy onelane.py into your app." if manifest["entry"] is None
                   else f"Run: farm start {ident}"))

    def device(self, base=None, key_stdin=False):
        scripted = base is not None or key_stdin or any(
            name in os.environ for name in ("TIINY_BASE", "TIINY_KEY"))
        if scripted:
            base = (base if base is not None else os.environ.get("TIINY_BASE", "")).strip()
            key = (sys.stdin.read() if key_stdin else os.environ.get("TIINY_KEY", "")).strip()
            if not base:
                raise FarmError("Provide --base or TIINY_BASE for device import.")
        else:
            # Refuse getpass's echoing fallback when no secure terminal is available.
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                base = getpass.getpass("Device base URL (hidden): ").strip()
                key = getpass.getpass("Device API key (hidden): ").strip()
        parsed = urlsplit(base)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise FarmError("Use an HTTP(S) base URL without credentials, query or fragment.")
        if not key:
            raise FarmError("Device key must not be empty.")
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_write(self.home / "device.json", json.dumps({"base": base, "key": key}) + "\n")
        print("Device settings saved.")

    def environment(self, ident, manifest):
        app = self.app_dir(ident)
        data = app / "data"
        data.mkdir(exist_ok=True, mode=0o700)
        if data.is_symlink():
            raise FarmError("Data directory must not be a symlink.")
        env = os.environ.copy()
        env.update(FARM_DATA_DIR=str(data), TIINY_DATA_DIR=str(data),
                   ONELANE_DIR=str(self.home / ".onelane"), PYTHONUNBUFFERED="1")
        (self.home / ".onelane").mkdir(exist_ok=True, mode=0o700)
        config = self.home / "device.json"
        if config.exists():
            config.chmod(0o600)
            settings = read_json(config)
            if not isinstance(settings, dict) or not all(isinstance(settings.get(k), str) for k in ("base", "key")):
                raise FarmError("Invalid device settings; run farm device.")
            env.update(TIINY_BASE=settings["base"], TIINY_KEY=settings["key"])
        if env.get("TIINY_BASE"):
            host = urlsplit(env["TIINY_BASE"]).hostname
            if host:
                env["TIINY_HOST"] = f"[{host}]" if ":" in host else host
        if ident == "story-lantern":
            if not manifest["requires"]["ports"]:
                raise FarmError("Story Lantern needs its declared HTTP port.")
            env.update(LANTERN_HOME=str(data), LANTERN_DB=str(data / "lantern.db"),
                       LANTERN_SAFETY_JSONL=str(data / "safety-events.jsonl"),
                       LANTERN_BLOCKLIST=str(data / "blocklist_extra.txt"),
                       PORT=str(manifest["requires"]["ports"][0]))
        return env

    def active(self, ident):
        app = self.app_dir(ident)
        try:
            pid = int((app / "farm.pid").read_text())
            if pid <= 1:
                return None
            # Apps inherit this descriptor. A stale PID alone never authorizes a signal.
            with (app / ".run.lock").open("a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return None
                except BlockingIOError:
                    pass
            return pid
        except (FileNotFoundError, ProcessLookupError, ValueError):
            return None

    @staticmethod
    def tcp_ready(port, timeout=0.2):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=timeout):
                return True
        except PermissionError:
            # Permission errors must not masquerade as an available port.
            raise
        except OSError:
            return False

    @staticmethod
    def health(port, path, timeout=0.5):
        result = []

        def request():
            try:
                with urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as response:
                    payload = json.loads(response.read(65537))
                if isinstance(payload, dict) and payload.get("ok") is not False:
                    result.append(payload)
            except (OSError, ValueError, HTTPException):
                pass

        # Socket timeouts alone do not bound a peer trickling headers/body bytes.
        # A daemon probe cannot hold the CLI open past this wall-clock deadline.
        probe = threading.Thread(target=request, daemon=True)
        probe.start()
        probe.join(timeout)
        return result[0] if not probe.is_alive() and result else None

    @staticmethod
    def startup_error(app, message):
        # Read backwards so old log history need not be loaded or scanned.
        log = app / "farm.log"
        tail = ""
        if log.exists():
            with log.open("rb") as source:
                position = source.seek(0, os.SEEK_END)
                chunks = []
                newlines = 0
                while position and newlines <= 10:
                    size = min(position, 8192)
                    position -= size
                    source.seek(position)
                    chunk = source.read(size)
                    chunks.append(chunk)
                    newlines += chunk.count(b"\n")
                tail = "\n".join(b"".join(reversed(chunks)).decode("utf-8", errors="replace").splitlines()[-10:])
        return FarmError(message + ("\n" + tail if tail else ""))

    def start(self, ident, port=None):
        if port is not None and (type(port) is not int or not 1 <= port <= 65535):  # noqa: E721
            raise FarmError("Port must be an integer between 1 and 65535.")
        with self.guard(ident):
            root, manifest = self.installed(ident)
            app = self.app_dir(ident)
            if self.active(ident):
                print(f"{ident} is already running.")
                return
            entry = manifest["entry"]
            if entry is None:
                raise FarmError(f"{ident} is a library, not a runnable app.")
            command = ([sys.executable, "-m", entry["python"], *entry["args"]]
                       if "python" in entry else shlex.split(entry["command"]))
            if command[0] in ("python", "python3"):
                command[0] = sys.executable
            ports = list(manifest["requires"]["ports"])
            if port is not None:
                ports = [port, *ports[1:]]
            for candidate in ports:
                if self.tcp_ready(candidate):
                    raise self.startup_error(app, f"Port {candidate} is already in use; use farm start {ident} --port N.")
            env = self.environment(ident, manifest)
            if ports:
                env["TINYAPP_PORT"] = str(ports[0])
                if ident == "titanium-tiiny-bot":
                    env["TIINY_PORT"] = str(ports[0])
                    # Lite's manifest supplies --port, which takes precedence over env.
                    for index, argument in enumerate(command):
                        if argument == "--port" and index + 1 < len(command):
                            command[index + 1] = str(ports[0])
                        elif argument.startswith("--port="):
                            command[index] = f"--port={ports[0]}"
                elif ident == "story-lantern":
                    env["PORT"] = str(ports[0])
            with (app / ".run.lock").open("a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise FarmError("Another process still holds the app's runtime lock.") from None
                with (app / "farm.log").open("ab") as log:
                    process = subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.DEVNULL,
                                               stdout=log, stderr=log, start_new_session=True,
                                               pass_fds=(lock.fileno(),))
                try:
                    atomic_write(app / "farm.pid", str(process.pid) + "\n")
                    atomic_write(app / "process.json", json.dumps({"started": time.time(),
                                 "ports": ports, "version": manifest["version"], "health": manifest.get("health")}) + "\n")
                    deadline = time.monotonic() + START_TIMEOUT
                    while True:
                        time.sleep(min(0.1, max(0, deadline - time.monotonic())))
                        if process.poll() is not None:
                            raise self.startup_error(app, f"{ident} exited at startup (exit {process.returncode}).")
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise self.startup_error(app, f"{ident} timed out waiting for readiness after {START_TIMEOUT:g} s.")
                        ready = True
                        for index, candidate in enumerate(ports):
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                ready = False
                                break
                            if index == 0 and manifest.get("health"):
                                ready = self.health(candidate, manifest["health"], min(0.5, remaining)) is not None
                            else:
                                ready = self.tcp_ready(candidate, min(0.2, remaining))
                            if not ready:
                                break
                        if ready:
                            # Check again after I/O: the child may have exited during a probe.
                            if process.poll() is not None:
                                raise self.startup_error(app, f"{ident} exited at startup (exit {process.returncode}).")
                            break
                except BaseException:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
                    (app / "farm.pid").unlink(missing_ok=True)
                    (app / "process.json").unlink(missing_ok=True)
                    raise
            threading.Thread(target=process.wait, daemon=True).start()
            print(f"Started {ident}: pid {process.pid}; log {app / 'farm.log'}")

    def _stop(self, ident):
        app = self.app_dir(ident)
        pid = self.active(ident)
        if pid:
            try:
                os.killpg(pid, signal.SIGINT)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + 5
            while self.active(ident) and time.monotonic() < deadline:
                time.sleep(0.05)
            if self.active(ident):
                os.killpg(pid, signal.SIGKILL)
                deadline = time.monotonic() + 2
                while self.active(ident) and time.monotonic() < deadline:
                    time.sleep(0.05)
                if self.active(ident):
                    raise FarmError("App did not stop after SIGKILL; keeping its process records.")
        (app / "farm.pid").unlink(missing_ok=True)
        (app / "process.json").unlink(missing_ok=True)
        return bool(pid)

    def stop(self, ident):
        with self.guard(ident):
            print(f"Stopped {ident}." if self._stop(ident) else f"{ident} is not running.")

    def status(self):
        print("APP PID PORT UPTIME VERSION")
        for path in sorted(self.home.glob("*/farm.pid")):
            ident = path.parent.name
            with self.guard(ident):
                pid = self.active(ident)
                if pid:
                    info = read_json(path.parent / "process.json")
                    ports = ",".join(map(str, info["ports"])) or "-"
                    _, manifest = self.installed(ident)
                    version = info.get("version", "unknown")
                    note = ""
                    health_path = info.get("health", manifest.get("health"))
                    if health_path and info["ports"]:
                        health = self.health(info["ports"][0], health_path)
                        if health is None:
                            note = " (health unavailable)"
                        elif isinstance(health.get("version"), str) and VERSION.fullmatch(health["version"]):
                            version = health["version"]
                        else:
                            note = " (health version unavailable)"
                    detail = f"running {version}"
                    if version != manifest["version"]:
                        detail += f", installed {manifest['version']}: restart to update"
                    print(f"{ident} {pid} {ports} {max(0, int(time.time() - info['started']))}s {detail}{note}")

    def remove(self, ident, purge=False):
        with self.guard(ident):
            app = self.app_dir(ident)
            if not app.exists():
                raise FarmError(f"{ident} is not installed.")
            self._stop(ident)
            for path in app.iterdir():
                if path.name == "data" and not purge:
                    continue
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            if purge or not any(app.iterdir()):
                app.rmdir()
            print(f"Removed {ident}; " + ("data purged." if purge else "data kept."))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("install", "update", "start", "stop", "remove"):
        command = commands.add_parser(name)
        command.add_argument("id")
        if name in ("install", "update"):
            command.add_argument("--yes", "-y", action="store_true", help="Accept the install prompt")
        if name == "start":
            command.add_argument("--port", type=int, help="Override the app's primary listening port")
        if name == "remove":
            command.add_argument("--purge", action="store_true", help="Also delete saved data")
    device = commands.add_parser("device")
    device.add_argument("--base", help="Device HTTP(S) base URL (or TIINY_BASE)")
    device.add_argument("--key-stdin", action="store_true", help="Read the device API key from stdin (or TIINY_KEY)")
    for name in ("status", "list"):
        commands.add_parser(name)
    args = parser.parse_args(argv)
    farm = Farm()
    try:
        if args.command in ("install", "update"):
            farm.install(args.id, yes=args.yes, update=args.command == "update")
        elif args.command == "device":
            farm.device(base=args.base, key_stdin=args.key_stdin)
        elif args.command == "remove":
            farm.remove(args.id, purge=args.purge)
        elif args.command == "start":
            farm.start(args.id, port=args.port)
        elif args.command == "stop":
            farm.stop(args.id)
        else:
            getattr(farm, args.command)()
    except (FarmError, OSError, ValueError, KeyError, TypeError, tarfile.TarError, getpass.GetPassWarning) as error:
        # Do not interpolate network/JSON errors: they can contain credentials.
        print(f"farm: {error}" if isinstance(error, FarmError) else
              f"farm: {type(error).__name__}; check the catalog, app files or device settings.", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("Cancelled.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
