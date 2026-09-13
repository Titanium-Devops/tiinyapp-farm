# The Tiiny App Farm Launcher

Status: design, 2026-09-13. Owner Jason Brashear. Nothing here is built. Every number below names
where it was measured or read, and estimates are labelled as estimates.

## What it is

The launcher is a small signed desktop app for macOS and Windows that installs and runs farm apps for
a person who will never open a terminal. It carries its own Python runtime and `farm/farm.py` inside
itself and uses them as its engine, so there is nothing to install first: no Python, no Node, no
Docker, no package manager. You download one file, open it, it finds your Tiiny on the network, you
paste your key once, you pick an app from the same catalog the site shows, and thirty seconds later
the app is running on your own computer with a menu bar or tray icon that says so. It is a face on
the command-line tool that already exists, not a second way of doing things: same install directory,
same device settings file, same lock, same logs. Somebody who starts with the launcher and later
learns the CLI finds their apps exactly where the CLI expects them.

## Who it is for

The person who bought a Tiiny AI Pocket Lab because it was interesting, runs macOS or Windows, and
would not get past step one of the current `/install/` page. That page opens with `pip install
tiinyapp-farm` and a note about what to do when pip answers "externally managed environment"
(`scripts/build-site.py`, the install page body). That note is correct and it is also the moment a
consumer closes the tab. Linux users are not the target: they already have the CLI and they are the
people least likely to need this.

Second audience, smaller but real: the maker who wants somebody non-technical to try their app. Today
the answer is a paragraph of terminal instructions. With the launcher it is a link.

## The first run, screen by screen

1. **Download.** `tiinyapp.farm/install/` shows one big button that already knows the platform:
   "Download for Mac" or "Download for Windows", the other one underneath as a small link.
2. **Open it.** macOS: drag to Applications from a notarised and stapled disk image, no Gatekeeper
   argument. Windows: an NSIS installer that installs for the current user with no administrator
   prompt (`installMode: "currentUser"`, already set in the Titanium Bot desktop config).
3. **Find your Tiiny.** The launcher probes `http://openai.api.tiiny/v1` first, which is what the
   TiinyOS client publishes on a Mac, then offers a manual box for `http://<your-tiiny-ip>/v1`. Both
   forms are the ones the install page documents today.
4. **Paste the key once.** TiinyOS, Settings, API Key. The launcher writes it through the same code
   path as `farm device`: `~/.tiinyapps/device.json` at mode 0600, never echoed, never in a command
   line. Every app then receives `TIINY_BASE`, `TIINY_KEY` and `TIINY_HOST` from the launcher exactly
   as the CLI sets them (`Farm.environment`).
5. **Pick an app.** A grid of the live catalog, read from `https://tiinyapp.farm/manifests/`. Each
   card is icon, name, one-line pitch, and a badge for Reviewed, New, Library or No release yet, the
   same four the site computes. Opening a card shows what it needs and what access it asks for before
   anything is downloaded, which is the prompt the CLI prints today.
6. **Plant it.** One button. Progress for the three real steps: download, checksum, unpack. Failures
   are sentences, not stack traces. The checksum is the CLI's, byte for byte, and an archive whose
   checksum differs is never unpacked.
7. **It runs.** The launcher starts the app and waits for it to be ready, up to the CLI's ten second
   ceiling (`START_TIMEOUT = 10.0`), preferring the manifest's `health` path when it has one. Then an
   Open button that opens `http://127.0.0.1:<port>` in the person's browser.
8. **The tray.** A menu bar icon on Mac, a tray icon on Windows, listing what is running with Open,
   Stop and Update beside each, and Quit at the bottom. Closing the window does not stop the apps.
   Stopping is the CLI's stop: SIGINT to the process group, SIGKILL after five seconds.

Nothing in that list asks the person to understand a port, a virtual environment or a checksum, and
nothing in it is new behaviour. Steps 4 through 8 are `farm device`, `farm install`, `farm start`,
`farm status`, `farm stop` and `farm update` with a window in front of them.

## Three shapes, and which one to build

### A. A Tauri shell with a bundled Python runtime and farm.py as its engine

