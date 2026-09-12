# Phase 3: the submission checks, and pip

Read SPEC.md (Submission), docs/manifest.schema.json, scripts/check-manifest.py, farm/farm.py.

1. .github/workflows/manifest-check.yml, on pull_request touching manifests/**: for each changed
   manifest run scripts/check-manifest.py (no --allow-pending on a PR), assert the id matches the
   filename and is unique, download the release archive, verify sha256 and size, unpack into a
   temp dir with a path-traversal guard, run a static scan (scripts/scan-archive.py, stdlib): list
   Python imports and flag socket/subprocess/ctypes/os.system/eval/exec, look for keys and
   tokens by pattern (AWS, GitHub, OpenAI, Bearer, private keys), and compare with the manifest's
   declared permissions (network needs "network", subprocess needs "shell" which we do not allow
   at all, microphone access is declared not detected); then, if the manifest declares a
   selfcheck, run it in a container with no network after the download (docker run --network
   none, python:3.11-slim, 120 s) and require exit 0. Post the results as one PR comment (a
   table: check, result, detail) and fail the job on any red. Verified is never set by CI: a
   maintainer edits `verified: true` in a follow-up commit.
2. .github/workflows/site.yml already deploys on push to main; make it also run build-site and
   the unittest suite first, and skip the deploy when only docs/ changed.
3. pyproject.toml for `pip install tiinyapp-farm` (console script `farm`), plus
   .github/workflows/publish.yml that builds and publishes to PyPI on a tag v* using trusted
   publishing (pypa/gh-action-pypi-publish with id-token: write; no token secret). Update the
   site's Plant step 1 text to `pip install tiinyapp-farm` with the git clone as the fallback
   line, and the README.
4. docs/SUBMIT.md: the contributor's guide in plain words, linked from the site's seeds page.
5. Tests for the scanner (a fixture archive with a hidden token and an undeclared socket import
   must fail; the Lite archive shape must pass) and for the workflow's manifest selection logic
   if it lives in a script. `python3 -m unittest` green. Write docs/PHASE-3-REPORT.md. No browser,
   no wrangler, no docker from your sandbox (write the workflow; the orchestrator proves it on a
   PR). Commit is not possible from your sandbox.
