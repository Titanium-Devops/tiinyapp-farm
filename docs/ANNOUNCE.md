# TiinyVerse announcement

Draft for Jason, refreshed 2026-09-13 for farm 0.1.3, the documentation site at
https://tiinyapp.farm/docs/, and five apps. Nothing here has been posted anywhere. Read it,
change what sounds wrong, then post it yourself. The long one is the TiinyVerse post. The short
one is for X or anywhere with a character limit.

Three things to check against the live site before you post, because they moved today.

If you do not merge pull request 9, the catalog is four apps and not five. Drop the Tiiny Brain
paragraph, change "Five apps" to "Four apps", and delete the sentence about the fifth one not
being reviewed yet.

The old draft said nothing in the catalog was reviewed. That is no longer true. All four of the
original apps carry `verified: true` and their pages read "Verified", so the post now says the
opposite. If you flip Tiiny Brain to verified before posting, cut that sentence too.

The install example used to be `story-lantern`. It is `titanium-tiiny-bot` now, because Story
Lantern is still listed at 0.1.0 and 0.1.0 is the release we think does not work on Tiiny 1.0
firmware. If you check it on your own Tiiny and it works, or the 0.1.1 bump lands first, put
Story Lantern back. It is the better demo.

## The post

I built a place to put the little apps people are writing for the Tiiny.

Here's what kept bugging me. I'd write something that talks to the device, it'd work, and then
it would sit in a folder on my laptop forever. Somebody in here would ask how to run it and the
honest answer was a zip file and two paragraphs of instructions. That happened enough times that
I went and built the thing I wanted instead.

It's a catalog and one command-line tool. The apps run on your own computer, next to the Tiiny,
and talk to it over its local API. Nothing gets installed into TiinyOS, so there's nothing to
undo if you don't like an app.

Five apps on it today, and all five are mine, which is the part I'd like to change.

Story Lantern writes a bedtime story, paints the page, and reads it out loud in a warm voice.
Characters come back the same across nights, which is the part a five-year-old notices.
TiinyBench measures what your Tiiny does under real work, including
what a reasoning model charges you in wall time for tokens nobody reads. Titanium Tiiny Bot is a
local assistant with chat, files, memories and voice, running on the standard library with no pip
installs. Tiiny Brain reads a folder of your own markdown notes, works out which names keep
turning up together, and answers questions about them with the notes it used, or tells you
plainly that nothing it found covers it. OneLane is a small library rather than an app. It lets
two programs take turns on one device so the second one waits instead of dying with error 150004.

Installing one is three commands.

```
pip install tiinyapp-farm
farm device
farm install titanium-tiiny-bot && farm start titanium-tiiny-bot
```

farm device asks for your base URL and your API key once, saves them where only you can read
them, and hands them to every app you start after that. You never put a key in an app's config.

If something is already sitting on the port an app wants, `farm start <id> --port 7799` moves it,
and the app's page tells you whether that app can be moved at all. That's new in 0.1.3 and it's
the kind of thing I only found by handing this to somebody who hadn't seen it.

There's documentation now too, at https://tiinyapp.farm/docs/. Getting started, every CLI command
and flag, the manifest field by field, what the permission scanner will and won't let you do, the
HTTP API, and a troubleshooting page that's mostly a list of the exact error strings and what to
do about each one. If you're writing an app to run beside a Tiiny, the app authors page is the one
I'd read.

Now the part I actually care about, which is getting your apps on there.

There are three ways in and they all end in the same place. You can do the whole thing on the
website at the submit page, which walks you through signing in, proving you own a Tiiny with a
code in your TiinyVerse bio, and filling in the form. You can do it from the terminal with
`farm login` and `farm publish` from inside your project folder. Or, if you build with an
assistant, point it at the guide I wrote for assistants and let it do the work:

```
Read https://tiinyapp.farm/docs/agents and publish this project to tiinyapp.farm.
My token is: <paste yours from tiinyapp.farm/account/>
```

That last one is a real page written for them, not a blog post about prompting. It has the whole
submission shape in it.

Whichever way you go, a pull request opens. The checks download your archive, check its hash,
unpack it safely, list what it imports, and compare that against the access you said it needs.
Then I read it. Nothing shows up in the catalog until a person merges it.

One thing worth knowing before you submit, because it's the check that catches people. The
scanner won't let an app shell out. If your code imports subprocess anywhere, even in a test or
an example that ships in your tarball, the check goes red. That's deliberate and I'm not going to
loosen it, but the fix is usually small: put the import behind the one function that needs it, or
ship a release asset instead of the whole repo. I hit it on two of my own apps this week, so
you're in good company.

This is early and it looks early in places. The submit flow is new and you'll be among the first
people through it who aren't me. The fifth app on there isn't reviewed yet, including by me, and
its page says so. If something breaks on you, tell me here and I'll fix it rather than explain it.

What I want is your apps. Even the scrappy ones. Especially the scrappy ones.

https://tiinyapp.farm

## The 280-character version

I built tiinyapp.farm, a catalog of small apps that run beside your Tiiny on your own computer.
Five on it today and all five are mine, which is what I want to change.

pip install tiinyapp-farm
farm device
farm install titanium-tiiny-bot

Bring your app. https://tiinyapp.farm

### If Tiiny Brain does not merge

I built tiinyapp.farm, a catalog of small apps that run beside your Tiiny on your own computer.
Four on it today and all four are mine, which is what I want to change.

pip install tiinyapp-farm
farm device
farm install titanium-tiiny-bot

Bring your app. https://tiinyapp.farm
