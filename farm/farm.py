#!/usr/bin/env python3
"""Install and run tiinyapp.farm apps. Python 3.9+, standard library, macOS, Linux and Windows."""
from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stdout
import errno
import getpass
import hashlib
from html.parser import HTMLParser
from http.client import HTTPException
import ipaddress
import json
import mimetypes
import ntpath
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
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
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import (ProxyHandler, Request, build_opener, getproxies_environment,
                            url2pathname)
import warnings

CATALOG = "https://tiinyapp.farm/manifests/"
API_ORIGIN = "https://tiinyapp.farm"
ID = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
START_TIMEOUT = 10.0
# A line about a newer version is worth a moment, never a stall on an unreachable catalog.
ADVISORY_TIMEOUT = 5.0
# How an app takes its port when its manifest does not say.
PORT_DEFAULT = {"env": "TIINYAPP_PORT"}
PORT_FLAG = re.compile(r"--?[A-Za-z0-9][A-Za-z0-9-]*\Z")
PORT_ENV = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
MAX_DOWNLOAD = 512 * 1024 * 1024
# Where a Tiiny answers /device.json on the local network.
DEVICE_PORT = 39218
LOCAL_NETWORK_TIMEOUT = 2.0
# A Tiiny on a cable sits on its own point to point /30 inside this /16, the box on the first
# usable address of the /30 and this machine on the second, so four boxes plugged in at once are
# four /30s. Nothing here shells out: an app that reads addresses out of ifconfig fails the archive
# scan, and the CLI holds itself to the rule it holds apps to.
USB_NET_PREFIX = "172.17."
# device.json advertises both of these itself. Sending the token to the port, unicast or broadcast,
# gets the whole of device.json back in one datagram, which finds a box whose address has moved
# since somebody last wrote it down.
UDP_DISCOVERY_PORT = 39217
DISCOVERY_TOKEN = b"GADGET_DISCOVER_V1"
# What the TiinyOS client on a Mac publishes for the box it is paired with.
TIINYOS_BASE = "http://openai.api.tiiny/v1"
# One probe, and the whole search. A box that is not there is absent rather than slow, so these are
# ceilings that nothing reaches rather than waits that everything pays.
FIND_TIMEOUT = 1.2
FIND_BUDGET = 6.0
# The cable never moves, a network address does, and the TiinyOS client knows its box by no serial
# number at all, so that is the order a found device is worth offering in.
VIA_CABLE, VIA_NETWORK, VIA_CLIENT = "cable", "network", "TiinyOS client"
VIA_ORDER = (VIA_CABLE, VIA_NETWORK, VIA_CLIENT)
VIA_WORDS = {VIA_CABLE: "over the cable", VIA_NETWORK: "on this network",
             VIA_CLIENT: "through the TiinyOS client"}
# 65 on macOS, 113 on Linux, and Windows sockets answer with the WSA number instead.
NO_ROUTE = {errno.EHOSTUNREACH, 10065}
# How often the farm looks to see whether the farm itself has moved on, and how long it waits.
UPDATE_CHECK_EVERY = 24 * 60 * 60
UPDATE_CHECK_TIMEOUT = 2.0
WINDOWS = os.name == "nt"
MAX_UNPACKED = 2 * 1024 * 1024 * 1024
MAX_PUBLISH = 50 * 1024 * 1024
PUBLISH_EXCLUDES = {".git", "node_modules", "__pycache__", ".venv"}
PUBLISH_FIELDS = {"id", "name", "pitch", "description", "version", "license", "category", "entry", "permissions", "links", "media"}
PUBLISH_CATEGORIES = {"assistant", "family", "audio", "developer-tools", "library"}


class FarmError(Exception):
    pass


