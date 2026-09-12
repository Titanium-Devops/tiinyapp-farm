# Bring your seeds

Have an app that works beside a Tiiny AI Pocket Lab? Submit one manifest in a pull
request. The app runs on the person's computer; it is not installed into TiinyOS.

1. Publish your source and a versioned tar or tar.gz release archive. Include your
   license and everything the app needs to start. Do not bundle API keys, tokens,
   private keys, virtual environments or local user data. Keep keys in runtime
   configuration instead.
2. Copy a manifest into `manifests/your-app.json`. Choose a unique lowercase ID
   with dashes; the filename must match it. `tiiny` is reserved. Follow
   [the schema](manifest.schema.json) and describe what the app does in plain words.
3. Fill in the release URL, SHA-256 checksum and exact size in bytes. Use a public
   HTTP(S) URL that returns the archive directly. PR checks do not accept local
   files or a `pending` checksum. You can calculate both values locally:

   ```sh
   python3 - <<'PY'
   from pathlib import Path
   import hashlib
   archive = Path('your-app-0.1.0.tar.gz')
   print('sha256:', hashlib.sha256(archive.read_bytes()).hexdigest())
   print('size:', archive.stat().st_size)
   PY
   ```

4. Declare access honestly in `permissions`: `network`, `files`, `device`, and/or
   `microphone`. Socket and other recognized networking imports need `network`,
   including local listeners. Shell access is not allowed: remove subprocess,
   `os.system`, and similar calls. `ctypes`, `eval`, `exec` and dynamic imports
   are flagged too. There is no `shell` permission you can add to bypass this.
   Microphone access is declared by you; the scanner cannot detect it reliably.
5. Set `entry` to a Python module and argument list, or a command string. Commands
   are split into arguments without a shell. Use `null` and the `library` tag if
   there is nothing to launch. A single wrapper directory is fine, as is a Python
   package directly at the archive root. Links, special files, unsafe paths and
   duplicate files are rejected. Downloads are limited to 512 MiB and unpacked
   contents to 2 GiB and 100,000 archive entries.
6. Add a quick offline check if your app supports one. Declare `"selfcheck": true`
   alongside `entry`; CI appends `--selfcheck` to that entry's normal arguments.
   For example, `{"python": "lite", "args": []}` becomes
   `python -m lite --selfcheck`. It must exit 0 within 120 seconds in
   `python:3.11-slim`, without network, a device, or installed third-party
   dependencies. The app directory is read-only; use `/tmp` for temporary writes.
   A missing or false declaration skips this check. A library cannot declare it.
7. Keep `verified` false. Fill in the author, dates, license, requirements and
   release notes. Run the local checks:

   ```sh
   python3 scripts/check-manifest.py manifests/your-app.json
   python3 scripts/scan-archive.py your-app-0.1.0.tar.gz manifests/your-app.json
   python3 -m unittest
   ```

8. Open the pull request. CI checks every added or changed manifest, including
   rename destinations, against trusted validation code from the base branch.
   Deleted manifests need no archive check. It checks identity, downloads and
   hashes the archive, safely unpacks it, lists Python imports, scans all files
   (including hidden files) for secret patterns, and checks declared permissions.
   Only after a clean scan does it run a declared selfcheck offline. Any red result
   fails the job. App output and secret matches are withheld from logs/comments.

The bot maintains one results comment with check, result and detail columns. The
full results are in the checks artifact. If the runner fails before creating the
report, the comment points you to the failed run. Fix the problem and push again.
The comment workflow lives on the default branch; it must be merged there before
it can report on submissions. The validation scripts must also exist on the PR's
base branch. The orchestrator will prove the workflows on a real PR after landing.

Passing a static scan does not prove that code is safe: aliases, generated code,
non-Python behavior and unknown token formats can escape pattern checks. It also
does not enforce permissions when someone installs your app. A maintainer reviews
the source and results, then records `verified: true` in a follow-up commit. CI
never changes that value. Merge publishes the updated catalog after site tests.

Release drafts may use `--allow-pending` for local schema checks only. They cannot
pass submission CI or be installed until the real archive is published.
