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
        result.append('<span class="badge verified">Reviewed</span>')
    if 0 <= (today - date.fromisoformat(app["addedAt"])).days < 30:
        result.append('<span class="badge new">New</span>')
    if app["entry"] is None:
        result.append('<span class="badge library">Library</span>')
    return '<div class="badges">' + "".join(result) + '</div>'


def page(title, body, path):
    lede = re.search(r'<p class="(?:lede|sub)">(.*?)</p>', body, re.S) or re.search(r'<p>(.*?)</p>', body, re.S)
    description = unescape(re.sub(r'<[^>]+>', '', lede.group(1))) if lede else title
    card = path + 'card.png' if path.startswith('/apps/') else '/brand/og-image.png'
    dimensions = '<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">' if path.startswith('/apps/') else ''
    active = 'install' if path == '/install/' else 'submit' if path == '/submit/' else 'apps' if path == '/' or path.startswith(('/apps/', '/makers/')) else ''
    navigation = ''.join(f'<a href="{url}"' + (' class="on" aria-current="page"' if key == active else '') + f'>{label}</a>' for key, url, label in [('apps', '/', 'Apps'), ('install', '/install/', 'Install'), ('submit', '/submit/', 'Submit an app')])
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
<header><a class="brand" href="/"><img class="brand-mark" src="/brand/icon-512.png" width="36" height="36" alt=""><span>tiinyapp.farm</span></a>
<nav aria-label="Main navigation">{navigation}<a class="me" data-farm-nav href="/submit/#account-panel">Sign in</a></nav></header>
<main id="main">{body}</main>
<footer><div class="marks"><a class="pill" href="https://titanium.bot"><img src="/brand/titanium-bot-logo.svg" width="120" height="30" alt="Titanium Bot"><span>Brought to you by Titanium Bot</span></a>
<a class="pill" href="https://tiiny.ai">Built for <img src="/brand/tiiny-logo.svg" width="80" height="28" alt="Tiiny"></a></div><span>Made by Titanium Computing</span><a href="/docs/SUBMIT.md">Contributor guide</a><a href="/docs/manifest.schema.json">Manifest schema</a></footer>
</div><script type="module" src="/assets/session.js"></script></body></html>'''


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
    header = f'<img class="seed-header" src="{e(media["header"])}" alt="{e(app["name"])} header">' if media.get("header") else ''
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


def social_strip(app):
    return f'''<section class="seed-social" data-seed-social="{e(app['id'])}" aria-labelledby="social-heading"><h2 id="social-heading">Comments</h2>
<p id="social-status" role="status" aria-live="polite">Loading comments and thumbs up…</p>
<p id="social-signin"><a href="/submit/">Sign in to give this app a thumbs up or leave a comment.</a></p>
<div id="seed-comments" aria-label="App comments"></div>
<form id="comment-form" hidden><label for="comment-text">Comment</label><textarea id="comment-text" name="text" rows="4" maxlength="1000" required aria-describedby="comment-help"></textarea><p id="comment-help" class="fine">Up to 1,000 characters. Five comments per hour.</p><button id="comment-submit" class="btn hay" type="submit">Post comment</button></form>
<noscript><p>JavaScript is needed to load thumbs and comments.</p></noscript></section>'''


def app_page(app, today, makers=()):
    header, visual_media = seed_media(app)
    links = app.get('links', {})
    repo = links.get('repo') or app.get('repo')
    homepage = links.get('homepage') or app.get('homepage')
    req = app['requires']
    release = app.get('release')
    maker = next((m for m in makers if m.get('tiinyverse') and m['tiinyverse'] == app['author'].get('tiinyverse')), None)
    maker_url = '/makers/' + maker['handle'] + '/' if maker else app['author']['url']
    avatar = f'<img class="av" src="{e(maker["avatar"])}" alt="" width="36" height="36">' if maker and maker.get('avatar') else ''
    owner = '<span class="chip">Verified Tiiny owner</span>' if app['author'].get('tiinyverse') else ''
    review = 'Reviewed by a maintainer' if app['verified'] else 'Not reviewed by a maintainer'
    if release:
        commands = 'farm install ' + app['id']
        if app['entry'] is not None:
            commands += '\nfarm start ' + app['id']
        local = f'Then open <code>http://localhost:{e(req["ports"][0])}</code>. ' if req['ports'] and app['entry'] is not None else ''
        install = '<h2>Install</h2>' + command(commands) + f'<p class="small">{local}New here? <a href="/install/">Install the farm CLI first.</a></p>'
        if app['entry'] is None:
            install += '<p>This is a library. There is no app to start. Use it from your own application.</p>'
        release_details = f'<dl><dt>Version</dt><dd>{e(app["version"])}</dd><dt>Size</dt><dd>{release["size"]} bytes</dd><dt>SHA-256</dt><dd class="checksum">{e(release["sha256"])}</dd><dt>Source</dt><dd>{link(repo or release["url"], "Source repository" if repo else "Release archive")}</dd></dl>'
        release_details += '<p>' + link(release['url'], 'Download release') + '</p>'
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
    permissions = ''.join(f'<span class="chip">{e("Your Tiiny" if permission == "device" else permission.capitalize())}</span>' for permission in app['permissions']) or '<span class="chip">None declared</span>'
    return f'''<section class="page app-page">{header}<div class="apphead">{seed_icon(app)}<div><h1>{e(app['name'])}</h1><div class="v">v{e(app['version'])} · {e(app['license'])} · {review}</div></div></div>
