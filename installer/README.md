# Windows installer

`CV-Scope-Setup-Windows-x64.exe` is a small (about 15 MB) online installer
built with [Inno Setup](https://jrsoftware.org/isinfo.php) 7. It carries the
application source, the built web interface and [uv](https://docs.astral.sh/uv/),
and downloads the rest on the user's computer: a private CPython, PyTorch for
the processor or NVIDIA graphics card, the Python packages, the chosen models
and the sample videos. The user-facing guide is
[docs/install-windows.md](../docs/install-windows.md).

| File | Purpose |
| --- | --- |
| `cvscope.iss` | The installer: wizard pages, components, download and installation steps, uninstall |
| `build.ps1` | Builds the installer (web interface, uv, pictures, pins, compiler) |
| `pins.json` | Everything the installer and its build download, with SHA-256: the PyTorch wheels per build, uv, Inno Setup |
| `constraints.txt` | The versions of every other Python package the installer installs |
| `update_pins.py` | Regenerates `pins.json` and `constraints.txt` |
| `make_assets.py` | Draws the icon and the wizard pictures (kept out of the repository as binaries) |
| `smoke_test.ps1` | Installs a build silently, starts it, runs a benchmark and uninstalls it |

The launcher that the shortcuts start is part of the Python package:
`backend/pathscope/launcher.py` (`pythonw -m pathscope.launcher`, or
`cvscope launch` from a terminal).

## Build it

On Windows with Node 20+ and an internet connection:

```powershell
powershell -ExecutionPolicy Bypass -File installer\build.ps1
```

The result is `installer\build\output\CV-Scope-Setup-Windows-x64.exe` with
`SHA256SUMS.txt`. The script builds the web interface (`npm ci`,
`npm run build`; `-SkipFrontend` reuses `frontend\dist`), downloads uv and,
when no `ISCC.exe` is found (`-Iscc` names one), a portable Inno Setup into
`installer\build`, checking both against `pins.json`. Nothing is installed
system-wide.

Test a build without touching your own installation: install it into a
scratch folder, which also installs a Start-menu entry that the uninstaller
removes again.

```powershell
powershell -ExecutionPolicy Bypass -File installer\smoke_test.ps1 -Installer installer\build\output\CV-Scope-Setup-Windows-x64.exe
```

## Release it

1. Refresh the pins if dependencies or PyTorch moved on, and review the diff:
   `python installer/update_pins.py` (add `--torch X --torchvision Y`,
   `--uv Z`, `--innosetup W` to change versions; uv must be on PATH).
2. Set the version in `backend/pyproject.toml` (and `pathscope/__init__.py`)
   and merge.
3. Tag the merge commit and push the tag: `git tag v0.2.0 && git push origin v0.2.0`.
4. The **Windows installer** workflow (`.github/workflows/installer.yml`)
   builds the installer on a clean Windows runner, runs `smoke_test.ps1`, and
   creates the GitHub Release with `CV-Scope-Setup-Windows-x64.exe` and
   `SHA256SUMS.txt`. The website and the README link to
   `releases/latest/download/<asset>`, so these names must not change.

The workflow can also be started by hand (**Actions → Windows installer →
Run workflow**) to build and test without publishing; the installer is then
an artifact of the run.

## How it works

* **Per-user, no administrator rights.** Installs to
  `%LOCALAPPDATA%\Programs\CV-Scope`; data goes to `%LOCALAPPDATA%\CV-Scope`
  or the folder chosen in Setup, recorded as `PATHSCOPE_DATA_DIR` in the
  installation's `.env`. The backend is installed editable
  (`pip install -e backend`) because it finds `frontend\dist`, `.env` and the
  migrations relative to its source folder.
* **PyTorch is downloaded, not bundled.** The CUDA build is 2.6 GB, above
  GitHub's 2 GB limit per release asset. Setup picks the build from
  `nvidia-smi`: CUDA 12.6 for compute capability 5.0 to 9.x (GTX 900 to
  RTX 40, driver 528+), CUDA 13.0 for 10.0 and newer (RTX 50, driver 580+),
  otherwise the CPU build. The wheels are downloaded before anything is
  installed (progress, Abort, SHA-256 from `pins.json`) and then installed
  with the other packages in one `uv pip install -c constraints.txt`.
  Updates reuse an installed PyTorch of the same version and build.
* **Private Python.** `uv python install --no-bin --no-registry` puts CPython
  in the installation folder without changing PATH or the registry. Setup
  sets `RedirectionGuard=no`: with Inno Setup's default, uv cannot use the
  junction it creates for the Python version (error 448). The guard protects
  elevated installers, and this one never elevates.
* **Models** are installed with `cvscope models install <ids>` (the same code
  as the Models page), local vision models with `cvscope anomaly setup-local`.
  Their failures do not fail Setup: its last page lists them, and the exit
  code is 11. `backend/tests/test_installer.py` fails when a catalog model
  has no installer component.
* **The launcher** starts the server with `pythonw`, without a console window,
  and tells it to stop over a loopback connection. A Windows job object ends
  the server and its camera workers if the launcher is killed. The launcher
  holds the `CV-Scope-Launcher` mutex, which Setup and Uninstall check.

## Code signing

The installer is not code-signed, so Windows SmartScreen warns on first
start until the file has built up reputation. Signing needs a certificate:
open-source projects can apply for free signing at
[SignPath Foundation](https://signpath.org), or use Azure Trusted Signing.
Sign `CV-Scope-Setup-Windows-x64.exe` after `build.ps1` and before the
checksum is written (Inno Setup's `SignTool` directive can also sign the
uninstaller).
