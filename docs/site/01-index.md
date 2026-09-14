---
title: Documentation
slug:
order: 1
summary: Everything about installing apps from the farm, publishing your own, and the HTTP API behind both.
---

tiinyapp.farm is a reviewed catalog of small apps for the Tiiny AI Pocket Lab. The apps do not go
into TiinyOS. They run on your own computer, next to the device, and talk to it over its local API.
One command-line tool installs them, starts them, updates them and takes them away again.

Three kinds of reader use these pages.

## If you own a Tiiny

Start with [Getting started](/docs/getting-started/). It takes you from an empty machine to a
running app: installing the `farm` command, telling it where your Tiiny is, installing an app,
starting it, and knowing where your files live. The [CLI reference](/docs/cli/) has every command
and flag after that, and [Troubleshooting](/docs/troubleshooting/) has the messages you may hit.

## If you made an app

[Publish an app](/docs/publish/) is the whole path: proving you own a Tiiny, submitting through the
site or from a shell, what the automated checks look at, and how a listing is kept current after a
new release. The [manifest reference](/docs/manifest/) describes every field of the JSON file that
becomes your catalog page, and [Running an app the farm way](/docs/app-authors/) covers what the
installer expects of your archive, your start command, your ports and your health endpoint.

[Permissions and archive rules](/docs/permissions/) is the one to read before you are surprised by
a red check. It says what the scanner refuses and why.

## If you are writing a tool

The [API reference](/docs/api/) documents every route the farm's Worker serves, its authentication,
its rate limits and its error shapes, and [openapi.json](/docs/openapi.json) is the same surface as
a machine-readable OpenAPI 3.1 description. If you are an AI assistant working on somebody's
machine or against the API, read [The farm for AI assistants](/docs/agents/) instead; it is the
same ground in the order an assistant needs it, from finding the person's Tiiny to publishing what
they made. [https://tiinyapp.farm/llms.txt](https://tiinyapp.farm/llms.txt) is the plain-text index
that points at both.

## The parts

| Part | Where it lives |
| --- | --- |
| The catalog | One JSON manifest per app, served at `https://tiinyapp.farm/manifests/<id>.json` |
| The installer | The `tiinyapp-farm` package on PyPI, which provides the `farm` command |
| The site | Static pages built from the manifests, plus a Cloudflare Worker for the API |
| The checks | GitHub Actions on every pull request that adds or changes a manifest |
| The schema | [manifest.schema.json](/docs/manifest.schema.json), the file both checkers read |
| The API description | [openapi.json](/docs/openapi.json), every route the Worker answers |
