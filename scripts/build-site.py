#!/usr/bin/env python3
"""Build the readable farm catalog using only the Python standard library."""

import argparse
from datetime import date, datetime, timezone
from html import escape
import json
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
    "name": "The name shown in the field.",
    "pitch": "One short line explaining what it does.",
    "description": "The full story, including limitations and release readiness.",
    "version": "The release version as major.minor.patch.",
    "author": "The maker's name and public web address (name and url).",
    "license": "The license identifier; NOASSERTION means a license is not confirmed.",
    "homepage": "The app's public home page.",
    "repo": "The source repository for review.",
    "screenshots": "A list of public image URLs; an empty list is fine.",
    "release": "The archive url, its sha256 checksum and its size in bytes. A pending checksum blocks installation; size 0 means unknown.",
    "entry": "A Python module (python) and args, or a command. Use null for a library with nothing to start.",
    "requires": "Minimum python version if known, local ports, and device requirements: models and npuUnits.",
    "permissions": "Declared access: microphone, files, network and device. An empty list asks for nothing.",
    "tags": "Short labels that help people find the app.",
    "verified": "Keep false when submitting. Farm CI and a human maintainer must approve verification.",
    "addedAt": "The day the app joined the farm, YYYY-MM-DD. New lasts less than 30 days.",
    "updatedAt": "The most recent manifest update, YYYY-MM-DD.",
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
    if app["verified"]:
        result.append('<span class="badge verified">Verified</span>')
    if 0 <= (today - date.fromisoformat(app["addedAt"])).days < 30:
        result.append('<span class="badge new">New</span>')
    if app["entry"] is None:
        result.append('<span class="badge library">Library</span>')
    return '<div class="badges">' + "".join(result) + '</div>'


def page(title, body, path):
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Community apps to plant beside your Tiiny AI Pocket Lab. Read what each app needs and asks for.">
<title>{e(title)} | tiinyapp.farm</title>
<link rel="canonical" href="{ORIGIN}{path}">
<link rel="icon" href="/brand/ti-mark.svg" type="image/svg+xml">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,800&amp;family=Nunito:wght@400;600;700&amp;display=swap">
<link rel="stylesheet" href="/assets/site.css"></head>
<body><a class="skip" href="#main">Skip to content</a><div class="wrap">
<header><a class="brand" href="/"><img src="/brand/ti-mark.svg" width="30" height="30" alt=""><span>tiinyapp.farm<small>apps you grow on your Tiiny</small></span></a>
<nav aria-label="Main navigation"><a href="/#field">The field</a><a href="/plant/">Plant an app</a><a class="cta" href="/seeds/">Bring your seeds</a></nav></header>
<main id="main">{body}</main>
<footer><div class="marks"><a class="pill" href="https://titanium.bot"><img src="/brand/titanium-bot-logo.svg" width="120" height="30" alt="Titanium Bot"><span>Brought to you by Titanium Bot</span></a>
<a class="pill" href="https://tiiny.ai">Built for <img src="/brand/tiiny-logo.svg" width="80" height="28" alt="Tiiny"></a></div><span>Made by Titanium Computing</span></footer>
</div></body></html>'''


def steps():
    return f'''<section class="sect"><h1>Plant an app in three steps</h1>
<p class="lede">One farmhand for the whole field. Apps run on your computer beside your Pocket Lab.</p>
<div class="steps"><section class="step"><h2>1. Get the farmhand</h2><p>Use Python 3.11 or newer on macOS or Linux. Get the source and install the tool from its checkout.</p>
{command('git clone ' + REPO + '.git' + chr(10) + 'cd tiinyapp-farm' + chr(10) + 'python3 -m pip install .')}</section>
<section class="step"><h2>2. Tell it about your Tiiny</h2><p>Find the base URL and key in TiinyOS, Settings, API Key. The farmhand asks once and keeps them private on your computer.</p>{command('farm device')}</section>
<section class="step"><h2>3. Plant and grow</h2><p>Read the app's requirements, permissions and release notes first. Once its release is available, plant it and start it.</p>{command('farm install titanium-tiiny-bot' + chr(10) + 'farm start titanium-tiiny-bot')}<p>Libraries have nothing to start. Pending checksums prevent installation.</p></section></div>
<p>Use <code>farm status</code> to see what is growing, <code>farm stop &lt;id&gt;</code> to stop it, and <code>farm update &lt;id&gt;</code> to update it. Start it again after updating.</p>
<p>Apps declare their access; the installer does not sandbox them. Cooperating apps can take turns on the device with OneLane.</p></section>'''


def plot(app, today):
    models = ", ".join(app["requires"]["device"]["models"]) or "no named models"
    permissions = "".join(f'<span>{e(p)}</span>' for p in app["permissions"]) or '<span>asks for nothing</span>'
    return f'''<article class="plot"><div class="plot-top">{badges(app, today)}<span class="ver">v{e(app['version'])}</span></div>
