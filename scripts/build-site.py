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
    "requires": "Minimum python version if known, local ports, and device requirements: models and npuUnits.",
    "permissions": "Declared access: microphone, files, network and device. An empty list no permissions declared.",
    "tags": "Short labels that help people find the app.",
    "verified": "Keep false when submitting. A maintainer sets true in a follow-up commit after CI and manual review.",
    "featured": "Optional maintainer-curated placement in the home page Featured section.",
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


ICONS = {
    "search": '<path d="M3 10a7 7 0 1 0 14 0a7 7 0 1 0-14 0m18 11l-6-6"/>',
    "copy": '<path d="M7 9.667A2.667 2.667 0 0 1 9.667 7h8.666A2.667 2.667 0 0 1 21 9.667v8.666A2.667 2.667 0 0 1 18.333 21H9.667A2.667 2.667 0 0 1 7 18.333z"/><path d="M4.012 16.737A2 2 0 0 1 3 15V5c0-1.1.9-2 2-2h10c.75 0 1.158.385 1.5 1"/>',
}


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
    navigation = ''.join(f'<a href="{url}"' + (' class="on" aria-current="page"' if key == active else '') + f'>{label}</a>' for key, url, label in [('apps', '/', 'Apps'), ('catalog', '/catalog/', 'Catalog'), ('install', '/install/', 'Install'), ('submit', '/submit/', 'Submit an app')])
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
<a class="pill" href="https://tiiny.ai">Built for <img src="/brand/tiiny-logo.svg" width="80" height="28" alt="Tiiny"></a></div><span>Made by Titanium Computing</span><a href="/docs/SUBMIT.md">Contributor guide</a><a href="/docs/manifest.schema.json">Manifest schema</a></div></footer>
{page_scripts}<script type="module" src="/assets/session.js"></script></body></html>'''


def steps():
    return '''<section class="page install-page"><h1>Install apps on your Tiiny</h1>
<p class="sub">Apps from the catalog run on your computer and talk to your Tiiny Pocket Lab over its local API. One command-line tool installs, starts and updates them.</p>
<div class="steps">
<div class="stp"><div class="n">1</div><div><h2>Install the farm CLI</h2><p>Python 3.9 or newer. macOS, Linux and Windows.</p><pre>pip install tiinyapp-farm</pre><p class="small">Check it: <code>farm --version</code></p></div></div>
<div class="stp"><div class="n">2</div><div><h2>Connect your Tiiny</h2><p>The CLI asks for two values once and saves them in <code>~/.tiinyapps/device.json</code>, readable only by you.</p><pre>farm device</pre>
<dl><dt>API base URL</dt><dd>On a Mac with the TiinyOS client installed: <code>http://openai.api.tiiny/v1</code><br>From any other computer on your network: <code>http://&lt;your-tiiny-ip&gt;/v1</code></dd><dt>API key</dt><dd>TiinyOS → Settings → API Key. Copy it.</dd></dl>
<p class="small">Run <code>farm device</code> again to change either value.</p></div></div>
<div class="stp"><div class="n">3</div><div><h2>Install and run an app</h2><p>Pick an app in the catalog. Its page shows what it needs and what it asks for before you install it.</p><pre>farm install titanium-tiiny-bot
farm start titanium-tiiny-bot</pre>
<dl><dt><code>farm list</code></dt><dd>installed apps and whether they are running</dd><dt><code>farm stop &lt;id&gt;</code></dt><dd>stop one</dd><dt><code>farm update &lt;id&gt;</code></dt><dd>update to the newest release, then start it again</dd><dt><code>farm remove &lt;id&gt;</code></dt><dd>uninstall</dd></dl></div></div>
</div>
<p class="note" style="margin-top:18px">Apps declare the access they use (microphone, files, network, your Tiiny). The CLI shows that before installing; it does not sandbox them. Read the source if that matters to you: every app in the catalog ships it.</p></section>'''


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


def editorial_item(app):
    media = app.get("media", {})
    art = (f'<div class="art" style="background-image:url(&quot;{e(media["header"])}&quot;)"></div>'
           if media.get("header") else '<div class="art"></div>')
    chips = ''.join(f'<span class="chip">{e(permission_label(value))}</span>' for value in app["permissions"])
    chips += f'<span class="chip">v{e(app["version"])}</span>'
    return f'''<article class="item">{art}<div class="text"><span class="cat-tag">{e(category_tag(app))}</span>
