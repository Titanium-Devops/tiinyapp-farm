# Submit an app from the site

Visit https://tiinyapp.farm/submit/ to submit without a GitHub account:

1. Sign in with an email code or GitHub. While signed in, use the other method to link it to the same account. Neither method replaces TiinyVerse proof.
2. Paste your public TiinyVerse `/users/<uuid>` profile URL. Put the issued code in your bio and press Verify within 24 hours. One profile can belong to one account.
3. Complete the app form, including the access it uses and runtime needs. Choose “Not yet, list it as No release yet” if there is no archive; otherwise include a version. Supply either a direct HTTPS tar.gz release URL (up to three HTTPS redirects) or a tar.gz upload up to 50 MiB. Include source and license in the archive. For a library, leave the start command empty and include the `library` tag.
4. The farm measures and hashes the archive, creates a review PR with its own account, and shows check results and review state at Your apps (`/account/`). A maintainer decides whether to merge. The site rebuilds after merge.

The optional source repository is useful for review; it is not a sign-in requirement. The maker name is taken from your verified TiinyVerse profile. The archive and its source become public. Uploads must finish within 30 seconds; direct release fetches have a 10-second deadline.

For hand-made pull requests, verify your profile on the farm first, set `author.tiinyverse` to that exact profile URL and `author.name` to the farm's verified display name. CI queries the farm owner endpoint and refuses unverified or mismatched owners. Existing catalog drafts without owner proof remain readable, but any changed submission must pass the owner gate. Leave `verified` false for maintainer review.

Use Your apps to update an existing app that you own, or submit a pull request using the same owner verification. An interrupted PR creation is shown as `submission uncertain`; a maintainer reconciles the saved branch before you retry, preserving the uploaded archive.

---

## Submit by hand with git

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
   Say how your app takes a port with the optional `port` field beside `entry`. Use
   `{"argv": "--port"}` when the port follows a flag, and the farm puts the number after
   that flag, replacing one that is already there. Use `{"env": "PORT"}` when your app
   reads it from the environment. Use `null` when the port is fixed, and
   `farm start <id> --port N` refuses in one line instead of starting the app somewhere
   you did not ask for. Leave the field out and the farm sets `TIINYAPP_PORT`, which is
   what it has always done, so read that variable if you want `--port` to work without
   declaring anything. `TIINYAPP_PORT` is set either way. The submit form does not ask
   for this field yet; set it in a hand-made pull request.

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
   Deleted manifests need no archive check. It checks identity and verified TiinyVerse ownership, downloads and
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
