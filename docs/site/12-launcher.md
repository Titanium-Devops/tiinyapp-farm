---
title: The launcher
slug: launcher
order: 12
summary: Tiiny App Farm, the desktop app that installs and runs farm apps without a terminal.
---

Tiiny App Farm is a small app for macOS and Windows. It installs farm apps, starts them, stops
them and updates them, and it does all of that with buttons rather than commands. It is the same
farm underneath: the same catalog, the same archives, the same checksums and the same folder on
your computer.

You do not need Python, Node, Docker or a package manager to use it. The app carries its own Python
inside itself and uses it to run the apps you install.

## One download

There is one file for each platform.

- **macOS.** A disk image. Open it and drag Tiiny App Farm to your Applications folder. It is
  signed and notarised by Apple, so it opens without an argument. There are two builds: the one
  the download button offers is for Apple silicon, and an Intel Mac takes the Intel one.
- **Windows.** An installer for the x64 build. It installs for your user account only, so Windows
  never asks for an administrator password. Windows on ARM is not built yet.
- **Linux.** An AppImage for x86_64, carrying the same bundled Python and the same engine as the
  other two. Make it executable and run it; there is nothing to install first. Two things are
  worth knowing before you do. It is not signed, because Linux has no notarisation and nothing a
  stranger's machine would check a desktop signature against, so the SHA-256 published with every
  release is what you can verify instead. And it has been built but not yet run on a Linux desktop
  by anybody here, so the tray, the deep link and the window are untested there. The command line
  remains the better-worn path on Linux: see [Getting started](/docs/getting-started/).

Every download comes from this site, at `tiinyapp.farm/launcher/`. The app checks the same place
for its own updates and installs them quietly when you next open it. That updater covers macOS
only for now; a newer Windows or Linux build means downloading it from
[Launcher versions](/launcher/versions/).

## Going back to an older version

[Launcher versions](/launcher/versions/) lists every version that has shipped, newest first, with
what changed in it and a link to each file. Every build stays where it was published, so a version
that worked for you is always still there.

Two things are worth knowing before you take one. The newest version is the one the app updates
itself to, so an older build you install stops being offered updates and is offered none of the
fixes in the versions above it. And every file on that page carries its size, its SHA-256 and
whether it is signed, so you can check what you downloaded is what the page describes.

## The first time you open it

Four things happen once, and then never again.

1. **It looks for your Tiiny.** It tries `http://openai.api.tiiny/v1` first, which is the address
   the TiinyOS client publishes on a Mac. If that does not answer, there is a box for
   `http://<your-tiiny-ip>/v1`.
2. **You paste your key.** TiinyOS, then Settings, then API Key. The app writes it to
   `~/.tiinyapps/device.json` with the file readable only by you, which is the same file
   `farm device` writes and the same permissions.
3. **You pick an app.** The grid is the live catalog from this site, icon first, with the same
   Reviewed and New marks the catalog pages show. Opening one shows what it needs and what access
   it asks for before anything is downloaded.
4. **It installs and starts it.** You see the download, the checksum and the unpack, and then a
   button that opens the app in your browser. An archive whose checksum does not match is never
   unpacked, exactly as on the command line.

After that there is a menu bar icon on macOS and a tray icon on Windows, listing what is running
with Open, Stop and Update beside each one. Closing the window does not stop your apps.

## It is the same farm as the command line

This matters more than it sounds. The app is a face on the `farm` command, not a second way of
doing things.

| Thing | Where it is |
| --- | --- |
| Installed apps | `~/tiinyapps/<id>/` |
| Your device settings | `~/.tiinyapps/device.json`, mode 0600 |
| An app's log | `~/tiinyapps/<id>/farm.log` |
| The catalog | `https://tiinyapp.farm/manifests/` |

So you can start with the app and move to the command line later, or the other way round. Install
the CLI with `pip install tiinyapp-farm`, run `farm list`, and everything the app installed is
already there, running or stopped, with its version and its port. Nothing is converted and nothing
is copied.

The reverse is just as true. If you have been using the command line for months, opening the app
shows you what you already have.

## What it never does

Being clear about this early saves a support message later.

- **It does not sandbox anything.** An app declares the access it uses, the card shows you that
  before you install, and the app then runs with your own permissions. That is the same promise
  the command line makes, and it is not a stronger one.
- **It does not install Docker, MySQL or Postgres.** A farm app is a program and a folder. If
  something needs a database that is a server, a system service or an administrator prompt, it is
  not a farm app.
- **It does not need a compiler.** Nothing is built on your machine.
- **It does not ask you to sign in.** Browsing and installing need no account. Publishing an app
  still happens through the site or `farm publish`, where your token already lives.

An app that needs more than the app can honestly give is refused at submission rather than left to
fail on somebody's laptop.

## When the operating system gets in the way

**macOS says the app cannot be opened.** The disk image is signed with a Developer ID certificate
and notarised, so this should not happen. If it does, you most likely have a copy that did not come
from `tiinyapp.farm/launcher/`. Delete it and download it again from
[the install page](/install/).

**Windows shows a blue "Windows protected your PC" panel.** Press More info, then Run anyway. The
installer is signed, but SmartScreen also weighs how many people have downloaded a given publisher
before, and a new one has no history yet. That history builds on its own over the first weeks.
Check that the publisher named on the panel is Titanium Computing before you continue.

**Your Tiiny is not found.** The app and the device have to be on the same network, and the Tiiny
has to be switched on. Try `http://<your-tiiny-ip>/v1` in the manual box. Everything in
[Troubleshooting](/docs/troubleshooting/) about reaching a device applies here too, because it is
the same code doing the reaching.
