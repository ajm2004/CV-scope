"""Refresh what the Windows installer downloads: installer/pins.json and installer/constraints.txt.

Run before a release, from the repository root, with uv on PATH:

    python installer/update_pins.py                          # keep the versions, refresh hashes and constraints
    python installer/update_pins.py --torch 2.14.0 --torchvision 0.29.0 --uv 0.12.20 --innosetup 7.1.0

pins.json holds, for each PyTorch build the installer offers (CPU, CUDA 12.6
for NVIDIA GPUs up to the RTX 40 series, CUDA 13.0 for the RTX 50 series), the
wheel URL, size and SHA-256; the installer verifies every download against
them. It also pins uv (which installs Python and the packages) and Inno Setup
(which builds the installer), with their SHA-256.

constraints.txt pins every other Python package to the versions resolved now
for CPython 3.11 on Windows, so each installation gets the set that was
tested at release time instead of whatever is newest on the day it runs.
Review both diffs before committing.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PINS = HERE / "pins.json"
CONSTRAINTS = HERE / "constraints.txt"
PYTHON = "3.11"
CP = "cp311"
# PyTorch builds offered by the installer: CPU, CUDA 12.6 (Maxwell to Ada, sm_50-sm_90),
# CUDA 13.0 (Turing to Blackwell; needed for the RTX 50 series, driver 580 or newer).
VARIANTS = ("cpu", "cu126", "cu130")
# Extras the installer installs (onnx-cpu, export, ultralytics always; llm and postgres on request)
EXTRAS = ("ultralytics", "onnx-cpu", "export", "llm", "postgres")
# Needed to export YOLO weights to ONNX without Ultralytics installing them unpinned at run time
EXTRA_REQUIREMENTS = ("onnx>=1.12,<2", "onnxslim>=0.1.82")
UA = {"User-Agent": "cv-scope-update-pins"}


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        return r.read()


def head_size(url: str) -> int:
    with urllib.request.urlopen(urllib.request.Request(url, method="HEAD", headers=UA), timeout=60) as r:
        return int(r.headers["Content-Length"])


def wheel(package: str, version: str, variant: str) -> dict:
    """URL, SHA-256 and size of the Windows wheel from the PyTorch index."""
    index = f"https://download.pytorch.org/whl/{variant}/{package}/"
    name = f"{package}-{version}+{variant}-{CP}-{CP}-win_amd64.whl"
    html = fetch(index).decode("utf-8", "replace")
    for href in re.findall(r'href="([^"]+)"', html):
        path, _, fragment = href.partition("#")
        if urllib.parse.unquote(path.rsplit("/", 1)[-1]) == name and fragment.startswith("sha256="):
            url = urllib.parse.urljoin(index, path)
            host = urllib.parse.urlsplit(url).hostname or ""
            if not url.startswith("https://") or not (host == "pytorch.org" or host.endswith(".pytorch.org")):
                raise SystemExit(f"{name}: unexpected host in {url}")
            return {"file": name, "url": url, "sha256": fragment.split("=", 1)[1], "size": head_size(url)}
    raise SystemExit(f"{name} is not on {index}; pick versions that exist for every variant ({', '.join(VARIANTS)})")


def uv_pin(version: str) -> dict:
    url = f"https://github.com/astral-sh/uv/releases/download/{version}/uv-x86_64-pc-windows-msvc.zip"
    sha = fetch(url + ".sha256").decode().split()[0].lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise SystemExit(f"unexpected checksum file for uv {version}")
    return {"version": version, "url": url, "sha256": sha}


def innosetup_pin(version: str) -> dict:
    """The x64 Inno Setup installer from its GitHub release; hashed locally."""
    tag = "is-" + version.replace(".", "_")
    name = f"innosetup-{version}-x64.exe"
    url = f"https://github.com/jrsoftware/issrc/releases/download/{tag}/{name}"
    data = fetch(url)
    sha = hashlib.sha256(data).hexdigest()
    # Cross-check with the digest GitHub records for the release asset.
    release = json.loads(fetch(f"https://api.github.com/repos/jrsoftware/issrc/releases/tags/{tag}"))
    digests = {a["name"]: a.get("digest", "") for a in release.get("assets", [])}
    if digests.get(name) and digests[name] != f"sha256:{sha}":
        raise SystemExit(f"{name}: downloaded file does not match the digest of the release asset")
    return {"version": version, "url": url, "sha256": sha}


def compile_constraints(torch: str, torchvision: str) -> str:
    uv = shutil.which("uv")
    if not uv:
        raise SystemExit("uv is needed to resolve the constraints (https://docs.astral.sh/uv/)")
    with tempfile.TemporaryDirectory() as tmp:
        extra = Path(tmp) / "installer-extra.in"
        extra.write_text("\n".join((f"torch=={torch}", f"torchvision=={torchvision}", *EXTRA_REQUIREMENTS)) + "\n", encoding="utf-8")
        cmd = [
            uv, "pip", "compile", "--no-config", "--quiet", str(ROOT / "backend" / "pyproject.toml"), str(extra),
            *[a for e in EXTRAS for a in ("--extra", e)],
            "--python-version", PYTHON, "--python-platform", "x86_64-pc-windows-msvc",
            "--index-url", "https://pypi.org/simple", "--no-annotate", "--no-header",
        ]
        out = subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=ROOT).stdout
    lines = [ln for ln in out.splitlines() if ln.strip() and not ln.startswith("#")]
    header = [
        "# Versions the Windows installer installs (uv pip install -c), resolved for",
        f"# CPython {PYTHON} on Windows x64. torch and torchvision come from the PyTorch",
        "# index in the build chosen in the installer; the local version (+cpu, +cu126, +cu130)",
        "# still matches these pins. Regenerate with: python installer/update_pins.py",
    ]
    return "\n".join(header + lines) + "\n"


def main() -> int:
    current = json.loads(PINS.read_text(encoding="utf-8")) if PINS.exists() else {}
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--torch", default=current.get("torch", {}).get("version"))
    parser.add_argument("--torchvision", default=current.get("torch", {}).get("torchvision"))
    parser.add_argument("--uv", default=current.get("uv", {}).get("version"))
    parser.add_argument("--innosetup", default=current.get("innosetup", {}).get("version"))
    args = parser.parse_args()
    missing = [k for k in ("torch", "torchvision", "uv", "innosetup") if not getattr(args, k)]
    if missing:
        parser.error("give --" + " --".join(missing))

    variants = {v: {"torch": wheel("torch", args.torch, v), "torchvision": wheel("torchvision", args.torchvision, v)} for v in VARIANTS}
    pins = {
        "comment": "Generated by installer/update_pins.py. Everything the Windows installer and its build download, with SHA-256.",
        "generated": dt.datetime.now(dt.UTC).date().isoformat(),
        "python": PYTHON,
        "uv": uv_pin(args.uv),
        "innosetup": innosetup_pin(args.innosetup),
        "torch": {"version": args.torch, "torchvision": args.torchvision, "variants": variants},
    }
    PINS.write_text(json.dumps(pins, indent=2) + "\n", encoding="utf-8")
    CONSTRAINTS.write_text(compile_constraints(args.torch, args.torchvision), encoding="utf-8")
    for v, w in variants.items():
        print(f"{v:6s} torch {w['torch']['size'] / 1e9:5.2f} GB  torchvision {w['torchvision']['size'] / 1e6:5.1f} MB")
    print(f"uv {args.uv}, Inno Setup {args.innosetup}; wrote {PINS.relative_to(ROOT)} and {CONSTRAINTS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
