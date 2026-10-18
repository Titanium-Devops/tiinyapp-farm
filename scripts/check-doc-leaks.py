#!/usr/bin/env python3
"""Fail the build if a published doc leaks a real device identifier.

Rule 41 / decision 191: the public /docs pages (built from docs/site/*.md) and
the public README must never carry a real Tiiny serial, a private LAN/USB IP, or
a real home path. Guides are captured against a fake device or rewritten with
documentation placeholders: serial TNYM00000000000000X, the 192.0.2.0/24 range,
and ~/ or /Users/you paths.

Scope: docs/site/*.md and README.md (what we actually publish). Internal report
files under docs/ are not served and are not scanned here.

    python3 scripts/check-doc-leaks.py            # scan, exit 1 on any finding
    python3 scripts/check-doc-leaks.py --selftest  # prove the patterns, no repo

ponytail: source scan, not the built HTML - the build never introduces a real
value the markdown did not already carry, and this runs with no build step.
"""
import os
import re
import sys

# A real Tiiny serial is TNYM + 15 chars; the documentation placeholder is the
# all-zero-with-trailing-X one, which is allowed.
SERIAL = re.compile(r"\bTNYM[0-9A-Z]{15}\b")
SERIAL_PLACEHOLDER = "TNYM00000000000000X"

# Private host addresses as full dotted quads, so a version like 10.0 or a
# timeout never trips it. RFC1918 plus the 172.16/12 block. The doc range
# 192.0.2.0/24 is deliberately not matched.
PRIVATE_IP = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"
)

# A real home path names a person. The placeholder user is "you".
HOME_PATH = re.compile(r"/(?:Users|home)/(?!you\b)[A-Za-z0-9._-]+")

CHECKS = (
    ("real device serial", lambda s: [m for m in SERIAL.findall(s) if m != SERIAL_PLACEHOLDER]),
    ("private IP address", lambda s: PRIVATE_IP.findall(s)),
    ("real home path", lambda s: HOME_PATH.findall(s)),
)


def scan_text(text):
    """List of (line_no, label, match) findings in one document's text."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        for label, finder in CHECKS:
            for hit in finder(line):
                out.append((n, label, hit))
    return out


def targets(root):
    site = os.path.join(root, "docs", "site")
    for name in sorted(os.listdir(site)):
        if name.endswith(".md"):
            yield os.path.join(site, name)
    readme = os.path.join(root, "README.md")
    if os.path.exists(readme):
        yield readme


def main(root):
    findings = []
    for path in targets(root):
        with open(path, encoding="utf-8") as fh:
            for n, label, hit in scan_text(fh.read()):
                findings.append((os.path.relpath(path, root), n, label, hit))
    if findings:
        print("Doc leak check FAILED: real identifiers in published docs.")
        print("Use placeholders: %s, the 192.0.2.0/24 range, ~/ or /Users/you paths.\n"
              % SERIAL_PLACEHOLDER)
        for rel, n, label, hit in findings:
            print("  %s:%d  %s: %s" % (rel, n, label, hit))
        return 1
    print("Doc leak check passed: no real serials, private IPs or home paths in docs/site or README.")
    return 0


def selftest():
    bad = ("serial TNYM26072400300011Q on usb 172.17.7.177 and wifi 192.168.100.94, "
           "key at /Users/sem/.tiiny_1_api_key, also 10.0.0.5")
    good = ("serial TNYM00000000000000X at 192.0.2.1 and 192.0.2.3, key at "
            "/Users/you/.tiiny-key, timeout 10.0, range 192.0.2.0/24")
    b = scan_text(bad)
    g = scan_text(good)
    labels = sorted({l for _, l, _ in b})
    assert labels == ["private IP address", "real device serial", "real home path"], labels
    assert len(b) >= 5, b
    assert g == [], g  # placeholders and version numbers must not trip
    print("selftest ok: bad text ->", len(b), "findings; good text -> 0")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main(here))
