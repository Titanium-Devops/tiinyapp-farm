#!/usr/bin/env python3
"""Build the readable farm catalog with Pillow share cards."""

import argparse
from datetime import date, datetime, timezone
from html import escape, unescape
import json
import re
from urllib.parse import parse_qs, urlsplit
from pathlib import Path
import runpy
import shlex
import shutil

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://tiinyapp.farm"
REPO = "https://github.com/Titanium-Devops/tiinyapp-farm"
PERMISSIONS = {
    "microphone": "Microphone: can listen through your microphone.",
    "files": "Files: can read or write files on your computer.",
    "network": "Network: can make network connections.",
    "device": "Device: can send requests to your Tiiny.",
}
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
    "requires": "Minimum python version if known, local ports, and device requirements: models and npuUnits.",
    "permissions": "Declared access: microphone, files, network and device. An empty list no permissions declared.",
    "tags": "Short labels that help people find the app.",
    "verified": "Keep false when submitting. A maintainer sets true in a follow-up commit after CI and manual review.",
    "addedAt": "The day the app joined the catalog, YYYY-MM-DD. New lasts less than 30 days.",
    "updatedAt": "The most recent manifest update, YYYY-MM-DD.",
    "selfcheck": "Optional boolean. When true, CI appends --selfcheck to the entry and requires exit 0 offline within 120 seconds.",
    "health": "Optional HTTP health path on the first declared port, returning a JSON object with version and optional ok.",
}


def e(value):
    return escape(str(value), quote=True)


def link(url, label):
    return f'<a href="{e(url)}">{e(label)}</a>'


def command(value):
    return f'<pre><code>{e(value)}</code></pre>'


def badges(app, today):
    result = []
    if "release" not in app:
        result.append('<span class="badge sprouting">No release yet</span>')
    if app["verified"]:
        result.append('<span class="badge verified">Verified</span>')
    if 0 <= (today - date.fromisoformat(app["addedAt"])).days < 30:
        result.append('<span class="badge new">New</span>')
    if app["entry"] is None:
        result.append('<span class="badge library">Library</span>')
    return '<div class="badges">' + "".join(result) + '</div>'


def page(title, body, path):
    lede = re.search(r'<p class="lede">(.*?)</p>', body, re.S) or re.search(r'<p>(.*?)</p>', body, re.S)
    description = unescape(re.sub(r'<[^>]+>', '', lede.group(1))) if lede else title
    card = path + 'card.png' if path.startswith('/apps/') else '/brand/og-image.png'
    dimensions = '<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">' if path.startswith('/apps/') else ''
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
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,800&amp;family=Nunito:wght@400;600;700&amp;display=swap">
<link rel="stylesheet" href="/assets/site.css"></head>
<body><a class="skip" href="#main">Skip to content</a><div class="wrap">
<header><a class="brand" href="/"><img class="brand-mark" src="/brand/icon-512.png" width="36" height="36" alt=""><span>tiinyapp.farm<small>apps for your Tiiny</small></span></a>
<nav aria-label="Main navigation"><a href="/#field">Catalog</a><a href="/plant/">Install an app</a><a class="cta" data-farm-nav href="/farm/">Your apps</a></nav></header>
<main id="main">{body}</main>
<footer><div class="marks"><a class="pill" href="https://titanium.bot"><img src="/brand/titanium-bot-logo.svg" width="120" height="30" alt="Titanium Bot"><span>Brought to you by Titanium Bot</span></a>
<a class="pill" href="https://tiiny.ai">Built for <img src="/brand/tiiny-logo.svg" width="80" height="28" alt="Tiiny"></a></div><span>Made by Titanium Computing</span></footer>
</div><script type="module" src="/assets/session.js"></script></body></html>'''


def steps():
    return f'''<section class="sect"><h1>Install and run an app</h1>