A Rust and web-view app, the same stack as the Titanium Bot desktop app, carrying a standalone CPython
tree and `farm.py` as bundled files. The shell draws the catalog and the tray; every action shells out
to the bundled interpreter running the bundled `farm.py`. One behaviour, two faces.

The reuse is not theoretical. `Titanium-Devops/titanium-bot-desktop` is Tauri 2 with the tray icon,
notifications, the updater, single instance, autostart, the OS credential store, macOS hardened
runtime with an entitlements file, and Windows NSIS in current-user mode. Its two workflows,
`.github/workflows/macos.yml` and `windows.yml`, already sign, notarise, staple and then verify the
result before they will upload it. Copying those two files is most of the release engineering for this
app.

There is one sharp edge and it is worth knowing before the first line of code. The Tauri bundler signs
frameworks and sidecar binaries inside out before it signs the app, per Apple's rule, and only those
(`crates/tauri-bundler/src/bundle/macos/app.rs`, read through Context7 on 2026-09-13). Files dropped
into the bundle as resources are not in that list, so a Python tree copied in as a resource arrives at
the notary unsigned and is refused. The good news is how small that job turns out to be: a whole
CPython 3.11.13 install for macOS arm64 contains **four** Mach-O files out of 2,762 files in total
(the interpreter, `libpython3.11.dylib`, and two small extension modules), measured on this Mac on
2026-09-13 against the copy in the local uv store. Four `codesign` calls in the workflow, before the
app is signed, and the tree is legal.

### B. An Electron shell, same engine

Identical idea, a browser instead of a web view. The catalog UI could share code with the site, which
is the honest argument for it, and more people can write it. It costs four to five times the download
and throws away the signing pipeline: Electron's notarisation runs through electron-builder, not
through the Tauri workflows Jason already has green.

### C. A native pair: SwiftUI on macOS, WinUI 3 on Windows

The best first-run feel and the smallest Mac download. It is also two applications, two languages, two
UI codebases and two sets of bugs, and the Windows half is the one with the least existing work behind
it. For a launcher whose entire job is a grid, a progress bar and a tray menu, that is a large bill for
a small gain.

### The sizes, measured

| What | macOS | Windows | Source |
| --- | --- | --- | --- |
| Tauri app bundle, no Python | 7.8 MB | not measured | `du -sh "~/Applications/Titanium Bot.app"` on this Mac, 2026-09-13 |
| CPython 3.11.16 standalone, as published | 27.1 MB (arm64) | 47.9 MB (x64) | astral-sh/python-build-standalone release 20260901, asset sizes from the GitHub API, 2026-09-13 |
| CPython 3.11.13, pruned and recompressed here | 16.1 MB | not measured | this Mac, 2026-09-13: 62 MB unpacked becomes 44 MB and 1,650 files after dropping tcl, tk, idlelib, tkinter, headers and caches |
| Electron runtime alone | 129.8 MB | 158.1 MB | electron/electron v44.3.0 release assets, GitHub API, 2026-09-13 |
| Node 22, if the catalog ever needs it | 50.1 MB | 35.7 MB | nodejs.org/dist v22.23.2 content-length, 2026-09-13 |

**Projection, not a measurement:** a Tauri launcher carrying a pruned Python should land near 25 MB on
macOS and near 60 MB on Windows, the Windows figure being larger because the published Windows runtime
is 77 percent heavier than the macOS one before pruning. The same app built on Electron starts at
roughly 130 MB and 160 MB before anything of ours is added. Phase 0 of the plan below replaces both
projections with real installer sizes in the first two days.

### Recommendation

**Build shape A: Tauri, bundled Python, farm.py as the engine.**

Three reasons, in order. The release pipeline exists and is proven green on both platforms, so the
work is a UI and not a distribution project. The download stays in the range where a consumer does not
think twice, and the difference against Electron is 100 MB of somebody's hotel wifi. And the engine
being the exact `farm.py` the CLI ships means there is one install format, one device file, one lock,
one set of failure messages to support, forever.

Keep shape B on the shelf for exactly one contingency: if bundling a runtime inside a notarised app
turns out to be worse than the four `codesign` calls above suggest, the fallback is not Electron, it is
to fetch the runtime on first run (see the decisions section). Shape C is declined on cost.

## Signing, notarisation and what Jason has to buy

