#!/usr/bin/env python3
"""Build the readable farm catalog with Pillow share cards."""

import argparse
from datetime import date, datetime, timezone
from html import escape, unescape
import json
import re
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen
from pathlib import Path
import runpy
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://tiinyapp.farm"
REPO = "https://github.com/Titanium-Devops/tiinyapp-farm"
PERMISSIONS = {
    "microphone": "Microphone: can listen through your microphone.",
    "files": "Files: can read or write files on your computer.",
    "network": "Network: can make network connections.",
    "device": "Device: can send requests to your Tiiny.",
}
CATEGORIES = {
    "developer-tools": "Developer tools",
    "coordination": "Developer tools",
    "benchmark": "Developer tools",
    "measurement": "Developer tools",
    "library": "Libraries",
    "stories": "Family",
    "family": "Family",
    "audio": "Audio",
    "assistant": "Assistants",
    "chat": "Assistants",
    "voice": "Assistants",
}
CATEGORY_ORDER = ["Assistants", "Family", "Audio", "Developer tools", "Libraries"]
FIELDS = {
    "id": "The unique lowercase app name used in commands and the manifest filename.",
    "name": "The name shown in the catalog.",
    "pitch": "One short line explaining what it does.",
    "description": "The app description, including limitations and release readiness.",
    "version": "The release version as major.minor.patch.",
    "author": "The maker's TiinyVerse display name, public URL and verified tiinyverse profile URL.",
    "license": "The license identifier; NOASSERTION means a license is not confirmed.",
    "homepage": "The app's public home page.",
    "repo": "Optional source repository; uploaded archives include source for review.",
    "media": "Optional icon, header and gallery image URLs; up to eight gallery images.",
    "links": "Optional repo, video (YouTube), and homepage links.",
    "screenshots": "A list of public image URLs; an empty list is fine.",
    "release": "The archive url, its sha256 checksum and its size in bytes. A pending checksum blocks installation; size 0 means unknown.",
    "entry": "A Python module (python) and args, or a command. Use null for a library with nothing to start.",
    "port": "Optional. How the app takes the port farm start gives it: {\"argv\": \"--port\"} for a command line flag, {\"env\": \"PORT\"} for an environment variable, or null for a fixed port. Leave it out and the farm sets TIINYAPP_PORT.",
    "requires": "Minimum python version if known, local ports, and device requirements: models and npuUnits.",
    "permissions": "Declared access: microphone, files, network and device. An empty list no permissions declared.",
    "tags": "Short labels that help people find the app.",
    "updates": "Optional. auto, the default, lets the farm open a pull request when the repository publishes a newer release; manual leaves this app's version alone.",
    "prereleases": "Optional. false by default, so release tracking considers only full GitHub releases.",
    "verified": "Keep false when submitting. A maintainer sets true in a follow-up commit after CI and manual review.",
    "featured": "Optional maintainer-curated placement in the home page Featured section.",
    "addedAt": "The day the app joined the catalog, YYYY-MM-DD. New lasts less than 30 days.",
    "updatedAt": "The most recent manifest update, YYYY-MM-DD.",
    "selfcheck": "Optional boolean. When true, CI appends --selfcheck to the entry and requires exit 0 offline within 120 seconds.",
    "health": "Optional HTTP health path on the first declared port, returning a JSON object with version and optional ok.",
    "open": "Optional first page on the first declared port, offered as a link when the app starts. It defaults to the root, and a health path is a probe rather than a page.",
}


def cli_version():
    """The farm version this site publishes, so the CLI can tell a person it has fallen behind
    without anything on this site or in the command talking to PyPI. It is the version of the
    package this script ships beside, whatever tree the manifests are built from."""
    found = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M)
    if not found:
        raise SystemExit("pyproject.toml has no version for the catalog to publish.")
    return found.group(1)


def e(value):
    return escape(str(value), quote=True)


def link(url, label):
    return f'<a href="{e(url)}">{e(label)}</a>'


def command(value):
    return f'<pre><code>{e(value)}</code></pre>'


# The desktop launcher is off until site/launcher.json says otherwise. Everything the launcher
# adds to this site hangs off that one file, so this script can sit on main for as long as it
# takes the app to ship and build the pages exactly as it built them before.
LAUNCHER_OFF = {"enabled": False, "version": None, "mac": None, "windows": None,
                "macIntel": None, "linux": None}
LAUNCHER_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def read_launcher(source):
    """The launcher switch, refusing a half-filled one rather than building a broken button."""
    path = Path(source) / "site/launcher.json"
    if not path.exists():
        return dict(LAUNCHER_OFF)
    setting = json.loads(path.read_text(encoding="utf-8"))
    if not setting.get("enabled"):
        return dict(LAUNCHER_OFF)
    for field in ("version", "mac", "windows"):
        if not isinstance(setting.get(field), str) or not setting[field].strip():
            raise ValueError(f"site/launcher.json is enabled but has no {field}")
    # macIntel and linux are optional: an Intel Mac gets a small link beside the Mac button,
    # and the Linux button appears only once there is an AppImage to point it at.
    fields = ("mac", "windows") + tuple(f for f in ("macIntel", "linux") if setting.get(f))
    for field in fields:
        # The same flat name the Worker will serve: no slash, no pair of dots, no surprises.
        if not isinstance(setting[field], str) or not LAUNCHER_FILE.fullmatch(setting[field]) \
                or ".." in setting[field]:
            raise ValueError(f"site/launcher.json {field} must be one launcher filename")
    return {"enabled": True, "version": setting["version"], "mac": setting["mac"],
            "windows": setting["windows"], "macIntel": setting.get("macIntel") or None,
            "linux": setting.get("linux") or None}


ICONS = {
    "search": '<path d="M3 10a7 7 0 1 0 14 0a7 7 0 1 0-14 0m18 11l-6-6"/>',
    "copy": '<path d="M7 9.667A2.667 2.667 0 0 1 9.667 7h8.666A2.667 2.667 0 0 1 21 9.667v8.666A2.667 2.667 0 0 1 18.333 21H9.667A2.667 2.667 0 0 1 7 18.333z"/><path d="M4.012 16.737A2 2 0 0 1 3 15V5c0-1.1.9-2 2-2h10c.75 0 1.158.385 1.5 1"/>',
}


# The three platform marks, drawn as one filled path each so a download button costs no image
# request and inherits the colour of the button it sits in. Holes are cut with the even-odd rule.
MARKS = {
    "apple": '<path d="M16.6 12.3c0-2 1.1-3.3 2.4-4.1-.9-1.3-2.3-2-4-2.1-1.6-.2-3.2.9-4 .9-.8 0-2.2-.9-3.5-.9C5.6 6.2 3.6 7.7 3.6 11c0 1.1.2 2.2.6 3.4.5 1.6 2.4 5.5 4.3 5.4 1-.1 1.7-.7 3-.7 1.3 0 1.9.7 3 .7 2-.1 3.7-3.6 4.2-5.2-2.5-1.2-2.1-3.4-2.1-3.4Z"/><path d="M14.3 4.6c1-1.1 1-2.3.9-2.9-.9.1-2 .6-2.6 1.3-.7.8-1.1 1.8-1 2.8 1 .1 2-.4 2.7-1.2Z"/>',
    "windows": '<path d="M3 5.6 10.2 4.6v6.8H3Zm8.4-1.15L21 3v8.4h-9.6ZM3 12.6h7.2v6.8L3 18.4Zm8.4 0H21V21l-9.6-1.4Z"/>',
    "microsoft": '<path d="M3 3h8.4v8.4H3Zm9.6 0H21v8.4h-8.4ZM3 12.6h8.4V21H3Zm9.6 0H21V21h-8.4Z"/>',
    "monitor": '<path d="M3.2 4.8c0-.66.54-1.2 1.2-1.2h15.2c.66 0 1.2.54 1.2 1.2v9.6c0 .66-.54 1.2-1.2 1.2H4.4c-.66 0-1.2-.54-1.2-1.2Zm2 .8v8h13.6v-8Zm3.3 12.8h7a1 1 0 0 1 0 2h-7a1 1 0 0 1 0-2Z"/>',
    "terminal": '<path d="M3.2 4.8c0-.66.54-1.2 1.2-1.2h15.2c.66 0 1.2.54 1.2 1.2v14.4c0 .66-.54 1.2-1.2 1.2H4.4c-.66 0-1.2-.54-1.2-1.2Zm2 .8v12.8h13.6V5.6Zm1.9 2.5 1.3-1.3 3.1 3.1-3.1 3.1-1.3-1.3 1.8-1.8Zm5.5 4.9h4.6v1.8h-4.6Z"/>',
    "download": '<path d="M12 3a1 1 0 0 1 1 1v8.6l2.5-2.5 1.4 1.4-4.9 4.9-4.9-4.9 1.4-1.4 2.5 2.5V4a1 1 0 0 1 1-1Zm-7 14h14a1 1 0 0 1 0 2H5a1 1 0 0 1 0-2Z"/>',
    "linux": '<path d="M12 1.8c-2.3 0-3.9 1.8-3.9 4.2 0 1 0 1.6-.5 2.4C6.3 10.4 5.2 12.6 5.2 15c0 1.8.6 3.3 1.6 4.3-.4.4-.8.9-1 1.4-.2.6.1 1.1.7 1.2 1 .2 2.1.1 3-.3.8.2 1.6.3 2.5.3s1.7-.1 2.5-.3c.9.4 2 .5 3 .3.6-.1.9-.6.7-1.2-.2-.5-.6-1-1-1.4 1-1 1.6-2.5 1.6-4.3 0-2.4-1.1-4.6-2.4-6.6-.5-.8-.5-1.4-.5-2.4 0-2.4-1.6-4.2-3.9-4.2Zm-1.9 4.5a.95.95 0 1 1 0 1.9.95.95 0 0 1 0-1.9Zm3.8 0a.95.95 0 1 1 0 1.9.95.95 0 0 1 0-1.9ZM12 8.6l1.7 1.1-1.7 1.1-1.7-1.1Z"/>',
}


