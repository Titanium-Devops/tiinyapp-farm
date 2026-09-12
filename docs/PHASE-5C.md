# Phase 5c: sprouting seeds, and makers tend their own plots

Jason hit this on the live form: "I had everything filled in and it wouldn't let me submit it. You have to
actually have a release tar file for this to work. Is that a requirement?" It should not be, for a first
listing. And once a seed exists, its maker must be able to update it from the site, not by hand PR.

Build on the tree as it stands (phase 5b landed; redirects on release URLs are followed now). Tests green
at the end. No framework, no dependency.

## Sprouting seeds
- The form on /seeds/ tab 03 accepts a seed with **no release** (no upload, no release URL). The manifest
  then carries no `release` block (schema: `release` becomes optional; the Python checker and the JS
  validator agree). Everything else stays required as now.
- The catalog shows such a seed as **Sprouting** (a small chip on the plot card and the seed page, muted
  hay), with its pitch, images, links, maker and comments, but no install command, no checksum, no
  Release section; instead one line: "No release yet. Follow the maker for the first planting." The
  farmhand installer (farm/farm.py) refuses to install a seed without a release with a one-sentence
  message and lists it with a "sprouting" state in `farm list`.
- The share card for a sprouting seed adds the word Sprouting under the pitch.
- CI (scripts/check-submission.py, manifest-check.yml) skips the archive download and scan when there is
  no release, and still runs the owner gate and schema.

## Makers tend their own plots
- `PUT /api/seeds/<id>`: signed in, verified, and the caller is the seed's owner (`seedowner:<id>`, or
  the manifest's `author.tiinyverse` matches the caller's verified profile for the four hand-added
  seeds). Accepts the same form as creation; the version must be strictly greater than the current one
  when a release is supplied (semver compare), may stay the same when only text, images or links change.
  Opens a PR on the same branch scheme with a manifest that replaces the old one; same label, same
  status tracking on /farm/.
- On /farm/, each of the maker's seeds gets an **Update** button that opens tab 03 on /seeds/ prefilled
  from the current manifest (fetch /manifests/<id>.json), with the ID locked, and submits through PUT.
  A sprouting seed's update form says "Add your first release" above the release fields.
- The seed page shows an **Update this seed** link to its owner only (client-side, after /api/me).

## Verify
`python3 -m unittest`, `node --test tests/worker.test.mjs`, `python3 scripts/build-site.py`,
`python3 scripts/check-manifest.py manifests/*.json`. Add tests for: a sprouting submission (201, no
release in the manifest), the installer refusing a sprouting seed, an owner update (201) and a
non-owner update (403). Write docs/PHASE-5C-REPORT.md (short). Never launch a browser, wrangler, docker
or any GUI. Do not commit.