<h3 class="name"><a href="/apps/{e(app['id'])}/">{e(app['name'])}</a></h3><p class="pitch">{e(app['pitch'])}</p>
<p class="desc">{e(first_two_sentences(app['description']))}</p><div class="chips">{chips}</div>
<div class="foot"><a class="btn hay" href="/apps/{e(app['id'])}/">Install</a>{copy_command('farm install ' + app['id'])}</div></div></article>'''


def ledger_row(app):
    media = app.get("media", {})
    icon_image = (f'<img src="{e(media["icon"])}" width="56" height="56" alt="">'
                  if media.get("icon") else '<span class="row-icon" aria-hidden="true"></span>')
    chips = f'<span class="chip">{e(needs(app))}</span>'
    chips += ''.join(f'<span class="chip">{e(permission_label(value))}</span>' for value in app["permissions"])
    return f'''<article class="row" data-catalog-search="{e(search_text(app))}">{icon_image}<div><span class="cat-tag">{e(category_tag(app))}</span>
<h3 class="name"><a href="/apps/{e(app['id'])}/">{e(app['name'])}</a></h3><p class="pitch">{e(app['pitch'])}</p><div class="chips">{chips}</div></div>
<span class="v">v{e(app['version'])}</span><a class="btn hay" href="/apps/{e(app['id'])}/">Install</a></article>'''


def home_page(apps):
    featured = [app for app in apps if app.get("featured")][:6]
    hero = '''<section class="hero"><img src="/assets/hero.jpg" width="1600" height="1066" alt="A fantasy farm at dusk with glowing apps in rows and Titan tending the field."><div class="copy"><h1>Little apps, <em>grown for your Tiiny.</em></h1><p class="lede">Community-made apps that run beside your Pocket Lab on your own computer. Choose an app to see its requirements and install commands.</p><div class="row"><a class="btn hay" href="#all-apps">Browse apps</a><a class="btn ghost" href="/install/">Install an app</a></div></div></section>'''
    featured_section = f'''<section class="feat wrap"><div class="sechead"><h2>Featured</h2><p>Picked by the maintainers</p></div>
<div class="v3"><div class="list">{''.join(editorial_item(app) for app in featured)}</div></div></section>'''
    ledger = f'''<section class="ledger wrap" id="all-apps"><div class="sechead"><h2>All apps</h2><p><a href="/catalog/">Browse the catalog with filters</a></p></div>
<div class="toolbar"><label class="search">{icon('search')}<span class="visually-hidden">Search apps</span><input id="q-home" type="search" placeholder="Search apps, makers, tags" autocomplete="off"></label><span class="count" id="count-home">{len(apps)} of {len(apps)}</span></div>
<div class="v2"><div class="rows" id="rows-home">{''.join(ledger_row(app) for app in apps)}</div><p class="empty" id="empty-home" hidden>No app matches. Try fewer words.</p></div></section>'''
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
<p id="social-status" role="status" aria-live="polite">Loading comments and thumbs up…</p>
<p id="social-signin"><a href="/submit/">Sign in to give this app a thumbs up or leave a comment.</a></p>
<div id="seed-comments" aria-label="App comments"></div>
<form id="comment-form" hidden><label for="comment-text">Comment</label><textarea id="comment-text" name="text" rows="4" maxlength="1000" required aria-describedby="comment-help"></textarea><p id="comment-help" class="fine">Up to 1,000 characters. Five comments per hour.</p><button id="comment-submit" class="btn hay" type="submit">Post comment</button></form>
<noscript><p>JavaScript is needed to load thumbs and comments.</p></noscript></section>'''