def mark(name):
    """One platform mark, filled with the colour of whatever it sits in."""
    return (f'<svg class="mk" viewBox="0 0 24 24" aria-hidden="true" fill="currentColor" '
            f'fill-rule="evenodd">{MARKS[name]}</svg>')


def icon(name):
    """Inline the checked-in Tabler paths with the locked size and stroke."""
    return (f'<svg class="ic" viewBox="0 0 24 24" aria-hidden="true" fill="none" '
            f'stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" '
            f'stroke-width="1.75">{ICONS[name]}</svg>')


def categories(app):
    present = {CATEGORIES[tag] for tag in app["tags"] if tag in CATEGORIES}
    return [name for name in CATEGORY_ORDER if name in present]


def permission_label(value):
    return "Your Tiiny" if value == "device" else value.capitalize()


def needs(app):
    models = app["requires"]["device"]["models"]
    return "needs " + ", ".join(models) if models else "no named models"


def category_tag(app):
    names = categories(app)
    return names[0] if names else "Developer tools"


def copy_command(value):
    return (f'<div class="cmd"><span>{e(value)}</span><button type="button" data-copy '
            f'aria-label="Copy command">{icon("copy")}</button></div>')


def search_text(app):
    return " ".join([app["name"], app["pitch"], app["author"]["name"], *app["tags"], *categories(app)]).lower()


def first_two_sentences(value):
    sentences = re.split(r'(?<=[.!?])\s+', value.strip())
    return " ".join(sentences[:2])


def badges(app, today):
    result = []
    if "release" not in app:
        result.append('<span class="badge sprouting">No release yet</span>')
    if app["verified"]:
        result.append('<span class="badge verified">Reviewed</span>')
    if 0 <= (today - date.fromisoformat(app["addedAt"])).days < 30:
        result.append('<span class="badge new">New</span>')
    if app["entry"] is None:
        result.append('<span class="badge library">Library</span>')
    return '<div class="badges">' + "".join(result) + '</div>'