**Nothing new.** Both certificates are already paid for and already wired into GitHub Actions.

**macOS.** Distribution outside the App Store needs a Developer ID Application certificate,
notarisation, and a stapled ticket. The Apple Developer Program is 99 USD a year (developer.apple.com
enrollment page, read 2026-09-13) and Jason's membership is current: team `F2DH8T4BVH`, with a
Developer ID Application certificate recorded in the signing notes as valid to 2027-02-01. The
`macos.yml` workflow imports the certificate into a throwaway keychain, builds a universal binary,
notarises through either the App Store Connect API key or an app-specific password, and then staples
the disk image itself, which the bundler does not do on its own. It also refuses to upload anything
that `spctl` and `stapler validate` do not accept. Copy it as it stands and add the runtime signing
step described above.

**Windows.** Azure Artifact Signing, formerly Trusted Signing, is 9.99 USD a month on the Basic plan
for up to 5,000 signatures (azure.microsoft.com pricing, read 2026-09-13). Jason's account is live:
the `windows.yml` workflow signs through `azure/trusted-signing-action@v0` against the signing account
`Titanium` and the certificate profile `titanium-public`, authenticating with a GitHub OIDC federated
credential scoped to `refs/heads/main` and no client secret anywhere. It then fails the run unless
Windows itself reports the Authenticode signature Valid. No EV token, no USB dongle, no hardware.

One honest caveat for the launch email: a correctly signed installer from a publisher with no download
history can still show the SmartScreen "More info" panel until reputation accumulates. That is a
function of downloads over time and no certificate purchase removes it.

**Two details in those workflows that were learned the hard way and must survive the copy.** The
bundle output directory is cleaned before every build, because the cargo cache otherwise carries an
older installer into the artifact and into the signing step. And the build fails on its own if the
updater private key does not match the public key in the config, because that mismatch is only a
warning from the CLI, which means a green build whose every update is silently refused by every
installed app.

## Auto update

The Tauri updater plugin, the same one the desktop app uses: a signed tarball plus a JSON feed at a
fixed URL, signature verified by minisign before anything is applied, Windows installing in passive
mode. The feed goes at `https://tiinyapp.farm/launcher/latest.json` and the artifacts beside it, served
by the Worker that already serves the site (`wrangler.toml` names the account, the KV namespace and the
R2 bucket `farm-seeds`). The macOS workflow already writes that feed from the signature file rather
than from anything retyped.

Two update tracks, kept apart in the UI because they are different questions. The launcher updates
itself, quietly, on a restart. The apps update through `farm update <id>`, which installs only a newer
version and keeps the data directory, and the launcher shows an Update badge when the catalog's
version differs from the installed one. `farm status` already computes that comparison, including the
case where the running app reports a different version than the one on disk.

## What an app declares, and what the launcher can honestly provide

The manifest already carries the answer. `requires` holds an optional minimum `python`, the `ports` the
app listens on, and the `device` block with model names and NPU units. `entry` is either a Python
module with arguments or a command string.

The bundled runtime works for every app in the catalog today without touching a single manifest,
because of one line in `Farm.start`: a command whose first word is `python` or `python3` is rewritten
to the interpreter farm.py is itself running under. Under the launcher that interpreter is the bundled
one. Story Lantern's `python3 lantern.py` and Tiiny Bench's `python3 tiiny-bench --serve` therefore run
on the launcher's Python with no change, and Titanium Tiiny Bot's `{"python": "lite"}` form was already
going to. The floor to bundle is 3.11, because that is what Titanium Tiiny Bot's manifest requires;
the other three ask for 3.9.

**What the launcher provides for free.**

- Its own CPython 3.11 or newer, which is what `requires.python` is measured against.
- A writable data directory per app, handed over as `FARM_DATA_DIR` and `TIINY_DATA_DIR`.
- SQLite, because `sqlite3` is in the Python standard library and a database is a file in that data
  directory. There is nothing to install and no server to run.
- The device base URL and key, the derived host, and the shared OneLane lock directory, so two apps
  take turns on one Tiiny instead of colliding.
- A port check before start and a working `--port` override when something else already holds one.