@contextmanager
def file_lock(lock, blocking=True):
    """Lock one stable byte on Windows, or the file description on POSIX."""
    if WINDOWS:
        import msvcrt
        lock.seek(0, os.SEEK_END)
        if not lock.tell():
            lock.write(b"\0")
            lock.flush()
        while True:
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError as error:
                if error.errno not in (13, 11, 36):
                    raise
                if not blocking:
                    raise BlockingIOError from error
                time.sleep(0.05)
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(lock, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        # Closing the parent's descriptor preserves an inherited runtime lock.
        yield


class WindowsProcess:
    """A held kernel handle prevents PID reuse between identity check and stop."""
    def __init__(self, pid):
        import ctypes
        from ctypes import wintypes
        self.ctypes = ctypes
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.api.OpenProcess.restype = wintypes.HANDLE
        self.api.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        self.api.GetProcessTimes.restype = wintypes.BOOL
        self.api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.api.WaitForSingleObject.restype = wintypes.DWORD
        self.api.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.api.TerminateProcess.restype = wintypes.BOOL
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api.CloseHandle.restype = wintypes.BOOL
        self.handle = self.api.OpenProcess(0x1000 | 0x100000 | 0x0001, False, pid)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        times = [wintypes.FILETIME() for _ in range(4)]
        if not self.api.GetProcessTimes(self.handle, *(ctypes.byref(t) for t in times)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error
        self.identity = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime

    def running(self):
        result = self.api.WaitForSingleObject(self.handle, 0)
        if result == 0xffffffff:
            raise self.ctypes.WinError(self.ctypes.get_last_error())
        return result == 258

    def terminate(self):
        if not self.api.TerminateProcess(self.handle, 1) and self.running():
            raise self.ctypes.WinError(self.ctypes.get_last_error())

    def close(self):
        self.api.CloseHandle(self.handle)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def windows_reserved(part):
    if hasattr(ntpath, "isreserved"):
        return ntpath.isreserved(part)
    return PureWindowsPath(part).is_reserved()


def private_mode(path):
    try:
        Path(path).chmod(0o600)
    except OSError:
        if not WINDOWS:
            raise


# One opener for everything the farm fetches, with a proxy handler that is handed the environment
# rather than left to ask the machine.
#
# Measured on macOS 25.6 on 2026-09-14. Two things that are each harmless on their own corrupt this
# process when they happen in order: the macOS system proxy lookup that urllib's default
# ProxyHandler runs when nobody hands it a dict, and then any name lookup. After those two, every
# fork in this process yields a child that dies of SIGSEGV before it reaches exec. Building the
# handler once from the environment keeps the first of them from ever running.
#
# It has to be fixed at the fetch rather than at the fork, because Farm.start cannot avoid forking.
# CPython posix_spawns only when cwd is None, pass_fds is empty and start_new_session is off, and a
# started app needs all three: the directory it runs in, the lock it inherits, and the session that
# detaches it. So an app launched after a poisoned fetch would exit -11, and no launch flag can fix
# that.
#
# HTTP_PROXY, HTTPS_PROXY, NO_PROXY and their lowercase spellings go on working, because that is
# what getproxies_environment reads and what proxy_bypass consults first. What is given up is a
# proxy configured in macOS System Settings and named nowhere else.
def farm_opener():
    """Every handler urllib would install, with the proxy one handed the environment.

    A proxy handler with nothing in it has no hooks to register, so an environment with no proxy
    set leaves the opener with no proxy handler at all, which is the quiet version of the same
    thing: nobody asks the machine.
    """
    return build_opener(ProxyHandler(getproxies_environment()))


_OPENER = farm_opener()


def urlopen(url, timeout):
    """Fetch one URL through the farm's own opener.

    Stands in for urllib.request.urlopen, and takes the timeout as an argument rather than a
    default because everything the farm opens has to carry one.
    """
    return _OPENER.open(url, timeout=timeout)


def open_url(url, timeout=30):
    """Every fetch the CLI makes carries its own User-Agent. Cloudflare's Browser Integrity Check
    answers 403 to Python's default agent on tiinyapp.farm, which is what made `farm install` fail
    for a brand-new user on 2026-09-12."""
    request = Request(url, headers={"User-Agent": "tiinyapp-farm/" + _version(), "Accept": "*/*"})
    try:
        return urlopen(request, timeout=timeout)
    except HTTPError as error:
        error.close()
        raise FarmError(f"HTTP {error.code} from {urlsplit(url).netloc}{urlsplit(url).path}") from None
    except URLError as error:
        raise FarmError(f"Could not reach {urlsplit(url).netloc}: {error.reason}") from None


def app_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value) or value == "tiiny":
        raise FarmError("Invalid app id; use lowercase letters, digits and dashes (not tiiny).")
    return value


def atomic_write(path, text, mode=0o600):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=".farm-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            if WINDOWS:
                private_mode(temporary)
            else:
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
        raise FarmError("That catalog entry is for a different app; its id does not match the one you asked for.")
    version = manifest.get("version")
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise FarmError("This app's catalog entry needs a version of three nonnegative numbers.")
    for field in ("name", "pitch", "description"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            raise FarmError(f"This app's catalog entry is missing its {field}.")
    if "release" in manifest:
        release = manifest.get("release")
        if not isinstance(release, dict) or not isinstance(release.get("url"), str) or not release["url"]:
            raise FarmError("This app's catalog entry is missing its release URL.")
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
        raise FarmError("This app's catalog entry is missing what it needs and the ports it uses.")
    if any(type(p) is not int or not 1 <= p <= 65535 for p in requires["ports"]):  # noqa: E721 - JSON integers exclude booleans.
        raise FarmError("Invalid port.")
    health = manifest.get("health")
    if "health" in manifest and (not isinstance(health, str)
                               or not re.fullmatch(r"/[A-Za-z0-9_./-]+", health)
                               or health.startswith("//") or not requires["ports"]):
        raise FarmError("Health must be a local HTTP path with a declared port.")
    page = manifest.get("open")
    if "open" in manifest and (not isinstance(page, str)
                               or not re.fullmatch(r"/[A-Za-z0-9_./-]*", page)
                               or page.startswith("//") or not requires["ports"]):
        raise FarmError("The open page must be a local path with a declared port.")
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
    takes = manifest.get("port", PORT_DEFAULT)
    if takes is not None:
        if not isinstance(takes, dict) or set(takes) not in ({"argv"}, {"env"}):
            raise FarmError("Port must name one of argv or env, or be null for a fixed port.")
        if "argv" in takes and not (isinstance(takes["argv"], str) and PORT_FLAG.fullmatch(takes["argv"])):
            raise FarmError("Port argv must be a command line flag.")
        if "env" in takes and not (isinstance(takes["env"], str) and PORT_ENV.fullmatch(takes["env"])):
            raise FarmError("Port env must be an environment variable name.")
    return manifest


def port_mechanism(manifest):
    """How an app takes its port: {"argv": flag}, {"env": name}, or None when it is fixed."""
    return manifest.get("port", PORT_DEFAULT)


def set_port_argument(command, flag, port):
    """Put the port on the command line after the flag the manifest names."""
    value = str(port)
    for index, argument in enumerate(command):
        if argument == flag:
            if index + 1 < len(command) and command[index + 1].isdigit():
                command[index + 1] = value
            else:
                command.insert(index + 1, value)
            return
        if argument.startswith(flag + "="):
            command[index] = f"{flag}={value}"
            return
    command += [flag, value]


class CatalogLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            name = Path(unquote(urlsplit(dict(attrs).get("href", "")).path)).name
            if name.endswith(".json") and ID.fullmatch(name[:-5]) and name != "index.json":
                self.ids.add(app_id(name[:-5]))


PERMISSION_WORDS = {"microphone": "your microphone", "files": "your files",
                    "network": "the network", "device": "your Tiiny"}


def join_words(parts):
    """A list the way a person says one: alone, two and three, or one, two and three."""
    parts = list(parts)
    if len(parts) < 2:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def describe_permissions(permissions):
    """The access an app declares, as a sentence rather than a row of field names."""
    words = [PERMISSION_WORDS[name] for name in permissions if name in PERMISSION_WORDS]
    if not words:
        return "It declares no access to anything on this computer."
    return "It can reach " + join_words(words) + "."


def describe_maker(manifest):
    """Who wrote it and whether the farm has looked at it, in one line."""
    author = manifest.get("author")
    name = author.get("name") if isinstance(author, dict) else None
    made = f"Made by {name}." if isinstance(name, str) and name.strip() else "Its maker is not named in the catalog."
    return made + (" The farm has reviewed it." if manifest.get("verified") is True
                   else " The farm has not reviewed it yet.")


def describe_size(size):
    """A download size a person can picture."""
    if size >= 1000000:
        return f"{size / 1000000:.1f} MB"
    if size >= 1000:
        return f"{round(size / 1000)} KB"
    return f"{size} bytes"


def landing_page(manifest):
    """The page farm start points at: the open field when the app names one, otherwise the root."""
    page = manifest.get("open", "/")
    return page if isinstance(page, str) and page.startswith("/") else "/"


def app_link(port, manifest):
    page = landing_page(manifest)
    return f"http://localhost:{port}" + ("" if page == "/" else page)


def url_host(address):
    """An IPv6 literal needs its brackets before it can go in a URL."""
    return f"[{address}]" if ":" in address else address


# The places a second Python 3 lives on a Mac, before anything on PATH.
PYTHON_PLACES = ("/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3")
# Windows keeps its interpreters somewhere else and names them differently, and pythonw.exe is
# deliberately not one of them: an app the farm starts writes to its log through a console handle.
PYTHON_NAMED = {False: re.compile(r"python3(\.[0-9]+)?"),
                True: re.compile(r"python(3(\.[0-9]+)?)?\.exe", re.IGNORECASE)}
MOST_PYTHONS_TRIED = 6


def runnable(path):
    try:
        return Path(path).is_file() and os.access(path, os.X_OK)
    except OSError:
        return False


def windows_python_places():
    """The launcher, then the per machine installs, the per user installs, and last the Microsoft
    Store alias, which is a stub until somebody installs Python behind it."""
    places = [str(Path(os.environ.get("SystemRoot", "C:\\Windows")) / "py.exe")]
    local = os.environ.get("LOCALAPPDATA")
    roots = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")]
    if local:
        roots.append(str(Path(local) / "Programs"))
    for root in roots:
        if not root:
            continue
        for pattern in ("Python*/python.exe", "Python*/Python*/python.exe"):
            # Per machine installs sit at Python312, per user ones at Programs/Python/Python312.
            try:
                places.extend(sorted(str(path) for path in Path(root).glob(pattern)))
            except OSError:
                continue
    if local:
        places.append(str(Path(local) / "Microsoft" / "WindowsApps" / "python.exe"))
    return places


def python_places():
    return windows_python_places() if WINDOWS else list(PYTHON_PLACES)


def python_candidates(skip=()):
    """Every Python 3 worth trying on this machine, the well known places first, then PATH,
    one entry per real binary and never one we already know cannot reach the Tiiny."""
    found = []
    seen = set()
    for path in skip:
        try:
            seen.add(Path(path).resolve())
        except OSError:
            pass
    named = PYTHON_NAMED[WINDOWS]
    places = python_places()
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        try:
            places.extend(sorted(str(entry) for entry in Path(directory).iterdir()
                                 if named.fullmatch(entry.name)))
        except OSError:
            continue
    for path in places:
        if not runnable(path):
            continue
        try:
            real = Path(path).resolve()
        except OSError:
            continue
        if real in seen:
            continue
        seen.add(real)
        found.append(path)
    return found


def newer_version(offered, running):
    """Whether the catalog is publishing a farm newer than this one. Anything unreadable is not."""
    if not isinstance(offered, str) or not VERSION.fullmatch(offered) or not VERSION.fullmatch(running or ""):
        return False
    return tuple(map(int, offered.split("."))) > tuple(map(int, running.split(".")))


def private_address(address):
    """Only a local network address can be the one macOS is refusing."""
    try:
        return ipaddress.ip_address(address).is_private
    except ValueError:
        return False


# --------------------------------------------------------------- finding a Tiiny
# Jason, 2026-09-14: "will the launcher not be able to FIND the tiiny?" It asked for an address
# blind. A person with a Pocket Lab on the cable and no TiinyOS client had nothing to type.
def _remaining(deadline, most):
    """What is left of the search's budget, capped at one probe's own ceiling."""
    return max(0.05, min(most, deadline - time.monotonic()))


def run_probe(command, timeout, stdin=None):
    """Ask another interpreter something, without forking this one.

    Measured on macOS 25.6 on 2026-09-14: once urllib has been through the macOS name and proxy
    path for a host it could not fetch, every fork in this process produces a child that dies of
    SIGSEGV before it reaches exec. subprocess forks whenever close_fds is on and posix_spawns when
    it is off, and the spawn survives it, so every probe asks for the spawn. Nothing of the farm's
    rides along: Python has opened its descriptors close-on-exec since PEP 446, so the fds that
    close_fds would have closed are closed anyway.

    Without this a Tiiny on the TiinyOS client's hostname makes farm doctor report that no other
    Python on the machine can reach the device, and stops the farm ever moving apps to one that
    can, because every child it asks is killed before it can answer. Found while building the
    finder, which walks the same Pythons.
    """
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                          close_fds=False, input=stdin)


def host_addresses():
    """Every 172.17 address this machine holds, settled by bind and nothing else.

    bind succeeds only on an address the host really has, so asking it of each candidate says which
    cables are plugged in without reading ifconfig and without sending a packet. A /30 has two
    usable addresses and this machine takes one of them, so 32768 candidates cover the whole /16.
    Measured at 0.35 s on an M-series Mac.
    """
    found = []
    for third in range(256):
        for block in range(0, 256, 4):
            for last in (block + 2, block + 1):
                address = f"{USB_NET_PREFIX}{third}.{last}"
                probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    probe.bind((address, 0))
                except OSError:
                    continue
                finally:
                    probe.close()
                found.append(address)
                break
    return found


def usb_peers():
    """The box's side of every cable in this machine, by arithmetic on our own side.

    A /30 holds a network address, two usable addresses and a broadcast. Ours is one of the two, so
    the box is the other, and no probe is needed to work out which.
    """
    peers = []
    for address in host_addresses():
        head, last = address.rsplit(".", 1)
        ours = int(last)
        network = ours & ~3
        peer = f"{head}.{network + 2 if ours == network + 1 else network + 1}"
        if peer not in peers:
            peers.append(peer)
    return peers


def device_json(address, timeout=FIND_TIMEOUT):
    """What the box at this address says about itself, and the routing error if it said nothing.

    No credential is involved. The discovery page is open, which is what lets the farm find a Tiiny
    before anybody has handed it a key, and the serial number in the answer means this identifies a
    box rather than merely finding an open port.

    A Python that macOS has refused the local network is told EHOSTUNREACH here rather than left in
    silence, and that is a different answer from a box that is not switched on. The errno is the
    only thing that tells the two apart, so it comes back with the payload.
    """
    try:
        with urlopen(f"http://{url_host(address)}:{DEVICE_PORT}/device.json", timeout=timeout) as answer:
            found = json.loads(answer.read(256 * 1024))
    except HTTPError as error:
        error.close()
        return None, 0
    except URLError as error:
        return None, getattr(error.reason, "errno", None) or 0
    except (OSError, ValueError, HTTPException) as error:
        return None, getattr(error, "errno", None) or 0
    return (found, 0) if isinstance(found, dict) and found.get("serial_number") else (None, 0)


def udp_devices(targets, timeout=FIND_TIMEOUT, grace=0.4):
    """Ask every Tiiny in earshot to introduce itself, in one datagram each.

    One packet finds what a port scan would need a whole sweep for, and it finds a box whose address
    has moved. The wait ends shortly after the first answer, because the rest of the budget was only
    ever for boxes that are not there. The routing error of the last datagram that could not be sent
    comes back with the answers, for the same reason the discovery page's does.
    """
    found, seen, refused = [], set(), 0
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except OSError:
            pass  # A host that forbids broadcast can still be asked directly.
        asked = False
        for target in targets:
            try:
                sock.sendto(DISCOVERY_TOKEN, (target, UDP_DISCOVERY_PORT))
                asked = True
            except OSError as error:
                refused = error.errno or refused
                continue
        if not asked:
            return found, refused
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            try:
                sock.settimeout(max(0.05, left))
                data, where = sock.recvfrom(65535)
            except (socket.timeout, OSError):
                break
            try:
                payload = json.loads(data.decode("utf-8", "replace"))
            except ValueError:
                continue
            if not isinstance(payload, dict) or not payload.get("serial_number"):
                continue
            if (where[0], payload["serial_number"]) in seen:
                continue
            seen.add((where[0], payload["serial_number"]))
            found.append((where[0], payload))
            deadline = min(deadline, time.monotonic() + grace)
    finally:
        sock.close()
    return found, refused


def tiinyos_serving(timeout=FIND_TIMEOUT):
    """Whether the TiinyOS client on this Mac is serving a Tiiny's model API.

    The client answers every name under api.tiiny on loopback, so a name that resolves proves
    nothing and the surface has to be asked. It refuses an unknown caller with 401, which is the
    answer that says a Tiiny is behind it; 404 or a refused connection says there is not. No key is
    sent, and no body is read, because a body can carry one.
    """
    try:
        with urlopen(TIINYOS_BASE + "/models", timeout=timeout) as answer:
            return answer.status != 404
    except HTTPError as error:
        error.close()
        return error.code != 404
    except (OSError, ValueError, HTTPException):
        return False


def device_interfaces(payload):
    """Every plane the box reports it is on, the cable and the network alike."""
    found = []
    for entry in (payload or {}).get("ipv4_addresses") or []:
        if not isinstance(entry, dict):
            continue
        address, interface = entry.get("address"), entry.get("interface")
        if isinstance(address, str) and address:
            found.append({"interface": interface if isinstance(interface, str) else "",
                          "address": address})
    return found


def device_base(payload, address):
    """The base URL the farm would save for a box at this address.

    Firmware 1.0 serves the model API on port 80 behind a virtual host, which is the form the docs
    use and so carries no port. Older firmware served it on 8800, and a device.json that names a
    backend port of its own is taken at its word rather than guessed at. Live firmware reports that
    port as 0, meaning it is not saying.
    """
    backend = (payload or {}).get("backend")
    port = backend.get("port") if isinstance(backend, dict) else None
    if isinstance(port, int) and not isinstance(port, bool) and port not in (0, 80):
        return f"http://{url_host(address)}:{port}/v1"
    return f"http://{url_host(address)}/v1"


def fold_device(records, address, payload, via):
    """Register one answer, or merge it into the box that already answered.

    One box answers on the cable and on the network at once, and answers the responder as well as
    its own discovery page, so the serial number is what says how many Tiinys are really there. An
    address only counts as the cable when it is the far end of a cable in this machine: a box on
    somebody else's desk advertises its USB address too, and that address is not ours to use.
    """
    serial = payload.get("serial_number")
    record = records.get(serial)
    if record is None:
        record = {"serial": serial, "name": payload.get("device_name") or payload.get("hostname"),
                  "address": address, "via": via, "addresses": [],
                  "interfaces": device_interfaces(payload), "payload": payload}
        records[serial] = record
    if address not in record["addresses"]:
        record["addresses"].append(address)
    if VIA_ORDER.index(via) < VIA_ORDER.index(record["via"]):
        record.update(via=via, address=address, payload=payload)
    if not record["interfaces"]:
        record["interfaces"] = device_interfaces(payload)
    return record


def probe_network(peers, budget=FIND_BUDGET):
    """Every Tiiny this machine can see, folded together by serial number, and the routing error
    met on the way if there was one.

    Three ways, in the order a found address is worth trusting. The cable is a /30 that never moves.
    The responder answers a broadcast, so it finds a box on the network as well, and finds one whose
    address has changed. The TiinyOS client is asked only when the first two found nothing, because
    the box it serves is the box on the cable and naming it twice would read as two Tiinys.

    Everything here puts a packet on the wire, which is why it is one function: macOS grants the
    local network per binary, so where this runs decides what it can see, and the farm runs all of
    it under the interpreter whose answer counts. The TiinyOS client is the exception, being
    loopback, and is asked anyway.
    """
    deadline = time.monotonic() + budget
    records, refused = {}, 0
    for peer in peers:
        payload, code = device_json(peer, timeout=_remaining(deadline, FIND_TIMEOUT))
        if payload:
            fold_device(records, peer, payload, VIA_CABLE)
        elif code in NO_ROUTE:
            refused = code
    answers, code = udp_devices(["255.255.255.255"] + list(peers),
                                timeout=_remaining(deadline, FIND_TIMEOUT))
    for address, payload in answers:
        fold_device(records, address, payload, VIA_CABLE if address in peers else VIA_NETWORK)
    if code in NO_ROUTE:
        refused = code
    found = sorted(records.values(), key=lambda r: (VIA_ORDER.index(r["via"]), r["serial"] or ""))
    for record in found:
        record["base"] = device_base(record.pop("payload"), record["address"])
    if not found and tiinyos_serving(timeout=_remaining(deadline, FIND_TIMEOUT)):
        found = [{"serial": None, "name": None, "address": urlsplit(TIINYOS_BASE).hostname,
                  "via": VIA_CLIENT, "base": TIINYOS_BASE, "interfaces": [], "addresses": []}]
    # Having reached a box over the cable or the network is proof the local network was not
    # refused, whatever else could not be sent. A host can forbid broadcast and route everything
    # else, and a GitHub macOS runner does exactly that, so a datagram that went nowhere is not
    # evidence on its own. The TiinyOS client does not count: it answers on loopback, which a
    # refused interpreter reaches as readily as an allowed one.
    reached = any(record["via"] in (VIA_CABLE, VIA_NETWORK) for record in found)
    return {"found": found, "errno": 0 if reached else refused}


def describe_device(record):
    """One line: which box, where it is, how it was reached, and the base URL to save."""
    named = record.get("name") or "A Tiiny"
    serial = f" ({record['serial']})" if record.get("serial") else ""
    return (f"{named}{serial} at {record['address']}, {VIA_WORDS[record['via']]},"
            f" base {record['base']}")


# Run by the interpreter the farm runs apps with, when that is not the one running the CLI. It
# imports this very module out of the directory it was handed, so the child runs the same finder
# rather than a second copy of it, and nothing secret goes anywhere near the command line.
FIND_PROBE = """import json, sys
sys.path.insert(0, sys.argv[1])
from farm.farm import probe_network
answer = probe_network(json.loads(sys.argv[2]), float(sys.argv[3]))
answer["python"] = list(sys.version_info[:2])
print(json.dumps(answer))
"""


# Run by the interpreter that reaches the Tiiny, with the key on stdin so no command line
# anywhere on this machine ever carries it.
MODELS_PROBE = """import json, sys, urllib.error, urllib.request
base, timeout = sys.argv[1], float(sys.argv[2])
key = sys.stdin.readline().strip()
answer = {"state": "unreachable", "models": []}
try:
    request = urllib.request.Request(base.rstrip("/") + "/models", headers={
        "Authorization": "Bearer " + key, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read(1024 * 1024))
    listed = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(listed, list):
        answer = {"state": "ok", "models": [m["id"] for m in listed
                                            if isinstance(m, dict) and isinstance(m.get("id"), str)]}
    else:
        answer["state"] = "unreadable"
except urllib.error.HTTPError as error:
    error.close()
    answer["state"] = "refused" if error.code in (401, 403) else "http " + str(error.code)
except Exception:
    answer["state"] = "unreachable"
print(json.dumps(answer))
"""


# Run by the interpreter an app runs under, when that is not the one running the CLI.
DEVICE_PROBE = """import json, socket, sys, urllib.error, urllib.request
host, port, timeout = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
answer = {"errno": 0, "address": "", "python": list(sys.version_info[:2])}
try:
    answer["address"] = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)[0][4][0]
    where = answer["address"]
    if ":" in where:
        where = "[" + where + "]"
    urllib.request.urlopen("http://" + where + ":" + str(port) + "/device.json", timeout=timeout).close()
except urllib.error.HTTPError:
    pass
except urllib.error.URLError as error:
    answer["errno"] = getattr(error.reason, "errno", 0) or 0
except OSError as error:
    answer["errno"] = error.errno or 0
print(json.dumps(answer))
"""


def describe_requirements(requires):
    """What an app needs, in the words the install prompt shows a person."""
    parts = []
    if requires.get("python"):
        parts.append(f"Python {requires['python']} or newer")
    ports = list(requires.get("ports") or [])
    if ports:
        parts.append(("port " if len(ports) == 1 else "ports ") + ", ".join(map(str, ports)))
    device = requires.get("device") or {}
    models = list(device.get("models") or [])
    if models:
        parts.append("your Tiiny, for " + ", ".join(models))
    if device.get("npuUnits"):
        parts.append(f"{device['npuUnits']} NPU units")
    return ", ".join(parts) if parts else "nothing beyond Python"


def newer(installed, available):
    """Whether the catalog's version is strictly ahead of the one on disk."""
    return tuple(map(int, available.split("."))) > tuple(map(int, installed.split(".")))


def release_note(manifest):
    """The one line a release may carry about what changed, when the catalog carries one."""
    note = (manifest.get("release") or {}).get("notes")
    lines = note.strip().splitlines() if isinstance(note, str) else []
    return lines[0].strip()[:200] if lines else ""


def update_available(installed, latest):
    """The catalog version when it is a newer release a person could take, otherwise nothing."""
    if not isinstance(latest, dict) or "release" not in latest or latest["release"]["sha256"] == "pending":
        return ""
    return latest["version"] if newer(installed["version"], latest["version"]) else ""


def describe_update(latest, installed):
    """One row of the update list: what is installed, what is out, and why it changed."""
    line = f"{latest['name']} {installed['version']}, {latest['version']} is out"
    note = release_note(latest)
    if note:
        return line + ". " + (note if note.endswith((".", "!", "?")) else note + ".")
    day = latest.get("updatedAt")
    if isinstance(day, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        return line + f", dated {day}."
    return line + "."


def interactive():
    """Whether a person is there to answer a question, or this is a script."""
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def ask_which(question, count, everything=False):
    """The one question the farm's choosers ask, and what the answer to it means.

    Returns the indexes chosen and the answer as typed. The indexes are None when there was nobody
    there to answer, and empty both when the person left them alone and when they named something
    that is not on the list, which the answer tells apart."""
    if everything:
        return list(range(count)), "all"
    if not interactive():
        return None, ""
    try:
        answer = input(question).strip().lower()
    except EOFError:
        # Windows calls NUL a terminal, so a script can reach the question anyway.
        # End of input is nobody there, not a person cancelling.
        print()
        return None, ""
    if not answer:
        return [], ""
    if answer == "all":
        return list(range(count)), answer
    if answer.isascii() and answer.isdigit() and 1 <= int(answer) <= count:
        return [int(answer) - 1], answer
    return [], answer


def ask_yes(question):
    """One question whose default is yes. None when there was nobody there to answer it."""
    if not interactive():
        return None
    try:
        answer = input(question).strip().lower()
    except EOFError:
        print()
        return None
    return not answer or answer in ("y", "yes")


def name_one(verb, idents):
    """How to do it by hand, for when there was nobody there to ask."""
    return (f"Run: farm {verb} {idents[0]}." if len(idents) == 1 else
            f"Run: farm {verb} <id>, naming one of {join_words(idents)}.")


class Farm:
    def __init__(self, home=None, catalog=None, api_origin=None):
        # What the last doctor run said, one entry per line it printed, so --json can hand an
        # agent the same sentences a person reads instead of a second set written beside them.
        self.findings = []
        self.home = Path(home) if home is not None else Path.home() / "tiinyapps"
        self.config_home = Path(home) if home is not None else Path.home() / ".tiinyapps"
        self.catalog = str(catalog or os.environ.get("FARM_CATALOG", CATALOG))
        self.api_origin = str(api_origin or os.environ.get("FARM_API_ORIGIN", API_ORIGIN)).rstrip("/")
        parsed = urlsplit(self.catalog)
        self.local_catalog = (Path(url2pathname(parsed.path)) if parsed.scheme == "file"
                              else Path(self.catalog).expanduser()
                              if not parsed.scheme or (WINDOWS and Path(self.catalog).is_absolute()) else None)

    @staticmethod
    def valid_token(token):
        return isinstance(token, str) and re.fullmatch(r"farm_[A-Za-z0-9_-]{40}", token) is not None

    def login(self, token=None, token_stdin=False):
        if token is None and token_stdin:
            token = sys.stdin.readline().strip()
        if token is None:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", getpass.GetPassWarning)
                    token = getpass.getpass("Farm API token (hidden): ").strip()
            except getpass.GetPassWarning:
                raise FarmError("No terminal to hide the token. Pipe it in instead: printf '%s' \"$(pbpaste)\" | farm login --token-stdin")
        if isinstance(token, str):
            token = token.strip().strip("\"'")
        if not self.valid_token(token):
            seen = f"{len(token)} characters starting {token[:5]!r}" if isinstance(token, str) else "nothing"
            raise FarmError(f"That is not a farm token: got {seen}; expected farm_ followed by 40 characters. Copy it again from your account page.")
        self.config_home.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_write(self.config_home / "token", token + "\n")
        print("Farm token saved.")

    def token(self, explicit=None):
        token = explicit if explicit is not None else os.environ.get("FARM_TOKEN")
        if token is None:
            try:
                path = self.config_home / "token"
                token = path.read_text(encoding="utf-8").strip()
                private_mode(path)
            except FileNotFoundError:
                raise FarmError("No API token. Run farm login or pass --token.") from None
        if not self.valid_token(token):
            raise FarmError("Use a valid farm_ API token.")
        return token

    def api(self, path, token, method="GET", body=None, content_type=None):
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json", "User-Agent": "tiinyapp-farm/" + _version()}
        if content_type:
            headers["Content-Type"] = content_type
        request = Request(self.api_origin + path, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=60) as response:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise FarmError("The farm returned an unexpectedly large response.")
        except HTTPError as error:
            try:
                detail = json.loads(error.read(1024 * 1024)).get("error")
            except (ValueError, AttributeError):
                detail = None
            error.close()
            raise FarmError(detail or f"The farm answered HTTP {error.code}.") from None
        except URLError:
            raise FarmError("Could not reach tiinyapp.farm.") from None
        try:
            return json.loads(raw)
        except (UnicodeDecodeError, ValueError):
            raise FarmError("The farm returned an invalid response.") from None

    @staticmethod
    def multipart(fields, archive, filename):
        boundary = "farm-" + hashlib.sha256(os.urandom(32)).hexdigest()
        marker = boundary.encode("ascii")
        chunks = []
        for name, value in fields.items():
            chunks.extend((b"--" + marker + b"\r\n",
                           f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"),
                           str(value).encode("utf-8"), b"\r\n"))
        chunks.extend((b"--" + marker + b"\r\n",
                       f'Content-Disposition: form-data; name="archive"; filename="{filename}"\r\n'.encode("ascii"),
                       b"Content-Type: application/gzip\r\n\r\n", archive, b"\r\n",
                       b"--" + marker + b"--\r\n"))
        return b"".join(chunks), "multipart/form-data; boundary=" + boundary

    @staticmethod
    def ask(prompt, optional=False):
        """Ask on a terminal; without one, optional answers are empty and required ones are an error."""
        if not sys.stdin.isatty():
            if optional:
                return ""
            raise FarmError(f"farm.json is missing a required field ({prompt.strip(': ')}). Add it, or run farm publish in a terminal.")
        return input(prompt).strip()

    @staticmethod
    def prompt_manifest(manifest):
        ask = Farm.ask
        prompts = {
            "id": "App ID: ", "name": "Name: ", "pitch": "One-line summary: ",
            "description": "What it does: ", "version": "Version (for example 0.1.0): ",
            "license": "License: ", "category": "Category: ",
        }
        for field, prompt in prompts.items():
            if not manifest.get(field):
                manifest[field] = ask(prompt)
        if "entry" not in manifest:
            command = ask("Start command (leave blank for a library): ", optional=True)
            manifest["entry"] = {"command": command} if command else None
        if "permissions" not in manifest:
            value = ask("Permissions, comma-separated (optional): ", optional=True)
            manifest["permissions"] = [part.strip() for part in value.split(",") if part.strip()]
        if "links" not in manifest:
            manifest["links"] = {}
            for key, label in (("repo", "Repository URL"), ("homepage", "Homepage URL"), ("video", "YouTube URL")):
                value = ask(label + " (optional): ", optional=True)
                if value:
                    manifest["links"][key] = value
        return manifest

    @staticmethod
    def pack_project(project, destination, ident, version):
        project = Path(project).resolve()
        with tarfile.open(destination, "w:gz") as archive:
            for path in sorted(project.rglob("*")):
                relative = path.relative_to(project)
                if any(part in PUBLISH_EXCLUDES for part in relative.parts):
                    continue
                if path.is_symlink():
                    raise FarmError(f"Project symlinks are refused: {relative}")
                if path.is_file() and path.stat().st_size > MAX_PUBLISH:
                    raise FarmError(f"Project file exceeds 50 MB: {relative}")
                archive.add(path, arcname=relative.as_posix(), recursive=False)
        if destination.stat().st_size > MAX_PUBLISH:
            raise FarmError("The packed project exceeds 50 MB.")
        return f"{ident}-{version}.tar.gz"

    def upload_media(self, manifest, project, token):
        source = manifest.get("media", {})
        if source is None:
            return {}
        if not isinstance(source, dict):
            raise FarmError("farm.json media must be an object.")
        if source.keys() - {"icon", "header", "screenshots"}:
            raise FarmError("Media may contain icon, header and screenshots only.")
        aliases = {"icon": "icon", "header": "header", "screenshots": "gallery"}
        uploaded = {}
        for supplied, target in aliases.items():
            if supplied not in source:
                continue
            values = source[supplied] if isinstance(source[supplied], list) else [source[supplied]]
            if target != "gallery" and len(values) != 1:
                raise FarmError(f"media.{supplied} must name one image file.")
            if target == "gallery" and (len(values) > 8 or any(not isinstance(value, str) for value in values)
                                        or len(values) != len(set(values))):
                raise FarmError("media.screenshots must contain up to eight unique paths.")
            urls = []
            for value in values:
                if not isinstance(value, str):
                    raise FarmError(f"media.{supplied} must contain file paths.")
                path = (project / value).resolve()
                try:
                    path.relative_to(project.resolve())
                except ValueError:
                    raise FarmError(f"Media path leaves the project: {value}") from None
                if not path.is_file() or path.is_symlink():
                    raise FarmError(f"Media file not found: {value}")
                content_type = mimetypes.guess_type(path.name)[0]
                if content_type not in ("image/png", "image/jpeg", "image/webp"):
                    raise FarmError(f"Media must be PNG, JPEG or WebP: {value}")
                if path.stat().st_size > 2 * 1024 * 1024:
                    raise FarmError(f"Media file exceeds 2 MiB: {value}")
                result = self.api("/api/media", token, "POST", path.read_bytes(), content_type)
                url = result.get("url") if isinstance(result, dict) else None
                if not isinstance(url, str):
                    raise FarmError("The farm did not return a media URL.")
                urls.append(url)
            uploaded[target] = urls if target == "gallery" else urls[0]
        return uploaded

    def publish(self, project=None, token=None, update=False):
        project = Path(project or Path.cwd()).resolve()
        manifest_path = project / "farm.json"
        manifest = read_json(manifest_path) if manifest_path.exists() else {}
        if not isinstance(manifest, dict):
            raise FarmError("farm.json must contain a JSON object.")
        unknown = manifest.keys() - PUBLISH_FIELDS
        if unknown:
            raise FarmError("farm.json has unknown fields: " + ", ".join(sorted(unknown)) + ".")
        manifest = self.prompt_manifest(manifest)
        ident = app_id(manifest.get("id"))
        version = manifest.get("version")
        if not isinstance(version, str) or not VERSION.fullmatch(version):
            raise FarmError("Version must be three nonnegative numbers, such as 0.1.0.")
        for field in ("name", "pitch", "description", "license", "category"):
            if not isinstance(manifest.get(field), str) or not manifest[field].strip():
                raise FarmError(f"farm.json needs {field}.")
        if manifest["category"] not in PUBLISH_CATEGORIES:
            raise FarmError("Category must be assistant, family, audio, developer-tools or library.")
        if "\n" in manifest["pitch"] or "\r" in manifest["pitch"] or len(manifest["pitch"]) > 100:
            raise FarmError("The one-line summary must be one line of 100 characters or fewer.")
        permissions = manifest.get("permissions")
        if isinstance(permissions, str):
            permissions = [part.strip() for part in permissions.split(",") if part.strip()]
        if not isinstance(permissions, list) or any(p not in ("microphone", "files", "network", "device") for p in permissions):
            raise FarmError("Permissions must use microphone, files, network or device.")
        links = manifest.get("links", {})
        if not isinstance(links, dict) or any(key not in ("repo", "homepage", "video") for key in links):
            raise FarmError("Links must be an object containing repo, homepage or video.")
        entry = manifest.get("entry")
        fields = {"id": ident, "name": manifest["name"], "pitch": manifest["pitch"],
                  "description": manifest["description"], "version": version,
                  "license": manifest["license"], "tags": manifest["category"],
                  "permissions": ",".join(permissions)}
        if entry is None:
            fields["entry"] = "null"
        elif isinstance(entry, str) and entry.strip():
            fields["command"] = entry
        elif isinstance(entry, dict) and set(entry) == {"command"} and isinstance(entry["command"], str) and entry["command"].strip():
            fields["command"] = entry["command"]
        elif (isinstance(entry, dict) and set(entry) == {"python", "args"}
              and isinstance(entry["python"], str)
              and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*", entry["python"])
              and isinstance(entry["args"], list)
              and all(isinstance(argument, str) for argument in entry["args"])):
            fields["entry"] = json.dumps(entry, separators=(",", ":"))
        else:
            raise FarmError("Entry must be null, a command, or a Python entry object.")
        for key, value in links.items():
            parsed = urlsplit(value) if isinstance(value, str) else None
            if (not parsed or parsed.scheme != "https" or not parsed.netloc or parsed.username
                    or parsed.password or any(character.isspace() for character in value)):
                raise FarmError(f"links.{key} must be an HTTPS URL.")
            fields[key] = value
        resolved_token = self.token(token)
        with tempfile.TemporaryDirectory(prefix="farm-publish-") as temporary:
            archive_path = Path(temporary) / f"{ident}-{version}.tar.gz"
            filename = self.pack_project(project, archive_path, ident, version)
            fields["media"] = json.dumps(self.upload_media(manifest, project, resolved_token), separators=(",", ":"))
            body, content_type = self.multipart(fields, archive_path.read_bytes(), filename)
            endpoint = "/api/seeds/" + ident if update else "/api/seeds"
            result = self.api(endpoint, resolved_token, "PUT" if update else "POST", body, content_type)
        if result.get("warning"):
            print(result["warning"])
        if result.get("prUrl"):
            print("Pull request: " + result["prUrl"])
        print("Your apps: " + urljoin(self.api_origin + "/", result.get("statusUrl", "/account/")))

    def release(self, ident=None, project=None):
        """Turn a tag the maker has just published into a catalog bump pull request."""
        try:
            from . import release as bump
        except ImportError:  # farm.py run as a loose script rather than the package
            import release as bump
        if ident is None:
            local = Path(project or Path.cwd()) / "farm.json"
            if not local.exists():
                raise FarmError("Name the app (farm release <id>) or run this where farm.json is.")
            described = read_json(local)
            ident = described.get("id") if isinstance(described, dict) else None
        ident = app_id(ident)
        api = bump.GitHub(bump.gh_token())
        catalog = bump.Catalog(api)
        where = catalog.use_fork(bump.gh_login(api))
        outcome = bump.check(catalog, ident, opened_by="a maker running farm release")
        print("{}: {}".format(ident, outcome.message))
        if outcome.pr:
            print(("Pull request: " if outcome.opened else "Already open: ") + outcome.pr)
            if where != catalog.repo:
                print("Opened from your fork at " + where + ".")
        return outcome

    def submission(self, ident, token=None):
        """What the farm says about your own submission of one app."""
        ident = app_id(ident)
        result = self.api("/api/seeds/mine", self.token(token))
        seeds = result.get("seeds") if isinstance(result, dict) else None
        if not isinstance(seeds, list):
            raise FarmError("The farm returned invalid app status.")
        matches = [seed for seed in seeds if isinstance(seed, dict) and seed.get("id") == ident]
        if not matches:
            raise FarmError(f"No submission found for {ident}.")
        return matches[-1]

    def submission_status(self, ident, token=None):
        ident = app_id(ident)
        seed = self.submission(ident, token)
        print(f"{ident}: {seed.get('state', 'unknown')}")
        for check in seed.get("checks", []):
            if isinstance(check, dict):
                print(f"  {check.get('name', 'Check')}: {check.get('status', 'unknown')}")
        for review in seed.get("reviews", []):
            print("  Review: " + str(review).lower().replace("_", " "))
        if seed.get("unavailable"):
            print("  Live checks are temporarily unavailable.")

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
        path = locks / (app_id(ident) + ".lock")
        try:
            with path.open("a+b") as lock:
                with file_lock(lock):
                    yield
        finally:
            # A mistyped app id should not leave a lock behind for ever, and only when
            # there was nothing to protect. After the handle closes, because Windows
            # refuses to unlink a file that is still open.
            try:
                if not (self.home / app_id(ident)).exists():
                    path.unlink()
            except OSError:
                pass

    def manifest(self, ident, timeout=30):
        ident = app_id(ident)
        if self.local_catalog is not None:
            result = read_json(self.local_catalog / (ident + ".json"))
        else:
            with open_url(self.catalog.rstrip("/") + "/" + ident + ".json", timeout=timeout) as response:
                data = response.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024:
                raise FarmError("This app's catalog entry is larger than 1 MiB.")
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
        with open_url(self.catalog.rstrip("/") + "/") as response:
            raw = response.read(2 * 1024 * 1024).decode("utf-8")
        if raw.lstrip().startswith("["):
            entries = json.loads(raw)
            return sorted({app_id(x if isinstance(x, str) else x["id"]) for x in entries})
        parser = CatalogLinks()
        parser.feed(raw)
        if not parser.ids:
            raise FarmError("Catalog must serve a JSON array of ids or links to manifest JSON files.")
        return sorted(parser.ids)

    def installed_rows(self, known):
        """Every installed app and its state, one at a time so a slow catalog answers as it goes."""
        for current in sorted(self.home.glob("*/current")):
            ident = current.parent.name
            with self.guard(ident):
                _, manifest = self.installed(ident)
                running = bool(self.active(ident))
            try:
                known[ident] = self.manifest(ident, timeout=ADVISORY_TIMEOUT)
            except (FarmError, OSError, ValueError, HTTPException):
                known[ident] = None
            yield {"id": manifest["id"], "name": manifest["name"], "version": manifest["version"],
                   "pitch": manifest["pitch"], "running": running,
                   "updateAvailable": update_available(manifest, known[ident]) or None}

    def catalog_rows(self, known, here):
        """Every app in the catalog, using the entries the installed rows already fetched."""
        for ident in self.catalog_ids():
            manifest = known.get(ident) or self.manifest(ident)
            yield {"id": ident, "name": manifest["name"], "version": manifest["version"],
                   "pitch": manifest["pitch"],
                   "release": ("none" if "release" not in manifest else
                               "pending" if manifest["release"]["sha256"] == "pending" else "ready"),
                   "installed": here.get(ident)}

    def listing(self):
        """The rows farm list prints: what is installed here, then the whole catalog."""
        known, here, installed = {}, {}, []
        for row in self.installed_rows(known):
            here[row["id"]] = row["version"]
            installed.append(row)
        return installed, list(self.catalog_rows(known, here))

    def list(self):
        known, here = {}, {}
        print("Installed:")
        for row in self.installed_rows(known):
            here[row["id"]] = row["version"]
            state = "running" if row["running"] else "stopped"
            if row["updateAvailable"]:
                state += f", update available: {row['updateAvailable']}"
            print(f"  {row['id']} {row['version']} {row['name']} [{state}] - {row['pitch']}")
        print("Catalog:")
        for row in self.catalog_rows(known, here):
            draft = {"none": " [No release yet]", "pending": " [release pending]", "ready": ""}[row["release"]]
            print(f"  {row['id']} {row['version']} {row['name']} - {row['pitch']}{draft}")

    def download(self, release, destination):
        location = release["url"]
        parsed = urlsplit(location)
        if self.local_catalog is not None and not parsed.scheme:
            source = (self.local_catalog / location).open("rb")
        elif parsed.scheme == "file" and self.local_catalog is not None:
            source = Path(url2pathname(parsed.path)).open("rb")
        elif parsed.scheme in ("http", "https"):
            source = open_url(location)
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
                        or any(":" in part for part in parts)
                        or (WINDOWS and any(part.endswith((".", " ")) or windows_reserved(part)
                                            for part in parts))
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

    def install(self, ident, yes=False, update=False, restart=False):
        with self.guard(ident):
            print(f"Looking up {app_id(ident)} in the catalog.")
            manifest = self.manifest(ident)
            if "release" not in manifest:
                raise FarmError("This app has no release to install yet.")
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
            py = manifest["requires"].get("python", "3.9")
            if tuple(map(int, py.split("."))) > sys.version_info[:2]:
                raise FarmError(f"This app needs Python {py} or newer.")
            print(f"{manifest['name']} {manifest['version']}\n{manifest['pitch']}")
            print(describe_maker(manifest))
            print("Needs: " + describe_requirements(manifest["requires"]))
            print(describe_permissions(manifest["permissions"]))
            if not yes and input("Install this release? [y/N] ").strip().lower() not in ("y", "yes"):
                print("Cancelled.")
                return
            # Stage and verify before touching the installed version or stopping an app.
            with tempfile.TemporaryDirectory(prefix=".install-", dir=self.home) as temporary:
                stage = Path(temporary)
                archive = stage / "release.tar"
                where = urlsplit(release["url"]).hostname
                # A catalog entry may carry size 0, meaning nobody has measured it yet.
                measured = describe_size(release["size"]) if release["size"] else "it"
                print(f"Downloading {measured}" + (f" from {where}." if where else "."))
                self.download(release, archive)
                print("The download matches the checksum the catalog lists.")
                content = stage / "content"
                content.mkdir()
                print(f"Unpacking it into {app / manifest['version']}.")
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
                if update:
                    print(f"Your data in {app / 'data'} is kept.")
                os.replace(root, destination)
                atomic_write(app / "launcher.json", json.dumps({"id": ident, "entry": manifest["entry"]}) + "\n")
                atomic_write(app / "current", manifest["version"] + "\n")
            if manifest["entry"] is not None:
                print("Ready." if restart else f"Ready. Run: farm start {ident}")
                return
            module = destination / (ident.replace("-", "_") + ".py")
            module = module if module.is_file() else destination / (ident + ".py")
            print(f"Ready. {manifest['name']} is a library, so there is nothing to start.")
            print(f"Copy {module.name} out of {destination} into your own app, or import it from there."
                  if module.is_file() else
                  f"Its files are in {destination}; import what you need from there.")

    def running_apps(self):
        """Every app running now, with the name a person reads and the port it really took."""
        rows = []
        for path in sorted(self.home.glob("*/farm.pid")):
            ident = path.parent.name
            with self.guard(ident):
                try:
                    if not self.active(ident):
                        continue
                    _, manifest = self.installed(ident)
                    _, port = self.running_port(ident)
                except (FarmError, OSError, ValueError):
                    continue
            rows.append((ident, manifest, port))
        return rows

    def startable_apps(self):
        """Every installed app that could be started right now: runnable, and not already running."""
        rows = []
        for current in sorted(self.home.glob("*/current")):
            ident = current.parent.name
            with self.guard(ident):
                try:
                    _, manifest = self.installed(ident)
                except (FarmError, OSError, ValueError):
                    continue
                if manifest["entry"] is None or self.active(ident):
                    continue
            rows.append((ident, manifest))
        return rows

    def choose_to_stop(self):
        """Jason, 2026-09-14: "Does it ask me which app I want to stop?" Now it does."""
        rows = self.running_apps()
        if not rows:
            print("Nothing is running.")
            return
        if len(rows) == 1:
            ident, manifest, _ = rows[0]
            answer = ask_yes(f"Stop {manifest['name']}? [Y/n] ")
            if answer is None:
                print(f"{manifest['name']} is running. " + name_one("stop", [ident]))
            elif answer:
                self.stop(ident)
            else:
                print("Left as it is.")
            return
        print(f"{len(rows)} apps are running.")
        for number, (_, manifest, port) in enumerate(rows, 1):
            print(f"{number}. {manifest['name']} {manifest['version']}"
                  + (f" on port {port}" if port else ""))
        chosen, answer = ask_which('Stop which? A number, "all", or Enter to leave them. ', len(rows))
        if chosen is None:
            print("Nothing was stopped. " + name_one("stop", [row[0] for row in rows]))
            return
        if not chosen:
            print("Left as they are." if not answer else
                  f"There is no {answer} in that list, so nothing was stopped.")
            return
        for index in chosen:
            self.stop(rows[index][0])

    def choose_to_start(self):
        """The same question farm stop asks, for the apps that are sitting there not running."""
        rows = self.startable_apps()
        if not rows:
            if not any(self.home.glob("*/current")):
                print("Nothing is installed yet. Run: farm list to see what the catalog has.")
            elif self.running_apps():
                print("Everything you have installed is already running.")
            else:
                print("Nothing you have installed is a runnable app; a library has nothing to start.")
            return
        if len(rows) == 1:
            ident, manifest = rows[0]
            answer = ask_yes(f"Start {manifest['name']}? [Y/n] ")
            if answer is None:
                print(f"{manifest['name']} is installed and not running. " + name_one("start", [ident]))
            elif answer:
                self.start(ident)
            else:
                print("Left as it is.")
            return
        print(f"{len(rows)} installed apps are ready to start.")
        for number, (_, manifest) in enumerate(rows, 1):
            print(f"{number}. {manifest['name']} {manifest['version']}")
        chosen, answer = ask_which('Start which? A number, "all", or Enter to leave them. ', len(rows))
        if chosen is None:
            print("Nothing was started. " + name_one("start", [row[0] for row in rows]))
            return
        if not chosen:
            print("Left as they are." if not answer else
                  f"There is no {answer} in that list, so nothing was started.")
            return
        for index in chosen:
            self.start(rows[index][0])

    def running_port(self, ident):
        """Whether an app is running now, and the port it really took, so an update can put it back."""
        if not self.active(ident):
            return False, None
        try:
            ports = read_json(self.app_dir(ident) / "process.json").get("ports") or []
        except (OSError, ValueError):
            ports = []
        return True, (ports[0] if ports else None)

    def newer_version(self, ident, installed):
        """The catalog's newer version for one installed app, and silence when the catalog cannot be read."""
        try:
            return update_available(installed, self.manifest(ident, timeout=ADVISORY_TIMEOUT))
        except (FarmError, OSError, ValueError, HTTPException):
            return ""

    def updates(self):
        """Every installed app the catalog has a newer version of, and what could not be checked."""
        found, unreachable = [], []
        for current in sorted(self.home.glob("*/current")):
            ident = current.parent.name
            try:
                with self.guard(ident):
                    _, installed = self.installed(ident)
            except (FarmError, OSError, ValueError):
                continue
            try:
                latest = self.manifest(ident)
            except (FarmError, OSError, ValueError, HTTPException):
                unreachable.append(ident)
                continue
            if update_available(installed, latest):
                found.append((ident, installed, latest))
        return found, unreachable

    def update(self, ident=None, yes=False, everything=False):
        """One app, after asking, or with no id the whole list and one question."""
        if ident is None:
            return self.check(yes=yes, everything=everything)
        ident = app_id(ident)
        with self.guard(ident):
            _, installed = self.installed(ident)
            running, port = self.running_port(ident)
        latest = self.manifest(ident)
        available = update_available(installed, latest)
        if not available:
            print(f"{latest['name']} {latest['version']} is in the catalog with no release to install yet."
                  if newer(installed["version"], latest["version"]) else
                  f"{installed['name']} {installed['version']} is installed, and that is the newest the catalog has.")
            return
        if not yes:
            asked = input(f"{installed['name']} {installed['version']} is installed and {available} is out."
                          " Update it? [Y/n] ").strip().lower()
            if asked and asked not in ("y", "yes"):
                print("Left as it is.")
                return
        if running:
            print(f"{installed['name']} is running on port {port}, so the farm stops it"
                  f" and starts it again on {port}." if port is not None else
                  f"{installed['name']} is running, so the farm stops it and starts it again.")
        self.install(ident, yes=True, update=True, restart=running)
        if running:
            movable = port is not None and port_mechanism(latest) is not None
            self.start(ident, port=port if movable else None)

    def check(self, yes=False, everything=False):
        """What the catalog has that you do not, and the one question that takes any of it."""
        idents = sorted(path.parent.name for path in self.home.glob("*/current"))
        if not idents:
            print("Nothing is installed yet. Run: farm list to see what the catalog has.")
            return
        counted = "the app" if len(idents) == 1 else f"all {len(idents)} apps"
        print(f"Looking up {counted} you have installed in the catalog.")
        found, unreachable = self.updates()
        for number, (_, installed, latest) in enumerate(found, 1):
            print(f"{number}. {describe_update(latest, installed)}")
        if unreachable:
            print("The catalog had nothing to say about " + join_words(unreachable) + ".")
        if not found:
            print("Everything you have installed is the newest the catalog has.")
            return
        chosen, answer = ask_which('Update which? A number, "all", or Enter to leave them. ',
                                   len(found), everything=everything or yes)
        if chosen is None:
            print("Nothing was updated. Run: farm update <id> to take one,"
                  " or farm update --all to take them all.")
            return
        if not chosen:
            print("Left as they are." if not answer else
                  f"There is no {answer} in that list, so nothing was updated.")
            return
        for index in chosen:
            self.update(found[index][0], yes=True)

    def probed(self, interpreter, peers, budget=FIND_BUDGET):
        """The half of the search that puts a packet on the wire, run by one named interpreter.

        In this process when that is the one already running, and in a child otherwise, because the
        only way to know what macOS lets a binary see is to ask that binary. The child imports this
        module out of the directory it is handed, so there is one finder and not two.
        """
        if not interpreter or Path(interpreter) == Path(sys.executable):
            return dict(probe_network(peers, budget), python=list(sys.version_info[:2]))
        try:
            done = run_probe([interpreter, "-c", FIND_PROBE,
                              str(Path(__file__).resolve().parents[1]),
                              json.dumps(list(peers)), str(budget)], budget + 5)
            answer = json.loads(done.stdout.strip().splitlines()[-1])
        except (OSError, ValueError, IndexError, TypeError, subprocess.SubprocessError):
            return {"found": [], "errno": 0, "python": []}
        if not isinstance(answer, dict) or not isinstance(answer.get("found"), list):
            return {"found": [], "errno": 0, "python": []}
        return {"found": [record for record in answer["found"] if isinstance(record, dict)],
                "errno": answer["errno"] if isinstance(answer.get("errno"), int) else 0,
                "python": answer.get("python") or []}

    def find_tiinys(self, budget=FIND_BUDGET):
        """Every Tiiny this machine can see, asked by the Python that would be doing the reaching.

        macOS grants the local network per binary and refuses a detached app silently, so a search
        that only ever ran in this process could tell somebody there is no Tiiny when what there
        really is is a refused Python. The interpreter the farm runs apps with is the one whose
        answer counts, and when that one is refused the farm walks the other Pythons on this
        machine exactly as it does for a start, and keeps the first that gets through.

        Returns what answered, whether the local network was refused, whose answer this is, and the
        interpreter the farm moved to and saved, if it had to move. Finding the cable is done here
        rather than in the child: bind reads an address this machine holds and sends no packet, so
        no permission gates it and one scan does for every interpreter.
        """
        peers = usb_peers()
        interpreter = self.app_python() or sys.executable
        answer = self.probed(interpreter, peers, budget)
        if answer["errno"] not in NO_ROUTE:
            return {"found": answer["found"], "blocked": False, "python": interpreter,
                    "moved": None}
        # The walk shares one budget, so a refused Python, which is told no in milliseconds rather
        # than left to time out, costs almost none of it and the one that works gets the rest.
        deadline = time.monotonic() + budget
        second = {}

        def reaches(candidate):
            second.update(self.probed(candidate, peers, _remaining(deadline, budget)))
            # Found something is not the test: the TiinyOS client is loopback and answers an
            # interpreter that has been refused the local network just as readily as one that has
            # not. Only a candidate that was not refused has anything better than this one.
            return (bool(second["found"]) and second["errno"] not in NO_ROUTE
                    and tuple(second["python"] or ()) >= (3, 9))

        moved = self.another_python(interpreter, reaches)
        if moved:
            return {"found": second["found"], "blocked": True, "python": moved, "moved": moved}
        return {"found": answer["found"], "blocked": True, "python": interpreter, "moved": None}

    def say_the_python_was_refused(self, answer):
        """The line a refused local network gets, and the settings path that lifts it.

        Never "no Tiiny found": macOS refusing this binary is not the same finding as an absent
        box, and saying the second when it is the first sends somebody to check their cable.
        """
        if answer["moved"]:
            print(f"{answer['moved']} found it. The Python the farm was using cannot reach your"
                  " local network, so the farm will run apps with that one from now on, and has"
                  " saved it.")
            return
        print(f"The farm cannot tell whether a Tiiny is there, because {answer['python']} was"
              " refused your local network." if not answer["found"] else
              "An app the farm starts will not reach a Tiiny on the cable or on this network,"
              f" because {answer['python']} was refused your local network.")
        self.local_network_hint()

    def find_device(self):
        """farm device --find: what is out there, before anybody has typed an address."""
        answer = self.find_tiinys()
        found = answer["found"]
        for record in found:
            print(describe_device(record))
        if answer["blocked"]:
            self.say_the_python_was_refused(answer)
        elif not found:
            print("No Tiiny answered. The farm looked on every USB cable in this machine, on this"
                  f" network, and at the TiinyOS client on {TIINYOS_BASE}.")
            print("Switch the Tiiny on, plug the cable in or put it on this network, then run:"
                  " farm device --find")
        if found:
            print("Run farm device to save one. It offers these and asks for the key."
                  if len(found) > 1 else
                  "Run farm device to save it. It offers this address and asks for the key.")
        else:
            print("To type the address in yourself: farm device --base http://<address>/v1"
                  " --key-stdin < key-file")
        return answer

    def offer_device(self):
        """The base URL the hidden prompt offers, or nothing when there is nothing to offer.

        Finding a Tiiny is a convenience on top of a command that has always worked by hand, so
        whatever the search runs into it hands back nothing rather than becoming the reason nobody
        can save an address.
        """
        try:
            answer = self.find_tiinys()
        except Exception:  # noqa: BLE001 - an offer must never be the reason a command fails.
            return ""
        found = answer["found"]
        if answer["blocked"]:
            self.say_the_python_was_refused(answer)
        if not found:
            return ""
        if len(found) == 1:
            print("Found " + describe_device(found[0]))
            return found[0]["base"]
        for number, record in enumerate(found, 1):
            print(f"{number}. {describe_device(record)}")
        chosen, typed = ask_which("Which one? A number, or Enter to type an address. ", len(found))
        if chosen:
            return found[chosen[0]]["base"]
        if typed:
            print(f"There is no {typed} in that list.")
        return ""

    def device(self, base=None, key_stdin=False, find=False):
        if find:
            # Looking and saving are different jobs, and a command that asked for both would
            # quietly do one of them.
            if base is not None or key_stdin:
                raise FarmError("farm device --find looks and saves nothing; drop --base and"
                                " --key-stdin, or drop --find.")
            return bool(self.find_device()["found"])
        scripted = base is not None or key_stdin or any(
            name in os.environ for name in ("TIINY_BASE", "TIINY_KEY"))
        if scripted:
            base = (base if base is not None else os.environ.get("TIINY_BASE", "")).strip()
            key = (sys.stdin.read() if key_stdin else os.environ.get("TIINY_KEY", "")).strip()
            if not base:
                raise FarmError("Provide --base or TIINY_BASE for device import.")
        else:
            # Look first, so the one thing a person cannot guess is offered rather than asked for.
            offered = self.offer_device()
            # Refuse getpass's echoing fallback when no secure terminal is available.
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                base = getpass.getpass(f"Device base URL [{offered}] (hidden): " if offered
                                       else "Device base URL (hidden): ").strip() or offered
                key = getpass.getpass("Device API key (hidden): ").strip()
        parsed = urlsplit(base)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise FarmError("Use an HTTP(S) base URL without credentials, query or fragment.")
        if not key:
            raise FarmError("Device key must not be empty.")
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.config_home.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_write(self.config_home / "device.json", json.dumps({"base": base, "key": key}) + "\n")
        print("Device settings saved.")
        self.device_users()
        # Apps are launched with this interpreter, so this is the one macOS has to have granted.
        _, refused = self.choose_python(self.app_python() or sys.executable, base)
        if refused:
            self.local_network_hint()
        return True

    def probe_device(self, host, interpreter):
        """One request to the Tiiny from one interpreter. Returns the errno it met, 0 when the
        device answered, the address it tried, and that interpreter's Python version."""
        if interpreter and Path(interpreter) != Path(sys.executable):
            try:
                done = run_probe([interpreter, "-c", DEVICE_PROBE, host, str(DEVICE_PORT),
                                  str(LOCAL_NETWORK_TIMEOUT)], LOCAL_NETWORK_TIMEOUT + 5)
                answer = json.loads(done.stdout.strip().splitlines()[-1])
                version = tuple(answer.get("python") or ())
            except (OSError, ValueError, IndexError, TypeError, subprocess.SubprocessError):
                return None, "", ()
            return answer.get("errno"), str(answer.get("address") or ""), version
        version = sys.version_info[:2]
        try:
            address = socket.getaddrinfo(host, DEVICE_PORT, type=socket.SOCK_STREAM)[0][4][0]
        except OSError:
            return None, "", version
        try:
            urlopen(f"http://{url_host(address)}:{DEVICE_PORT}/device.json",
                    timeout=LOCAL_NETWORK_TIMEOUT).close()
        except HTTPError:
            return 0, address, version
        except URLError as error:
            return getattr(error.reason, "errno", None), address, version
        except OSError as error:
            return error.errno, address, version
        return 0, address, version

    def another_python(self, interpreter, reaches):
        """The first other Python on this machine that manages what this one was refused, kept so
        every later command takes it too.

        macOS grants the local network per binary, so "it works over there" is a real answer rather
        than a coincidence, and the farm saves it instead of asking somebody to find it again.
        `reaches(candidate)` says whether that interpreter managed the thing in question.
        """
        for candidate in python_candidates(skip=[interpreter])[:MOST_PYTHONS_TRIED]:
            if reaches(candidate):
                self.save_setting("python", candidate)
                return candidate
        return None

    def working_python(self, interpreter, base):
        """Jason, 2026-09-14: "How is an end user going to know that's an issue when they install
        it? They may not have you sitting there to fix it." macOS Local Network privacy refuses a
        binary it has never been granted, silently for a detached app, so when the Python an app
        would run under cannot reach the Tiiny the farm tries the other Pythons on the machine and
        keeps the first one that can. Returns the interpreter to use, the one it moved to, and
        whether the local network was refused at all."""
        host = urlsplit(base).hostname if base else None
        if not host or not interpreter:
            return interpreter, None, False
        code, address, _ = self.probe_device(host, interpreter)
        if code not in NO_ROUTE or not private_address(address):
            return interpreter, None, False

        def reaches(candidate):
            found, _, version = self.probe_device(host, candidate)
            return found == 0 and version >= (3, 9)

        moved = self.another_python(interpreter, reaches)
        return moved or interpreter, moved, True

    def choose_python(self, interpreter, base, app=None):
        """Say what the farm is doing about a Python macOS will not let near the Tiiny. This is a
        repair and a hint, never a reason to fail a command, whatever it runs into."""
        try:
            interpreter, moved, refused = self.working_python(interpreter, base)
        except Exception:  # noqa: BLE001 - a hint must never be the reason a command fails.
            return interpreter, False
        if moved:
            print("This Python cannot reach your Tiiny, so the farm "
                  + (f"is running {app} with {moved} instead." if app
                     else f"will run apps with {moved} instead."))
        return interpreter, refused and not moved

    @staticmethod
    def local_network_hint():
        print("macOS is blocking this Python from your local network.")
        print("System Settings, Privacy and Security, Local Network, turn on Python,"
              " then farm stop and farm start again.")

    def device_users(self):
        """Name the installed apps these settings reach, and one command that proves they work."""
        wanting, runnable = [], []
        for current in sorted(self.home.glob("*/current")):
            ident = current.parent.name
            try:
                _, manifest = self.installed(ident)
            except (FarmError, OSError, ValueError):
                continue
            if "device" in manifest["permissions"] or (manifest["requires"].get("device") or {}).get("models"):
                wanting.append(ident)
                if manifest["entry"] is not None:
                    runnable.append(ident)
        if not wanting:
            print("No app you have installed uses your Tiiny yet. Run: farm list to see what the catalog has.")
            return
        print("These installed apps will use it: " + join_words(wanting) + ".")
        if runnable:
            print(f"Try it now: farm start {runnable[0]}")

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
        config = self.config_home / "device.json"
        if not config.exists():
            config = self.home / "device.json"  # Read settings from pre-0.1 installations.
        if config.exists():
            private_mode(config)
            settings = read_json(config)
            if not isinstance(settings, dict) or not all(isinstance(settings.get(k), str) for k in ("base", "key")):
                raise FarmError("Invalid device settings; run farm device.")
            env.update(TIINY_BASE=settings["base"], TIINY_KEY=settings["key"])
        if env.get("TIINY_BASE"):
            host = urlsplit(env["TIINY_BASE"]).hostname
            if host:
                env["TIINY_HOST"] = f"[{host}]" if ":" in host else host
        if ident == "story-lantern":
            # Data paths only. Its port comes from the manifest port field, like every app's.
            env.update(LANTERN_HOME=str(data), LANTERN_DB=str(data / "lantern.db"),
                       LANTERN_SAFETY_JSONL=str(data / "safety-events.jsonl"),
                       LANTERN_BLOCKLIST=str(data / "blocklist_extra.txt"))
        return env

    def active(self, ident):
        app = self.app_dir(ident)
        try:
            pid = int((app / "farm.pid").read_text())
            if pid <= 1:
                return None
            if WINDOWS:
                try:
                    identity = read_json(app / "process.json").get("identity")
                    with WindowsProcess(pid) as process:
                        return pid if process.identity == identity and process.running() else None
                except OSError as error:
                    if getattr(error, "winerror", None) == 87:  # PID no longer exists.
                        return None
                    raise
            # Apps inherit this descriptor. A stale PID alone never authorizes a signal.
            with (app / ".run.lock").open("a+b") as lock:
                try:
                    with file_lock(lock, blocking=False):
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

    def device_configured(self):
        return (self.config_home / "device.json").exists() or (self.home / "device.json").exists()

    def device_settings(self):
        """The device address and key on file, or None when there is nothing saved."""
        config = self.config_home / "device.json"
        if not config.exists():
            config = self.home / "device.json"  # Settings from a pre-0.1 installation.
        try:
            settings = read_json(config)
        except (OSError, ValueError):
            return None
        if not isinstance(settings, dict) or not all(isinstance(settings.get(k), str) for k in ("base", "key")):
            return None
        return settings

    def settings(self):
        """What this machine has told the farm, such as which Python to run apps with."""
        try:
            saved = read_json(self.config_home / "settings.json")
        except (OSError, ValueError):
            return {}
        return saved if isinstance(saved, dict) else {}

    def save_setting(self, name, value):
        saved = self.settings()
        saved[name] = value
        self.config_home.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_write(self.config_home / "settings.json", json.dumps(saved, indent=2) + "\n")

    def published_cli(self, timeout=UPDATE_CHECK_TIMEOUT):
        """The farm version the catalog publishes. The site writes it into catalog.json, so this
        never asks PyPI anything, and an older catalog that is still an array simply has none."""
        with open_url(self.api_origin + "/catalog.json", timeout=timeout) as response:
            published = json.loads(response.read(4 * 1024 * 1024))
        return published.get("cli") if isinstance(published, dict) else None

    def remembered_cli(self):
        """What the last look found, and when. One look a day is enough to catch a release."""
        try:
            stamp = read_json(self.config_home / "update-check.json")
            return (str(stamp.get("cli") or ""), float(stamp.get("checked") or 0))
        except (OSError, ValueError, TypeError, AttributeError):
            return "", 0.0

    def offered_cli(self, now=None):
        """The newest farm the catalog has offered, looked up at most once a day and never in a
        way that can delay or fail the command a person actually ran."""
        if os.environ.get("FARM_NO_UPDATE_CHECK"):
            return ""
        offered, checked = self.remembered_cli()
        now = time.time() if now is None else now
        if 0 <= now - checked < UPDATE_CHECK_EVERY:
            return offered
        try:
            offered = self.published_cli() or ""
        except Exception:  # noqa: BLE001 - offline, slow, or a catalog that has not shipped one yet.
            offered = ""
        try:
            self.config_home.mkdir(parents=True, exist_ok=True, mode=0o700)
            atomic_write(self.config_home / "update-check.json",
                         json.dumps({"cli": offered, "checked": now}) + "\n")
        except OSError:
            pass
        return offered

    def update_notice(self):
        """Jason, 2026-09-14: "there's a new farm update out there, should there be some sort of
        polling that checks and says, hey, you're running at X and version XYZ is out." One line,
        after whatever the person actually asked for, and never in a script."""
        try:
            if not sys.stdout.isatty():
                return
            running = _version()
            offered = self.offered_cli()
            if newer_version(offered, running):
                print(f"farm {offered} is out and you are on {running}. Run: farm self-update")
        except Exception:  # noqa: BLE001 - a notice must never be the reason a command fails.
            return

    def pipx_venv(self):
        """pipx puts each command in its own virtual environment, and pip inside one of those is
        not how a person is meant to move it forward."""
        parts = Path(sys.prefix).parts
        return "pipx" in parts and "venvs" in parts

    def self_update(self):
        """Move the farm itself forward. It never touches an installed app."""
        running = _version()
        if self.pipx_venv():
            command = [shutil.which("pipx") or "pipx", "upgrade", "tiinyapp-farm"]
            print("Upgrading the farm with pipx.")
        else:
            command = [sys.executable, "-m", "pip", "install", "--upgrade", "tiinyapp-farm"]
            print(f"Upgrading the farm with pip, in {sys.executable}.")
        try:
            done = run_probe(command, 600)
        except FileNotFoundError:
            raise FarmError("pipx is not on this machine, so the farm cannot upgrade itself."
                            " Run: pipx upgrade tiinyapp-farm where pipx is installed.") from None
        except subprocess.SubprocessError:
            raise FarmError("The upgrade did not finish. Run it again, or upgrade by hand with"
                            f" {shlex.join(command)}.") from None
        said = [line.strip() for line in (done.stdout or done.stderr or "").splitlines() if line.strip()]
        if said:
            print(said[-1])
        if done.returncode:
            raise FarmError("The upgrade did not go through, and the farm is still "
                            + running + ". The line above is what it said.")
        now = self.installed_cli()
        print(f"farm is now {now}." if now else f"The farm was {running} and has been upgraded.")
        print("That is the version you were already on, so nothing changed." if now == running else
              "The next farm command you run is the new one.")

    @staticmethod
    def installed_cli():
        """Ask a fresh interpreter, because this one is still running the version it started with."""
        try:
            done = run_probe([sys.executable, "-c",
                              "from importlib.metadata import version; print(version('tiinyapp-farm'))"],
                             60)
            found = done.stdout.strip().splitlines()[-1].strip()
        except (OSError, IndexError, subprocess.SubprocessError):
            return ""
        return found if VERSION.fullmatch(found) else ""

    def app_python(self):
        """The interpreter the farm runs apps with, when it has had to pick one and it is still there."""
        saved = self.settings().get("python")
        return saved if isinstance(saved, str) and runnable(saved) else None

    def start_failure(self, app, ident, manifest, message, port=None, exited=False):
        """Add the two causes of a failed start that leave nothing useful in the log."""
        declared = list(manifest["requires"]["ports"])
        takes = port_mechanism(manifest)
        # A fixed port refuses --port before launch, so only a movable app reaches this.
        if port is not None and takes is not None and declared and declared[0] != port and self.tcp_ready(declared[0]):
            message += (f"\n{ident} never opened {port}, and something is listening on {declared[0]},"
                        " the port it normally uses.")
            if "argv" in takes:
                message += (f" It was started with {takes['argv']} {port} and did not use it."
                            f" Ask its author about {takes['argv']}.")
            else:
                message += (f" This app does not read {takes['env']}, so --port cannot move it."
                            f" Ask its author to read {takes['env']}.")
        if exited and (manifest["requires"].get("device") or {}).get("models") and not self.device_configured():
            message += (f"\nNo device is configured. If {ident} needs your Tiiny,"
                        f" run farm device and start it again.")
        return self.startup_error(app, message)

    def free_port_above(self, ident, busy, span=50):
        """The first free port above a busy one, so a movable app can start without being asked."""
        for candidate in range(busy + 1, min(busy + 1 + span, 65536)):
            if not self.tcp_ready(candidate):
                return candidate
        raise FarmError(f"Port {busy} is already in use and nothing above it up to {busy + span} is free;"
                        f" use farm start {ident} --port N.")

    def start(self, ident=None, port=None, python=None):
        if ident is None:
            if port is not None:
                raise FarmError("A port belongs to one app, so name it: farm start <id> --port N.")
            if python is not None:
                raise FarmError("A Python belongs to one app, so name it: farm start <id> --python PATH.")
            return self.choose_to_start()
        if port is not None and (type(port) is not int or not 1 <= port <= 65535):  # noqa: E721
            raise FarmError("Port must be an integer between 1 and 65535.")
        if python is not None and not runnable(python):
            raise FarmError(f"There is no Python to run at {python}.")
        with self.guard(ident):
            root, manifest = self.installed(ident)
            app = self.app_dir(ident)
            if self.active(ident):
                print(f"{manifest['name']} is already running.")
                try:
                    live = read_json(app / "process.json").get("ports") or []
                except (OSError, ValueError):
                    live = []
                if live:
                    print("Open " + app_link(live[0], manifest))
                print(f"Stop it with: farm stop {ident}")
                return
            entry = manifest["entry"]
            if entry is None:
                raise FarmError(f"{ident} is a library, not a runnable app.")
            # The one this machine has settled on, unless the person names one on the spot.
            chosen = python or self.app_python() or sys.executable
            command = ([chosen, "-m", entry["python"], *entry["args"]]
                       if "python" in entry else shlex.split(entry["command"]))
            if command[0] in ("python", "python3"):
                command[0] = chosen
            # The binary macOS has to have granted is the one the app itself runs under.
            interpreter = (command[0] if "python" in entry
                           or Path(command[0]).name.lower().startswith("python") else None)
            if python:
                self.save_setting("python", python)
            ports = list(manifest["requires"]["ports"])
            takes = port_mechanism(manifest)
            if port is not None and takes is None:
                raise FarmError(f"{ident} runs on port {ports[0]} only and cannot be moved, so start it without --port."
                                if ports else f"{ident} has no port to move, so start it without --port.")
            if port is not None:
                ports = [port, *ports[1:]]
            moved = None
            for index, candidate in enumerate(ports):
                if self.tcp_ready(candidate):
                    if index == 0 and port is None and takes is not None:
                        # Jason, 2026-09-14: "It should have checked to see if a port was in use and
                        # then put it on a different one." A movable app steps up to the next free
                        # port on its own; an explicit --port is the person's choice and is never moved.
                        chosen = self.free_port_above(ident, candidate)
                        moved = (candidate, chosen)
                        ports[0] = chosen
                        continue
                    # Nothing launched this time, so quoting farm.log would show a stale run.
                    raise FarmError(f"Port {candidate} is already in use; use farm start {ident} --port N."
                                    if takes is not None else
                                    f"Port {candidate} is already in use, and {ident} cannot be moved off it.")
            env = self.environment(ident, manifest)
            refused = False
            if interpreter and not python:
                interpreter, refused = self.choose_python(interpreter, env.get("TIINY_BASE"), manifest["name"])
                command[0] = interpreter
            if ports:
                # Every app is told the farm's port; the manifest says how this one takes it.
                env["TIINYAPP_PORT"] = str(ports[0])
                if takes and "argv" in takes:
                    set_port_argument(command, takes["argv"], ports[0])
                elif takes:
                    env[takes["env"]] = str(ports[0])
            with (app / ".run.lock").open("a+b") as lock:
                with file_lock(lock, blocking=False), (app / "farm.log").open("ab") as log:
                    options = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS}
                               if WINDOWS else {"start_new_session": True, "pass_fds": (lock.fileno(),)})
                    process = subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.DEVNULL,
                                               stdout=log, stderr=log, **options)
                try:
                    identity = None
                    if WINDOWS:
                        try:
                            with WindowsProcess(process.pid) as running:
                                identity = running.identity
                        except OSError:
                            if process.poll() is not None:
                                raise self.start_failure(app, ident, manifest, f"{ident} exited at startup (exit {process.returncode}).", exited=True)
                            raise
                    atomic_write(app / "farm.pid", str(process.pid) + "\n")
                    atomic_write(app / "process.json", json.dumps({"started": time.time(),
                                 "ports": ports, "version": manifest["version"], "health": manifest.get("health"), "identity": identity}) + "\n")
                    deadline = time.monotonic() + START_TIMEOUT
                    while True:
                        time.sleep(min(0.1, max(0, deadline - time.monotonic())))
                        if process.poll() is not None:
                            raise self.start_failure(app, ident, manifest, f"{ident} exited at startup (exit {process.returncode}).", exited=True)
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise self.start_failure(app, ident, manifest,
                                f"{ident} timed out waiting for readiness after {START_TIMEOUT:g} s.", port)
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
                                raise self.start_failure(app, ident, manifest, f"{ident} exited at startup (exit {process.returncode}).", exited=True)
                            break
                except BaseException:
                    try:
                        if WINDOWS:
                            process.terminate()
                        else:
                            os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
                    (app / "farm.pid").unlink(missing_ok=True)
                    (app / "process.json").unlink(missing_ok=True)
                    raise
            threading.Thread(target=process.wait, daemon=True).start()
            print(f"{manifest['name']} is running.")
            if moved:
                print(f"Port {moved[0]} was busy, so it started on {moved[1]}.")
            if ports:
                print("Open " + app_link(ports[0], manifest))
            available = self.newer_version(ident, manifest)
            if available:
                print(f"Version {available} is out. Run: farm update {ident}")
            print(manifest["pitch"])
            print(f"Stop it with: farm stop {ident}")
            print(f"Log: {app / 'farm.log'}")
            if refused:
                self.local_network_hint()

    def _stop(self, ident):
        app = self.app_dir(ident)
        pid = self.active(ident)
        if pid and WINDOWS:
            try:
                with WindowsProcess(pid) as process:
                    # Recheck using the same handle that will receive termination.
                    if process.identity == read_json(app / "process.json").get("identity"):
                        process.terminate()
                        deadline = time.monotonic() + 5
                        while process.running() and time.monotonic() < deadline:
                            time.sleep(0.05)
                        if process.running():
                            raise FarmError("App did not stop; keeping its process records.")
            except OSError as error:
                if getattr(error, "winerror", None) != 87:
                    raise
        elif pid:
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

    def stop(self, ident=None):
        if ident is None:
            return self.choose_to_stop()
        with self.guard(ident):
            print(f"Stopped {ident}." if self._stop(ident) else f"{ident} is not running.")

    def status_rows(self):
        """One row per running app: its process, the port it took, and what it reports."""
        for path in sorted(self.home.glob("*/farm.pid")):
            ident = path.parent.name
            with self.guard(ident):
                pid = self.active(ident)
                if not pid:
                    continue
                info = read_json(path.parent / "process.json")
                ports = list(info["ports"])
                _, manifest = self.installed(ident)
                version = info.get("version", "unknown")
                state = None
                health_path = info.get("health", manifest.get("health"))
                if health_path and ports:
                    health = self.health(ports[0], health_path)
                    if health is None:
                        state = "unavailable"
                    elif isinstance(health.get("version"), str) and VERSION.fullmatch(health["version"]):
                        version = health["version"]
                        state = "ok"
                    else:
                        state = "unversioned"
                yield {"id": ident, "pid": pid, "ports": ports, "port": ports[0] if ports else None,
                       "url": app_link(ports[0], manifest) if ports else None,
                       "uptime": max(0, int(time.time() - info["started"])),
                       "version": version, "installed": manifest["version"],
                       "restartToUpdate": version != manifest["version"], "health": state,
                       "updateAvailable": self.newer_version(ident, manifest) or None}

    def status(self):
        print("APP PID PORT LINK UPTIME STATUS")
        for row in self.status_rows():
            detail = f"running {row['version']}"
            if row["restartToUpdate"]:
                detail += f", installed {row['installed']}: restart to update"
            if row["updateAvailable"]:
                detail += f", update available: {row['updateAvailable']}"
            note = {"unavailable": " (health unavailable)",
                    "unversioned": " (health version unavailable)"}.get(row["health"], "")
            print(f"{row['id']} {row['pid']} {','.join(map(str, row['ports'])) or '-'}"
                  f" {row['url'] or '-'} {row['uptime']}s {detail}{note}")

    def device_models(self, settings, interpreter=None, timeout=5.0):
        """What the Tiiny lists on /v1/models, using the saved key, asked by the interpreter that
        can reach the device. The key is never printed, and neither is any error text, because
        both can carry it."""
        if interpreter and Path(interpreter) != Path(sys.executable):
            try:
                done = run_probe([interpreter, "-c", MODELS_PROBE, settings["base"], str(timeout)],
                                 timeout + 5, stdin=settings["key"] + "\n")
                answer = json.loads(done.stdout.strip().splitlines()[-1])
            except (OSError, ValueError, IndexError, subprocess.SubprocessError):
                return "unreachable", []
            listed = answer.get("models")
            return (str(answer.get("state") or "unreachable"),
                    [name for name in listed if isinstance(name, str)] if isinstance(listed, list) else [])
        request = Request(settings["base"].rstrip("/") + "/models",
                          headers={"Authorization": "Bearer " + settings["key"],
                                   "Accept": "application/json",
                                   "User-Agent": "tiinyapp-farm/" + _version()})
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read(1024 * 1024))
        except HTTPError as error:
            error.close()
            return ("refused" if error.code in (401, 403) else f"http {error.code}"), []
        except (OSError, URLError, ValueError, HTTPException):
            return "unreachable", []
        listed = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(listed, list):
            return "unreadable", []
        return "ok", [model["id"] for model in listed
                      if isinstance(model, dict) and isinstance(model.get("id"), str)]

    def note(self, check, ok, message, fix="", **detail):
        """One line a person reads, kept where an agent can act on the same sentence.

        A finding with no message of its own is a Fix line under the one before it, and carries
        that line as its message, so the JSON and the printing say the same words either way."""
        if message:
            print(message)
        if fix:
            print("Fix: " + fix)
        self.findings.append({"check": check, "ok": ok, "message": message or "Fix: " + fix,
                              "fix": fix or None, **detail})
        return ok

    def doctor_nothing_on_file(self):
        """No settings to check, so the next best answer is whether there is a Tiiny to save.

        A person who has not run farm device yet is the person least able to work out what to type,
        so doctor does the looking instead of telling them to go and look. Three answers, never two:
        one it can see, nothing there, or a Python macOS will not let look.
        """
        try:
            answer = self.find_tiinys()
        except Exception:  # noqa: BLE001 - a finding must never be the reason doctor falls over.
            answer = {"found": [], "blocked": False, "python": sys.executable, "moved": None}
        found = answer["found"]
        detail = {"found": [{"serial": r["serial"], "name": r["name"], "address": r["address"],
                             "via": r["via"], "base": r["base"]} for r in found],
                  "blocked": answer["blocked"], "python": answer["python"],
                  "moved": answer["moved"]}
        if not found and answer["blocked"]:
            return self.note("device", False, "No Tiiny is on file, and the farm cannot tell"
                             f" whether one is there: macOS refused {answer['python']} your local"
                             " network.",
                             "System Settings, Privacy and Security, Local Network, turn on"
                             " Python, then run farm doctor again.", **detail)
        if not found:
            return self.note("device", False, "No Tiiny is on file, and nothing answered on the"
                             " cable, on this network, or at the TiinyOS client.",
                             "switch the Tiiny on and plug the cable in, then run farm device"
                             " --find; or run farm device with the address and its API key.",
                             **detail)
        counted = describe_device(found[0]) if len(found) == 1 else \
            f"{len(found)} of them, the first " + describe_device(found[0])
        moved = (f" It had to look with {answer['moved']}, because macOS refused the Python it was"
                 " using, and will run apps with that one from now on." if answer["moved"] else "")
        ok = self.note("device", False, "No Tiiny is on file, so no app can reach one."
                       f" The farm can see {counted}.{moved}",
                       f"run farm device, take {found[0]['base']} when it offers it, and paste"
                       " the key from TiinyOS, Settings, API Key.", **detail)
        if answer["blocked"] and not answer["moved"]:
            # Something answered, but not over the local network, so saving its address would set
            # somebody up to watch every app fail at the thing doctor already knows about.
            self.note("python", False, f"macOS refused {answer['python']} your local network, so"
                      " an app the farm starts will not reach a Tiiny on the cable or on this"
                      " network.",
                      "System Settings, Privacy and Security, Local Network, turn on Python, then"
                      " run farm doctor again.", python=answer["python"])
        return ok

    def doctor_device(self, settings, interpreter):
        """The address on file, whether this Python reaches it, and whether the key is taken."""
        host = urlsplit(settings["base"]).hostname
        started = time.monotonic()
        code, address, _ = self.probe_device(host, interpreter)
        took = max(1, int((time.monotonic() - started) * 1000))
        where = address or host
        if code == 0:
            self.note("device", True, f"Your Tiiny at {where} answered this Python in {took} ms.",
                      address=where, milliseconds=took)
        elif code in NO_ROUTE and private_address(address):
            self.note("device", False, f"This Python cannot reach your Tiiny at {where},"
                      " because macOS is blocking it from your local network.", address=where)
            return False, [], True
        else:
            self.note("device", False, f"Nothing answered at {where}, port {DEVICE_PORT}.",
                      "switch the Tiiny on and put it on this network, or run farm device"
                      " if its address has changed.", address=where)
            return False, [], False
        state, models = self.device_models(settings, interpreter)
        if state == "ok":
            self.note("key", True, "The key on file is accepted by your Tiiny.")
            return True, models, False
        self.note("key", False,
                  "Your Tiiny refused the key on file." if state == "refused" else
                  f"Your Tiiny would not answer for the key on file ({state}).",
                  "copy the key again from TiinyOS, Settings, API Key, then run farm device.",
                  state=state)
        return False, models, False

    def doctor_pythons(self, host, interpreter):
        """Which other Pythons on this machine can reach the Tiiny, and the first that can."""
        said, working, tried = [], None, []
        for candidate in python_candidates(skip=[interpreter])[:MOST_PYTHONS_TRIED]:
            code, _, version = self.probe_device(host, candidate)
            reaches = code == 0 and version >= (3, 9)
            working = working or (candidate if reaches else None)
            said.append(f"{candidate} {'reaches it' if reaches else 'does not'}")
            tried.append({"path": candidate, "reaches": reaches})
        self.note("pythons", True,
                  "Other Pythons here: " + join_words(said) + "." if said else
                  "There is no other Python on this machine to fall back to.", pythons=tried)
        return working

    def doctor_apps(self):
        """Every installed app, the port it declares, and who is holding it."""
        idents = sorted(path.parent.name for path in self.home.glob("*/current"))
        if not idents:
            return self.note("apps", True, "No apps are installed yet."
                             " Run: farm list to see what the catalog has.")
        ok = True
        for ident in idents:
            with self.guard(ident):
                try:
                    _, manifest = self.installed(ident)
                except (FarmError, OSError, ValueError):
                    ok = self.note("app", False, f"{ident} is installed but the farm cannot read it.",
                                   f"install it again with farm remove {ident} and farm install {ident}.",
                                   id=ident) and ok
                    continue
                running = self.active(ident)
                live = []
                if running:
                    try:
                        live = read_json(self.app_dir(ident) / "process.json").get("ports") or []
                    except (OSError, ValueError):
                        live = []
            if manifest["entry"] is None:
                self.note("app", True, f"{ident} is a library, so it has no port and nothing to start.",
                          id=ident)
                continue
            if not manifest["requires"]["ports"]:
                self.note("app", True, f"{ident} declares no port.", id=ident)
                continue
            for port in manifest["requires"]["ports"]:
                if not self.tcp_ready(port):
                    self.note("port", True, f"{ident} declares port {port}, and it is free.",
                              id=ident, port=port)
                elif port in live:
                    self.note("port", True,
                              f"{ident} declares port {port}, and {ident} itself is holding it.",
                              id=ident, port=port)
                else:
                    ok = self.note("port", False,
                                   f"{ident} declares port {port}, and something else is holding it.",
                                   f"stop whatever has it, or put the app somewhere else:"
                                   f" farm start {ident} --port N.", id=ident, port=port) and ok
        return ok

    def doctor(self):
        """Everything a person would otherwise have to ask somebody else to check for them."""
        self.findings = []
        interpreter = self.app_python() or sys.executable
        version = ".".join(map(str, sys.version_info[:3]))
        self.note("farm", True, f"farm {_version()}, running apps with {interpreter}"
                  + (f" (Python {version})." if Path(interpreter) == Path(sys.executable) else "."),
                  farm=_version(), python=interpreter)
        offered = self.offered_cli()
        if newer_version(offered, _version()):
            self.note("cli", False, f"farm {offered} is out and you are on {_version()}."
                      " Run: farm self-update", offered=offered)
        settings = self.device_settings()
        models, working = [], None
        if not settings:
            ok = self.doctor_nothing_on_file()
        else:
            self.note("settings", True, f"The Tiiny on file is at {settings['base']}.",
                      base=settings["base"])
            ok, models, blocked = self.doctor_device(settings, interpreter)
            working = self.doctor_pythons(urlsplit(settings["base"]).hostname, interpreter)
            if blocked and working:
                self.note("python", False, "",
                          f"the farm can run apps with {working}, which does reach it."
                          f" Take it with: farm start <id> --python {working}", python=working)
            elif blocked:
                self.note("python", False, "",
                          "System Settings, Privacy and Security, Local Network, turn on Python,"
                          " then run farm doctor again.")
        listed = ok
        ok = self.doctor_apps() and ok
        if listed and models:
            counted = "1 model" if len(models) == 1 else f"{len(models)} models"
            self.note("models", True, f"Your Tiiny lists {counted}: " + join_words(models) + ".",
                      models=models)
        elif listed:
            self.note("models", False, "Your Tiiny has no models on it right now.",
                      "load one from TiinyOS, or from an app that manages them.", models=[])
        print("Everything the farm checks is working." if ok else
              "Something above needs attention, and each Fix line says what to do.")
        return ok

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