def page(title, body, path, scripts=()):
    lede = re.search(r'<p class="(?:lede|sub|pitch)">(.*?)</p>', body, re.S) or re.search(r'<p>(.*?)</p>', body, re.S)
    description = unescape(re.sub(r'<[^>]+>', '', lede.group(1))) if lede else title
    card = path + 'card.png' if path.startswith('/apps/') else '/brand/og-image.png'
    dimensions = '<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">' if path.startswith('/apps/') else ''
    active = ('install' if path == '/install/' else 'submit' if path.startswith('/submit/') else
              'catalog' if path == '/catalog/' else 'apps' if path == '/' or path.startswith(('/apps/', '/makers/')) else '')
    navigation = ''.join(f'<a href="{url}"' + (' class="on" aria-current="page"' if key == active else '') + f'>{label}</a>' for key, url, label in [('apps', '/', 'Apps'), ('catalog', '/catalog/', 'Catalog'), ('install', '/install/', 'Install'), ('docs', '/docs/', 'Docs'), ('submit', '/submit/', 'Submit an app')])
    page_scripts = ''.join(f'<script type="module" src="{e(src)}"></script>' for src in scripts)
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{e(description)}">
<meta property="og:title" content="{e(title)} | tiinyapp.farm">
<meta property="og:description" content="{e(description)}">
<meta property="og:image" content="{ORIGIN}{card}">{dimensions}
<meta property="og:url" content="{ORIGIN}{path}">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#090D14">
<title>{e(title)} | tiinyapp.farm</title>
<link rel="canonical" href="{ORIGIN}{path}">
<link rel="icon" href="/brand/favicon.ico" type="image/x-icon">
<link rel="icon" href="/brand/favicon-32.png" sizes="32x32" type="image/png">
<link rel="icon" href="/brand/favicon-192.png" sizes="192x192" type="image/png">
<link rel="apple-touch-icon" href="/brand/apple-touch-icon.png">
<link rel="manifest" href="/site.webmanifest">
<link rel="stylesheet" href="/assets/site.css"></head>
<body><a class="skip" href="#main">Skip to content</a>
<header><div class="wrap"><a class="brand" href="/"><img class="brand-mark" src="/brand/tiinyapp-farm-square-logo.png" width="34" height="34" alt=""><span>tiinyapp.farm</span></a>
<nav aria-label="Main navigation">{navigation}<a class="me" data-farm-nav href="/submit/#account-panel">Sign in</a></nav></div></header>
<main id="main">{body}</main>
<footer><div class="wrap"><div class="marks"><a class="pill" href="https://titanium.bot"><img src="/brand/titanium-bot-logo.svg" width="120" height="30" alt="Titanium Bot"><span>Brought to you by Titanium Bot</span></a>
<a class="pill" href="https://tiiny.ai">Built for <img src="/brand/tiiny-logo.svg" width="80" height="28" alt="Tiiny"></a></div><span>Made by Titanium Computing</span><a href="/submit/">Submit an app</a><a href="/docs/">Documentation</a></div></footer>
{page_scripts}<script type="module" src="/assets/session.js"></script></body></html>'''


INSTALL_STEPS = '''<div class="steps">
<div class="stp"><div class="n">1</div><div><h2>Install the farm CLI</h2><p>Python 3.9 or newer. macOS, Linux and Windows.</p><pre>pip install tiinyapp-farm</pre><p class="small">If pip answers "externally managed environment" (Homebrew Python, recent Debian), use <code>pipx install tiinyapp-farm</code> instead.</p><p class="small">Check it: <code>farm --version</code></p></div></div>
<div class="stp"><div class="n">2</div><div><h2>Connect your Tiiny</h2><p>The CLI asks for two values once and saves them in <code>~/.tiinyapps/device.json</code>, readable only by you.</p><pre>farm device</pre>
<dl><dt>API base URL</dt><dd>On a Mac with the TiinyOS client installed: <code>http://openai.api.tiiny/v1</code><br>From any other computer on your network: <code>http://&lt;your-tiiny-ip&gt;/v1</code></dd><dt>API key</dt><dd>TiinyOS → Settings → API Key. Copy it.</dd></dl>
<p class="small">Run <code>farm device</code> again to change either value.</p></div></div>
<div class="stp"><div class="n">3</div><div><h2>Install and run an app</h2><p>Pick an app in the catalog. Its page shows what it needs and what it asks for before you install it.</p><pre>farm install titanium-tiiny-bot
farm start titanium-tiiny-bot</pre>
<p class="small">The install prints what the app asks for and waits for a yes. In a script, <code>farm install &lt;id&gt; -y</code> answers it.</p>
<p class="small">A start that worked ends with the link to open, what the app is for, and <code>Stop it with: farm stop &lt;id&gt;</code>.</p>
<p class="small">If something already holds the app's port, the farm steps up to the next free port and says so, unless that app's port is fixed. To pick the port yourself: <code>farm start &lt;id&gt; --port 7799</code>.</p>
<dl><dt><code>farm list</code></dt><dd>installed apps and whether they are running</dd><dt><code>farm stop &lt;id&gt;</code></dt><dd>stop one</dd><dt><code>farm update &lt;id&gt;</code></dt><dd>update to the newest release, then start it again</dd><dt><code>farm remove &lt;id&gt;</code></dt><dd>uninstall</dd></dl></div></div>
</div>'''

INSTALL_HEAD = '''<section class="page install-page"><h1>Install apps on your Tiiny</h1>
<p class="sub">Apps from the catalog run on your computer and talk to your Tiiny Pocket Lab over its local API. One command-line tool installs, starts and updates them.</p>'''

INSTALL_NOTE = '''<p class="note" style="margin-top:18px">Apps declare the access they use (microphone, files, network, your Tiiny). The CLI shows that before installing; it does not sandbox them. Read the source if that matters to you: every app in the catalog ships it.</p>'''


def download_row(platform, symbol, title, subtitle, href, recommend=True, hook=''):
    """One row of the desktop grid: the mark, what it is, which file it gives you, and an arrow.

    The whole row is the link, so the target is the row rather than a word inside it. The
    recommendation is in the markup but hidden, because nothing on the server knows which
    computer is reading; launcher.js reveals the one row that matches."""
    note = ('<span class="dl-rec" data-launcher-recommended hidden>'
            'Recommended for this computer</span>' if recommend else '')
    return (f'<a class="dl-row" data-platform="{platform}" data-launcher-get="{platform}"{hook} '
            f'href="{e(href)}" aria-label="Download Tiiny App Farm for {e(title)}, {e(subtitle)}">'
            f'{mark(symbol)}<span class="dl-text"><b>{e(title)}</b>'
            f'<span class="dl-sub">{e(subtitle)}</span>{note}</span>{mark("download")}</a>')


def download_block(launcher):
    """The desktop downloads: one panel, four rows, and the command line in its own box.

    Every row is a real link in the markup, so the panel works with JavaScript switched off."""
    rows = [download_row('mac', 'apple', 'macOS', 'Apple Silicon DMG',
                         '/launcher/' + launcher['mac'])]
    if launcher.get('macIntel'):
        # An Intel Mac is a row of its own rather than a footnote, because it is a different file.
        # It is recommended only where the browser actually reports an Intel Mac. Safari says
        # MacIntel on every Mac and cannot be asked, so there the Apple silicon row keeps it.
        rows.append(download_row('mac-intel', 'apple', 'macOS Intel', 'Intel DMG',
                                 '/launcher/' + launcher['macIntel'],
                                 hook=' data-launcher-intel'))
    rows.append(download_row('windows', 'microsoft', 'Windows', 'Windows 10/11 x64 installer',
                             '/launcher/' + launcher['windows']))
    if launcher.get('linux'):
        rows.append(download_row('linux', 'linux', 'Linux', 'AppImage',
                                 '/launcher/' + launcher['linux']))
    else:
        rows.append(download_row('linux', 'linux', 'Linux', 'Use the command line',
                                 '#command-line'))
    return ('<section class="dl" aria-labelledby="desktop">'
            '<div class="dl-head"><h2 id="desktop">' + mark('monitor') + 'Desktop</h2>'
            '<a class="btn ghost" href="/launcher/versions/">All releases</a></div>'
            '<p class="sub">Download the latest desktop build, or browse every release.</p>'
            '<div class="dl-grid" data-launcher>' + ''.join(rows) + '</div>'
            '<div class="dl-cli"><p class="dl-cli-head">' + mark('terminal')
            + '<b>CLI</b><span class="dl-sub">Linux</span></p>'
            + copy_command('pip install tiinyapp-farm')
            + f'<p class="fine">Version {e(launcher["version"])} on the desktop. The command line '
            'carries everything it needs too: no Docker, nothing to install first.</p>'
            '</div></section>')


def steps(launcher=None):
    """The install page. With the launcher on, the download leads and the CLI keeps its steps."""
    launcher = launcher or LAUNCHER_OFF
    if not launcher['enabled']:
        return INSTALL_HEAD + '\n' + INSTALL_STEPS + '\n' + INSTALL_NOTE + '</section>'
    where = 'Mac, Windows and Linux' if launcher.get('linux') else 'Mac and Windows'
    return ('<section class="page install-page"><h1>Install apps on your Tiiny</h1>\n'
            '<p class="sub">Apps from the catalog run on your computer and talk to your Tiiny '
            f'Pocket Lab over its local API. Tiiny App Farm is a small app for {where} '
            'that installs, starts and updates them for you.</p>\n'
            + download_block(launcher) + '\n'
            + '<h2 id="command-line">Prefer the command line?</h2>\n'
            '<p class="sub">The farm CLI does everything the app does, on every platform '
            'including Linux, and it is the same install directory either way. Start with the '
            'app and move to the CLI whenever you like: it finds what the app already put there.</p>\n'
            + INSTALL_STEPS + '\n' + INSTALL_NOTE + '</section>')


PLATFORMS = [("mac", "apple", "macOS"), ("windows", "windows", "Windows"),
             ("linux", "linux", "Linux")]
# A files key in the release history is a platform, optionally with the architecture it was built
# for: mac, or mac-arm64. The platform decides the mark and the anchor and is a closed set the
# site owns. The architecture is only a label, so an architecture nobody has shipped yet prints
# its own name rather than stopping a build.
ARCH_NAMES = {("mac", "arm64"): "Apple silicon", ("mac", "aarch64"): "Apple silicon",
              ("mac", "x64"): "Intel", ("mac", "x86_64"): "Intel",
              ("mac", "universal"): "Apple silicon and Intel"}
ARCH_ORDER = {"mac": ["arm64", "aarch64", "universal", "", "x64", "x86_64"],
              "windows": ["x64", "x86_64", "", "arm64", "aarch64"],
              "linux": ["x64", "x86_64", "", "arm64", "aarch64"]}
ARCH = re.compile(r"[a-z0-9_]+")
RELEASES_URL = ORIGIN + "/launcher/releases.json"
COUNTS_URL = ORIGIN + "/api/social/counts"
SHA256 = re.compile(r"[0-9a-f]{64}")


def arch_label(platform, arch):
    """What to call this build beside the platform, for a person choosing between two files."""
    if not arch:
        return ""
    return ARCH_NAMES.get((platform, arch), arch)


def check_releases(data):
    """The release history, refused rather than half-drawn when it is not the shape it promised.

    The launcher writes this file; the site only reads it. A page built from a history it did not
    understand would tell somebody a build is unsigned when nobody said so, so anything unexpected
    stops the build instead."""
    if isinstance(data, dict):
        data = data.get("releases")
    if not isinstance(data, list) or not data:
        raise ValueError("The launcher release history is empty or not a list of releases.")
    releases = []
    for entry in data:
        if not isinstance(entry, dict):
            raise ValueError("A launcher release is not an object.")
        version = entry.get("version")
        if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
            raise ValueError(f"A launcher release has no major.minor.patch version: {version!r}")
        try:
            day = date.fromisoformat(entry["date"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"Launcher release {version} has no YYYY-MM-DD date.")
        files = entry.get("files")
        if not isinstance(files, dict) or not any(files.values()):
            raise ValueError(f"Launcher release {version} lists no files.")
        known = {name for name, _, _ in PLATFORMS}
        kept = {}
        for key, entries in files.items():
            platform, dash, arch = str(key).partition("-")
            # A trailing dash names no architecture at all, which is a typo rather than a build.
            if platform not in known or (dash and not ARCH.fullmatch(arch)):
                raise ValueError(f"Launcher release {version} names a platform the site does not"
                                 f" know: {key}")
            # One platform usually ships one file, and the launcher writes that as the object
            # itself rather than a list of one. Both are read; a list is what a platform that
            # ever ships two files at once would need.
            if isinstance(entries, dict):
                entries = [entries]
            if not isinstance(entries, list):
                raise ValueError(f"Launcher release {version} {key} is not a file or a list"
                                 f" of files.")
            for item in entries:
                name = item.get("name") if isinstance(item, dict) else None
                if not isinstance(name, str) or not LAUNCHER_FILE.fullmatch(name) or ".." in name:
                    raise ValueError(f"Launcher release {version} {platform} has no usable"
                                     f" filename: {name!r}")
                size = item.get("size")
                if size is not None and (not isinstance(size, int) or size < 0):
                    raise ValueError(f"{name} has a size that is not a count of bytes.")
                checksum = item.get("sha256")
                if checksum is not None and not SHA256.fullmatch(str(checksum)):
                    raise ValueError(f"{name} has a sha256 that is not 64 hexadecimal characters.")
                kept.setdefault(platform, []).append({
                    "name": name, "size": size, "sha256": checksum and str(checksum),
                    "arch": arch, "signed": bool(item.get("signed")),
                    "notarised": bool(item.get("notarised"))})
        for platform, entries in kept.items():
            # The build most people want comes first, so the card at the top offers that one.
            order = ARCH_ORDER.get(platform, [])
            entries.sort(key=lambda item: order.index(item["arch"])
                         if item["arch"] in order else len(order))
        releases.append({"version": version, "date": day, "commit": entry.get("commit") or "",
                         "notes": entry.get("notes") or "", "files": kept})
    releases.sort(key=lambda release: [int(part) for part in release["version"].split(".")],
                  reverse=True)
    return releases


def read_releases(source, url=None, timeout=6.0, allow_stale=False):
    """The launcher's own release history: the live file when it answers, else the copy here.

    The live file is the one the launcher just wrote, so a deploy publishes the release it is
    deploying. The checked-in copy is what keeps a build working offline and in every test.

    A build that asked for the live file and did not get it stops. Quietly falling back to the
    copy is how a deploy once published a version history that was missing a release, its notes
    and its real filenames, and nothing in the log said so. Pass allow_stale to build from the
    copy on purpose."""
    fallback = Path(source) / "site/launcher-releases.json"
    data, refused = None, ""
    if url:
        try:
            request = Request(url, headers={"User-Agent": "tiinyapp-farm-site/1.0"})
            with urlopen(request, timeout=timeout) as answer:
                data = json.loads(answer.read(2_000_000).decode("utf-8"))
            print(f"launcher history: read {len(data if isinstance(data, list) else data.get('releases', []))}"
                  f" releases from {url}")
        except Exception as problem:
            refused = f"{type(problem).__name__}: {problem}"
    if refused:
        print(f"launcher history: {url} could not be read ({refused})", file=sys.stderr)
        if not allow_stale:
            raise ValueError(
                f"The launcher release history at {url} could not be read ({refused}). Building"
                " from site/launcher-releases.json would publish a copy that may be older than"
                " what is live, which is what a person reads when they go back a version. Fix the"
                " fetch, or pass --allow-stale-history to build from the copy on purpose.")
        print("launcher history: building from site/launcher-releases.json instead, as asked",
              file=sys.stderr)
    if data is None:
        if not fallback.exists():
            raise ValueError("The launcher is switched on but there is no release history:"
                             " site/launcher-releases.json is missing and the live file did not"
                             " answer.")
        data = json.loads(fallback.read_text(encoding="utf-8"))
    return check_releases(data)


def signing_words(item):
    """What a person needs to know about a file before they run it, in words rather than flags."""
    if item["signed"] and item["notarised"]:
        return "signed and notarised"
    if item["signed"]:
        return "signed"
    return "unsigned"


def release_files(release):
    """One release's files as a table: what to download, how big, and what it is checked by."""
    rows = []
    for platform, _, title in PLATFORMS:
        for item in release["files"].get(platform, []):
            named = f'{title}, {arch_label(platform, item["arch"])}' if item["arch"] else title
            size = f'{item["size"] / 1_000_000:.1f} MB' if item["size"] else "not recorded"
            if item["sha256"]:
                checksum = (f'<span class="mono" title="{e(item["sha256"])}">'
                            f'{e(item["sha256"][:12])}\u2026</span>')
            else:
                checksum = '<span class="fine">not recorded</span>'
            rows.append(f'<tr><td>{e(named)}</td>'
                        f'<td><a href="/launcher/{e(item["name"])}">{e(item["name"])}</a></td>'
                        f'<td>{e(size)}</td><td>{checksum}</td>'
                        f'<td>{e(signing_words(item))}</td></tr>')
    head = ''.join(f'<th scope="col">{label}</th>'
                   for label in ('Platform', 'File', 'Size', 'SHA-256', 'Signing'))
    return ('<div class="docs-table"><table><thead><tr>' + head + '</tr></thead><tbody>'
            + ''.join(rows) + '</tbody></table></div>')


def versions_page(releases):
    """Every launcher version, newest first, with a way back to any of them."""
    newest = releases[0]
    current = []
    for platform, symbol, title in PLATFORMS:
        files = newest["files"].get(platform, [])
        if files:
            which = arch_label(platform, files[0]["arch"])
            link = (f'<a class="btn ghost" href="/launcher/{e(files[0]["name"])}">'
                    f'{mark(symbol)}Download {e(newest["version"])}</a>')
            note = (f'<p class="fine">{e(signing_words(files[0]))}'
                    + (f', {e(which)}' if which else '') + '.</p>')
        else:
            link = f'<p class="get-os">{mark(symbol)}Not built yet</p>'
            note = '<p class="fine">There is no build for this platform.</p>'
        current.append(f'<div class="ver-plat" id="{platform}"><p class="get-os">{e(title)}</p>'
                       f'{link}{note}</div>')
    history = []
    for release in releases:
        day = release["date"]
        stamp = f'{day.day} {day:%B %Y}'
        commit = (f' <span class="fine">commit {e(release["commit"])}</span>'
                  if release["commit"] else '')
        notes = markdown(release["notes"]) if release["notes"] else '<p>No notes for this one.</p>'
        history.append(f'<section class="rel"><h2 id="v{e(release["version"].replace(".", "-"))}">'
                       f'{e(release["version"])}</h2>'
                       f'<p class="rel-when">{e(stamp)}{commit}</p>{notes}'
                       + release_files(release) + '</section>')
    return ('<section class="page versions-page"><h1>Launcher versions</h1>'
            '<p class="sub">Every version of Tiiny App Farm that has shipped, what changed in it, '
            'and a link to each file. Newest first.</p>'
            '<div class="ver-now">' + ''.join(current) + '</div>'
            '<p class="note">The newest version is the one the app updates itself to. An older '
            'build installs and runs, and it stays where it is: it stops being offered updates, '
            'and it is offered none of the fixes in the versions above it. Take one to get back '
            'to a working day, then move forward again when the reason is fixed.</p>'
            '<h2 id="history">History</h2>' + ''.join(history)
            + '<p class="docs-foot"><a href="/install/">Install an app</a> '
            '<a href="/docs/launcher/">About the launcher</a></p></section>')


def seed_kind(count):
    """Which of the three piles this count draws: nothing, a countable row, or a heap."""
    seeds = max(0, int(count or 0))
    return "none" if seeds == 0 else "seeds" if seeds <= 9 else "heap"


def seed_rows(count):
    """How many seeds sit in each row, counted from the bottom of the pile up.

    One shape, drawn four times: here, in worker/catalog.mjs for the pages the Worker writes, in
    site/assets/seed-stack.js for the counts a browser refreshes, and in the desktop launcher.
    Keep them in step. Nothing is one hollow husk and no rows. One to three lie in a single row.
    Four to nine split in two, the wider row underneath. Ten and up hold at a nine-seed heap and
    let the number do the counting, so the pile never shrinks as the count rises."""
    seeds = max(0, int(count or 0))
    if seeds == 0:
        return []
    if seeds <= 3:
        return [seeds]
    if seeds <= 9:
        return [-(-seeds // 2), seeds // 2]
    return [5, 4]


def seed_words(count):
    """What the pile says in its label and its tooltip."""
    seeds = max(0, int(count or 0))
    return "No seeds yet" if seeds == 0 else "1 seed" if seeds == 1 else f"{seeds} seeds"


def seed_stack(count, app_id=None):
    """A small pile of seeds that grows with the count. No button, just the tally.

    The pile reads as a picture, so the words travel in the label and the tooltip rather than
    beside every count. Only a heap shows a numeral, because nine seeds cannot be counted to 57.
    """
    seeds = max(0, int(count or 0))
    kind = seed_kind(seeds)
    pile = ('<i class="seed seed-husk"></i>' if kind == "none" else
            "".join('<span class="seed-row">' + '<i class="seed"></i>' * row + "</span>"
                    for row in seed_rows(seeds)))
    words = seed_words(seeds)
    tally = f'<span class="seed-count">{seeds}</span>' if kind == "heap" else ""
    marker = f' data-seed-stack="{e(app_id)}"' if app_id else ""
    return (f'<span class="seed-stack" data-seeds="{seeds}" data-kind="{kind}" role="img"'
            f' aria-label="{e(words)}" title="{e(words)}"{marker}>'
            f'<span class="seed-pile" aria-hidden="true">{pile}</span>{tally}</span>')


def read_counts(url=None, timeout=6.0):
    """Every app's seed count from the live farm, or nothing, which reads as zero.

    A fresh app has no seeds and a farm that cannot be reached looks the same to a visitor, so a
    build never stops here. The page a visitor loads refreshes these numbers a moment later from
    the same endpoint, which is what makes a stale build harmless."""
    if not url:
        return {}
    try:
        request = Request(url, headers={"User-Agent": "tiinyapp-farm-site/1.0"})
        with urlopen(request, timeout=timeout) as answer:
            data = json.loads(answer.read(2_000_000).decode("utf-8"))
        apps = data.get("apps") if isinstance(data, dict) else None
        if not isinstance(apps, dict):
            raise ValueError("no apps object in the answer")
        counts = {str(key): int(value.get("seeds", 0)) for key, value in apps.items()
                  if isinstance(value, dict)}
        print(f"seed counts: read {len(counts)} apps from {url}")
        return counts
    except Exception as problem:
        print(f"seed counts: {url} could not be read ({type(problem).__name__}: {problem});"
              " building every pile at zero, the page refreshes them live", file=sys.stderr)
        return {}


def seed_icon(app):
    url = app.get("media", {}).get("icon")
    return f'<img class="seed-icon" src="{e(url)}" width="72" height="72" alt="" loading="lazy">' if url else ''


def seed_media(app):
    media = app.get("media", {})
    header = (f'<div class="band" role="img" aria-label="{e(app["name"])} header" '
              f'style="background-image:url(&quot;{e(media["header"])}&quot;)"></div>'
              if media.get("header") else '')
    gallery = ''.join(f'<a class="gallery-thumb" href="{e(url)}" data-gallery-image><img src="{e(url)}" alt="{e(app["name"])} gallery image {i}" loading="lazy"></a>' for i, url in enumerate(media.get("gallery", []), 1))
    if gallery:
        gallery = '<section><h2>Screenshots</h2><div class="seed-gallery">' + gallery + '</div><dialog id="gallery-dialog" aria-label="Full-size app image"><form method="dialog"><button class="btn hay">Close image</button></form><img id="gallery-image" alt=""></dialog></section>'
    video = app.get("links", {}).get("video")
    trailer = ''
    if video:
        parsed = urlsplit(video)
        video_id = parsed.path.lstrip('/') if parsed.hostname == 'youtu.be' else parse_qs(parsed.query).get('v', [''])[0]
        if re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
            poster = media.get("header") or media.get("icon")
            picture = f'<img src="{e(poster)}" alt="" loading="lazy">' if poster else ''
            trailer = f'<section><h2>Video</h2><button class="video-poster" type="button" data-youtube-id="{e(video_id)}" aria-label="Play {e(app["name"])} video">{picture}<span>Play video</span></button><p class="fine">YouTube loads only when you press play.</p><noscript><p>{link(video, "Watch on YouTube")}</p></noscript></section>'
    return header, gallery + trailer


def plot(app, today, makers=()):
    maker = next((m for m in makers if m.get('tiinyverse') and m['tiinyverse'] == app['author'].get('tiinyverse')), None)
    maker_url = '/makers/' + maker['handle'] + '/' if maker else app['author']['url']
    models = ", ".join(app["requires"]["device"]["models"]) or "no named models"
    permissions = "".join(f'<span>{e("Your Tiiny" if p == "device" else p.capitalize())}</span>' for p in app["permissions"]) or '<span>no permissions declared</span>'
    planting = (f'<code>farm install {e(app["id"])}</code><a class="btn hay" href="/apps/{e(app["id"])}/" aria-label="Install {e(app["name"])}">Install</a>'
                if 'release' in app else f'<a class="btn hay" href="/apps/{e(app["id"])}/">View app</a>')
    return f'''<article class="plot"><div class="plot-top">{badges(app, today)}<span class="ver">v{e(app['version'])}</span></div>
