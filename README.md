# tinyapp.farm

Community apps for the Tiiny AI Pocket Lab that run beside the device on your own computer.
Browse at https://tinyapp.farm, install with one command, share the device without collisions.

Brought to you by [Titanium Bot](https://titanium.bot). Made by Titanium Computing.

- `manifests/` one JSON file per app, the whole catalog.
- `farm/` the installer: `farm install <app>`, `farm start`, `farm stop`, `farm update`, `farm list`.
- `site/` the static catalog, built from the manifests.
- `.github/workflows/` the checks a submitted manifest must pass.

See `SPEC.md`.
