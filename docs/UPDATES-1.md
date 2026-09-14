# UPDATES-1: the farm tells you what has a newer version, and updates what you pick

Jason, 2026-09-14 05:29 CDT: "the farm also needs a way to check whether any of the applications
have been updated and to update any applications the farm has installed. You get to choose:
'Would you like to update AI Node?' Yes, and then it pulls in the updates. 'Check updates' would
come back with a list of all the apps that have been updated, and then maybe show you a list:
1, 2, 3, 4, 5, 6, 7. Select the one you want to update. I press 7 and it updates that app."

Today `farm update <id>` exists and updates one app when the catalog is newer, keeping its data.
There is no way to ask "what is newer?" across everything installed, and no choice.

## What changes, in farm/farm.py, standard library only

1. `farm update` with no id checks every installed app against the live catalog and prints a
   numbered list of the ones with a newer version, each as `1. AINode Pocket 0.1.0, 0.1.1 is
   out` with the release's one-line note if the catalog carries one (the manifest `updatedAt`
   and version are enough when it does not). Then one prompt: `Update which? A number, "all",
   or Enter to leave them.` A number updates that one, `all` updates each in order, Enter
   leaves. With nothing newer it says so in one line. With no tty (a script), it prints the
   list and leaves; `--all` or `-y` updates everything newer without asking.
2. `farm update <id>` asks first: `AINode Pocket 0.1.0 is installed and 0.1.1 is out. Update
   it? [Y/n]`, then does it, in the install voice from CLI-VOICE-1 (looking up, downloading
   with size, checksum, unpacking, data kept, ready). `-y` skips the question. Already current
   says so in one line. A running app is stopped for the update and started again on the same
   port if it was running, and the person is told both.
3. `farm status` and `farm list` carry `update available: 0.1.1` on any row that has one, and
   `farm start` prints one line after the link when the app it just started has a newer version.
4. `farm check` is an alias for `farm update` with no id, since that is the word Jason used.

## Tests and measurement

- tests/test_farm.py: the list with one newer, two newer and none; the number choice, "all",
  Enter, and the no-tty path; the single-app question with Y, n and -y; the running app
  restarted on its port; status and list rows; start's one line. Use the existing fake catalog
  fixtures.
- A real transcript from a fresh venv against the live catalog, where you pin an older version
  by editing the installed manifest copy in the scratch home, then run `farm update` and pick
  it. Paste it in docs/UPDATES-1-REPORT.md.
- Update docs/site/02-getting-started.md and 03-cli.md.

## Rules

Model opus. No em dashes. Spell it Tiiny. Do not bump pyproject version. Commit on branch
updates, push it, open a PR against main with gh, never push main, never merge. Never read
~/.api_keys or any file with key, token or secret in its name. Ports 7861 to 7869 only; never
7788 or 8430 or 8431; HOME redirected to a scratch directory for every real run.
