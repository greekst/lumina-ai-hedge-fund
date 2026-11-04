#!/usr/bin/env python3
"""
check_no_secrets.py — Hard rule 2: fail loudly if a secret appears in git.

Scans (default) the staged diff, or with --all every tracked file, or with
--range A..B the diff of a commit range. Two detectors:
  1. Known key formats (Google/OpenAI/Anthropic/GitHub/AWS/Slack/private keys, ...).
  2. The literal values of secret-looking env vars present in this process
     (names ending in _API_KEY, _SECRET, _TOKEN, _PASSWORD) — catches a pasted key
     of any format. Values are never printed, only the variable name.
Exit code 1 on any finding.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from typing import Iterable, List, Tuple

PATTERNS = {
    "google_api_key": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    "openai_key": re.compile(r"(?<![A-Za-z0-9])sk-(?:proj-)?[A-Za-z0-9_\-]{32,}"),
    "anthropic_key": re.compile(r"(?<![A-Za-z0-9])sk-ant-[A-Za-z0-9_\-]{20,}"),
    "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
    "aws_access_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "slack_token": re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),
    "private_key_block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "discord_webhook": re.compile(r"https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_\-]+"),
    "generic_assignment": re.compile(
        r"(?i)\b(?:api[_-]?key|secret|token|password)\b\s*[:=]\s*['\"]([A-Za-z0-9_\-/+]{24,})['\"]"
    ),
}
SECRET_ENV = re.compile(r"(?:_API_KEY|_SECRET|_TOKEN|_PASSWORD|_SECRET_KEY)$")
ALLOW_FILES = {"scripts/check_no_secrets.py", "tests/test_secret_guard.py"}
FORBIDDEN_PATHS = re.compile(r"(^|/)(\.env|\.env\.local|config/settings\.json)$|\.(db|sqlite3?)$")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False).stdout


def _env_secret_values() -> List[Tuple[str, str]]:
    out = []
    for name, val in os.environ.items():
        if SECRET_ENV.search(name) and val and len(val) >= 12:
            out.append((name, val))
    return out


def scan_text(path: str, text: str, env_secrets: Iterable[Tuple[str, str]]) -> List[str]:
    if path in ALLOW_FILES:
        return []
    findings = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for name, rx in PATTERNS.items():
            if rx.search(line):
                findings.append(f"{path}:{lineno}: matches pattern '{name}'")
        for env_name, val in env_secrets:
            if val in line:
                findings.append(f"{path}:{lineno}: contains the value of ${env_name}")
    return findings


def _added_lines_by_file(diff: str) -> List[Tuple[str, str]]:
    files, cur, buf = [], None, []
    for line in diff.splitlines():
        if line.startswith("+++ "):
            if cur is not None:
                files.append((cur, "\n".join(buf)))
            cur = line[6:] if line.startswith("+++ b/") else line[4:]
            buf = []
        elif line.startswith("+") and not line.startswith("+++"):
            buf.append(line[1:])
    if cur is not None:
        files.append((cur, "\n".join(buf)))
    return files


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--all", action="store_true", help="scan every tracked file")
    g.add_argument("--range", help="scan the diff of a commit range, e.g. origin/main..HEAD")
    args = ap.parse_args(argv)

    env_secrets = _env_secret_values()
    findings: List[str] = []

    tracked = _git("ls-files").splitlines()
    for p in tracked:
        if FORBIDDEN_PATHS.search(p):
            findings.append(f"{p}: file type must never be tracked (.env / settings.json / *.db)")

    if args.all:
        for p in tracked:
            try:
                with open(p, "r", encoding="utf-8") as fh:
                    findings += scan_text(p, fh.read(), env_secrets)
            except (UnicodeDecodeError, IsADirectoryError, FileNotFoundError):
                continue
    else:
        diff = _git("diff", args.range) if args.range else _git("diff", "--cached")
        for p, added in _added_lines_by_file(diff):
            findings += scan_text(p, added, env_secrets)

    if findings:
        print("SECRET GUARD FAILED — refusing to proceed:", file=sys.stderr)
        for f in findings:
            print("  " + f, file=sys.stderr)
        return 1
    print(f"secret guard: OK ({'all tracked files' if args.all else args.range or 'staged diff'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