<h3>{e(app['name'])}</h3><p class="pitch">{e(app['pitch'])}</p><p class="by">by {e(app['author']['name'])} · needs {e(models)}</p>
<div class="perms">{permissions}</div><div class="plant"><code>farm install {e(app['id'])}</code><a class="btn hay" href="/apps/{e(app['id'])}/" aria-label="Plant {e(app['name'])}">Plant it</a></div></article>'''


def app_page(app, today):
    req = app["requires"]
    device = req["device"]
    entry = app["entry"]
    release = app["release"]
    if entry is None:
        start = '<p>This is a library. There is no app to start. Use it from your own application.</p>'
    else:
        invocation = (shlex.join(["python", "-m", entry["python"], *entry["args"]])
                      if "python" in entry else entry["command"])
        start = command(f"farm start {app['id']}") + '<p>The farmhand launches:</p>' + command(invocation)
    screenshots = "".join(f'<figure><img src="{e(url)}" alt="{e(app["name"])} screenshot {i}" loading="lazy"></figure>'
                          for i, url in enumerate(app["screenshots"], 1)) or '<p>No screenshots supplied yet.</p>'
    perms = "".join(f'<li>{e(PERMISSIONS[p])}</li>' for p in app["permissions"])
    rows = {
        "App ID": app["id"], "Version": app["version"], "License": app["license"],
        "Tags": ", ".join(app["tags"]) or "None", "Added to the farm": app["addedAt"],
        "Last updated": app["updatedAt"],
        "Farmhand review": "Verified: farmhands ran it and read it." if app["verified"] else "Not verified by the farmhands.",
    }
    details = "".join(f'<dt>{e(k)}</dt><dd>{e(v)}</dd>' for k, v in rows.items())
    return f'''<section class="sect"><p>{link('/#field', 'Back to the field')}</p>{badges(app, today)}<h1>{e(app['name'])}</h1><p class="lede">{e(app['pitch'])}</p>
<section><h2>What it does</h2><p>{e(app['description'])}</p></section>
<section><h2>What it needs</h2><ul><li>Python: {e(req.get('python', 'minimum not specified'))}. The farmhand itself needs Python 3.11 or newer.</li>
<li>Local ports: {e(', '.join(map(str, req['ports'])) or 'none')}.</li><li>Tiiny models: {e(', '.join(device['models']) or 'none specified')}.</li><li>NPU units: {device['npuUnits']}.</li></ul></section>
<section><h2>What it asks for</h2>{'<ul>' + perms + '</ul>' if perms else '<p>Asks for nothing.</p>'}<p>These are declared permissions, not sandbox restrictions.</p></section>
<section><h2>Plant it</h2><p>Read the release notes below before installing. {link('/plant/', 'Set up the farmhand')}.</p>{command('farm install ' + app['id'])}{start}</section>
<section><h2>Screenshots</h2>{screenshots}</section>
<section><h2>The maker and the seed</h2><p>Author: {link(app['author']['url'], app['author']['name'])}</p><dl>{details}</dl>
<p>{link(app['homepage'], 'App home')} {link(app['repo'], 'Source repository')} {link('/manifests/' + app['id'] + '.json', 'Original manifest')}</p></section>
<section><h2>Release</h2><p>{link(release['url'], 'Release archive')}</p><dl><dt>SHA-256 checksum</dt><dd><code>{e(release['sha256'])}</code></dd><dt>Archive size</dt><dd>{str(release['size']) + ' bytes' if release['size'] else '0 bytes recorded (size unknown)'}</dd></dl>
{'<p>Release pending: the installer cannot install this seed until its checksum is published.</p>' if release['sha256'] == 'pending' else ''}
<p>Release notes: {e(app['description'])}</p></section>
{'<section><h2>Health check</h2><p>HTTP GET <code>' + e(app['health']) + '</code> on the first declared port; expects a JSON object with version and optional ok.</p></section>' if 'health' in app else ''}</section>'''


def seeds():
    fields = ''.join(f'<dt><code>{e(k)}</code></dt><dd>{e(v)}</dd>' for k, v in FIELDS.items())
    return f'''<section class="sect"><h1>Bring your seeds</h1><p class="lede">Built something for the Pocket Lab? Give it a plot on the farm.</p>