<div class="seed-title">{seed_icon(app)}<h3>{e(app['name'])}</h3></div><p class="pitch">{e(app['pitch'])}</p><p class="by">by {link(maker_url, app['author']['name'])} · needs {e(models)}</p>
<div class="perms">{permissions}</div><div class="plant">{planting}</div></article>'''


def editorial_item(app, counts=None):
    media = app.get("media", {})
    art = (f'<div class="art" style="background-image:url(&quot;{e(media["header"])}&quot;)"></div>'
           if media.get("header") else '<div class="art"></div>')
    chips = ''.join(f'<span class="chip">{e(permission_label(value))}</span>' for value in app["permissions"])
    chips += f'<span class="chip">v{e(app["version"])}</span>'
    pile = seed_stack((counts or {}).get(app["id"], 0), app["id"])
    return f'''<article class="item">{art}<div class="text"><span class="cat-tag">{e(category_tag(app))}</span>
<h3 class="name"><a href="/apps/{e(app['id'])}/">{e(app['name'])}</a></h3><p class="pitch">{e(app['pitch'])}</p>
<p class="desc">{e(first_two_sentences(app['description']))}</p><div class="chips">{chips}{pile}</div>
<div class="foot"><a class="btn hay" href="/apps/{e(app['id'])}/">Install</a>{copy_command('farm install ' + app['id'])}</div></div></article>'''


def ledger_row(app, counts=None):
    media = app.get("media", {})
    icon_image = (f'<img src="{e(media["icon"])}" width="56" height="56" alt="">'
                  if media.get("icon") else '<span class="row-icon" aria-hidden="true"></span>')
    chips = f'<span class="chip">{e(needs(app))}</span>'
    chips += ''.join(f'<span class="chip">{e(permission_label(value))}</span>' for value in app["permissions"])
    pile = seed_stack((counts or {}).get(app["id"], 0), app["id"])
    return f'''<article class="row" data-catalog-search="{e(search_text(app))}">{icon_image}<div><span class="cat-tag">{e(category_tag(app))}</span>