def app_page(app, today, makers=()):
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
        install = '<h2>Install</h2>' + copy_command(commands) + f'<p class="sub install-note">{local}New here? <a href="/install/">Install the farm CLI first.</a></p>'
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
    return f'''<section class="app wrap">{band}<div class="head">{app_icon}<div><h1>{e(app['name'])}</h1><div class="sub">v{e(app['version'])} · {e(app['license'])} · {review} · Grown by {link(maker_url, app['author']['name'])}</div></div></div>
<p class="pitch">{e(app['pitch'])}</p>
<a hidden data-seed-update="{e(app['id'])}" href="/submit/?update={e(app['id'])}">Update this app</a>
<div class="two"><div>{install}<h2>What it does</h2><p class="desc">{e(app['description'])}</p>{'<p>' + link(homepage, 'Home page') + '</p>' if homepage else ''}{images}{social_strip(app)}</div><aside class="rail">
<div class="card"><h3>Needs</h3><dl><dt>Python</dt><dd>{python}</dd><dt>Port</dt><dd>{e(', '.join(map(str, req['ports'])) or 'None')}</dd><dt>Models</dt><dd>{e(', '.join(req['device']['models']) or 'None')}</dd><dt>NPU</dt><dd>{e(req['device']['npuUnits'])} units</dd><dt>Uses</dt><dd><div class="chips">{permissions}</div></dd></dl></div>
<div class="card"><h3>Release</h3>{release_details}</div>
<div class="card"><h3>Maker</h3><div class="maker">{avatar}<div><b>{link(maker_url, app['author']['name'])}</b><br>{owner}</div></div></div>
<div class="rail-actions"><button id="seed-thumb" class="btn ghost" type="button" aria-pressed="false" disabled>Thumbs up · <span id="thumb-count">0</span></button><button type="button" class="btn ghost" data-share data-share-title="{e(app['name'])}" data-share-text="{e(app['pitch'])}">Share</button></div><span data-share-status role="status" aria-live="polite"></span>
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
<noscript><p>JavaScript is needed to load your profile settings and submission status.</p></noscript></section><script type="module" src="/assets/farm.js"></script>'''


def agent_guide(text):
    return f'''<section class="page agent-doc"><h1>Publish to tiinyapp.farm</h1>
<p class="lede">Plain instructions for AI assistants and people publishing from a project folder.</p>
<pre class="agent-guide">{e(text)}</pre></section>'''


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

        apps = [app for _, app in manifests]
        guide = (source / 'docs/agents.txt').read_text(encoding='utf-8')
        pages = {"/": ("App catalog", home_page(apps)), "/catalog/": ("Catalog", catalog_page(apps)),
                 "/install/": ("Install an app", steps()), "/submit/": ("Submit an app", seeds()),
                 "/submit/done/": ("App submitted", seeds()), "/account/": ("Your apps", my_farm()),
                 "/docs/agents/": ("Publish for a person", agent_guide(guide))}
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
            scripts = ('/assets/catalog.js',) if url in ('/', '/catalog/') else (
                ('/assets/catalog.js', '/assets/share.js', '/assets/seed-media.js', '/assets/social.js')
                if url.startswith('/apps/') else ())
            write(url.lstrip('/') + 'index.html', page(title, body, url, scripts))
        write('404.html', page('Page not found', '<section class="sect"><h1>Page not found</h1><p>This page does not exist. ' + link('/', 'Return to the catalog') + '.</p></section>', '/404.html'))
        write('sitemap.xml', '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(f'<url><loc>{ORIGIN}{url}</loc></url>' for url in sorted(pages) if url not in ("/account/", "/submit/done/")) + '</urlset>\n')
        write('catalog.json', json.dumps([app for _, app in manifests], ensure_ascii=False) + '\n')
        write('categories.json', json.dumps({'map': CATEGORIES, 'order': CATEGORY_ORDER}, ensure_ascii=False) + '\n')
        write('llms.txt', guide)
        write('site.webmanifest', json.dumps({'name': 'tiinyapp.farm', 'short_name': 'tiinyapp.farm',
              'start_url': '/', 'display': 'standalone', 'theme_color': '#090D14', 'background_color': '#090D14',
              'icons': [{'src': '/brand/favicon-192.png', 'sizes': '192x192', 'type': 'image/png'},
                        {'src': '/brand/icon-512.png', 'sizes': '512x512', 'type': 'image/png'}]}) + '\n')
        shutil.copytree(source / 'brand', dest / 'brand')
        shutil.copytree(source / 'site/fonts', dest / 'fonts')
        write('robots.txt', f'User-agent: *\nAllow: /\nSitemap: {ORIGIN}/sitemap.xml\n')
        for folder, files in {'assets': ['hero.jpg', 'site.css', 'catalog.js', 'seeds.js', 'session.js', 'farm.js', 'seed-media.js', 'social.js', 'share.js', 'titanium-icon.png', 'titanium-header.webp'], 'docs': ['manifest.schema.json', 'SUBMIT.md']}.items():
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
    args = parser.parse_args()
    count = build(output=args.output, today=args.today)
    print(f'Built {count} app pages in {args.output or ROOT / "site/dist"}')


if __name__ == '__main__':
    main()