# Every command that answers a machine as well as a person. The shapes are documented in the
# agent guide at https://tiinyapp.farm/docs/agents/ and pinned by tests/test_farm.py.
JSON_COMMANDS = ("list", "status", "check", "doctor", "install", "update", "start", "stop",
                 "device")


def live_process(farm, ident):
    """The process record of a running app, or empty when there is none to read."""
    try:
        return read_json(farm.app_dir(ident) / "process.json")
    except (FarmError, OSError, ValueError):
        return {}


def installed_json(farm, ident):
    """Where an installed app sits now and what its catalog entry declares."""
    with farm.guard(ident):
        root, manifest = farm.installed(ident)
    return {"id": ident, "name": manifest["name"], "version": manifest["version"],
            "path": str(root), "library": manifest["entry"] is None,
            "ports": list(manifest["requires"]["ports"]),
            "permissions": list(manifest["permissions"])}


def running_json(farm, ident):
    """The version on disk, the pid, the port it really took, and the link to open."""
    with farm.guard(ident):
        pid = farm.active(ident)
        _, manifest = farm.installed(ident)
    ports = list(live_process(farm, ident).get("ports") or []) if pid else []
    return {"version": manifest["version"], "running": pid is not None, "pid": pid, "ports": ports,
            "port": ports[0] if ports else None,
            "url": app_link(ports[0], manifest) if ports else None}