<p class="lede">The farm CLI (<code>farm</code>) installs apps on your computer and connects them to your Tiiny.</p>
<div class="steps"><section class="step"><h2>1. Install the CLI</h2><p>Python 3.9 or newer. macOS, Linux and Windows.</p>
{command('pip install tiinyapp-farm')}</section>
<section class="step"><h2>2. Connect your Tiiny</h2>{command('farm device')}
<p>It asks for two things: the API base URL (on the Mac with the TiinyOS client that is <code>http://openai.api.tiiny/v1</code>; from any other computer it is <code>http://&lt;your-tiiny-ip&gt;/v1</code>) and the API key, which you copy from TiinyOS &gt; Settings &gt; API Key.</p>
<p>Replace <code>&lt;your-tiiny-ip&gt;</code> with your Tiiny's IP address shown in your router's connected-device list. Both settings are saved in <code>~/.tiinyapps/device.json</code>, readable only by you on macOS and Linux; on Windows, access follows your user-folder permissions. Run <code>farm device</code> again to change them.</p></section>
<section class="step"><h2>3. Install and run an app</h2><p>Copy the app ID from its catalog page and replace <code>&lt;app-id&gt;</code> in these commands.</p>{command('farm install <app-id>' + chr(10) + 'farm start <app-id>')}
<p>The install command shows the app's requirements and permissions and asks you to confirm. It saves the app under <code>~/tiinyapps/&lt;app-id&gt;</code>; the start command writes output to <code>farm.log</code> there.</p><p>Libraries have nothing to start. Apps without a release or a published checksum cannot be installed.</p></section></div>
<p><code>farm list</code> lists catalog apps; <code>farm status</code> lists running apps. Use <code>farm stop &lt;app-id&gt;</code> to stop an app, <code>farm update &lt;app-id&gt;</code> to update it, and <code>farm remove &lt;app-id&gt;</code> to remove it while keeping its data. Start the app again after updating.</p>
<p>Apps declare their access; the installer does not sandbox them.</p></section>'''


def seed_icon(app):
    url = app.get("media", {}).get("icon")
    return f'<img class="seed-icon" src="{e(url)}" width="72" height="72" alt="" loading="lazy">' if url else ''


def seed_media(app):
    media = app.get("media", {})
    header = f'<img class="seed-header" src="{e(media["header"])}" alt="{e(app["name"])} header">' if media.get("header") else ''
    gallery = ''.join(f'<a class="gallery-thumb" href="{e(url)}" data-gallery-image><img src="{e(url)}" alt="{e(app["name"])} gallery image {i}" loading="lazy"></a>' for i, url in enumerate(media.get("gallery", []), 1))
    if gallery:
        gallery = '<section><h2>Gallery</h2><div class="seed-gallery">' + gallery + '</div><dialog id="gallery-dialog" aria-label="Full-size app image"><form method="dialog"><button class="btn hay">Close image</button></form><img id="gallery-image" alt=""></dialog></section>'
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


def plot(app, today):
    models = ", ".join(app["requires"]["device"]["models"]) or "no named models"
    permissions = "".join(f'<span>{e(p)}</span>' for p in app["permissions"]) or '<span>no permissions declared</span>'
    planting = (f'<code>farm install {e(app["id"])}</code><a class="btn hay" href="/apps/{e(app["id"])}/" aria-label="Install {e(app["name"])}">Install</a>'
                if 'release' in app else f'<a class="btn hay" href="/apps/{e(app["id"])}/">View app</a>')
    return f'''<article class="plot"><div class="plot-top">{badges(app, today)}<span class="ver">v{e(app['version'])}</span></div>
<div class="seed-title">{seed_icon(app)}<h3>{e(app['name'])}</h3></div><p class="pitch">{e(app['pitch'])}</p><p class="by">by {e(app['author']['name'])} · needs {e(models)}</p>
<div class="perms">{permissions}</div><div class="plant">{planting}</div></article>'''


def social_strip(app):
    return f'''<section class="seed-social" data-seed-social="{e(app['id'])}" aria-labelledby="social-heading"><h2 id="social-heading">Comments</h2>
<p id="social-status" role="status" aria-live="polite">Loading comments and thumbs up…</p>
<button id="seed-thumb" class="btn hay" type="button" aria-pressed="false" disabled>Thumbs up <span id="thumb-count">0</span></button>
<p id="social-signin"><a href="/seeds/">Sign in to give this app a thumbs up or leave a comment.</a></p>
<div id="seed-comments" aria-label="App comments"></div>
<form id="comment-form" hidden><label for="comment-text">Comment</label><textarea id="comment-text" name="text" rows="4" maxlength="1000" required aria-describedby="comment-help"></textarea><p id="comment-help" class="fine">Up to 1,000 characters. Five comments per hour.</p><button id="comment-submit" class="btn hay" type="submit">Post comment</button></form>
<noscript><p>JavaScript is needed to load thumbs and comments.</p></noscript></section>'''


def grown_by(app, makers=()):
    """Author line: the maker page when the seed's TiinyVerse owner is a known maker, else the author URL."""
    profile = app['author'].get('tiinyverse')
    maker = next((m for m in makers if profile and m.get('tiinyverse') == profile), None)
    if maker:
        return (f"Maker: <a href=\"/makers/{e(maker['handle'])}/\">{e(maker['name'])}</a> <span class=\"badge\">Verified Tiiny</span>"
                f" · {link(app['author']['url'], app['author']['name'])}")
    return f"Author: {link(app['author']['url'], app['author']['name'])}"

def app_page(app, today, makers=()):
    header, visual_media = seed_media(app)
    links = app.get("links", {})
    homepage = links.get("homepage") or app.get("homepage")
    repo = links.get("repo") or app.get("repo")
    req = app["requires"]
    device = req["device"]
    entry = app["entry"]
    release = app.get("release")
    if entry is None:
        start = '<p>This is a library. There is no app to start. Use it from your own application.</p>'
    else:
        invocation = (shlex.join(["python", "-m", entry["python"], *entry["args"]])
                      if "python" in entry else entry["command"])
        start = command(f"farm start {app['id']}") + '<p>The farm CLI (<code>farm</code>) runs:</p>' + command(invocation)
    screenshots = "".join(f'<figure><img src="{e(url)}" alt="{e(app["name"])} screenshot {i}" loading="lazy"></figure>'
                          for i, url in enumerate(app["screenshots"], 1))
    images = visual_media + (f'<section><h3>Screenshots</h3>{screenshots}</section>' if screenshots else '')
    permissions = ' '.join(PERMISSIONS[p] for p in app['permissions']) or 'None declared.'
    rows = {
        "App ID": app["id"], "License": app["license"],
        "Tags": ", ".join(app["tags"]) or "None", "Catalog date": app["addedAt"],
        "Update date": app["updatedAt"],
        "Maintainer review": "Verified: a maintainer ran the app and reviewed its source." if app["verified"] else "Not verified by a maintainer.",
    }
    details = "".join(f'<dt>{e(k)}</dt><dd>{e(v)}</dd>' for k, v in rows.items())
    install = (f'<p>{link("/plant/", "Set up the farm CLI (farm)")} before running these commands. The app is saved under <code>~/tiinyapps/{e(app["id"])}</code>.</p>{command("farm install " + app["id"])}{start}'
               if release else '<p>No release yet. This app cannot be installed.</p>')
    release_details = f'''<p>{link(release['url'], 'Release archive')}</p><dl><dt>Version</dt><dd>{e(app['version'])}</dd><dt>Size</dt><dd>{str(release['size']) + ' bytes' if release['size'] else '0 bytes recorded (size unknown)'}</dd><dt>Checksum</dt><dd>SHA-256: <code>{e(release['sha256'])}</code></dd></dl>
{'<p>The checksum is pending. This release cannot be installed yet.</p>' if release['sha256'] == 'pending' else ''}''' if release else '<p>No release yet.</p>'
    health = ('<li>Health endpoint: <code>' + e(app['health']) + '</code> on the first declared port.</li>' if 'health' in app else '')
    return f'''<section class="sect"><p>{link('/#field', 'Catalog')}</p>{header}{badges(app, today)}<div class="seed-title">{seed_icon(app)}<h1>{e(app['name'])}</h1></div><p class="lede">{e(app['pitch'])}</p>
<p>Status: In the catalog</p>
<a hidden data-seed-update="{e(app['id'])}" href="/seeds/?update={e(app['id'])}">Update this app</a>
<button type="button" class="btn ghost" data-share data-share-title="{e(app['name'])}" data-share-text="{e(app['pitch'])}">Share</button><span data-share-status role="status" aria-live="polite"></span>
<section><h2>Description</h2><p>{e(app['description'])}</p>{images}</section>
<section><h2>Install</h2>{install}</section>
<section><h2>Requirements</h2><ul><li>Python: {e(req.get('python', 'minimum not specified'))}; the farm CLI (<code>farm</code>) needs Python 3.9 or newer.</li>
<li>Ports: {e(', '.join(map(str, req['ports'])) or 'none')}.</li><li>Models: {e(', '.join(device['models']) or 'none specified')}.</li><li>NPU units: {device['npuUnits']}.</li>
<li>Permissions: {e(permissions)}</li>{health}</ul><p>Permissions describe app access; the installer does not enforce them.</p></section>
<section><h2>Release</h2>{release_details}</section>
<section><h2>Maker</h2><p>{grown_by(app, makers)}</p><dl>{details}</dl>
<p>{link(homepage, 'Homepage') if homepage else ''} {link(repo, 'Source repository') if repo else 'Source supplied in the release archive.' if release else ''} {link('/manifests/' + app['id'] + '.json', 'Manifest')}</p></section>
{social_strip(app)}</section><script type="module" src="/assets/share.js"></script><script type="module" src="/assets/seed-media.js"></script><script type="module" src="/assets/social.js"></script>'''


def seeds():
    return r'''<section class="sect seed-intro"><h1>Submit an app</h1>
<p class="lede">Sign in, verify your TiinyVerse profile, then submit your app for the catalog.</p>
<p>No GitHub account is required. Your verified TiinyVerse display name appears beside your app.</p>
<noscript><p>These forms need JavaScript to send codes and check your profile. You can still read the whole guide below.</p></noscript>
<p id="farm-status" role="status" aria-live="polite"></p>
<div class="seed-tabs" role="tablist" aria-labelledby="account-tab proof-tab seed-tab">
<button id="account-tab" type="button" role="tab" aria-selected="true" aria-controls="account-panel" tabindex="0">1 Sign in</button>
<button id="proof-tab" class="locked" type="button" role="tab" aria-selected="false" aria-controls="proof-panel" tabindex="-1">2 Verify you own a Tiiny</button>
<button id="seed-tab" class="locked" type="button" role="tab" aria-selected="false" aria-controls="seed-panel" tabindex="-1">3 Submit your app</button>
</div><div class="seed-cards">
<section class="seed-card" id="account-panel" role="tabpanel" aria-labelledby="account-tab" tabindex="0"><span class="step-number" aria-hidden="true">01</span><h2 id="account-heading">Sign in</h2>
<p>Enter your email address to receive a six-digit code, then enter that code below. You can also sign in with GitHub.</p>
<p><a id="account-farm" href="/farm/" hidden>Your apps</a></p>
<p id="account-state" class="card-state" role="status">Start here. No password to remember.</p>
<form id="email-start"><label for="email">Email address</label><input id="email" name="email" type="email" autocomplete="email" maxlength="254" required><button class="btn hay" type="submit">Send my code</button></form>
<form id="email-verify"><label for="code">Six-digit email code</label><input id="code" name="code" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" required><button class="btn ghost" type="submit">Sign in with code</button></form>
<p class="fine">Codes last 10 minutes. Up to three per hour.</p>
<a class="btn ghost" id="github-signin" href="/api/auth/github">Sign in with GitHub</a>
<p class="fine">Already signed in? Add the other sign-in here to link it to this account.</p>
<button id="logout" class="btn ghost" type="button" hidden>Sign out</button></section>
<section class="seed-card" id="proof-panel" role="tabpanel" aria-labelledby="proof-tab" tabindex="0" hidden><span class="step-number" aria-hidden="true">02</span><h2 id="proof-heading">Verify you own a Tiiny</h2>
<p>Paste the URL of your TiinyVerse profile. We give you a short code. Put that code anywhere in your TiinyVerse bio, save, then press Verify. We read your public profile once to confirm you own it (the same idea as a DNS TXT record). You can remove the code afterwards.</p>
<p id="proof-state" class="card-state" role="status">First, sign in.</p>
<form id="tiiny-link"><fieldset id="proof-fields" disabled><legend>Your TiinyVerse profile</legend><label for="profileUrl">TiinyVerse profile URL</label><input id="profileUrl" name="profileUrl" type="url" placeholder="https://www.tiinyverse.com/users/…" required><button class="btn hay" type="submit">Get my bio code</button></fieldset></form>
<div id="bio-challenge" hidden><p>Open your TiinyVerse profile, edit it, and paste this code anywhere in the bio (the description box). Save, then press Verify. Once it verifies you can take the code back out.</p><output id="bio-code"></output><p class="fine" id="bio-expiry">Your code lasts 24 hours.</p><button id="tiiny-verify" class="btn hay" type="button">Verify</button></div>
<p class="fine">One TiinyVerse profile belongs to one farm account. Sign in to that same account next time.</p></section>
<section class="seed-card" id="seed-panel" role="tabpanel" aria-labelledby="seed-tab" tabindex="0" hidden><span class="step-number" aria-hidden="true">03</span><h2 id="seed-heading">Submit your app</h2>
<p>This opens a pull request on the catalog; automated checks run, a maintainer reviews it, and it appears in the catalog when merged. Track it on <a href="/farm/">Your apps</a>.</p>
<p id="seed-state" class="card-state" role="status">Sign in and verify your TiinyVerse profile to submit an app.</p>
<form id="seed-form"><fieldset id="seed-fields" disabled><legend>Your app</legend><div class="seed-form-grid">
<div class="seed-field"><label for="seed-name">Name</label><input id="seed-name" name="name" required maxlength="120"></div>
<div class="seed-field"><label for="seed-id">App ID</label><input id="seed-id" name="id" pattern="[a-z][a-z0-9]*(-[a-z0-9]+)*" placeholder="my-little-app" required maxlength="80"></div>
<div class="seed-field"><label for="version">Version</label><input id="version" name="version" pattern="(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)" value="0.1.0" required></div>
<div class="seed-field"><label for="pitch">One-line pitch</label><input id="pitch" name="pitch" required maxlength="240"></div>
<div class="seed-field seed-wide"><label for="description">What does it do?</label><textarea id="description" name="description" rows="4" required maxlength="12000"></textarea></div>
<div class="seed-field"><label for="license">License</label><input id="license" name="license" placeholder="MIT" required maxlength="100"></div>
<div class="seed-field"><label for="homepage">Home page (optional)</label><input id="homepage" name="homepage" type="url" placeholder="https://…"></div>
<div class="seed-wide"><h3>Images</h3><p class="fine" id="seed-media-help">PNG, JPEG or WebP, up to 2 MiB each. Gallery: up to eight images.</p></div>
<div class="seed-field"><label for="seed-icon">Main image (optional)</label><input id="seed-icon" type="file" accept="image/png,image/jpeg,image/webp" aria-describedby="seed-media-help"></div>
<div class="seed-field"><label for="seed-header">Header image (optional)</label><input id="seed-header" type="file" accept="image/png,image/jpeg,image/webp" aria-describedby="seed-media-help"></div>
<div class="seed-field seed-wide"><label for="seed-gallery">Gallery (optional)</label><input id="seed-gallery" type="file" accept="image/png,image/jpeg,image/webp" multiple aria-describedby="seed-media-help"></div>
<div class="seed-field"><label for="repo">Source repository URL (optional)</label><input id="repo" name="repo" type="url" pattern="https://.*" placeholder="https://…"></div>
<div class="seed-field"><label for="video">YouTube video (optional)</label><input id="video" name="video" type="url" pattern="https://.*" placeholder="https://www.youtube.com/watch?v=…"></div>
<h3 id="release-heading" class="seed-wide">Release (optional)</h3><p id="release-help" class="fine seed-wide">Leave the release empty to submit an app with no release yet.</p>
<div class="seed-field"><label for="releaseUrl">Direct release URL</label><input id="releaseUrl" name="releaseUrl" type="url" placeholder="https://…/release.tar.gz"></div>
<p class="fine seed-wide">Optionally provide a direct HTTPS tar.gz link or an upload below. The archive must include the source for review.</p>
<div class="seed-field seed-wide"><label for="archive">Or upload a tar.gz (up to 50 MB)</label><input id="archive" name="archive" type="file" accept=".tar.gz,application/gzip"></div>
<div class="seed-field seed-wide"><label for="permissions">Permissions</label><select id="permissions" name="permissionChoices" multiple size="4" aria-describedby="permission-help"><option value="microphone">Microphone</option><option value="files">Files</option><option value="network">Network</option><option value="device">Tiiny device</option></select></div>
<p class="fine seed-wide" id="permission-help">Choose all access your app uses. Leave empty if it needs no permissions. Use Control or Command to select several.</p>
<div class="seed-field seed-wide"><label for="command">Start command (optional)</label><input id="command" name="command" placeholder="python -m my_app"><p class="fine">The command the farm CLI (farm) runs. Leave it empty for a library or an app with no release yet.</p></div>
<button class="btn hay seed-wide" type="submit">Send</button><p id="seed-error" class="seed-wide card-state error" role="alert" hidden></p></div></fieldset></form>
<a href="/farm/">Your apps</a></section></div>
<section class="seed-notes"><h2>Review</h2><p>Automated checks validate the manifest, archive size and checksum, then scan for unsafe paths, secrets and undeclared access. If the app declares a selfcheck, CI runs it offline.</p>
<p>A maintainer reviews the source and check results before merging. Verified means a maintainer has run the app and reviewed its source.</p>
<p>Follow progress on <a href="/farm/">Your apps</a>. You do not need to visit GitHub to submit or check progress.</p></section>
<section class="seed-faq"><h2>FAQ</h2>
<details open><summary>Do I need GitHub?</summary><p>No. Sign in with your email and submit your app here.</p></details>
<details><summary>Why TiinyVerse?</summary><p>TiinyVerse is the Tiiny owner community. A code in your public bio proves that you control that profile.</p></details>
<details><summary>Can I link email and GitHub?</summary><p>Sign in first, then use the other sign-in method on this page to link it. An identity already linked to another account cannot be moved here.</p></details>
<details><summary>Can I still send a pull request myself?</summary><p>Yes; verify your profile here first, then set author.tiinyverse and the same display name in your manifest. Pull requests pass the same checks as apps submitted here.</p></details>
<details><summary>What belongs in the archive?</summary><p>Include your source, license and instructions in a versioned tar.gz archive, plus an offline selfcheck if available. The <a href="/docs/SUBMIT.md">contributor guide</a> and <a href="/docs/manifest.schema.json">manifest schema</a> explain the details.</p></details></section></section>
<script type="module" src="/assets/seeds.js"></script>'''


def my_seeds():
    return '<meta http-equiv="refresh" content="0;url=/farm/"><section class="sect"><h1>Your apps</h1><p><a href="/farm/">Go to Your apps</a></p></section>'


def my_farm():
    return '''<section class="sect"><h1>Your apps</h1>
<p class="lede">Edit your public profile and check the review status of your apps.</p>
<p><a href="/seeds/">Submit your app or manage your sign-in</a></p><p id="farm-status" role="status" aria-live="polite">Loading your apps…</p>
<section class="seed-card" aria-labelledby="maker-name"><div class="maker-heading"><img id="maker-avatar" class="maker-avatar" width="96" height="96" alt="" hidden><div><h2 id="maker-name">Your profile</h2><p id="maker-handle"></p></div></div>
<p id="maker-bio" class="maker-bio"></p><div id="maker-links" class="row"></div><p><a id="public-maker" hidden>Visit your public maker page</a></p>
<p id="maker-proof"></p><form id="maker-form"><fieldset id="maker-fields" disabled><legend>Edit your profile</legend>
<label for="bio">Bio</label><textarea id="bio" name="bio" maxlength="600" rows="4" aria-describedby="bio-help"></textarea><p id="bio-help" class="fine">Describe yourself in up to 600 characters.</p>
<label for="avatar">Your icon</label><input id="avatar" type="file" accept="image/png,image/jpeg,image/webp" aria-describedby="avatar-help"><p id="avatar-help" class="fine">PNG, JPEG or WebP, up to 2 MiB.</p><button id="remove-avatar" class="btn ghost" type="button" hidden>Remove icon</button>
<label for="github">GitHub link</label><input id="github" name="github" type="url" pattern="https://.*" placeholder="https://…">
<label for="website">Website link</label><input id="website" name="website" type="url" pattern="https://.*" placeholder="https://…">
<label for="youtube">YouTube link</label><input id="youtube" name="youtube" type="url" pattern="https://.*" placeholder="https://…">
<button class="btn hay" type="submit">Save profile</button></fieldset></form></section>
<section aria-labelledby="my-seeds-heading"><h2 id="my-seeds-heading">Your apps</h2><button id="refresh-seeds" class="btn hay" type="button">Refresh checks</button><div id="my-seeds" class="field"></div></section>
<noscript><p>JavaScript is needed to load your profile settings and submission status.</p></noscript></section><script type="module" src="/assets/farm.js"></script>'''


def build(source=ROOT, output=None, today=None):
    source = Path(source)
    output = Path(output) if output else source / "site" / "dist"
    today = today or datetime.now(timezone.utc).date()
    render_card = runpy.run_path(str(ROOT / 'scripts/share-cards.py'))['render_card']
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

        hero = '''<section class="hero"><img src="/assets/hero.jpg" width="1600" height="1066" alt="A fantasy farm at dusk with glowing apps in rows and Titan tending the field."><div class="copy"><h1>Little apps, <em>grown for your Tiiny.</em></h1><p class="lede">Community-made apps that run beside your Pocket Lab on your own computer. Choose an app to see its requirements and install commands.</p><div class="row"><a class="btn hay" href="#field">Browse apps</a><a class="btn ghost" href="/plant/">Install an app</a></div></div></section>'''
        field = '<section class="sect" id="field"><h2>Catalog</h2><p class="lede">Each app lists its requirements, permissions and release details. Verified means a maintainer has run the app and reviewed its source; some apps do not yet have an installable release.</p><div class="field">'
        field += ''.join(plot(app, today) for _, app in manifests) + '</div></section>'
        invitation = '<section class="seeds"><div><h2>Submit an app</h2><p>Submit an app for automated checks and maintainer review.</p></div><a class="btn hay" href="/seeds/">Share your app</a></section>'
        pages = {"/": ("App catalog", hero + field + steps().replace('<h1>', '<h2>').replace('</h1>', '</h2>') + invitation),
                 "/plant/": ("Install an app", steps()), "/seeds/": ("Submit an app", seeds()), "/seeds/mine/": ("Your apps", my_seeds()), "/farm/": ("Your apps", my_farm())}
        listing = '<section class="sect"><h1>App manifests</h1><p>The installer catalog at https://tiinyapp.farm/manifests/.</p><ul>'
        for path, app in manifests:
            pages[f"/apps/{app['id']}/"] = (app["name"], app_page(app, today, makers))
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
            write(url.lstrip('/') + 'index.html', page(title, body, url))
        write('404.html', page('Page not found', '<section class="sect"><h1>Page not found</h1><p>This page does not exist. ' + link('/', 'Return to the catalog') + '.</p></section>', '/404.html'))
        write('sitemap.xml', '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(f'<url><loc>{ORIGIN}{url}</loc></url>' for url in sorted(pages) if url not in ("/farm/", "/seeds/mine/")) + '</urlset>\n')
        write('catalog.json', json.dumps([app for _, app in manifests], ensure_ascii=False) + '\n')
        write('site.webmanifest', json.dumps({'name': 'tiinyapp.farm', 'short_name': 'tiinyapp.farm',
              'start_url': '/', 'display': 'standalone', 'theme_color': '#090D14', 'background_color': '#090D14',
              'icons': [{'src': '/brand/favicon-192.png', 'sizes': '192x192', 'type': 'image/png'},
                        {'src': '/brand/icon-512.png', 'sizes': '512x512', 'type': 'image/png'}]}) + '\n')
        shutil.copytree(source / 'brand', dest / 'brand')
        shutil.copytree(source / 'site/fonts', dest / 'fonts')
        write('robots.txt', f'User-agent: *\nAllow: /\nSitemap: {ORIGIN}/sitemap.xml\n')
        for folder, files in {'assets': ['hero.jpg', 'site.css', 'seeds.js', 'session.js', 'farm.js', 'seed-media.js', 'social.js', 'share.js', 'titanium-icon.png', 'titanium-header.webp'], 'docs': ['manifest.schema.json', 'SUBMIT.md']}.items():
            for name in files:
                origin = source / ('site/assets' if folder == 'assets' else folder) / name
                (dest / folder).mkdir(exist_ok=True)
                shutil.copyfile(origin, dest / folder / name)
        if output.exists():
            shutil.rmtree(output)
        shutil.copytree(dest, output)
    return len(manifests)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Destination (default: site/dist)')
    parser.add_argument('--today', type=date.fromisoformat, help='UTC date override for reproducible badges')
    args = parser.parse_args()
    count = build(output=args.output, today=args.today)
    print(f'Built {count} app pages in {args.output or ROOT / "site/dist"}')


if __name__ == '__main__':
    main()
