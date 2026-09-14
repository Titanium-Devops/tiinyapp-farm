# The farm's GitHub App

The release-to-listing path opens pull requests on this repository: the hourly poller in
`.github/workflows/release-poll.yml` and the "Check for a new release" button on an app page.
Those pull requests have to run the manifest checks, and a pull request opened with a workflow's
built-in `GITHUB_TOKEN` does not start other workflows. So both open their pull requests with a
token from a GitHub App instead.

Makers install nothing. The App lives on this repository only. When it looks at a maker's
repository for a new release it uses the public API, and if GitHub refuses the App's credential
there, the call is repeated without one.

## Register it

Only a person with a browser can create an App and download its key. These are the exact settings.

| Setting | Value |
| --- | --- |
| Owner | Titanium-Devops |
| GitHub App name | tiinyapp-farm releases |
| Homepage URL | https://tiinyapp.farm |
| Callback URL | leave empty |
| Request user authorization (OAuth) | off |
| Webhook | Active off |
| Repository permission: Contents | Read and write |
| Repository permission: Pull requests | Read and write |
| Repository permission: Metadata | Read-only (GitHub sets this for you) |
| Any other permission | none |
| Where can this App be installed | Only on this account |
| Installed on | Titanium-Devops/tiinyapp-farm, and nothing else |

Contents write is what creates the branch and the manifest commit. Pull requests write is what
opens and refreshes the pull request. Nothing else is needed, so nothing else is granted.

After creating it, press Generate a private key and keep the downloaded `.pem`. Note the App ID
from the App's settings page. The key is a credential: it never goes in this repository, in a
manifest, or in a chat window.

## The two secrets

Both names are read by the code as written today. Nothing else has to change once they exist.

| Name | Value | Where |
| --- | --- | --- |
| `FARM_APP_ID` | the App ID, a number | Repository Actions secret, and a Worker secret |
| `FARM_APP_PRIVATE_KEY` | the whole `.pem`, including the BEGIN and END lines | Repository Actions secret, and a Worker secret |

The Actions secrets go in Settings, Secrets and variables, Actions on this repository. The Worker
secrets go to Cloudflare:

```sh
npx wrangler secret put FARM_APP_ID
npx wrangler secret put FARM_APP_PRIVATE_KEY < farm-releases.private-key.pem
```

GitHub hands out the key in PKCS#1 form, whose first line reads `BEGIN RSA PRIVATE KEY`. Both the
workflow and the Worker accept that form as it is, and a PKCS#8 key as well, so there is nothing
to convert. If you would rather store PKCS#8:

```sh
openssl pkcs8 -topk8 -nocrypt -in farm-releases.private-key.pem -out farm-releases.pkcs8.pem
```

## What runs without them

The poller reports that the App is not registered and checks nothing. The button still answers
"already listed at vX" and "no release newer than vX on GitHub", because those need no credential.
When it does find a newer release it answers that release checks are not switched on yet. Adding
the two secrets is the only step that turns the whole path on.

## Check that it works

1. Actions, Poll for new app releases, Run workflow. The summary lists one row per app.
2. Open an app you own on the site while signed in and press Check for a new release.
3. On a pull request the path opened, confirm that Manifest submission checks ran. That is the
   reason the App exists; if the checks are missing, the pull request was opened with the wrong
   credential.

## Rotating or revoking

Generate a new private key in the App's settings, replace both secrets, then delete the old key
from the App. Deleting the App, or uninstalling it from this repository, stops the poller and the
button and changes nothing else: the catalog, the site and `farm install` do not use it.