<h3 class="name"><a href="/apps/{e(app['id'])}/">{e(app['name'])}</a></h3><p class="pitch">{e(app['pitch'])}</p><div class="chips">{chips}{pile}</div></div>
<span class="v">v{e(app['version'])}</span><a class="btn hay" href="/apps/{e(app['id'])}/">Install</a></article>'''


def home_page(apps, launcher=None, counts=None):
    launcher = launcher or LAUNCHER_OFF
    featured = [app for app in apps if app.get("featured")][:6]
    second = ('<a class="btn ghost" href="/install/">Get the launcher</a>' if launcher['enabled']
              else '<a class="btn ghost" href="/install/">Install an app</a>')
    hero = '''<section class="hero"><img src="/assets/hero.jpg" width="1600" height="1066" alt="A fantasy farm at dusk with glowing apps in rows and Titan tending the field."><div class="copy"><h1>Little apps, <em>grown for your Tiiny.</em></h1><p class="lede">Community-made apps that run beside your Pocket Lab on your own computer. Choose an app to see its requirements and install commands.</p><div class="row"><a class="btn hay" href="#all-apps">Browse apps</a>''' + second + '''</div></div></section>'''
    featured_section = f'''<section class="feat wrap"><div class="sechead"><h2>Featured</h2><p>Picked by the maintainers</p></div>
<div class="v3"><div class="list">{''.join(editorial_item(app, counts) for app in featured)}</div></div></section>'''
    ledger = f'''<section class="ledger wrap" id="all-apps"><div class="sechead"><h2>All apps</h2><p><a href="/catalog/">Browse the catalog with filters</a></p></div>
<div class="toolbar"><label class="search">{icon('search')}<span class="visually-hidden">Search apps</span><input id="q-home" type="search" placeholder="Search apps, makers, tags" autocomplete="off"></label><span class="count" id="count-home">{len(apps)} of {len(apps)}</span></div>
<div class="v2"><div class="rows" id="rows-home">{''.join(ledger_row(app, counts) for app in apps)}</div><p class="empty" id="empty-home" hidden>No app matches. Try fewer words.</p></div></section>'''
    invitation = '''<section class="seeds wrap"><div><h2>Submit an app</h2><p>Submit an app for automated checks and maintainer review.</p></div><a class="btn hay" href="/submit/">Share your app</a></section>'''
    return hero + featured_section + ledger + invitation


def catalog_page(apps):
    available = [name for name in CATEGORY_ORDER if any(name in categories(app) for app in apps)]
    category_buttons = ''.join(
        f'<button class="cat" type="button" data-cat="{e("" if name == "All" else name)}" aria-pressed="{str(name == "All").lower()}">{e(name)}</button>'
        for name in ['All', *available])
    return f'''<section class="catalog wrap"><h1>Catalog</h1><p class="lede">Every app on the farm. Each page shows what it needs and what it asks for before you install.</p>
<div class="toolbar"><label class="search">{icon('search')}<span class="visually-hidden">Search apps</span><input id="q-catalog" type="search" placeholder="Search apps, makers, tags" autocomplete="off"></label><span class="count" id="count-catalog" aria-live="polite"></span></div>
<div class="cats" id="catalog-categories" role="group" aria-label="Categories">{category_buttons}</div>
<div class="v1 catalog-grid"><div class="grid" id="catalog-grid"></div><p class="empty" id="empty-catalog" hidden>Nothing in that category yet. <a href="/submit/">Submit an app</a>.</p></div></section>'''


def social_strip(app):
    return f'''<section class="seed-social" data-seed-social="{e(app['id'])}" aria-labelledby="social-heading"><h2 id="social-heading">Comments</h2>
