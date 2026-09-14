#!/usr/bin/env python3
"""The farm's whole HTTP surface, written once.

scripts/build-site.py turns this into /docs/openapi.json, and tests/test_openapi.py walks the
Worker's route table against it, so a route added to worker/*.mjs without a path here fails the
suite, and a path here with no route fails it too. Each path carries x-farm-source, the module
that answers it, and assets means the static site serves the file.

Written in Python rather than YAML because the standard library has no YAML reader and every
other build step here is Python.
"""
from pathlib import Path
import re

ORIGIN = "https://tiinyapp.farm"
APP_ID = r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$"
ERROR = {"$ref": "#/components/schemas/Error"}


def version():
    """The repository version this document was built from."""
    try:
        text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
        found = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
        return found.group(1) if found else "unknown"
    except OSError:
        return "unknown"


def obj(properties, required=(), extra=True):
    return {"type": "object", "properties": properties,
            **({"required": list(required)} if required else {}),
            **({} if extra else {"additionalProperties": False})}


def answer(description, schema=None, media="application/json", headers=None):
    body = {"description": description}
    if schema is not None:
        body["content"] = {media: {"schema": schema}}
    if headers:
        body["headers"] = headers
    return body


def fails(*pairs):
    """The error answers a route gives, every one of them the same one-sentence shape."""
    return {str(status): answer(description, ERROR) for status, description in pairs}


def op(summary, description, *, auth=(), body=None, answers=None, errors=(), limit=None,
       parameters=(), tags=()):
    operation = {"summary": summary, "description": description,
                 "security": [{name: []} for name in auth],
                 "responses": {**(answers or {}), **fails(*errors)}}
    if tags:
        operation["tags"] = list(tags)
    if parameters:
        operation["parameters"] = list(parameters)
    if body is not None:
        operation["requestBody"] = body
    if limit:
        operation["x-farm-rate-limit"] = limit
    return operation


def json_body(schema, required=True, description=None):
    return {"required": required, **({"description": description} if description else {}),
            "content": {"application/json": {"schema": schema}}}


APP = {"name": "id", "in": "path", "required": True, "description": "The app id.",
       "schema": {"type": "string", "pattern": APP_ID}, "example": "sample-app"}
HANDLE = {"name": "handle", "in": "path", "required": True, "description": "The maker's handle.",
          "schema": {"type": "string", "pattern": r"^[a-z0-9]+(?:-[a-z0-9]+)*$"},
          "example": "sample-maker"}
LAUNCHER = {"name": "file", "in": "path", "required": True,
            "description": "One launcher filename. Take it from the feed rather than assembling"
                           " it yourself, because the version is part of the name.",
            "schema": {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9._-]*$"},
            "example": "Tiiny-App-Farm_0.1.0_universal.dmg"}
KEY = {"name": "key", "in": "path", "required": True,
       "description": "Your account id and the image name. Use the url the upload answered"
                      " with rather than assembling this yourself.",
       "schema": {"type": "string"}, "example": "sample-maker/" + "0" * 32 + ".png"}

