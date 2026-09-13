# TiinyVerse announcement

Draft for Jason. Nothing here has been posted anywhere. Read it, change what sounds
wrong, then post it yourself. The long one is the TiinyVerse post. The short one is
for X or anywhere with a character limit.

## The post

I built a place to put the little apps people are writing for the Tiiny.

Here's what kept bugging me. I'd write something that talks to the device, it'd work,
and then it would sit in a folder on my laptop forever. Somebody in here would ask how
to run it and the honest answer was a zip file and two paragraphs of instructions. That
happened enough times that I went and built the thing I wanted instead.

It's a catalog and one command-line tool. The apps run on your own computer, next to the
Tiiny, and talk to it over its local API. Nothing gets installed into TiinyOS, so there's
nothing to undo if you don't like an app.

Four apps on it today, and all four are mine, which is the part I'd like to change.

Story Lantern writes a bedtime story, paints the page, and reads it out loud in a warm
voice. Characters come back the same across nights, which is the part a five-year-old
notices. TiinyBench measures what your Tiiny actually does instead of what the spec sheet
says, including what a reasoning model charges you in wall time for tokens nobody reads.
Titanium Tiiny Bot is a local assistant with chat, files, memories and voice, running on
the standard library with no pip installs. OneLane is a small library rather than an app.
It lets two programs take turns on one device so the second one waits instead of dying
with error 150004.

Installing one is three commands.

```
pip install tiinyapp-farm
farm device
farm install story-lantern && farm start story-lantern
```

farm device asks for your base URL and your API key once, saves them where only you can
read them, and hands them to every app you start after that. You never put a key in an
app's config.

Now the part I actually care about, which is getting your apps on there.

There are three ways in and they all end in the same place. You can do the whole thing on
the website at the submit page, which walks you through signing in, proving you own a
Tiiny with a code in your TiinyVerse bio, and filling in the form. You can do it from the
terminal with `farm login` and `farm publish` from inside your project folder. Or, if you
build with an assistant, point it at the guide I wrote for assistants and let it do the
work:

```
Read https://tiinyapp.farm/docs/agents and publish this project to tiinyapp.farm.
My token is: <paste yours from tiinyapp.farm/account/>
```

That last one is a real page written for them, not a blog post about prompting. It has the
whole submission shape in it.

Whichever way you go, a pull request opens. The checks download your archive, check its
hash, unpack it safely, list what it imports, and compare that against the access you said
it needs. Then I read it. Nothing shows up in the catalog until a person merges it.

This is early and it looks early in places. The submit flow is new and you'll be among the
first people through it who aren't me. There are no reviews on anything yet, including my
own four apps. If something breaks on you, tell me here and I'll fix it rather than explain
it.

What I want is your apps. Even the scrappy ones. Especially the scrappy ones.

https://tiinyapp.farm

## The 280-character version

I built tiinyapp.farm, a catalog of small apps that run beside your Tiiny on your own
computer. Four on it today and all four are mine, which is what I want to change.

pip install tiinyapp-farm
farm device
farm install story-lantern

Bring your app. https://tiinyapp.farm