<p class="sub">Tell the maker how it is growing.</p>
<p id="social-status" role="status" aria-live="polite">Loading seeds and comments…</p>
<p id="social-signin"><a href="/submit/">Sign in to give this app a seed or leave a comment.</a></p>
<div id="seed-comments" aria-label="App comments"></div>
<form id="comment-form" hidden><label for="comment-text">Comment</label><textarea id="comment-text" name="text" rows="4" maxlength="1000" required aria-describedby="comment-help"></textarea><p id="comment-help" class="fine">Up to 1,000 characters. Five comments per hour.</p><button id="comment-submit" class="btn hay" type="submit">Post comment</button></form>
<noscript><p>JavaScript is needed to load seeds and comments.</p></noscript></section>'''


def art_panel(app):
    """The maker's own scene field and Generate art button. session.js reveals it for the owner."""
    return (f'<section class="art-panel owner-art" data-art-panel data-art-owner="{e(app["id"])}" hidden>'
            f'<h2>Art in the farm\'s hand</h2>'
            '<p class="sub">Describe this app\'s scene in one sentence and the farm draws a header and an icon '
            'in the same style as every other app on the shelf. '
            '<a href="/docs/art/">How this works</a>.</p>'
            '<label class="seed-field" for="scene">Describe your app\'s scene in one sentence '
            '<small>name the objects in the picture, not your app</small>'
            '<input id="scene" maxlength="200" placeholder="a corkboard of pinned cards joined by threads of light"></label>'
            '<div class="art-actions"><button class="btn ghost" id="art-generate" type="button">Generate art</button>'
            '<span class="small" id="art-state" role="status" aria-live="polite">Three drawings a day for one app.</span></div>'
            f'<div class="art-result" id="art-result" hidden>'
            f'<img class="art-header" id="art-header" alt="The header the farm drew for {e(app["name"])}">'
            f'<img class="art-icon" id="art-icon" alt="The icon the farm drew for {e(app["name"])}">'
            '<div class="art-actions"><button class="btn hay" id="art-use" type="button">Use these</button>'
            '<button class="btn ghost" id="art-again" type="button">Try again</button></div></div>'
            '<p class="fine">Use these opens the update form with the new pair attached. A published app\'s '
            'images change through the same pull request as everything else.</p></section>')


def app_page(app, today, makers=(), launcher=None, counts=None):
    launcher = launcher or LAUNCHER_OFF
    counts = counts or {}
    band, visual_media = seed_media(app)
    links = app.get('links', {})
    repo = links.get('repo') or app.get('repo')
    homepage = links.get('homepage') or app.get('homepage')
    req = app['requires']
    release = app.get('release')
    maker = next((m for m in makers if m.get('tiinyverse') and m['tiinyverse'] == app['author'].get('tiinyverse')), None)
    maker_url = '/makers/' + maker['handle'] + '/' if maker else app['author']['url']
    avatar = f'<img src="{e(maker["avatar"])}" alt="" width="36" height="36">' if maker and maker.get('avatar') else ''
    owner = '<span class="chip ok">Verified Tiiny owner</span>' if app['author'].get('tiinyverse') else ''
    review = 'Reviewed' if app['verified'] else 'Not reviewed yet'
    media = app.get('media', {})
    app_icon = (f'<img src="{e(media["icon"])}" width="72" height="72" alt="">'
                if media.get('icon') else '')
    if release:
        commands = f'farm install {app["id"]} && farm start {app["id"]}'
        local = f'Then open <code>http://localhost:{e(req["ports"][0])}</code>. ' if req['ports'] and app['entry'] is not None else ''
        # With the launcher on, the button is the way in and the two commands stay visible
        # underneath, because they are the answer when nothing on the machine knows the scheme.
        opener = (f'<p class="open-in"><a class="btn hay" href="tiinyfarm://install/{e(app["id"])}">Open in Tiiny App Farm</a></p>'
                  '<p class="small">Nothing opened? <a href="/install/">Get the launcher</a>.</p>'
                  if launcher['enabled'] else '')
        install = '<h2>Install</h2>' + opener + copy_command(commands) + f'<p class="sub install-note">{local}New here? <a href="/install/">Install the farm CLI first.</a></p>'
        if app['entry'] is None:
            install += '<p>This is a library. There is no app to start. Use it from your own application.</p>'
        size_mb = f'{release["size"] / 1_000_000:.1f} MB'
        short_sha = release['sha256'] if release['sha256'] == 'pending' else release['sha256'][:12] + '…'
        release_details = f'<dl><dt>Version</dt><dd>{e(app["version"])}</dd><dt>Size</dt><dd>{e(size_mb)}</dd><dt>SHA-256</dt><dd class="mono" title="{e(release["sha256"])}">{e(short_sha)}</dd><dt>Source</dt><dd>{link(repo or release["url"], "GitHub" if repo else "Release archive")}</dd></dl>'
        if release['sha256'] == 'pending':
            install += '<p class="note">The checksum is pending. This release cannot be installed yet.</p>'
    else:
        install = '<p>No release yet. This app cannot be installed.</p>'
        release_details = '<p>No release yet</p>'
    screenshots = ''.join(f'<a class="gallery-thumb" href="{e(url)}"><img src="{e(url)}" alt="{e(app["name"])} screenshot {i}" loading="lazy"></a>' for i, url in enumerate(app['screenshots'], 1))
    images = visual_media
    if screenshots:
        images += '<section><h2>Screenshots</h2><div class="seed-gallery">' + screenshots + '</div></section>'
    if not images:
        images = '<h2>Screenshots</h2><p class="fine">No screenshots yet.</p>'
    permissions = ''.join(f'<span class="chip">{e(permission_label(permission))}</span>' for permission in app['permissions']) or '<span class="chip">None declared</span>'
    python = e(req.get('python', 'Not specified')) + (' or newer' if req.get('python') else '')
    movable = ''
    if req['ports'] and app['entry'] is not None:
        movable = ('<dt>Move it</dt><dd>' + (f'<code>farm start {e(app["id"])} --port N</code>'
                   if 'port' not in app or app['port'] is not None
                   else f'Fixed on {e(req["ports"][0])}') + '</dd>')
    return f'''<section class="app wrap">{band}<div class="head">{app_icon}<div><h1>{e(app['name'])}</h1><div class="sub">v{e(app['version'])} · {e(app['license'])} · {review} · Grown by {link(maker_url, app['author']['name'])}</div></div></div>
<p class="pitch">{e(app['pitch'])}</p>
<div class="owner-tools"><a hidden data-seed-update="{e(app['id'])}" href="/submit/?update={e(app['id'])}">Update this app</a><span hidden data-seed-release="{e(app['id'])}"><button id="release-check" class="btn ghost" type="button">Check for a new release</button> <span id="release-status" role="status" aria-live="polite"></span> <a id="release-pr" hidden>View the pull request</a></span></div>
<div class="two"><div>{install}<h2>What it does</h2><p class="desc">{e(app['description'])}</p>{'<p>' + link(homepage, 'Home page') + '</p>' if homepage else ''}{images}{art_panel(app)}{social_strip(app)}</div><aside class="rail">
<div class="card"><h3>Needs</h3><dl><dt>Python</dt><dd>{python}</dd><dt>Port</dt><dd>{e(', '.join(map(str, req['ports'])) or 'None')}</dd>{movable}<dt>Models</dt><dd>{e(', '.join(req['device']['models']) or 'None')}</dd><dt>NPU</dt><dd>{e(req['device']['npuUnits'])} units</dd><dt>Uses</dt><dd><div class="chips">{permissions}</div></dd></dl></div>
<div class="card"><h3>Release</h3>{release_details}</div>
<div class="card"><h3>Maker</h3><div class="maker">{avatar}<div><b>{link(maker_url, app['author']['name'])}</b><br>{owner}</div></div></div>
<div class="rail-actions"><button id="seed-thumb" class="btn ghost give-seed" type="button" aria-pressed="false" disabled><span id="seed-give">Give a seed</span>{seed_stack(counts.get(app['id'], 0), app['id'])}</button><button type="button" class="btn ghost" data-share data-share-title="{e(app['name'])}" data-share-text="{e(app['pitch'])}">Share</button></div><span data-share-status role="status" aria-live="polite"></span>
</aside></div></section>'''


def seeds():
    return (ROOT / 'scripts/submit-page.html').read_text(encoding='utf-8')


def my_farm():
    return '''<section class="prof"><aside class="card-me" aria-labelledby="maker-name"><img id="maker-avatar" class="maker-avatar" width="96" height="96" src="/brand/tiinyapp-farm-square-logo.png" alt=""><div><h1 id="maker-name">Your profile</h1><p id="maker-handle" class="h"></p></div>