def name_the_app(farm, verb):
    """The sentence a person gets when nobody is there to answer the chooser's question."""
    rows = farm.startable_apps() if verb == "start" else farm.running_apps()
    if rows:
        return name_one(verb, [row[0] for row in rows])
    if verb == "stop":
        return "Nothing is running."
    if not any(farm.home.glob("*/current")):
        return "Nothing is installed yet. Run: farm list to see what the catalog has."
    if farm.running_apps():
        return "Everything you have installed is already running."
    return "Nothing you have installed is a runnable app; a library has nothing to start."


def check_json(farm, args):
    """What the catalog has that this machine does not, and anything --yes or --all then took."""
    found, unreachable = ([], []) if not any(farm.home.glob("*/current")) else farm.updates()
    updates = []
    for ident, installed, latest in found:
        day = latest.get("updatedAt")
        updates.append({"id": ident, "name": latest["name"], "installed": installed["version"],
                        "available": latest["version"], "notes": release_note(latest) or None,
                        "updatedAt": day if isinstance(day, str)
                        and re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) else None})
    taken = []
    if getattr(args, "every", False) or getattr(args, "yes", False):
        for ident, _, _ in found:
            farm.update(ident, yes=True)
            taken.append(ident)
    return {"command": "check", "updates": updates, "unreachable": unreachable, "updated": taken}


