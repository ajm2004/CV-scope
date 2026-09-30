# Maintaining CV-Scope

How the repository is protected against bad or malicious changes, the GitHub
settings that go with the files in `.github/`, and how to review a pull
request safely.

## How a change reaches `main`

1. A contributor forks the repository and opens a pull request. Nobody
   without write access can push to this repository.
2. For outside contributors, GitHub waits for a maintainer to press
   **Approve and run** before any workflow runs their code.
3. CI runs with a read-only token and no secrets:
   * `repo-guard` rejects keys, licences, databases, model weights, pickles,
     binaries, archives, pictures or videos outside `docs/`, files over
     3 MB, invisible Unicode characters, dependencies from anywhere but PyPI
     and the npm registry, and `pull_request_target`/`workflow_run` workflows
     (`.github/scripts/repo_guard.py`);
   * `backend`: ruff and the full pytest suite;
   * `frontend`: `npm ci --ignore-scripts` (no install scripts run), type
     check, tests, production build;
   * `dependency-review`: fails if the change adds a dependency with a known
     high-severity vulnerability.
4. The branch ruleset requires all four checks, an approving review from a
   code owner (`.github/CODEOWNERS`) given after the last push, resolved
   review threads and an up-to-date branch. It allows squash merges only and
   blocks force pushes and deletion of `main`.
5. Dependabot proposes dependency updates weekly, waiting 7 days after each
   release (`.github/dependabot.yml`).

The checks run the pull request's own version of the workflows and the guard
script. A pull request that edits `.github/` can change what "passed" means,
which is why every file there has a code owner and must be read line by line.

## One-time settings after the first push

1. **Branch ruleset.** Either with the GitHub CLI:

   ```bash
   gh api --method POST repos/ajm2004/CV-Scope/rulesets --input .github/rulesets/protect-main.json
   ```

   or in the browser: **Settings → Rules → Rulesets → New ruleset → Import a
   ruleset**, and choose `.github/rulesets/protect-main.json`. The repository
   administrator is on the bypass list (*Always*): you can push straight to
   `main` and merge your own pull requests without a second reviewer, while
   everyone else must go through a pull request with passing checks and your
   approval. CI still runs on every push to `main`; check the Actions tab
   after pushing. The bypass covers every rule, including force pushes, so
   never use `git push --force` on `main`. For a stricter setup, set the
   bypass to *For pull requests only*: then your own changes also go through
   a pull request, which you can merge without a second reviewer.
2. **Settings → General → Pull Requests:** allow **squash merging** only;
   turn on *Always suggest updating pull request branches* and
   *Automatically delete head branches*.
3. **Settings → Actions → General:**
   * *Actions permissions:* **Allow ajm2004, and select non-ajm2004, actions and
     reusable workflows**, with **Allow actions created by GitHub** ticked
     (the workflows use only `actions/*`). If the page offers *Require
     actions to be pinned to a full-length commit SHA*, tick it.
   * *Approval for running fork pull request workflows from contributors:*
     **Require approval for all external contributors**.
   * *Workflow permissions:* **Read repository contents and packages
     permissions**; untick *Allow GitHub Actions to create and approve pull
     requests*.
4. **Settings → Advanced Security** (or *Code security*): turn on the
   dependency graph, Dependabot alerts, Dependabot security updates, secret
   scanning with push protection, CodeQL **Default setup**, and **Private
   vulnerability reporting** (`SECURITY.md` points reporters there).
5. **Your account:** two-factor authentication with a passkey or security
   key. Give helpers the *Triage* role; anyone with *Write* can approve and
   merge. Add a second code owner to `.github/CODEOWNERS` only when you trust
   them with the whole repository.

## Reviewing a pull request safely

* **Read before you run.** `scripts/setup.*`, `npm install`, `pip install -e`
  and the test suite all execute code from the pull request. Read the diff
  first. If you need to run it, use a throwaway virtual machine or a GitHub
  Codespace, not the computer with your cameras, recordings and keys.
* **Press "Approve and run" only after a first look** at a new contributor's
  pull request, especially at `.github/` and `scripts/`.
* **Read these paths first and completely:** `.github/`, `scripts/`,
  Dockerfiles, `backend/pyproject.toml`, `frontend/package.json` and
  `package-lock.json`, `backend/pathscope/models/catalog.py` and
  `backend/pathscope/recognition/catalog.py`. The catalogs hold the download
  URLs of model weights, and downloads are not checksum-verified: a changed
  URL can deliver a `.pt` file, which is a Python pickle that runs code when
  it is loaded.
* **Red flags:** new URLs or hosts; long base64 or hex strings; minified,
  generated or oddly formatted code; `eval`, `exec`, `subprocess`, `pickle`,
  `torch.load`, `os.system`; tests changed so they assert less; a lockfile
  change without a matching `package.json` change (ask the contributor to
  drop it and regenerate it yourself); a "typo fix" that also touches CI; a
  large reformatting that hides a small change.
* **Merge what you reviewed.** If commits arrive after your review, the
  ruleset dismisses your approval; use *Files changed → Changes since your
  last review* before approving again.
* **Dependabot pull requests** get the same care: read the release notes of
  major updates, and do not merge a dependency you cannot explain.

## Releasing the Windows installer

The installer (`installer/`, described in `installer/README.md`) is built
and published by `.github/workflows/installer.yml` when a `v*` tag is pushed:

1. Before a release, run `python installer/update_pins.py` (uv on PATH) and
   review the diff of `installer/pins.json` and `installer/constraints.txt`:
   they fix what every installation downloads, including the SHA-256 of the
   PyTorch wheels, uv and Inno Setup. A changed URL or hash deserves the same
   care as a new dependency.
2. Set the version in `backend/pyproject.toml` and
   `backend/pathscope/__init__.py`, and merge.
3. `git tag vX.Y.Z` on that commit and `git push origin vX.Y.Z`. The
   workflow checks that the tag matches the version, builds the installer on
   a clean Windows runner, installs, starts, benchmarks and uninstalls it
   (`installer/smoke_test.ps1`), then creates the release with
   `CV-Scope-Setup-Windows-x64.exe` and `SHA256SUMS.txt`. Only that last job
   has `contents: write`, which it requests itself; the repository default
   stays read-only.
4. The website and the README link to
   `releases/latest/download/CV-Scope-Setup-Windows-x64.exe` and
   `.../SHA256SUMS.txt`: never rename these assets, and publish releases (not
   drafts) so that *latest* points at them.

`installer/` is owned by the code owners like `scripts/`: the installer
runs on users' machines and decides what they download.

## If something bad was merged

Revert it with a pull request (`git revert <commit>`), check the Actions logs
of the runs that included it, and if a release or users were affected,
publish a security advisory from the Security tab. The repository holds no
secrets, so there is nothing to rotate unless one was committed by mistake;
in that case revoke it first, then clean the history.
