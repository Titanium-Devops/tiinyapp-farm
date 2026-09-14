#!/usr/bin/env python3
"""Fetch the public farm the way a stranger's browser does, before and after a deploy.

Every page and file is fetched twice with no cookie and no session: once with a plain
Mozilla user agent, once with whatever urllib sends by default. Two agents because a
bot rule that only bites the second one is invisible in a browser. Anything that is not
the status this script expects is a failure, and the run exits 1.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ORIGIN = "https://tiinyapp.farm"
ROOT = Path(__file__).resolve().parents[1]
BROWSER = "Mozilla/5.0"
AGENTS = (("browser", BROWSER), ("python", None))

# Everything a person or a crawler can reach without signing in. /account/ answers 302
# to the sign-in step; every other path answers 200 or the deploy is wrong.
PAGES = [
    "/", "/catalog/", "/install/", "/submit/", "/submit/done/", "/docs/agents/",
]
FILES = [
    "/llms.txt", "/robots.txt", "/sitemap.xml", "/catalog.json", "/categories.json",
    "/site.webmanifest", "/assets/site.css", "/assets/farm.js", "/assets/session.js",
    "/brand/og-image.png", "/brand/favicon.ico", "/docs/SUBMIT.md",
    "/docs/manifest.schema.json", "/manifests/",
]
REDIRECTS = {"/account/": 302}


def app_ids(origin, timeout):
    """App ids from the manifests in this checkout, or from the live catalog."""
    folder = ROOT / "manifests"
    if folder.is_dir():
        ids = sorted(path.stem for path in folder.glob("*.json"))
        if ids:
            return ids
    body, _, _ = fetch(origin + "/catalog.json", BROWSER, timeout)
    published = json.loads(body)
    apps = published if isinstance(published, list) else published.get("apps", [])
    return sorted(app["id"] for app in apps)


def fetch(url, agent, timeout):
    """Return (body, status, milliseconds). A 3xx or 4xx is a result, not an exception."""
    headers = {"User-Agent": agent} if agent else {}
    request = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(NoRedirect)
    started = time.perf_counter()
    try:
        with opener.open(request, timeout=timeout) as answer:
            body, status = answer.read(), answer.status
    except urllib.error.HTTPError as error:
        body, status = error.read(), error.code
    return body, status, (time.perf_counter() - started) * 1000


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Report the redirect instead of following it, so /account/ shows its 302."""

    def redirect_request(self, *_args, **_kwargs):
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--origin", default=ORIGIN, help=f"default {ORIGIN}")
    parser.add_argument("--timeout", type=float, default=30.0, help="seconds per request")
    parser.add_argument("--json", action="store_true", help="print results as JSON too")
    options = parser.parse_args(argv)
    origin = options.origin.rstrip("/")

    expected = {path: 200 for path in PAGES + FILES}
    expected.update(REDIRECTS)
    for ident in app_ids(origin, options.timeout):
        expected[f"/apps/{ident}/"] = 200
        expected[f"/apps/{ident}/card.png"] = 200
        expected[f"/manifests/{ident}.json"] = 200

    print(f"{origin} as an anonymous visitor, {time.strftime('%Y-%m-%d %H:%M %Z')}")
    print(f"{'path':<34}{'want':>5}  {'browser':>22}  {'python':>22}")
    failures, results = [], []
    for path, want in expected.items():
        row, cells = {"path": path, "expected": want}, []
        for label, agent in AGENTS:
            body, status, elapsed = fetch(origin + path, agent, options.timeout)
            row[label] = {"status": status, "bytes": len(body), "ms": round(elapsed)}
            cells.append(f"{status:>3}  {len(body):>7}B  {round(elapsed):>5}ms")
            if status != want:
                failures.append((path, label, want, status))
        results.append(row)
        print(f"{path:<34}{want:>5}  {cells[0]}  {cells[1]}")

    if options.json:
        print(json.dumps(results, indent=2))
    print()
    if failures:
        print(f"FAILED. {len(failures)} of {len(expected) * len(AGENTS)} fetches answered wrong:")
        for path, label, want, status in failures:
            print(f"  {path} as {label}: wanted {want}, got {status}")
        print("Do not announce this deploy. Fix it, deploy again, run this again.")
        return 1
    print(f"All {len(expected) * len(AGENTS)} fetches answered as expected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