SCHEMAS = {
    "Error": obj({"error": {"type": "string",
                            "description": "One sentence meant for a person to read."}},
                 ["error"], extra=False),
    "User": obj({
        "id": {"type": "string"}, "createdAt": {"type": "string", "format": "date-time"},
        "email": {"type": "string"},
        "github": obj({"id": {"type": "integer"}, "login": {"type": "string"},
                       "name": {"type": "string"}, "avatar": {"type": "string"}}),
        "tiinyverse": {"$ref": "#/components/schemas/Tiinyverse"},
        "handle": {"type": ["string", "null"]}, "bio": {"type": "string"},
        "avatarKey": {"type": ["string", "null"]},
        "links": obj({"github": {"type": "string"}, "website": {"type": "string"},
                      "youtube": {"type": "string"}}),
        "public": {"type": "boolean"}}, ["id"]),
    "Tiinyverse": obj({"profileUrl": {"type": "string", "format": "uri"},
                       "name": {"type": "string"},
                       "verifiedAt": {"type": "string", "format": "date-time"}},
                      ["profileUrl", "name"]),
    "Token": obj({"id": {"type": "string"}, "name": {"type": "string"},
                  "prefix": {"type": "string", "description": "The first 13 characters, for display."},
                  "createdAt": {"type": "string", "format": "date-time"},
                  "lastUsedAt": {"type": ["string", "null"], "format": "date-time"}},
                 ["id", "name", "prefix", "createdAt", "lastUsedAt"]),
    "Comment": obj({"id": {"type": "string"},
                    "author": obj({"handle": {"type": ["string", "null"]},
                                   "name": {"type": "string"},
                                   "avatar": {"type": ["string", "null"]}}),
                    "text": {"type": "string"}, "at": {"type": "string", "format": "date-time"},
                    "canDelete": {"type": "boolean"}},
                   ["id", "author", "text", "at", "canDelete"]),
    "Social": obj({"thumbs": {"type": "integer"}, "mine": {"type": "boolean"},
                   "comments": {"type": "array", "items": {"$ref": "#/components/schemas/Comment"}}},
                  ["thumbs", "mine", "comments"]),
    "Seed": obj({
        "id": {"type": "string", "pattern": APP_ID}, "name": {"type": "string"},
        "version": {"type": "string"}, "icon": {"type": "string"},
        "state": {"type": "string", "enum": ["preparing", "label pending", "awaiting review",
                                             "draft", "closed", "merged", "published",
                                             "sprouting", "submission failed",
                                             "submission uncertain"]},
        "prUrl": {"type": "string", "format": "uri"},
        "checks": {"type": "array", "items": obj({"name": {"type": "string"},
                                                  "status": {"type": "string"}})},
        "reviews": {"type": "array", "items": {"type": "string"}},
        "thumbs": {"type": "integer"}, "comments": {"type": "integer"},
        "url": {"type": "string"}, "canUpdate": {"type": "boolean"},
        "release": {"oneOf": [{"$ref": "#/components/schemas/ReleaseCheck"}, {"type": "null"}]},
        "unavailable": {"type": "boolean",
                        "description": "GitHub could not be read, so state is the stored one."}},
        ["id", "name", "version", "state", "checks", "reviews"]),
    "ReleaseCheck": obj({
        "status": {"type": "string", "enum": ["found", "listed", "none", "manual", "untracked"]},
        "message": {"type": "string", "description": "The sentence shown to the maker."},
        "checkedAt": {"type": "integer", "description": "Milliseconds since the epoch."},
        "version": {"type": "string"}, "prUrl": {"type": "string", "format": "uri"}},
        ["status", "message", "checkedAt", "version"]),
    "Art": obj({"scene": {"type": "string"},
                "header": {"type": "string", "format": "uri"},
                "icon": {"type": "string", "format": "uri"},
                "remaining": {"type": "integer",
                              "description": "Drawings left for this app today."}},
               ["scene", "remaining"]),
    "Manifest": {"type": "object", "description":
                 "One catalog entry. Every field is documented at " + ORIGIN +
                 "/docs/manifest/ and the machine-readable schema is at " + ORIGIN +
                 "/docs/manifest.schema.json."},
}

SUBMISSION_FORM = {
    "required": True,
    "description": "The catalog text, the runtime needs, and either a release URL or one upload.",
    "content": {"multipart/form-data": {"schema": obj({
        "id": {"type": "string", "pattern": APP_ID},
        "name": {"type": "string"}, "pitch": {"type": "string", "maxLength": 100},
        "description": {"type": "string"}, "version": {"type": "string"},
        "license": {"type": "string"},
        "tags": {"type": "string", "description": "Comma separated. The site sends one category."},
        "permissions": {"type": "string",
                        "description": "Comma separated: microphone, files, network, device."},
        "command": {"type": "string", "description": "A start command."},
        "entry": {"type": "string",
                  "description": 'JSON entry object, or the string null for a library.'},
        "repo": {"type": "string"}, "homepage": {"type": "string"}, "video": {"type": "string"},
        "media": {"type": "string", "description": "JSON of uploaded icon, header and gallery URLs."},
        "screenshots": {"type": "string", "description": "JSON array of uploaded image URLs."},
        "python": {"type": "string"}, "ports": {"type": "string"}, "models": {"type": "string"},
        "npuUnits": {"type": "string"}, "health": {"type": "string"},
        "selfcheck": {"type": "string", "enum": ["true"]},
        "releaseUrl": {"type": "string", "format": "uri"},
        "archive": {"type": "string", "format": "binary",
                    "description": "A gzip tar archive up to 50 MB."}},
        ["id", "name", "pitch", "description", "version", "license"])}},
}

SUBMISSION_ANSWERS = {
    "201": answer("The pull request is open.",
                  obj({"id": {"type": "string"}, "prUrl": {"type": "string", "format": "uri"},
                       "statusUrl": {"type": "string"}}, ["id", "statusUrl"])),
    "202": answer("Saved, but one step did not finish. The warning says what to do next.",
                  obj({"id": {"type": "string"}, "statusUrl": {"type": "string"},
                       "warning": {"type": "string"}}, ["id", "statusUrl", "warning"])),
}

