#!/usr/bin/env python3
"""Validate the farm schema's keywords using only Python's standard library.

This intentionally implements the subset used by manifest.schema.json, not a
universal JSON Schema engine. Pending releases are catalog drafts, not installs.
"""
import argparse
import datetime
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

SCHEMA = Path(__file__).resolve().parents[1] / "docs" / "manifest.schema.json"


def validate(value, rule, root, path="$", allow_pending=False):
    if "$ref" in rule:
        target = root
        for part in rule["$ref"][2:].split("/"):
            target = target[part]
        validate(value, target, root, path, allow_pending)
    if "oneOf" in rule:
        matches = 0
        for option in rule["oneOf"]:
            try:
                validate(value, option, root, path, allow_pending)
                matches += 1
            except ValueError:
                pass
        if matches != 1:
            raise ValueError(f"{path}: must match exactly one allowed entry shape")
    if "not" in rule:
        try:
            validate(value, rule["not"], root, path, allow_pending)
        except ValueError:
            pass
        else:
            raise ValueError(f"{path}: reserved value")
    kinds = {"object": dict, "array": list, "string": str,
             "integer": int, "boolean": bool, "null": type(None)}
    if "type" in rule and type(value) is not kinds[rule["type"]]:
        raise ValueError(f"{path}: expected {rule['type']}")
    if "const" in rule and value == rule["const"]:
        pass
    elif "const" in rule:
        raise ValueError(f"{path}: unexpected value")
    if "enum" in rule and value not in rule["enum"]:
        raise ValueError(f"{path}: not an allowed value")
    if isinstance(value, dict):
        for key in rule.get("required", []):
            if key not in value:
                raise ValueError(f"{path}: missing {key}")
        props = rule.get("properties", {})
        if rule.get("additionalProperties") is False and value.keys() - props.keys():
            raise ValueError(f"{path}: unknown properties {sorted(value.keys() - props.keys())}")
        for key, item in value.items():
            if key in props:
                validate(item, props[key], root, f"{path}.{key}", allow_pending)
    if isinstance(value, list):
        if rule.get("uniqueItems") and len({json.dumps(x, sort_keys=True) for x in value}) != len(value):
            raise ValueError(f"{path}: duplicate items")
        for index, item in enumerate(value):
            validate(item, rule.get("items", {}), root, f"{path}[{index}]", allow_pending)
    if isinstance(value, str):
        if len(value) < rule.get("minLength", 0):
            raise ValueError(f"{path}: must not be empty")
        if "pattern" in rule and re.search(rule["pattern"], value) is None:
            raise ValueError(f"{path}: invalid format")
        if rule.get("format") == "date":
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    raise ValueError()
                datetime.date.fromisoformat(value)
            except ValueError:
                raise ValueError(f"{path}: expected YYYY-MM-DD date") from None
        if rule.get("format") == "uri":
            # Relative and absolute paths are supported for local release fixtures.
            parsed = urlsplit(value)
            if parsed.scheme in ("http", "https") and (not parsed.netloc or any(c.isspace() for c in value)):
                raise ValueError(f"{path}: invalid URL")
    if type(value) is int:  # noqa: E721 - JSON integers exclude booleans.
        if value < rule.get("minimum", value) or value > rule.get("maximum", value):
            raise ValueError(f"{path}: out of range")
    if path == "$.release.sha256" and value == "pending" and not allow_pending:
        raise ValueError(f"{path}: pending checksum requires --allow-pending")


def check_manifest(manifest, allow_pending=False):
    schema = json.loads(SCHEMA.read_text())
    validate(manifest, schema, schema, allow_pending=allow_pending)
    if manifest.get("selfcheck") and manifest["entry"] is None:
        raise ValueError("$.selfcheck: needs a runnable entry")
    if "health" in manifest and not manifest["requires"]["ports"]:
        raise ValueError("$.health: needs a declared port")
    if manifest["entry"] is None and "library" not in manifest["tags"]:
        raise ValueError("$.tags: a null entry requires the library tag")
    if manifest["release"]["sha256"] == "pending" and "pending" not in manifest["description"].lower():
        raise ValueError("$.description: explain the pending release")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--allow-pending", action="store_true")
    args = parser.parse_args()
    try:
        check_manifest(json.loads(args.file.read_text()), args.allow_pending)
    except (OSError, ValueError) as exc:
        print(f"Invalid manifest: {exc}", file=sys.stderr)
        return 1
    print(f"Valid: {args.file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