<p id="maker-proof"><span class="chip ok">Verified Tiiny owner</span></p><p id="maker-bio" class="maker-bio"></p><div id="maker-links" class="chips"></div><p><a id="public-maker" hidden>Visit your public maker page</a></p>
<button id="edit-profile" class="btn ghost" type="button" aria-expanded="false" aria-controls="maker-form">Edit profile</button><form id="maker-form" hidden><fieldset id="maker-fields" disabled><legend>Edit your profile</legend>
<label for="bio">Bio</label><textarea id="bio" name="bio" maxlength="600" rows="4" aria-describedby="bio-help"></textarea><p id="bio-help" class="fine">Describe yourself in up to 600 characters.</p>
<label for="avatar">Your icon</label><input id="avatar" type="file" accept="image/png,image/jpeg,image/webp" aria-describedby="avatar-help"><p id="avatar-help" class="fine">PNG, JPEG or WebP, up to 2 MiB.</p><button id="remove-avatar" class="btn ghost" type="button" hidden>Remove icon</button>
<label for="github">GitHub link</label><input id="github" name="github" type="url" pattern="https://.*" placeholder="https://…">
<label for="website">Website link</label><input id="website" name="website" type="url" pattern="https://.*" placeholder="https://…">
<label for="youtube">YouTube link</label><input id="youtube" name="youtube" type="url" pattern="https://.*" placeholder="https://…">
<button class="btn hay" type="submit">Save profile</button></fieldset></form>
<div class="vis"><div class="sw"><span>Public profile</span><button id="profile-visibility" class="toggle" type="button" role="switch" aria-checked="true" aria-label="Public profile"></button></div><p id="visibility-text">Anyone can open your maker page and see your apps, bio and links. Your email is never shown.</p></div>
<div class="vis signed-in"><div class="sw"><span>Signed in with</span><span id="signed-in-with" class="lock"></span></div><p>Both lead here when linked. <button id="account-logout" class="help-link" type="button">Sign out</button></p></div></aside>
<div class="apps"><h2 id="my-seeds-heading">Your apps</h2><div class="account-tools"><a class="btn hay" href="/submit/">Submit an app</a><button id="refresh-seeds" class="btn ghost" type="button">Refresh checks</button></div><p id="farm-status" role="status" aria-live="polite">Loading your apps…</p><div id="my-seeds" class="mine"></div>
<p class="small">Published apps can be updated any time. Updates go through the same checks and review.</p>
<section class="token-card" aria-labelledby="api-tokens-heading"><div class="token-head"><div><h2 id="api-tokens-heading">API tokens</h2><p>Create a token when an AI assistant or <code>farm publish</code> will publish for you.</p></div><button id="create-token" class="btn ghost" type="button">Create a token</button></div>
<form id="token-form" class="token-form" hidden><label for="token-name">Token name <small>Use a name that says where you will use it.</small></label><div class="row2"><input id="token-name" name="name" type="text" maxlength="80" autocomplete="off" placeholder="Laptop or assistant" required><button class="btn hay" type="submit">Create</button></div></form>
<div id="token-reveal" class="token-reveal" hidden><p><b>Copy this token now.</b> It is shown only once.</p><div class="cmd"><code id="new-token"></code><button id="copy-token" type="button" aria-label="Copy API token">{icon("copy")}</button></div></div>
<p id="token-status" class="small" role="status" aria-live="polite">Loading tokens…</p><div id="api-tokens" class="token-list"></div></section></div>
<noscript><p>JavaScript is needed to load your profile settings and submission status.</p></noscript></section><script type="module" src="/assets/farm.js"></script>'''.replace('{icon("copy")}', icon("copy"))


# The documentation pages are written as markdown in docs/site/ so that editing them
# never means editing HTML. This is the small subset of markdown those files use.
LIST_ITEM = re.compile(r'^(\s*)([-*]|[0-9]+\.)\s+(.*)$')
TABLE_RULE = re.compile(r'\|[\s:|-]+\|')


def doc_slug(value):
    return re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', value.lower())).strip('-')


def doc_inline(text):
    """Set code spans aside, escape and mark up the rest, then put them back."""
    spans = []

    def stash(match):
        spans.append('<code>' + e(match.group(1)) + '</code>')
        return f'\x00{len(spans) - 1}\x00'

    piece = e(re.sub(r'`([^`]+)`', stash, text))
    piece = re.sub(r'\[([^\]]+)\]\(([^)\s]+)\)', r'<a href="\2">\1</a>', piece)
    piece = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', piece)
    return re.sub(r'\x00([0-9]+)\x00', lambda match: spans[int(match.group(1))], piece)


def doc_list(lines, index, indent):
    tag = 'ul' if LIST_ITEM.match(lines[index]).group(2) in ('-', '*') else 'ol'
    items = []
    while index < len(lines):
        line = lines[index]
        found = LIST_ITEM.match(line)
        if not found:
            # A wrapped line belongs to the item above it, so docs can wrap at a sane width.
            if not items or not line.strip() or line.lstrip().startswith(('#', '```', '|', '> ')):
                break
            items[-1] += ' ' + doc_inline(line.strip())
            index += 1
            continue
        if len(found.group(1)) < indent:
            break
        if len(found.group(1)) > indent:
            nested, index = doc_list(lines, index, len(found.group(1)))
            items[-1] += nested
            continue
        items.append(doc_inline(found.group(3)))
        index += 1
    return '<{0}>{1}</{0}>'.format(tag, ''.join(f'<li>{item}</li>' for item in items)), index


def doc_table(lines, index):
    rows = []
    while index < len(lines) and lines[index].strip().startswith('|'):
        rows.append([cell.strip() for cell in lines[index].strip().strip('|').split('|')])
        index += 1
    head = ''.join(f'<th scope="col">{doc_inline(cell)}</th>' for cell in rows[0])
    body = ''.join('<tr>' + ''.join(f'<td>{doc_inline(cell)}</td>' for cell in row) + '</tr>' for row in rows[2:])
    return f'<div class="docs-table"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>', index


def markdown(text):
    """Headings, paragraphs, lists, tables, fenced code, notes and inline marks."""
    lines = text.split('\n')
    html = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if line.startswith('```'):
            index += 1
            block = []
            while index < len(lines) and not lines[index].startswith('```'):
                block.append(lines[index])
                index += 1
            html.append('<pre><code>' + e('\n'.join(block)) + '</code></pre>')
            index += 1
            continue
        heading = re.match(r'(#{1,6})\s+(.*)$', line)
        if heading:
            # The page title is the only h1, so a section heading starts at h2.
            level = max(2, len(heading.group(1)))
            html.append(f'<h{level} id="{doc_slug(heading.group(2))}">{doc_inline(heading.group(2))}</h{level}>')
            index += 1
            continue
        if line.startswith('|') and index + 1 < len(lines) and TABLE_RULE.fullmatch(lines[index + 1].strip()):
            block, index = doc_table(lines, index)
            html.append(block)
            continue
        if LIST_ITEM.match(line):
            block, index = doc_list(lines, index, len(LIST_ITEM.match(line).group(1)))
            html.append(block)
            continue
        if line.startswith('> '):
            note = []
            while index < len(lines) and lines[index].startswith('> '):
                note.append(lines[index][2:])
                index += 1
            html.append('<p class="note">' + doc_inline(' '.join(note)) + '</p>')
            continue
        paragraph = []
        while index < len(lines) and lines[index].strip() and not lines[index].startswith(('#', '```', '|', '> ')) \
                and not LIST_ITEM.match(lines[index]):
            paragraph.append(lines[index].strip())
            index += 1
        html.append('<p>' + doc_inline(' '.join(paragraph)) + '</p>')
    return ''.join(html)


def read_doc(path):
    """A documentation source: key: value lines between --- markers, then markdown."""
    text = path.read_text(encoding='utf-8')
    meta = {}
    if text.startswith('---\n'):
        head, _, text = text[4:].partition('\n---\n')
        for line in head.split('\n'):
            key, _, value = line.partition(':')
            if key.strip():
                meta[key.strip()] = value.strip()
    for field in ('title', 'summary', 'order'):
        if not meta.get(field):
            raise ValueError(f'{path.name} needs a {field} in its front matter')
    meta['slug'] = meta.get('slug', '')
    if meta['slug'] and not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', meta['slug']):
        raise ValueError(f'{path.name} has an invalid slug')
    meta['url'] = '/docs/' + (meta['slug'] + '/' if meta['slug'] else '')
    meta['body'] = text
    return meta


def doc_entries(source):
    entries = [read_doc(path) for path in sorted((source / 'docs/site').glob('*.md'))]
    entries.sort(key=lambda entry: int(entry['order']))
    if not entries or entries[0]['slug']:
        raise ValueError('docs/site needs an index page whose slug is empty')
    return entries


def doc_page(entry, entries, launcher=None):
    """One documentation page: the section list, the page, and its own contents."""
    launcher = launcher or LAUNCHER_OFF
    links = ''.join(
        f'<li><a href="{item["url"]}"' + (' aria-current="page"' if item is entry else '') + f'>{e(item["title"])}</a></li>'
        for item in entries)
    # The version history is a page of the site rather than a documentation file, and somebody
    # reading about the launcher is exactly the person looking for it.
    if launcher['enabled']:
        links += '<li><a href="/launcher/versions/">Launcher versions</a></li>'
    body = markdown(entry['body'])
    if not launcher['enabled']:
        # With the downloads switched off the history page is not built at all, so the prose
        # keeps its words and loses the link rather than pointing at a page that is not there.
        body = re.sub(r'<a href="/launcher/versions/"[^>]*>(.*?)</a>', r'\1', body)
    sections = re.findall(r'<h2 id="([^"]+)">(.*?)</h2>', body)
    contents = ''
    if entry['slug'] and len(sections) > 2:
        contents = ('<nav class="docs-toc" aria-label="On this page"><b>On this page</b><ul>'
                    + ''.join(f'<li><a href="#{anchor}">{title}</a></li>' for anchor, title in sections)
                    + '</ul></nav>')
    if not entry['slug']:
        body += ('<div class="docs-index">' + ''.join(
            f'<a class="docs-card" href="{item["url"]}"><b>{e(item["title"])}</b><span>{e(item["summary"])}</span></a>'
            for item in entries if item['slug']) + '</div>')
    return f'''<div class="docs"><nav class="docs-nav" aria-label="Documentation"><b>Documentation</b><ul>{links}</ul></nav>
