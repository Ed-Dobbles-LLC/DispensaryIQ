#!/usr/bin/env python3
"""CI guard (brief #392): fail the build if an admin-key literal is committed.

This repo (`DispensaryIQ`) is a pure static site served by Caddy — everything
under `site/` ships verbatim to any browser. `site/cpo.html` and
`site/status.html` collect an admin key from an operator (prompt/password
field) and forward it as the `X-Admin-Key` header to the external
dip-service API; no key value is currently hardcoded there, but this guard
exists so a future "quick fix" default never lands one. Companion to the
same guard added in dip-service, which found and scrubbed a real leaked key
literal in a docs file (`docs/RUNBOOK_autonomous_execution.md`).

Usage: python3 scripts/admin_key_guard.py [path ...]   (default: repo root)
Exit 0 = clean, exit 1 = literal-looking key value found (build fails).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

EXCLUDE_DIR_NAMES = {".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache"}
EXCLUDE_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".ttf",
    ".pdf", ".svg", ".lock",
}
# This guard's own patterns would otherwise flag its docstring/allowlist.
EXCLUDE_FILES = {"scripts/admin_key_guard.py"}

# A captured value counts as a safe placeholder/reference, not a real secret.
_PLACEHOLDER_RE = re.compile(
    r"^(<|\$\{?\w|os\.environ|ADMIN_API_KEY$|ADMIN_KEYS$|admin_key$|x_admin_key$|"
    r"replace[-_]|your[-_]|xxx+|\.\.\.|change[-_]?me|example|testkey|test-key|"
    r"old-key|new-key|anything$|badkey$|wrong$|invalid$)",
    re.IGNORECASE,
)

# `x-admin-key: <value>` or `"X-Admin-Key": "<value>"` — the header name
# immediately followed by a literal, anywhere (docs, code, config). Real
# secrets run longer than 5 chars; a 6-char floor keeps short test fixture
# words like "wrong" out without needing to enumerate every one.
_HEADER_RE = re.compile(r"x-admin-key[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9_.\-]{6,})", re.IGNORECASE)

# Only meaningful as a literal-value assignment outside Python source, where
# `ADMIN_API_KEY=...`/`ADMIN_KEYS=...` is env-file/shell/yaml syntax rather
# than a `os.environ.get(...)` read.
_ENV_ASSIGN_RE = re.compile(r"^\s*ADMIN_(?:API_)?KEYS?\s*=\s*([A-Za-z0-9_.,\-]{6,})", re.MULTILINE)
_ENV_ASSIGN_SUFFIXES = {".env", ".yml", ".yaml", ".sh", ".txt", ""}


def _scan_text(path: Path, text: str) -> list[str]:
    hits: list[str] = []
    for m in _HEADER_RE.finditer(text):
        value = m.group(1)
        if _PLACEHOLDER_RE.match(value):
            continue
        line_no = text.count("\n", 0, m.start()) + 1
        hits.append(f"{path}:{line_no}: literal-looking value next to x-admin-key: {value!r}")

    if path.suffix in _ENV_ASSIGN_SUFFIXES and path.name != ".env.example":
        for m in _ENV_ASSIGN_RE.finditer(text):
            value = m.group(1)
            if _PLACEHOLDER_RE.match(value):
                continue
            line_no = text.count("\n", 0, m.start()) + 1
            hits.append(f"{path}:{line_no}: literal-looking ADMIN_KEYS/ADMIN_API_KEY assignment: {value!r}")
    return hits


def scan_file(path: Path) -> list[str]:
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return []
    return _scan_text(path, text)


def iter_files(target: Path):
    if target.is_file():
        yield target
        return
    for path in target.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDE_DIR_NAMES for part in path.parts):
            continue
        if path.suffix.lower() in EXCLUDE_SUFFIXES:
            continue
        rel = path.relative_to(REPO_ROOT) if REPO_ROOT in path.parents or path.parent == REPO_ROOT else path
        if str(rel) in EXCLUDE_FILES:
            continue
        yield path


def main() -> int:
    targets = [Path(t) for t in sys.argv[1:]] or [REPO_ROOT]
    all_hits: list[str] = []
    for target in targets:
        base = target if target.is_absolute() else REPO_ROOT / target
        for path in iter_files(base):
            all_hits.extend(scan_file(path))

    if all_hits:
        print("ADMIN KEY GUARD: literal-looking admin key value(s) found — do not commit real keys:")
        for hit in all_hits:
            print(f"  {hit}")
        return 1

    print("ADMIN KEY GUARD: clean — no literal admin-key values found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
