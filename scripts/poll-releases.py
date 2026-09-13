#!/usr/bin/env python3
"""Look for new GitHub releases of listed apps and open the bump pull requests.

Run hourly by .github/workflows/release-poll.yml with a GitHub App token in
GITHUB_TOKEN. The work itself is farm/release.py, the same code farm release
runs for a maker, so the poller and the maker cannot disagree.
"""
import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from farm.farm import FarmError  # noqa: E402
from farm import release  # noqa: E402


def summary(lines):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as out:
        out.write("\n".join(lines) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", action="append", default=[], help="Check only this app (repeatable)")
    parser.add_argument("--repo", default=release.FARM_REPO, help="Catalog repository")
    parser.add_argument("--dry-run", action="store_true", help="Report findings without opening pull requests")
    args = parser.parse_args(argv)
    api = release.GitHub(os.environ.get("GITHUB_TOKEN", ""))
    catalog = release.Catalog(api, args.repo)
    try:
        idents = args.app or catalog.ids()
    except FarmError as error:
        print("The catalog could not be read: {}".format(error), file=sys.stderr)
        return 1
    lines = ["| App | Result |", "| --- | --- |"]
    failures = []
    for ident in idents:
        try:
            outcome = release.check(catalog, ident, submit=not args.dry_run)
            note = outcome.message + (" " + outcome.pr if outcome.pr else "")
        except FarmError as error:
            note = "could not be checked: {}".format(error)
            failures.append(ident)
        print("{}: {}".format(ident, note))
        lines.append("| {} | {} |".format(ident, note))
    summary(lines)
    if failures:
        print("Could not check: {}".format(", ".join(failures)), file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