**What the launcher will never provide.** Docker. MySQL, Postgres or any database that is a server.
Anything that needs an installer, an administrator prompt, a system service or a kernel extension. A
compiler toolchain. If an app needs those, it is not a farm app, and the right place to say so is the
submission check rather than a support email six months later.

**A second runtime, if and only if a real app needs one.** Node is the only plausible candidate. The
proposal is to add `requires.runtime` as an enum defaulting to `python`, and to fetch the Node build on
demand into the launcher's own directory rather than ship 35 to 50 MB of it to everybody who never
uses it. Do not add the field before the first app that needs it exists.

**What the launcher does not do, stated plainly in the UI.** It does not sandbox anything. Permissions
in a manifest are declared by the author and shown to the person before installing; they are not
enforced at runtime, which is what the CLI's own documentation says today. The launcher shows them on
the card and in the install confirmation, and claims nothing more.

## What changes for makers

Almost nothing, and that is deliberate. Same tar or tar.gz archive, same SHA-256 and exact byte size in
the manifest, same 512 MiB download ceiling and 2 GiB unpacked ceiling and 100,000 entry limit, same
refusal of symlinks, special files, traversal paths and duplicate entries, same static scan, same
offline selfcheck, same 50 MB cap on a `farm publish` upload. There is no launcher-specific package
format and there never should be, because the moment there are two, an app works in one place and not
the other.

Three small things do change, and all three are presentation:

1. **An icon stops being optional in practice.** The launcher's grid is icon first. Three of the four
   manifests today carry `media.icon`; the submission flow should generate or require one rather than
   let a card ship blank.
2. **A `health` path becomes strongly recommended.** Without it the launcher can only say "started"
   after the liveness check. With it the launcher can say "ready" and can tell the person when the
   running version no longer matches the installed one.
3. **`requires` grows a runtime field only when a non-Python app appears**, as above.

Nothing in the review pipeline changes. A maker who never hears about the launcher keeps publishing the
way they publish now, and their app appears in it.

## What the site shows a consumer who has no CLI

**On `/install/`:** the download button becomes the top of the page, with the platform detected in a
few lines of JavaScript and the other platform offered underneath. The three existing steps stay, moved
below a heading along the lines of "Prefer the command line?". Nobody loses anything; the default path
stops being the developer one.

**On every app page:** beside the existing copyable `farm install <id>` block, a primary button that
opens the app in the launcher through a `tiinyfarm://install/<id>` deep link, with the current install
instructions as the fallback when nothing on the machine handles the scheme. The Tauri deep link plugin
is already in use in the desktop app with two registered schemes, so this is configuration rather than
new code.

**On the home page:** the hero's second button changes from "Install an app" to "Get the launcher".

All of it is static site work in `scripts/build-site.py`. No manifest changes, no Worker changes except
serving the download and the update feed.

## The build, two weeks, and what each phase proves

| Phase | Days | What it proves |
| --- | --- | --- |
| 0. The riskiest thing first | 1 to 2 | A Mac app containing a CPython tree signs, notarises, staples, and passes `spctl` and `stapler validate`, and its bundled interpreter runs `farm.py --version` from inside the bundle. A Windows NSIS build installs with no administrator prompt and reports an Authenticode signature of Valid. Real installer sizes replace the projections above. If this fails, the fallback decision below is taken on day 2, not on day 12. |
| 1. The engine | 3 to 4 | The shell drives install, start, stop, status, list, update and remove through the bundled CLI and gets structured results back, with progress during a download. Proves one behaviour rather than two. |
| 2. First run | 5 to 7 | Find the Tiiny, save the key once at 0600, read the live catalog, install an app with progress, start it with the health wait, open it. A person who has never seen a terminal reaches a running Story Lantern. |
| 3. The tray | 8 to 9 | What is running, Open, Stop, Update, Quit. Closing the window leaves apps running. Single instance, autostart off by default. |
| 4. Failure, in words | 10 to 11 | Port already in use offers another port. A checksum mismatch says so and installs nothing. A crashed app shows the last lines of `farm.log` in a pane rather than a dead icon. Proves the launcher is usable on a bad day, which is the only day support hears about. |
| 5. The site and the feed | 12 | Download buttons, the per-app deep link, the artifacts and `latest.json` served from the farm's own Worker, and a launcher updating itself from one version to the next. |
| 6. The beta | 13 to 14 | Five people who are not developers, on real Tiinys, on both platforms. The number that matters is minutes from download to a running app, and how many of them needed a human. |

