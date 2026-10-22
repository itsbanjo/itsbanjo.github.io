#!/usr/bin/env python3
"""Validate Snot Shot's force-update config.

Usage:
  python3 tools/validate_version_json.py snotshot/version.json
  python3 tools/validate_version_json.py snotshot/version.json --live

The client compares integer build numbers (CFBundleVersion / versionCode).
The App Store only exposes marketing versions through iTunes Lookup, so the
CI guard compares minVersion/latestVersion with the live store version. When
the config is disabled the live check is skipped: a disabled config cannot
block anyone, and this lets the file ship before the next build is live.
"""
import argparse
import json
import re
import sys
import urllib.parse
import urllib.request

IOS_APP_ID = "6818944453"
SEMVER = re.compile(r"^\d+\.\d+(?:\.\d+)?$")
HOSTS = {"ios": "apps.apple.com", "android": "play.google.com"}


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    return 1


def version_tuple(text):
    parts = [int(x) for x in text.split(".")]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def live_ios_version():
    url = f"https://itunes.apple.com/lookup?id={IOS_APP_ID}&country=us"
    req = urllib.request.Request(url, headers={"User-Agent": "snotshot-version-check/1.0"})
    with urllib.request.urlopen(req, timeout=20) as res:
        data = json.load(res)
    results = data.get("results") or []
    if not results:
        raise RuntimeError("iTunes Lookup returned no results")
    version = results[0].get("version")
    if not version:
        raise RuntimeError("iTunes Lookup result has no version")
    return version


def validate_platform(name, obj, errors):
    if not isinstance(obj, dict):
        errors.append(f"{name} must be an object")
        return
    min_build = obj.get("minBuild")
    latest_build = obj.get("latestBuild")
    for key, value in (("minBuild", min_build), ("latestBuild", latest_build)):
        if type(value) is not int or value < 1:
            errors.append(f"{name}.{key} must be a positive integer")
    if type(min_build) is int and type(latest_build) is int and min_build > latest_build:
        errors.append(f"{name}.minBuild must be <= {name}.latestBuild")

    min_version = obj.get("minVersion")
    latest_version = obj.get("latestVersion")
    for key, value in (("minVersion", min_version), ("latestVersion", latest_version)):
        if not isinstance(value, str) or not SEMVER.match(value):
            errors.append(f"{name}.{key} must be a numeric version such as 1.4.0")
    if isinstance(min_version, str) and isinstance(latest_version, str) and SEMVER.match(min_version) and SEMVER.match(latest_version):
        if version_tuple(min_version) > version_tuple(latest_version):
            errors.append(f"{name}.minVersion must be <= {name}.latestVersion")

    url = obj.get("url")
    if not isinstance(url, str):
        errors.append(f"{name}.url must be a string")
    else:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != HOSTS[name]:
            errors.append(f"{name}.url must be an https://{HOSTS[name]}/... URL")

    if "message" in obj:
        message = obj["message"]
        if not isinstance(message, str):
            errors.append(f"{name}.message must be a string")
        elif len(message) > 240:
            errors.append(f"{name}.message must be 240 characters or less (the client truncates)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--live", action="store_true", help="compare marketing versions with the live App Store listing")
    args = ap.parse_args()

    try:
        with open(args.path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except Exception as exc:
        return fail(f"cannot read {args.path}: {exc}")

    if not isinstance(cfg, dict):
        return fail("top level must be an object")
    enabled = cfg.get("enabled")
    if type(enabled) is not bool:
        return fail("enabled must be true or false")

    platforms = [p for p in ("ios", "android") if p in cfg]
    if not platforms:
        return fail("config must contain ios and/or android")

    errors = []
    for platform in platforms:
        validate_platform(platform, cfg[platform], errors)

    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1

    print(f"OK: schema valid (enabled={str(enabled).lower()}, platforms={', '.join(platforms)})")
    if not enabled:
        print("OK: live version check skipped because enabled is false")
        return 0
    if not args.live:
        print("OK: live version check skipped (pass --live to enable it)")
        return 0

    # The store only exposes marketing versions here; build numbers stay in the app.
    try:
        live = live_ios_version() if "ios" in cfg else None
    except Exception as exc:
        return fail(f"could not read the live App Store version: {exc}")
    if live:
        live_t = version_tuple(live)
        for key in ("minVersion", "latestVersion"):
            want = version_tuple(cfg["ios"][key])
            if want > live_t:
                return fail(f"ios.{key}={cfg['ios'][key]} is ahead of the live App Store version {live}")
        print(f"OK: iOS {cfg['ios']['minVersion']}..{cfg['ios']['latestVersion']} <= live {live}")
    if "android" in cfg:
        print("OK: Android live check skipped (no public Play listing yet)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