<p class="sub">{e(app['pitch'])}</p>
<a hidden data-seed-update="{e(app['id'])}" href="/submit/?update={e(app['id'])}">Update this app</a>
<div class="two"><div>{install}<h2>What it does</h2><p>{e(app['description'])}</p>{'<p>' + link(homepage, 'Home page') + '</p>' if homepage else ''}{images}{social_strip(app)}</div><aside>
<div class="card2"><h2>Needs</h2><dl><dt>Python</dt><dd>{e(req.get('python', 'Not specified'))}</dd><dt>Port</dt><dd>{e(', '.join(map(str, req['ports'])) or 'None')}</dd><dt>Models</dt><dd>{e(', '.join(req['device']['models']) or 'None specified')}</dd><dt>Uses</dt><dd><div class="chips">{permissions}</div></dd></dl></div>
<div class="card2"><h2>Release</h2>{release_details}</div>
<div class="card2"><h2>Maker</h2><div class="maker">{avatar}<div><b>{link(maker_url, app['author']['name'])}</b><br>{owner}</div></div></div>
<div class="row"><button id="seed-thumb" class="btn ghost" type="button" aria-pressed="false" disabled>Thumbs up · <span id="thumb-count">0</span></button><button type="button" class="btn ghost" data-share data-share-title="{e(app['name'])}" data-share-text="{e(app['pitch'])}">Share</button></div><span data-share-status role="status" aria-live="polite"></span>
</aside></div></section><script type="module" src="/assets/share.js"></script><script type="module" src="/assets/seed-media.js"></script><script type="module" src="/assets/social.js"></script>'''


def seeds():
    return (ROOT / 'scripts/submit-page.html').read_text(encoding='utf-8')


def my_farm():
    return '''<section class="page"><h1>Your apps</h1>
<p class="lede">Edit your public profile and check the review status of your apps.</p>
<p><a href="/submit/">Submit your app or manage your sign-in</a></p><p id="farm-status" role="status" aria-live="polite">Loading your apps…</p>
<section class="seed-card" aria-labelledby="maker-name"><div class="maker-heading"><img id="maker-avatar" class="maker-avatar" width="96" height="96" alt="" hidden><div><h2 id="maker-name">Your profile</h2><p id="maker-handle"></p></div></div>
<p id="maker-bio" class="maker-bio"></p><div id="maker-links" class="row"></div><p><a id="public-maker" hidden>Visit your public maker page</a></p>
<p id="maker-proof"></p><button id="edit-profile" class="btn ghost" type="button" aria-expanded="false" aria-controls="maker-form">Edit</button><form id="maker-form" hidden><fieldset id="maker-fields" disabled><legend>Edit your profile</legend>
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

        hero = '''<section class="hero"><img src="/assets/hero.jpg" width="1600" height="1066" alt="A fantasy farm at dusk with glowing apps in rows and Titan tending the field."><div class="copy"><h1>Little apps, <em>grown for your Tiiny.</em></h1><p class="lede">Community-made apps that run beside your Pocket Lab on your own computer. Choose an app to see its requirements and install commands.</p><div class="row"><a class="btn hay" href="#field">Browse apps</a><a class="btn ghost" href="/install/">Install an app</a></div></div></section>'''
        field = '<section class="sect" id="field"><h2>Apps</h2><p class="lede">Each app lists its requirements, permissions and release details. Reviewed means a maintainer has run the app and reviewed its source; some apps do not yet have an installable release.</p><div class="field">'
        field += ''.join(plot(app, today, makers) for _, app in manifests) + '</div></section>'
        invitation = '<section class="seeds"><div><h2>Submit an app</h2><p>Submit an app for automated checks and maintainer review.</p></div><a class="btn hay" href="/submit/">Share your app</a></section>'
        pages = {"/": ("App catalog", hero + field + invitation),
                 "/install/": ("Install an app", steps()), "/submit/": ("Submit an app", seeds()), "/account/": ("Your apps", my_farm())}
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
        write('sitemap.xml', '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(f'<url><loc>{ORIGIN}{url}</loc></url>' for url in sorted(pages) if url not in ("/account/",)) + '</urlset>\n')
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