def json_command(farm, args, ident):
    """One JSON object for one command, built from the same work the printed command does."""
    if args.command == "list":
        installed, catalog = farm.listing()
        return {"command": "list", "installed": installed, "catalog": catalog}
    if args.command == "status":
        if ident:
            seed = farm.submission(ident, token=args.token)
            return {"command": "status", "id": app_id(ident), "state": seed.get("state", "unknown"),
                    "checks": [check for check in seed.get("checks", []) if isinstance(check, dict)],
                    "reviews": [str(review) for review in seed.get("reviews", [])],
                    "prUrl": seed.get("prUrl"), "unavailable": bool(seed.get("unavailable"))}
        return {"command": "status", "running": list(farm.status_rows())}
    if args.command == "check":
        return check_json(farm, args)
    if args.command == "doctor":
        ok = farm.doctor()
        return {"command": "doctor", "ok": ok, "farm": _version(), "findings": farm.findings}
    if args.command == "device":
        if not args.find:
            raise FarmError("farm device --json answers --find only; saving a key needs the"
                            " hidden prompt or --key-stdin.")
        answer = farm.find_device()
        return {"command": "device", "ok": bool(answer["found"]),
                "blocked": answer["blocked"], "python": answer["python"],
                "moved": answer["moved"],
                "found": [{"serial": record["serial"], "name": record["name"],
                           "address": record["address"], "via": record["via"],
                           "base": record["base"], "interfaces": record["interfaces"]}
                          for record in answer["found"]]}
    if args.command == "install":
        if not args.yes:
            raise FarmError("Add --yes: with --json the farm never asks you to confirm an install.")
        farm.install(ident, yes=True)
        return {"command": "install", "installed": True, **installed_json(farm, ident)}
    if args.command == "update":
        if ident is None:
            return check_json(farm, args)
        with farm.guard(ident):
            _, before = farm.installed(ident)
        available = update_available(before, farm.manifest(ident))
        farm.update(ident, yes=True)
        live = running_json(farm, ident)
        return {"command": "update", "id": app_id(ident),
                "updated": live["version"] != before["version"], "previous": before["version"],
                "available": available or None, **live}
    if args.command == "start":
        if ident is None:
            raise FarmError(name_the_app(farm, "start"))
        with farm.guard(ident):
            already = bool(farm.active(ident))
        farm.start(ident, port=args.port, python=args.python)
        return {"command": "start", "id": app_id(ident), "already": already,
                **running_json(farm, ident), "log": str(farm.app_dir(ident) / "farm.log")}
    if ident is None:
        raise FarmError(name_the_app(farm, "stop"))
    with farm.guard(ident):
        running = bool(farm.active(ident))
    farm.stop(ident)
    return {"command": "stop", "id": app_id(ident), "stopped": running}