REDIRECT = answer("A redirect.", headers={"Location": {"schema": {"type": "string"}}})


def paths():
    """Every path the farm answers, in the order the Worker tries them."""
    return {
        "/api/auth/start": {"x-farm-source": "index.mjs", "post": op(
            "Send a sign-in code", "Emails a six digit code that lasts ten minutes and dies after"
            " five wrong attempts.", tags=["Sign in"], limit="3 per hour per address",
            body=json_body(obj({"email": {"type": "string", "maxLength": 254}}, ["email"])),
            answers={"200": answer("The code was sent.", obj({"sent": {"const": True}}, ["sent"]))},
            errors=[(400, "That is not an email address."), (403, "The Origin header is missing."),
                    (429, "Three codes an hour is the limit."), (502, "The mail service failed."),
                    (503, "Email sign-in is not configured yet.")])},
        "/api/auth/verify": {"x-farm-source": "index.mjs", "post": op(
            "Finish signing in with a code", "Sets the session cookie. Signed in already, this"
            " links the address to that account instead of making a second one.", tags=["Sign in"],
            body=json_body(obj({"email": {"type": "string"},
                                "code": {"type": "string", "pattern": r"^\d{6}$"}},
                               ["email", "code"])),
            answers={"200": answer("Signed in.", obj({"user": {"$ref": "#/components/schemas/User"}},
                                                     ["user"]), headers={
                "Set-Cookie": {"description": "__Host-farm, HttpOnly, Secure, SameSite=Lax, 30 days.",
                               "schema": {"type": "string"}}})},
            errors=[(400, "The code has expired or is wrong."),
                    (403, "Finish linking from the account that asked for the code.")])},
        "/api/auth/github": {"x-farm-source": "index.mjs", "get": op(
            "Start signing in with GitHub", "Redirects to GitHub's authorize page.",
            tags=["Sign in"], answers={"302": REDIRECT},
            errors=[(503, "GitHub sign-in is not configured yet.")])},
        "/api/auth/github/callback": {"x-farm-source": "index.mjs", "get": op(
            "Finish signing in with GitHub", "GitHub sends the visitor back here. On success it"
            " redirects to /submit/ and sets the session cookie.", tags=["Sign in"],
            parameters=[{"name": "code", "in": "query", "schema": {"type": "string"}},
                        {"name": "state", "in": "query", "schema": {"type": "string"}}],
            answers={"302": REDIRECT},
            errors=[(400, "GitHub sign-in was not completed."),
                    (403, "The sign-in expired or the state did not match."),
                    (502, "GitHub did not answer as expected.")])},
        "/api/auth/logout": {"x-farm-source": "index.mjs", "post": op(
            "Sign out", "Ends this session and clears the cookie.", tags=["Sign in"],
            auth=["session"],
            answers={"200": answer("Signed out.", obj({"signedOut": {"const": True}},
                                                      ["signedOut"]))})},
        "/api/me": {"x-farm-source": "index.mjs", "get": op(
            "Who is signed in", "Answers the account on this cookie, or null when there is none."
            " A bearer token is ignored here.", tags=["Your account"], auth=["session"],
            answers={"200": answer("The account, or null.", obj(
                {"user": {"oneOf": [{"$ref": "#/components/schemas/User"}, {"type": "null"}]}},
                ["user"]))})},
        "/api/tokens": {"x-farm-source": "index.mjs", "post": op(
            "Create an API token", "The full token is in this answer and nowhere else afterwards."
            " Creating one needs the cookie, so a token cannot mint another token.",
            tags=["Your account"], auth=["session"], limit="5 live tokens per account",
            body=json_body(obj({"name": {"type": "string", "maxLength": 80}}, ["name"])),
            answers={"201": answer("Copy the token now.", obj(
                {"token": {"type": "string", "pattern": r"^farm_[a-f0-9]{40}$"},
                 "id": {"type": "string"}, "name": {"type": "string"},
                 "prefix": {"type": "string"}, "createdAt": {"type": "string"},
                 "lastUsedAt": {"type": "null"}}, ["token", "id", "name", "prefix"]))},
            errors=[(400, "Give the token a name of 80 characters or fewer."),
                    (401, "Sign in first."), (403, "Verify you own a Tiiny first."),
                    (409, "Five tokens is the limit. Revoke one first.")]),
            "get": op("List your API tokens", "Their names and prefixes, never the tokens.",
                      tags=["Your account"], auth=["session"],
                      answers={"200": answer("Your tokens.", obj(
                          {"tokens": {"type": "array",
                                      "items": {"$ref": "#/components/schemas/Token"}}},
                          ["tokens"]))},
                      errors=[(401, "Sign in first.")])},
        "/api/tokens/{id}": {"x-farm-source": "index.mjs", "delete": op(
            "Revoke an API token", "The token stops working at once.", tags=["Your account"],
            auth=["session"],
            parameters=[{"name": "id", "in": "path", "required": True,
                         "description": "The token id from GET /api/tokens, not the token.",
                         "schema": {"type": "string", "pattern": "^[a-f0-9]{32}$"},
                         "example": "0" * 32}],
            answers={"200": answer("Revoked.", obj({"revoked": {"const": True}}, ["revoked"]))},
            errors=[(401, "Sign in first."), (404, "No such token on this account.")])},
        "/api/seeds/{id}/social": {"x-farm-source": "social.mjs", "get": op(
            "Read an app's thumbs and comments", "Reading needs no credential. mine is true when"
            " the signed-in visitor has a thumb on this app.", tags=["Comments and thumbs up"],
            parameters=[APP],
            answers={"200": answer("The conversation.", {"$ref": "#/components/schemas/Social"})},
            errors=[(404, "That app is not in the catalog."),
                    (405, "That action does not use this method.")])},
        "/api/seeds/{id}/thumb": {"x-farm-source": "social.mjs", "post": op(
            "Toggle your thumbs up", "Pressing it again takes it back.",
            tags=["Comments and thumbs up"], auth=["session"], parameters=[APP],
            answers={"200": answer("The conversation, with your thumb toggled.",
                                   {"$ref": "#/components/schemas/Social"})},
            errors=[(401, "Sign in first."), (404, "That app is not in the catalog.")])},
        "/api/seeds/{id}/comments": {"x-farm-source": "social.mjs", "post": op(
            "Leave a comment", "Needs a verified Tiiny profile. Deleting comments does not give"
            " the hourly limit back.", tags=["Comments and thumbs up"], auth=["session"],
            parameters=[APP], limit="5 per hour per account",
            body=json_body(obj({"text": {"type": "string", "minLength": 1, "maxLength": 1000}},
                               ["text"])),
            answers={"201": answer("Posted.", {"$ref": "#/components/schemas/Social"})},
            errors=[(400, "Write 1 to 1000 characters."), (401, "Sign in first."),
                    (403, "Verify you own a Tiiny first."),
                    (404, "That app is not in the catalog."),
                    (429, "Five comments an hour is the limit.")])},
        "/api/seeds/{id}/comments/{commentId}": {"x-farm-source": "social.mjs", "delete": op(
            "Remove a comment", "Its author or a farm admin.", tags=["Comments and thumbs up"],
            auth=["session"],
            parameters=[APP, {"name": "commentId", "in": "path", "required": True,
                              "description": "The id of the comment, from the conversation.",
                              "schema": {"type": "string", "pattern": "^[a-f0-9]{32}$"},
                              "example": "0" * 32}],
            answers={"200": answer("Removed.", {"$ref": "#/components/schemas/Social"})},
            errors=[(401, "Sign in first."), (403, "Only the author or a farm admin."),
                    (404, "That app is not in the catalog, or that comment is not here.")])},
        "/api/maker": {"x-farm-source": "makers.mjs", "post": op(
            "Save your maker profile", "The bio, the links and the avatar shown on your maker page.",
            tags=["Your account"], auth=["session"],
            body=json_body(obj({"bio": {"type": "string", "maxLength": 600},
                                "links": obj({"github": {"type": "string"},
                                              "website": {"type": "string"},
                                              "youtube": {"type": "string"}}, extra=False),
                                "avatarKey": {"type": ["string", "null"]}}, ["bio", "links"])),
            answers={"200": answer("Saved.", obj({"user": {"$ref": "#/components/schemas/User"}},
                                                 ["user"]))},
            errors=[(400, "A field is too long, an unknown link, or an image that is not yours."),
                    (401, "Sign in first.")])},
        "/api/maker/visibility": {"x-farm-source": "makers.mjs", "put": op(
            "Show or hide your maker page", "Hidden leaves it reachable to signed-in visitors only.",
            tags=["Your account"], auth=["session"],
            body=json_body(obj({"public": {"type": "boolean"}}, ["public"])),
            answers={"200": answer("Saved.", obj({"public": {"type": "boolean"}}, ["public"]))},
            errors=[(400, "Choose true or false."), (401, "Sign in first.")])},
        "/api/media": {"x-farm-source": "makers.mjs", "post": op(
            "Upload an image", "The type is read from the file's own first bytes, not its name."
            " Keep the URL that comes back and put it in the submission form.", tags=["Images"],
            auth=["farmToken", "session"], limit="2 MiB per image",
            body={"required": True, "description": "The image bytes.",
                  "content": {"image/png": {"schema": {"type": "string", "format": "binary"}},
                              "image/jpeg": {"schema": {"type": "string", "format": "binary"}},
                              "image/webp": {"schema": {"type": "string", "format": "binary"}}}},
            answers={"201": answer("Stored.", obj({"key": {"type": "string"},
                                                   "url": {"type": "string", "format": "uri"}},
                                                  ["key", "url"]))},
            errors=[(401, "Sign in or send a token."), (403, "Verify you own a Tiiny first."),
                    (413, "Larger than 2 MiB."), (415, "Not a PNG, JPEG or WebP.")])},
        "/api/media/{key}": {"x-farm-source": "makers.mjs", "delete": op(
            "Delete one of your images", "Only your own.", tags=["Images"], auth=["session"],
            parameters=[KEY],
            answers={"200": answer("Deleted.", obj({"deleted": {"const": True}}, ["deleted"]))},
            errors=[(401, "Sign in first."), (403, "That image is not yours.")])},
        "/api/owners": {"x-farm-source": "proof.mjs", "get": op(
            "Look up a verified owner", "The public lookup the pull request checks use. It needs"
            " no credential and skips the Worker's request queue, so it stays quick during an"
            " upload.", tags=["Prove you own a Tiiny"],
            parameters=[{"name": "profile", "in": "query", "required": True,
                         "description": "https://www.tiinyverse.com/users/<uuid>",
                         "schema": {"type": "string", "format": "uri"}}],
            answers={"200": answer("Whether that profile is verified here.", obj(
                {"verified": {"type": "boolean"}, "name": {"type": ["string", "null"]}},
                ["verified", "name"]))},
            errors=[(400, "That is not a TiinyVerse profile URL.")])},
        "/api/tiinyverse/link": {"x-farm-source": "proof.mjs", "post": op(
            "Ask for a bio code", "Put the code anywhere in your TiinyVerse bio, save the profile,"
            " then call verify. The code lasts 24 hours.", tags=["Prove you own a Tiiny"],
            auth=["session"],
            body=json_body(obj({"profileUrl": {"type": "string", "format": "uri"}}, ["profileUrl"])),
            answers={"200": answer("The code and what to do with it.", obj(
                {"profileUrl": {"type": "string"}, "code": {"type": "string"},
                 "expires": {"type": "integer"}, "instruction": {"type": "string"}},
                ["profileUrl", "code", "expires", "instruction"]))},
            errors=[(400, "That is not a TiinyVerse profile URL."), (401, "Sign in first."),
                    (409, "Already verified, or that profile belongs to another account.")])},
        "/api/tiinyverse/verify": {"x-farm-source": "proof.mjs", "post": op(
            "Check the bio code", "Reads your public profile, looks for the code as a whole word,"
            " and takes your display name from the page.", tags=["Prove you own a Tiiny"],
            auth=["session"],
            answers={"200": answer("Verified.", obj(
                {"tiinyverse": {"$ref": "#/components/schemas/Tiinyverse"}}, ["tiinyverse"]))},
            errors=[(400, "Ask for a new code; the last one expired."), (401, "Sign in first."),
                    (409, "That profile belongs to another account."),
                    (422, "The profile could not be read, or the code is not on it yet.")])},
        "/api/seeds/{id}/art": {"x-farm-source": "art.mjs", "get": op(
            "The art the farm last drew", "The pair drawn for this app, the scene it was drawn"
            " from, and how many drawings are left today.", tags=["Art in the farm's hand"],
            auth=["farmToken", "session"], parameters=[APP],
            answers={"200": answer("The last pair, or empty strings when there is none.",
                                   {"$ref": "#/components/schemas/Art"})},
            errors=[(401, "Sign in or send a token."),
                    (403, "Verify you own a Tiiny, and the app id must be yours or unclaimed."),
                    (405, "Use GET or POST for app art.")]),
            "post": op("Draw a header and an icon", "One sentence describing the scene. A drawing"
                       " takes a minute or two, so give the call a generous timeout. A refusal or"
                       " a failure costs you nothing.", tags=["Art in the farm's hand"],
                       auth=["farmToken", "session"], parameters=[APP],
                       limit="3 per app per day, one drawing at a time",
                       body=json_body(obj({"scene": {"type": "string", "minLength": 3,
                                                     "maxLength": 200}}, ["scene"])),
                       answers={"201": answer("Both images are stored and answered as URLs.",
                                              {"$ref": "#/components/schemas/Art"})},
                       errors=[(400, "The scene is empty, too long, or not one line."),
                               (401, "Sign in or send a token."),
                               (403, "This app id belongs to another maker."),
                               (409, "The farm is still drawing this app."),
                               (422, "The drawing service refused those words."),
                               (429, "Three drawings a day for one app."),
                               (502, "The drawing could not be made or kept."),
                               (503, "Drawing app art is not switched on yet."),
                               (504, "The drawing took too long.")])},
        "/api/seeds/{id}/release-check": {"x-farm-source": "release.mjs", "post": op(
            "Check GitHub for a newer release", "Asks GitHub for the newest full release of the"
            " repository in the manifest, downloads that archive, measures its checksum and size"
            " here, and opens or refreshes one pull request for this app. The session cookie only:"
            " a bearer token is not accepted on this route.", tags=["Releases"], auth=["session"],
            parameters=[APP], limit="1 per minute per app",
            answers={"200": answer("What the check found.",
                                   {"$ref": "#/components/schemas/ReleaseCheck"}),
                     "429": answer("Checked a moment ago. The message says how long to wait.",
                                   {"$ref": "#/components/schemas/ReleaseCheck"})},
            errors=[(401, "Sign in first."), (403, "Only this app's verified maker."),
                    (404, "That app is not in the catalog."),
                    (405, "Use POST to check for a new release."),
                    (422, "The release archive could not be measured."),
                    (503, "Release checks are not switched on yet.")])},
        "/api/seeds/mine": {"x-farm-source": "seeds.mjs", "get": op(
            "Your submissions and their checks", "Every app you have submitted with its state,"
            " its checks, its reviews and its release tracking. This is what farm status <id>"
            " reads.", tags=["Apps"], auth=["farmToken", "session"],
            answers={"200": answer("Your apps.", obj(
                {"seeds": {"type": "array", "items": {"$ref": "#/components/schemas/Seed"}}},
                ["seeds"]))},
            errors=[(401, "Sign in or send a token.")])},
        "/api/seeds": {"x-farm-source": "seeds.mjs", "post": op(
            "Submit an app", "Validates the manifest, measures the archive, and opens a pull"
            " request on the catalog repository. Nothing is published until a maintainer merges"
            " it. Send a release URL or an upload, never both.", tags=["Apps"],
            auth=["farmToken", "session"], limit="5 per hour per account", body=SUBMISSION_FORM,
            answers=SUBMISSION_ANSWERS,
            errors=[(400, "A field is wrong, or both a release URL and an upload were sent."),
                    (401, "Sign in or send a token."), (403, "Verify you own a Tiiny first."),
                    (408, "The upload took too long."),
                    (409, "That app id belongs to another maker, or is already in the catalog."),
                    (413, "Larger than 50 MB."), (415, "Send the form as multipart/form-data."),
                    (422, "The release link did not answer 200 with a gzip archive."),
                    (429, "Five submissions an hour is the limit."),
                    (502, "GitHub could not finish the request."),
                    (503, "App submission is not configured yet.")])},
        "/api/seeds/{id}": {"x-farm-source": "seeds.mjs", "put": op(
            "Update an app you own", "The same form. The id cannot change. A release change needs"
            " a strictly newer version; text alone may keep the current one.", tags=["Apps"],
            auth=["farmToken", "session"], parameters=[APP], limit="5 per hour per account",
            body=SUBMISSION_FORM, answers=SUBMISSION_ANSWERS,
            errors=[(400, "A field is wrong, or the version is not newer."),
                    (401, "Sign in or send a token."),
                    (403, "Only this app's verified maker can update it."),
                    (404, "That app is not in the catalog yet."),
                    (413, "Larger than 50 MB."), (415, "Send the form as multipart/form-data."),
                    (429, "Five submissions an hour is the limit.")])},
        "/account/": {"x-farm-source": "makers.mjs", "get": op(
            "Your apps", "The page that shows your submissions, your profile and your API tokens."
            " Signed out it redirects to /submit/.", tags=["Pages the Worker serves"],
            auth=["session"],
            answers={"200": answer("The page.", {"type": "string"}, media="text/html"),
                     "302": REDIRECT})},
        "/makers/{handle}/": {"x-farm-source": "makers.mjs", "get": op(
            "A maker's public page", "Built live from the catalog. A maker who has turned their"
            " page off is reachable to signed-in visitors only.", tags=["Pages the Worker serves"],
            parameters=[HANDLE],
            answers={"200": answer("The page.", {"type": "string"}, media="text/html")},
            errors=[(404, "That maker was not found.")])},
        "/makers/{handle}/card.png": {"x-farm-source": "makers.mjs", "get": op(
            "A maker's share card", "The 1200 by 630 image social sites show.",
            tags=["Pages the Worker serves"], parameters=[HANDLE],
            answers={"200": answer("The image.", {"type": "string", "format": "binary"},
                                   media="image/png")},
            errors=[(404, "Share card not found."), (405, "Use GET or HEAD for share cards.")])},
        "/media/{key}": {"x-farm-source": "main.mjs", "get": op(
            "An uploaded image", "Immutable, cached for a year.", tags=["Files"],
            parameters=[KEY],
            answers={"200": answer("The image.", {"type": "string", "format": "binary"},
                                   media="image/png")},
            errors=[(404, "Image not found."), (405, "Use GET or HEAD for images.")])},
        "/seeds-files/{id}/{version}/{name}": {"x-farm-source": "main.mjs", "get": op(
            "An archive uploaded through the site", "The release archive for an app whose maker"
            " uploaded one rather than linking a GitHub release.", tags=["Files"],
            parameters=[APP,
                        {"name": "version", "in": "path", "required": True,
                         "schema": {"type": "string", "pattern": r"^\d+\.\d+\.\d+$"},
                         "example": "0.1.0"},
                        {"name": "name", "in": "path", "required": True,
                         "description": "The archive filename, ending .tar.gz.",
                         "schema": {"type": "string"}, "example": "sample-app-0.1.0.tar.gz"}],
            answers={"200": answer("The archive.", {"type": "string", "format": "binary"},
                                   media="application/gzip")},
            errors=[(404, "That app file does not exist."),
                    (405, "Use GET or HEAD for app files.")])},
        "/launcher/latest.json": {"x-farm-source": "main.mjs", "get": op(
            "The launcher update feed", "What the Tiiny App Farm desktop launcher reads to learn"
            " whether a newer version of itself exists. The shape is the Tauri updater's: a"
            " version, the day it was published, and one entry per platform holding a signed"
            " archive url. It is never cached, and until the first launcher release it answers"
            " 404.", tags=["Files"],
            answers={"200": answer("The feed.", obj(
                {"version": {"type": "string", "description": "major.minor.patch."},
                 "notes": {"type": "string"},
                 "pub_date": {"type": "string", "format": "date-time"},
                 "platforms": {"type": "object", "description":
                               "Keyed by darwin-aarch64, darwin-x86_64 and windows-x86_64.",
                               "additionalProperties": obj(
                                   {"signature": {"type": "string"},
                                    "url": {"type": "string", "format": "uri"}},
                                   ["signature", "url"])}},
                ["version", "platforms"]))},
            errors=[(404, "The launcher has not been published yet."),
                    (405, "Use GET or HEAD for launcher downloads.")])},
        "/launcher/{file}": {"x-farm-source": "main.mjs", "get": op(
            "A launcher download", "The disk image, the installer, or the signed archive an"
            " installed launcher updates itself from. A filename carrying a version is cached for"
            " a year, because that name can never hold different bytes.", tags=["Files"],
            parameters=[LAUNCHER],
            answers={"200": answer("The file.", {"type": "string", "format": "binary"},
                                   media="application/octet-stream")},
            errors=[(404, "That launcher file does not exist."),
                    (405, "Use GET or HEAD for launcher downloads.")])},
        "/plant": {"x-farm-source": "makers.mjs", "get": op(
            "An old path", "301 to /install/.", tags=["Pages the Worker serves"],
            answers={"301": REDIRECT})},
        "/seeds": {"x-farm-source": "makers.mjs", "get": op(
            "An old path", "301 to /submit/.", tags=["Pages the Worker serves"],
            answers={"301": REDIRECT})},
        "/farm": {"x-farm-source": "makers.mjs", "get": op(
            "An old path", "301 to /account/.", tags=["Pages the Worker serves"],
            answers={"301": REDIRECT})},
        "/seeds/mine": {"x-farm-source": "makers.mjs", "get": op(
            "An old path", "301 to /account/.", tags=["Pages the Worker serves"],
            answers={"301": REDIRECT})},
        "/catalog.json": {"x-farm-source": "assets", "get": op(
            "Every manifest in one file", "The whole catalog, and the newest farm version, in one"
            " file. Read this first when you want to see what the farm has. A deploy in flight"
            " can still be serving the older shape, which is the apps array on its own.",
            tags=["The catalog"],
            answers={"200": answer("The catalog.", obj(
                {"cli": {"type": "string",
                         "description": "The newest tiinyapp-farm on PyPI, as the site knows it."},
                 "apps": {"type": "array",
                          "items": {"$ref": "#/components/schemas/Manifest"}}},
                ["cli", "apps"]))})},
        "/manifests/{id}.json": {"x-farm-source": "assets", "get": op(
            "One app manifest", "The file the installer reads before it downloads anything.",
            tags=["The catalog"], parameters=[APP],
            answers={"200": answer("The manifest.", {"$ref": "#/components/schemas/Manifest"}),
                     "404": answer("No such app.", {"type": "string"}, media="text/html")})},
        "/categories.json": {"x-farm-source": "assets", "get": op(
            "The tag to category map", "How the site groups tags, and the order it shows them in.",
            tags=["The catalog"],
            answers={"200": answer("The map and the order.", obj(
                {"map": {"type": "object", "additionalProperties": {"type": "string"}},
                 "order": {"type": "array", "items": {"type": "string"}}}, ["map", "order"]))})},
        "/llms.txt": {"x-farm-source": "assets", "get": op(
            "The index for assistants", "A short plain-text index that names the agent guide, this"
            " document, and the pages behind them. Fetch it first.", tags=["The catalog"],
            answers={"200": answer("The index.", {"type": "string"}, media="text/plain")})},
        "/docs/openapi.json": {"x-farm-source": "assets", "get": op(
            "This document", "The whole HTTP surface as OpenAPI 3.1.", tags=["The catalog"],
            answers={"200": answer("This document.", {"type": "object"})})},
        "/docs/manifest.schema.json": {"x-farm-source": "assets", "get": op(
            "The manifest schema", "The JSON Schema both the site and the pull request checks"
            " validate a manifest against.", tags=["The catalog"],
            answers={"200": answer("The schema.", {"type": "object"})})},
    }


