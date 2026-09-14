# LOCALNET-2: the farm fixes the blocked Python, and farm doctor says what is wrong

Jason, 2026-09-14 06:21: "How is an end user going to know that's an issue when they install it?
They may not have you sitting there to fix it."

So the farm no longer waits to be told. Before it launches an app, when a Tiiny is on file, it asks
the device for its page from the Python that app would run under. If macOS refuses that Python the
local network, the farm tries the other Pythons on this machine and runs the app with the first one
that reaches the Tiiny, saving that choice for this machine. `farm doctor` checks everything else a
person would otherwise have to ask somebody about.

Both runs below are the real command, built as a wheel and installed with `pip install --no-index`
into a fresh virtual environment, with `HOME` redirected to a scratch directory so nothing in
`~/tiinyapps` was touched. The device key went in by shell redirection from the file on this Mac and
was never printed, by the farm or by anything else. Measured on macOS 26.6.2 arm64 on 2026-09-14,
against Jason's Tiiny at 172.17.7.177. The paths below are abbreviated to SCRATCH; nothing else is
edited.

## Everything working

```
# Homebrew Python 3.14.6, a scratch HOME, the live Tiiny at 172.17.7.177

$ farm doctor
farm 0.1.7, running apps with SCRATCH/v3-brew/bin/python3.14 (Python 3.14.6).
The Tiiny on file is at http://172.17.7.177/v1.
Your Tiiny at 172.17.7.177 answered this Python in 15 ms.
The key on file is accepted by your Tiiny.
Other Pythons here: /usr/bin/python3 reaches it, /opt/homebrew/bin/python3.12 does not and /opt/homebrew/bin/python3.13 does not.
onelane is a library, so it has no port and nothing to start.
titanium-tiiny-bot declares port 7788, and it is free.
Your Tiiny lists 4 models: Qwen/Qwen3-8B, Qwen/Qwen3-Embedding-0.6B, Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice and Tongyi-MAI/Z-Image-Turbo.
Everything the farm checks is working.
exit 0
```

The two ports that are not free on this machine belong to Jason's own running copies of tiiny-bench
and ainode-pocket, which is why the transcript installs titanium-tiiny-bot, whose 7788 was free.

## The Python macOS will not let near the Tiiny

```
# miniconda Python 3.13.2, a scratch HOME, the same Tiiny, minutes later

$ farm device --base http://172.17.7.177/v1 --key-stdin < key-file
Device settings saved.
No app you have installed uses your Tiiny yet. Run: farm list to see what the catalog has.
This Python cannot reach your Tiiny, so the farm will run apps with /opt/homebrew/bin/python3 instead.
exit 0

$ farm doctor    (with the choice the farm just saved put aside, the way a new install starts)
farm 0.1.7, running apps with SCRATCH/v3-conda/bin/python (Python 3.13.2).
The Tiiny on file is at http://172.17.7.177/v1.
This Python cannot reach your Tiiny at 172.17.7.177, because macOS is blocking it from your local network.
Other Pythons here: /opt/homebrew/bin/python3 reaches it, /usr/bin/python3 reaches it, /opt/homebrew/bin/python3.12 does not and /opt/homebrew/bin/python3.13 does not.
Fix: the farm can run apps with /opt/homebrew/bin/python3, which does reach it. Take it with: farm start <id> --python /opt/homebrew/bin/python3
No apps are installed yet. Run: farm list to see what the catalog has.
Something above needs attention, and each Fix line says what to do.
exit 1

$ farm doctor    (with the Python the farm settled on)
farm 0.1.7, running apps with /opt/homebrew/bin/python3.
The Tiiny on file is at http://172.17.7.177/v1.
Your Tiiny at 172.17.7.177 answered this Python in 60 ms.
The key on file is accepted by your Tiiny.
Other Pythons here: /usr/bin/python3 reaches it, /opt/homebrew/bin/python3.12 does not and /opt/homebrew/bin/python3.13 does not.
No apps are installed yet. Run: farm list to see what the catalog has.
Your Tiiny lists 4 models: Qwen/Qwen3-8B, Qwen/Qwen3-Embedding-0.6B, Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice and Tongyi-MAI/Z-Image-Turbo.
Everything the farm checks is working.
exit 0

$ farm start ainode-pocket --port 7894
AINode Pocket is running.
Open http://localhost:7894
One endpoint and one page for every Tiiny you own.
Stop it with: farm stop ainode-pocket
Log: SCRATCH/h3-conda/tiinyapps/ainode-pocket/farm.log
exit 0
```

Three things in that run are worth reading twice. `farm device` healed by itself and said so in one
sentence. `farm doctor` on an install that has not healed yet names the exact Python that does reach
the Tiiny and the command that takes it. And the last start ran an app under miniconda's farm with
the Homebrew Python, which is the thing Jason had to do by hand this morning.

Note that /opt/homebrew/bin/python3.12 and python3.13 cannot reach the Tiiny either, on the same
machine, in the same second as the 3.14 that can. macOS grants the local network to one binary at a
time, and two Homebrew Pythons are two binaries.

## What the live run caught that the tests had not

The first live doctor run found two real defects, both now fixed and both now covered:

- The key check ran in the CLI's own Python. On a healed install, that Python is the blocked one, so
  doctor called a perfectly good key bad. The key is now asked for by the interpreter that reaches
  the device, travelling on that child's stdin so it never appears in a command line.
- A refused key was answered with "the farm can run apps with another Python", which would not have
  helped. That advice now appears only when the local network is the thing that failed.

## Tests

273 pass, 2 skipped, up from 270 on main, on macOS 26.6.2 arm64 with Python 3.14.6. The new ones
mock the probes and the interpreter list: the swap and the saved choice, the saved choice being used
again without searching, `--python` overriding and being kept, a Python that is not there, one too
old to take, a Tiiny that is merely switched off never moving anything, the candidate list and its
deduplication, doctor passing, doctor blocked, a refused key that never prints and never suggests a
Python, who is holding a port, no Tiiny on file, the exit codes, and both probe scripts run for real.
