"""Repository guard, run by CI on every pull request and push.

Fails when the tracked files contain something that can hide code or leak data:

* secrets, licences and local data (keys, .env, licence files, databases);
* files that execute or unpickle code when used (model weights, pickles,
  binaries, archives, packages);
* pictures or videos outside the documentation (personal recordings, camera
  frames, or payloads disguised as media);
* very large files;
* invisible Unicode (bidirectional controls, zero-width characters) that can
  make code read differently from how it runs ("Trojan Source");
* dependencies from anywhere but PyPI and the npm registry, and dangerous
  GitHub Actions triggers.

Usage: python .github/scripts/repo_guard.py   (from the repository root)
"""

from __future__ import annotations

import fnmatch
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

MAX_BYTES = 3 * 1024 * 1024

FORBIDDEN = {
    "secret, licence or local data": [
        "*.key", "*.pem", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*", ".env", ".env.*",
        "license.json", "licence.json", "*.license.json", "*.licence.json",
        "*.db", "*.db-wal", "*.db-shm", "*.sqlite", "*.sqlite3",
    ],
    "executable, pickled or packaged content": [
        "*.pt", "*.pth", "*.ckpt", "*.pkl", "*.pickle", "*.joblib", "*.npy", "*.npz",
        "*.onnx", "*.engine", "*.tflite", "*.safetensors", "*.h5", "*.bin",
        "*.exe", "*.dll", "*.so", "*.dylib", "*.msi", "*.bat", "*.cmd", "*.scr", "*.jar", "*.whl",
        "*.zip", "*.7z", "*.rar", "*.tar", "*.gz", "*.tgz", "*.xz", "*.bz2",
    ],
}
ALLOWED_FORBIDDEN = {".env.example"}

MEDIA = ["*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.bmp", "*.tif", "*.tiff", "*.heic", "*.ico", "*.svg",
         "*.mp4", "*.webm", "*.avi", "*.mkv", "*.mov", "*.m4v", "*.h264", "*.mp3", "*.wav"]
MEDIA_ALLOWED_UNDER = ("docs/", "frontend/public/")

TEXT_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".json", ".md", ".css", ".html", ".toml",
                 ".ini", ".cfg", ".yml", ".yaml", ".sh", ".ps1", ".txt", ".mako", ".example", ".iss", ""}
# Bidirectional controls, zero-width and invisible characters (U+FEFF only allowed as a leading BOM).
HIDDEN_CODEPOINTS = (*range(0x202A, 0x202F), *range(0x2066, 0x206A), *range(0x200B, 0x200E),
                     *range(0x2060, 0x2065), 0xFEFF, 0x00AD)
HIDDEN = re.compile("[" + "".join(map(chr, HIDDEN_CODEPOINTS)) + "]")
BOM = chr(0xFEFF)

DANGEROUS_TRIGGERS = re.compile(r"^\s*(pull_request_target|workflow_run)\s*:", re.MULTILINE)


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], check=True, capture_output=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def matches(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(name.lower(), p) for p in patterns)


def main() -> int:
    errors: list[tuple[str, str]] = []
    files = tracked()
    for path in files:
        p = Path(path)
        if not p.is_file():
            continue  # deleted in the working tree
        name = p.name
        if name not in ALLOWED_FORBIDDEN:
            for reason, patterns in FORBIDDEN.items():
                if matches(name, patterns):
                    errors.append((path, f"{reason} must not be committed"))
        if matches(name, MEDIA) and not path.startswith(MEDIA_ALLOWED_UNDER):
            errors.append((path, "pictures and videos belong under docs/ (demo material only)"))
        size = p.stat().st_size
        if size > MAX_BYTES:
            errors.append((path, f"file is {size / 1024 / 1024:.1f} MB; the limit is {MAX_BYTES // 1024 // 1024} MB"))
        if p.suffix.lower() in TEXT_SUFFIXES and size <= MAX_BYTES:
            try:
                text = p.read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                errors.append((path, "text file is not valid UTF-8"))
                continue
            m = HIDDEN.search(text, 1 if text.startswith(BOM) else 0)
            if m:
                line = text.count("\n", 0, m.start()) + 1
                errors.append((f"{path}:{line}", f"invisible character U+{ord(m.group()):04X}"))

    lock = Path("frontend/package-lock.json")
    if lock.is_file():
        data = json.loads(lock.read_text(encoding="utf-8"))
        for key, pkg in data.get("packages", {}).items():
            resolved = pkg.get("resolved")
            if resolved and not resolved.startswith("https://registry.npmjs.org/"):
                errors.append((str(lock), f"{key or 'root'} resolves outside the npm registry: {resolved}"))
    pkg_json = Path("frontend/package.json")
    if pkg_json.is_file():
        data = json.loads(pkg_json.read_text(encoding="utf-8"))
        for section in ("dependencies", "devDependencies", "optionalDependencies"):
            for dep, spec in data.get(section, {}).items():
                if re.match(r"^(git|http|https|file|link|github):|/", spec) or "://" in spec:
                    errors.append((str(pkg_json), f"{dep} is not installed from the npm registry: {spec}"))
    pyproject = Path("backend/pyproject.toml")
    if pyproject.is_file():
        project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {})
        reqs = list(project.get("dependencies", []))
        for extra in project.get("optional-dependencies", {}).values():
            reqs += extra
        for req in reqs:
            if "@" in req or "://" in req:  # PEP 508 direct reference (URL, git, local path)
                errors.append((str(pyproject), f"dependency must come from PyPI, not a URL: {req}"))

    for wf in sorted(Path(".github/workflows").glob("*.y*ml")):
        if DANGEROUS_TRIGGERS.search(wf.read_text(encoding="utf-8")):
            errors.append((str(wf), "pull_request_target / workflow_run run with repository secrets; not allowed"))

    for where, msg in errors:
        file, _, line = where.partition(":")
        loc = f"file={file}" + (f",line={line}" if line else "")
        print(f"::error {loc}::{msg}")
    print(f"repo guard: {len(files)} tracked files, {len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