def spec():
    """The whole document, ready to serialize."""
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "tiinyapp.farm",
            "version": version(),
            "summary": "The reviewed catalog of small apps for the Tiiny AI Pocket Lab.",
            "description":
                "Everything under /api/, plus the account, maker and file routes, is answered by a"
                " Cloudflare Worker; everything else is a static file. Responses are JSON with"
                " Cache-Control: no-store unless said otherwise.\n\n"
                "Any POST, PUT, PATCH or DELETE that does not carry a bearer token on a route that"
                " accepts one must send Origin: https://tiinyapp.farm, or it is refused with 403."
                "\n\nEvery failure is a JSON object with one error field holding a sentence meant"
                " for a person. An unexpected failure answers 502 with a general sentence rather"
                " than the underlying text, because that text can carry credentials.",
            "license": {"name": "MIT",
                        "url": "https://github.com/Titanium-Devops/tiinyapp-farm/blob/main/LICENSE"},
        },
        "servers": [{"url": ORIGIN}],
        "externalDocs": {"description": "The written guide for assistants",
                         "url": ORIGIN + "/docs/agents/"},
        "tags": [{"name": name} for name in
                 ["Sign in", "Prove you own a Tiiny", "Your account", "Images",
                  "Art in the farm's hand", "Apps", "Releases", "Comments and thumbs up",
                  "The catalog", "Files", "Pages the Worker serves"]],
        "paths": paths(),
        "components": {
            "securitySchemes": {
                "farmToken": {
                    "type": "http", "scheme": "bearer",
                    "description":
                        "A token you create on " + ORIGIN + "/account/ and copy once. It is farm_"
                        " followed by 40 hexadecimal characters. Five routes accept one: POST"
                        " /api/seeds, PUT /api/seeds/<id>, POST /api/media, GET /api/seeds/mine,"
                        " and GET and POST /api/seeds/<id>/art. Everywhere else it is ignored and"
                        " the cookie decides, so a token cannot mint another token.",
                },
                "session": {
                    "type": "apiKey", "in": "cookie", "name": "__Host-farm",
                    "description":
                        "Set by signing in with an email code or with GitHub. HttpOnly, Secure,"
                        " SameSite=Lax, 30 days. Signing in again replaces the previous session.",
                },
            },
            "schemas": SCHEMAS,
        },
    }


if __name__ == "__main__":
    import json
    print(json.dumps(spec(), indent=2))