The plan front-loads the only part that can fail in a way that changes the design. Everything from
phase 2 onward is a known quantity: a grid, a progress bar, a tray menu and a wrapper around a CLI that
already works.

## Decisions for Jason

1. **Shape: Tauri, Electron, or a native pair.** Tauri reuses the signed pipeline and ships near 25 MB
   on Mac. Electron costs roughly 130 MB before our code and a new notarisation path. The native pair
   is two codebases for one grid.
   **Recommended: Tauri.**

2. **Bundle the Python runtime, or fetch it on first run.** Bundling means one download and no network
   step, and puts four Mach-O files through the signing workflow. Fetching saves 16 to 48 MB in the
   installer and sidesteps the runtime signing question entirely, because a separately downloaded
   interpreter is a separate process and not part of our signature, at the cost of a first-run download
   and a checksum to verify.
   **Recommended: bundle, with fetch held as the phase 0 fallback.**

3. **How the shell talks to the engine.** Add a `--json` output mode to `farm.py` and run it as a child
   process, or import the `Farm` class in-process through an embedded interpreter. The child process
   with structured output is simpler, keeps the CLI honest, and makes the CLI better for AI agents at
   the same time. In-process is faster and couples the two together.
   **Recommended: `--json` on the CLI, roughly two days of the phase 1 budget.**

4. **Does the launcher also put `farm` on the PATH?** Automatic means a consumer's shell gains a command
   they did not ask for. Never means a developer who starts with the launcher has to install it twice.
   **Recommended: a one-click toggle in Settings, off by default.**

5. **Updater keypair.** A new minisign keypair for the launcher, or reuse the desktop app's. Separate
   keys mean a compromise or a loss touches one product. A lost key strands every installed copy of
   whatever it signed.
   **Recommended: a new keypair, generated and stored in Bitwarden before phase 5.**

6. **Where the downloads and the feed live.** The farm's existing Cloudflare Worker and R2 bucket, or
   GitHub Releases. The Worker keeps one domain and one set of analytics and is already deployed.
   GitHub Releases is free bandwidth and a public download count.
   **Recommended: the Worker, with the artifacts in R2.**

7. **Windows architectures.** x64 only, or x64 and arm64. Every architecture is another signed artifact
   and another build leg. Windows on ARM is a small but growing share of new consumer laptops.
   **Recommended: x64 at launch, arm64 when somebody asks.**

8. **Name, bundle identifier and deep link scheme.** These are decided once and are painful to change,
   because the identifier is what the OS uses to recognise an installed app across updates. Suggestion:
   the product name "Tiiny App Farm", the identifier `farm.tiinyapp.launcher`, the scheme `tiinyfarm`.
   **Recommended: as suggested, unless the name is wrong.**

9. **Linux.** Ship an AppImage too, or say no. The consumer premise is Mac and Windows, and Linux users
   already have a working `pip install`.
   **Recommended: no, and say so on the download page rather than leaving people guessing.**

10. **Does the launcher sign in to a farm account?** Browsing and installing need no account today; only
    publishing does. Adding sign-in means the account flows, the token store and a support surface, for
    a person who wants to run an app.
    **Recommended: no sign-in in version 1. Publishing stays in the CLI, where the token already lives.**

## What this costs

No new subscription. The Apple membership at 99 USD a year and the Azure signing plan at 9.99 USD a
month are both paid and both already automated, the Cloudflare Worker and the R2 bucket already exist,
and the runtime is free and redistributable. The cost of the launcher is two weeks of building it and
the ongoing cost of one more release artifact to sign per version.

---

*A shareable one-page version of this document is `docs/LAUNCHER.html`, self-contained with no
external requests. Measured on this Mac on 2026-09-13: headless Chromium at 1440x900 renders it 1440
by 19,762 px with 300 px side gutters, and WebKit at 390x844 renders it 390 by 28,365 px with 20 px
side gutters. Neither run scrolls horizontally, and the two tables scroll inside their own
containers.*