<h2>How to submit</h2><ol><li>Publish the app's source and a versioned release archive. Include a selfcheck.</li><li>Add <code>manifests/your-app.json</code> using an {link('/manifests/', 'existing seed')} and the {link('/docs/manifest.schema.json', 'manifest schema')}.</li><li>Open a pull request in {link(REPO, 'Titanium-Devops/tiinyapp-farm')}. Leave <code>verified</code> false for the farmhands.</li></ol>
<h2>The manifest fields</h2><dl>{fields}</dl><h2>The checks</h2><p>Run the local schema check before submitting:</p>{command('python3 scripts/check-manifest.py manifests/your-app.json')}
<p>For a clearly described release draft only, add <code>--allow-pending</code>. Draft validation does not make an app installable.</p>
<ul><li>The schema checks required fields, formats, permissions and entry shape.</li><li>The installer checks the archive checksum and byte size before extraction.</li><li>Before verification, farmhands must run the selfcheck, review the source for secrets and confirm declared permissions match the code.</li></ul>
<p>Schema validation alone does not run the app or perform a security review. Verified requires CI and human review; it is not awarded by this site builder.</p></section>'''


def build(source=ROOT, output=None, today=None):
    source = Path(source)
    output = Path(output) if output else source / "site" / "dist"
    today = today or datetime.now(timezone.utc).date()
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

        hero = '''<section class="hero"><img src="/assets/hero.jpg" width="1600" height="1066" alt="A fantasy farm at dusk with glowing apps in rows and Titan tending the field."><div class="copy"><h1>Little apps, <em>grown for your Tiiny.</em></h1><p>Community-made apps that run beside your Pocket Lab on your own computer. Pick one, plant it, and let it grow.</p><div class="row"><a class="btn hay" href="#field">Browse the field</a><a class="btn ghost" href="/plant/">How planting works</a></div></div></section>'''
        field = '<section class="sect" id="field"><h2>The field</h2><p class="lede">Every app shows what it needs and what it asks for before you plant it. Verified means the farmhands ran it and read it. Read each seed\'s release notes: some releases are still pending.</p><div class="field">'
        field += ''.join(plot(app, today) for _, app in manifests) + '</div></section>'
        invitation = '<section class="seeds"><div><h2>Bring your seeds</h2><p>One manifest, a place in the field, and farmhands to help it grow.</p></div><a class="btn hay" href="/seeds/">Share your app</a></section>'
        pages = {"/": ("The field", hero + field + steps().replace('<h1>', '<h2>').replace('</h1>', '</h2>') + invitation),
                 "/plant/": ("Plant an app", steps()), "/seeds/": ("Bring your seeds", seeds())}
        listing = '<section class="sect"><h1>The seeds</h1><p>The installer catalog at https://tiinyapp.farm/manifests/.</p><ul>'
        for path, app in manifests:
            pages[f"/apps/{app['id']}/"] = (app["name"], app_page(app, today))
            write(f"manifests/{app['id']}.json", "")
            shutil.copyfile(path, dest / "manifests" / path.name)
            listing += '<li>' + link(path.name, app['name']) + '</li>'
        pages['/manifests/'] = ('The seeds', listing + '</ul></section>')
        for url, (title, body) in pages.items():
            write(url.lstrip('/') + 'index.html', page(title, body, url))
        write('404.html', page('This plot is empty', '<section class="sect"><h1>This plot is empty</h1><p>That seed is not here. ' + link('/', 'Return to the field') + '.</p></section>', '/404.html'))
        write('sitemap.xml', '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(f'<url><loc>{ORIGIN}{url}</loc></url>' for url in sorted(pages)) + '</urlset>\n')
        write('robots.txt', f'User-agent: *\nAllow: /\nSitemap: {ORIGIN}/sitemap.xml\n')
        for folder, files in {'assets': ['hero.jpg', 'site.css'], 'brand': ['ti-mark.svg', 'titanium-bot-logo.svg', 'tiiny-logo.svg'], 'docs': ['manifest.schema.json']}.items():
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