def run_json(farm, args):
    """One JSON object on stdout and nothing else; the prose a person would read goes to stderr."""
    ident = getattr(args, "id", None)
    try:
        # Everything the command prints is the running commentary, not the answer.
        with redirect_stdout(sys.stderr):
            payload = json_command(farm, args, ident)
    except (FarmError, OSError, ValueError, KeyError, TypeError, tarfile.TarError, getpass.GetPassWarning) as error:
        payload = {"error": {"command": args.command, "message": str(error) if isinstance(error, FarmError)
                             else f"{type(error).__name__}; check the catalog, app files or device settings.",
                             **({"id": ident} if ident else {})}}
    except (EOFError, KeyboardInterrupt):
        payload = {"error": {"command": args.command, "message": "Cancelled.",
                             **({"id": ident} if ident else {})}}
    print(json.dumps(payload))
    return 0 if payload.get("ok", "error" not in payload) else 1


def _version():
    try:
        from importlib.metadata import version
        return version("tiinyapp-farm")
    except Exception:  # running from a checkout without an install
        pass
    try:
        project = Path(__file__).resolve().parents[1] / "pyproject.toml"
        found = re.search(r'^version\s*=\s*"([^"]+)"', project.read_text(), re.M)
        if found:
            return found.group(1)
    except OSError:
        pass
    return "unknown"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version="farm " + _version())
    parser.add_argument("--no-update-check", action="store_true",
                        help="Do not look for a newer farm (or set FARM_NO_UPDATE_CHECK=1)")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("install", "update", "start", "stop", "remove"):
        command = commands.add_parser(name)
        asks = {"update": "App id; with no id it lists everything newer and asks which to take",
                "start": "App id; with no id it lists what is not running and asks which to start",
                "stop": "App id; with no id it lists what is running and asks which to stop"}
        command.add_argument("id", nargs="?" if name in asks else None, help=asks.get(name))
        if name == "install":
            command.add_argument("--yes", "-y", action="store_true", help="Accept the install prompt")
        if name == "update":
            command.add_argument("--yes", "-y", action="store_true", help="Update without asking")
            command.add_argument("--all", dest="every", action="store_true",
                                 help="Update everything with a newer version without asking")
        if name == "start":
            command.add_argument("--port", type=int, help="Override the app's primary listening port")
            command.add_argument("--python", help="Run this app with this Python, and keep it for later starts")
        if name == "remove":
            command.add_argument("--purge", action="store_true", help="Also delete saved data")
    device = commands.add_parser("device")
    device.add_argument("--find", action="store_true",
                        help="Look for a Tiiny on the cable, on this network and at the TiinyOS"
                             " client, and save nothing")
    device.add_argument("--base", help="Device HTTP(S) base URL (or TIINY_BASE)")
    device.add_argument("--key-stdin", action="store_true", help="Read the device API key from stdin (or TIINY_KEY)")
    login = commands.add_parser("login")
    login.add_argument("--token-stdin", action="store_true", help="Read the token from standard input (one line)")
    publish = commands.add_parser("publish")
    publish.add_argument("--token", help="API token (otherwise FARM_TOKEN or ~/.tiinyapps/token)")
    publish.add_argument("--update", action="store_true", help="Update an existing app")
    bump = commands.add_parser("release")
    bump.add_argument("id", nargs="?", help="App id (otherwise the id in farm.json here)")
    status = commands.add_parser("status")
    status.add_argument("id", nargs="?", help="Show submission checks for this app")
    status.add_argument("--token", help="API token (otherwise FARM_TOKEN or ~/.tiinyapps/token)")
    commands.add_parser("list")
    commands.add_parser("doctor")
    commands.add_parser("self-update")
    check = commands.add_parser("check")
    check.add_argument("--yes", "-y", action="store_true", help="Update everything newer without asking")
    check.add_argument("--all", dest="every", action="store_true",
                       help="Update everything with a newer version without asking")
    for command in commands.choices.values():
        # The docs say "on any command", so the flag is taken after the command too; a
        # subparser default would overwrite the top-level one, hence SUPPRESS.
        command.add_argument("--no-update-check", action="store_true", default=argparse.SUPPRESS,
                             help=argparse.SUPPRESS)
    for name in JSON_COMMANDS:
        commands.choices[name].add_argument(
            "--json", action="store_true",
            help="Answer with one JSON object on stdout; the prose goes to standard error")
    args = parser.parse_args(argv)
    farm = Farm()
    # An answer meant for a machine carries no notice about the farm itself; farm doctor --json
    # keeps that among its findings, where something can act on it.
    if getattr(args, "json", False):
        return run_json(farm, args)
    code = 0
    try:
        if args.command == "install":
            farm.install(args.id, yes=args.yes)
        elif args.command == "update":
            farm.update(args.id, yes=args.yes, everything=args.every)
        elif args.command == "check":
            farm.update(None, yes=args.yes, everything=args.every)
        elif args.command == "login":
            farm.login(token_stdin=args.token_stdin)
        elif args.command == "publish":
            farm.publish(token=args.token, update=args.update)
        elif args.command == "release":
            farm.release(args.id)
        elif args.command == "status" and args.id:
            farm.submission_status(args.id, token=args.token)
        elif args.command == "device":
            code = 0 if farm.device(base=args.base, key_stdin=args.key_stdin, find=args.find) else 1
        elif args.command == "remove":
            farm.remove(args.id, purge=args.purge)
        elif args.command == "doctor":
            code = 0 if farm.doctor() else 1
        elif args.command == "self-update":
            farm.self_update()
        elif args.command == "start":
            farm.start(args.id, port=args.port, python=args.python)
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
    # After the work, never before it, and never on top of a command that failed.
    if not args.no_update_check and args.command not in ("doctor", "self-update"):
        farm.update_notice()
    return code


if __name__ == "__main__":
    sys.exit(main())