<section class="page docs-body"><h1>{e(entry['title'])}</h1><p class="lede">{e(entry['summary'])}</p>{contents}{body}
<p class="docs-foot"><a href="/docs/">All documentation</a> <a href="/install/">Install an app</a> <a href="/submit/">Submit an app</a></p></section></div>'''


def build(source=ROOT, output=None, today=None, releases_url=None, allow_stale=False,
          counts_url=None):
    """Build the site. releases_url fetches the launcher history live; None reads the copy here.

    counts_url reads every app's seed count from the live farm; None builds every pile at zero,
    which is what every test and every offline build does."""
    source = Path(source)
    output = Path(output) if output else source / "site" / "dist"
    today = today or datetime.now(timezone.utc).date()
    render_card = runpy.run_path(str(ROOT / 'scripts/share-cards.py'))['render_card']
    # The one description of the HTTP surface, served at /docs/openapi.json.
    openapi = runpy.run_path(str(ROOT / 'worker/openapi.py'))['spec']
    launcher = read_launcher(source)
    counts = read_counts(counts_url)
    snapshot = source / 'site/makers.json'
    makers = json.loads(snapshot.read_text()) if snapshot.exists() else []
    for maker in makers:
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', maker['handle']):
            raise ValueError('Invalid maker handle in site/makers.json')
    validator = runpy.run_path(str(ROOT / "scripts" / "check-manifest.py"))["check_manifest"]
    manifests = []
    for path in sorted((source / "manifests").glob("*.json")):
        app = json.loads(path.read_bytes())
        validator(app, allow_pending=True)
        if path.stem != app["id"]:
            raise ValueError(f"Manifest filename must match id: {path.name}")
        manifests.append((path, app))
    if not manifests:
        raise ValueError("No manifests found")
    # Build into a sibling staging directory so stale pages disappear on rebuild.
    import tempfile
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix=".farm-build-") as temporary:
        dest = Path(temporary)

        def write(path, content):
            target = dest / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        apps = [app for _, app in manifests]
        # /llms.txt is the plain-text index an assistant fetches first. The guide it points at is
        # a documentation page like any other, at /docs/agents/.
        guide = (source / 'docs/agents.txt').read_text(encoding='utf-8')
        pages = {"/": ("App catalog", home_page(apps, launcher, counts)), "/catalog/": ("Catalog", catalog_page(apps)),
                 "/install/": ("Install an app", steps(launcher)), "/submit/": ("Submit an app", seeds()),
                 "/submit/done/": ("App submitted", seeds()), "/account/": ("Your apps", my_farm())}
        if launcher['enabled']:
            # The history is a page of the site rather than a file in the bucket, and the Worker
            # knows to hand this one path back to the static site.
            pages['/launcher/versions/'] = ('Launcher versions',
                                            versions_page(read_releases(
                                                source, releases_url, allow_stale=allow_stale)))
        entries = doc_entries(source)
        for entry in entries:
            pages[entry['url']] = (entry['title'], doc_page(entry, entries, launcher))
        listing = '<section class="sect"><h1>App manifests</h1><p>The installer catalog at https://tiinyapp.farm/manifests/.</p><ul>'
        for path, app in manifests:
            pages[f"/apps/{app['id']}/"] = (app["name"], app_page(app, today, makers, launcher, counts))
            owner = next((maker for maker in makers if maker.get('tiinyverse') and maker['tiinyverse'] == app['author'].get('tiinyverse')), {})
            render_card(source, dest / 'apps' / app['id'] / 'card.png', name=app['name'],
                        pitch=app['pitch'], maker=app['author']['name'], media=app.get('media'),
                        avatar=owner.get('avatar'), verified=bool(app['author'].get('tiinyverse')),
                        sprouting='release' not in app)
            write(f"manifests/{app['id']}.json", "")
            shutil.copyfile(path, dest / "manifests" / path.name)
            listing += '<li>' + link(path.name, app['name']) + '</li>'
        for maker in makers:
            count = sum(bool(maker.get('tiinyverse')) and app['author'].get('tiinyverse') == maker['tiinyverse'] for _, app in manifests)
            render_card(source, dest / 'makers' / maker['handle'] / 'card.png',
                        name='Apps by ' + maker['name'], pitch=f"{count} app{'s' if count != 1 else ''} in the catalog. " + maker.get('bio', ''),
                        maker=maker['name'], media={'header': maker.get('avatar')},
                        avatar=maker.get('avatar'), verified=bool(maker.get('tiinyverse')))
        pages['/manifests/'] = ('App manifests', listing + '</ul></section>')
        for url, (title, body) in pages.items():
            scripts = ('/assets/catalog.js',) if url in ('/', '/catalog/') else (
                ('/assets/catalog.js', '/assets/share.js', '/assets/seed-media.js', '/assets/social.js', '/assets/art.js', '/assets/release.js')
                if url.startswith('/apps/') else ())
            # The platform swap and nothing else, so it ships only where there is a button to swap.
            if launcher['enabled'] and (url == '/install/' or url.startswith('/apps/')):
                scripts = scripts + ('/assets/launcher.js',)
            write(url.lstrip('/') + 'index.html', page(title, body, url, scripts))
        write('404.html', page('Page not found', '<section class="sect"><h1>Page not found</h1><p>This page does not exist. ' + link('/', 'Return to the catalog') + '.</p></section>', '/404.html'))
        write('sitemap.xml', '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(f'<url><loc>{ORIGIN}{url}</loc></url>' for url in sorted(pages) if url not in ("/account/", "/submit/done/")) + '</urlset>\n')
        write('catalog.json', json.dumps({'cli': cli_version(), 'apps': [app for _, app in manifests]},
                                         ensure_ascii=False) + '\n')
        write('categories.json', json.dumps({'map': CATEGORIES, 'order': CATEGORY_ORDER}, ensure_ascii=False) + '\n')
        write('llms.txt', guide)
        write('docs/openapi.json', json.dumps(openapi(), indent=2, ensure_ascii=False) + '\n')
        write('site.webmanifest', json.dumps({'name': 'tiinyapp.farm', 'short_name': 'tiinyapp.farm',
              'start_url': '/', 'display': 'standalone', 'theme_color': '#090D14', 'background_color': '#090D14',
              'icons': [{'src': '/brand/favicon-192.png', 'sizes': '192x192', 'type': 'image/png'},
                        {'src': '/brand/icon-512.png', 'sizes': '512x512', 'type': 'image/png'}]}) + '\n')
        shutil.copytree(source / 'brand', dest / 'brand')
        shutil.copytree(source / 'site/fonts', dest / 'fonts')
        write('robots.txt', f'User-agent: *\nAllow: /\nSitemap: {ORIGIN}/sitemap.xml\n')
        assets = ['hero.jpg', 'site.css', 'catalog.js', 'seeds.js', 'session.js', 'farm.js', 'seed-media.js', 'seed-stack.js', 'social.js', 'share.js', 'art.js', 'release.js', 'titanium-icon.png', 'titanium-header.webp']
        if launcher['enabled']:
            assets.append('launcher.js')
        for folder, files in {'assets': assets, 'docs': ['manifest.schema.json', 'SUBMIT.md']}.items():
            for name in files:
                origin = source / ('site/assets' if folder == 'assets' else folder) / name
                (dest / folder).mkdir(exist_ok=True)
                shutil.copyfile(origin, dest / folder / name)
        shutil.copytree(source / 'site/assets/art', dest / 'assets/art')
        if output.exists():
            shutil.rmtree(output)
        shutil.copytree(dest, output)
    return len(manifests)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Destination (default: site/dist)')
    parser.add_argument('--today', type=date.fromisoformat, help='UTC date override for reproducible badges')
    parser.add_argument('--no-fetch', action='store_true',
                        help='Read the launcher history from site/launcher-releases.json only '
                             'and build every seed pile at zero')
    parser.add_argument('--allow-stale-history', action='store_true',
                        help='Build from the checked-in launcher history when the live one '
                             'cannot be read, instead of stopping')
    args = parser.parse_args()
    if args.no_fetch:
        print('launcher history: reading site/launcher-releases.json, no live fetch asked')
    count = build(output=args.output, today=args.today,
                  releases_url=None if args.no_fetch else RELEASES_URL,
                  allow_stale=args.allow_stale_history,
                  counts_url=None if args.no_fetch else COUNTS_URL)
    print(f'Built {count} app pages in {args.output or ROOT / "site/dist"}')


if __name__ == '__main__':
    main()
