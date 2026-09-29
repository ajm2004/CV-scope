# Contributing to CV-Scope

Thank you for considering a contribution. CV-Scope is a research and
monitoring platform; changes that make it more truthful, more robust or easier
to use for non-programmers are the most valuable ones.

## Ground rules

* Keep the layers separate: detectors and trackers know nothing about scenes,
  the spatial engine knows only geometry, the rule engine assigns meaning, and
  analytics only read stored events (see `docs/architecture.md`).
* Never fabricate numbers. Accuracy, FPS and load figures come from local
  measurements or manual verdicts, or they are labelled as estimates.
* No face recognition, re-identification across sessions, or identity storage.
* Anything unfinished is marked as such in the UI rather than simulated.

## Development setup

```
bash scripts/setup.sh        # or scripts\setup.ps1 on Windows
bash scripts/dev.sh          # API on :8420, frontend on :5173
```

Backend tests and linting:

```
.venv/bin/python -m pytest backend/tests
.venv/bin/python -m ruff check backend
```

Frontend type-check and build:

```
cd frontend && npm run typecheck && npm run build
```

## Database changes

Edit `backend/pathscope/db/models.py`, then create a migration:

```
cd backend && ../.venv/bin/alembic revision --autogenerate -m "describe change"
```

Review the generated file (SQLite needs `render_as_batch`, already enabled)
and commit it under `backend/alembic/versions/`.

## Adding a detector provider

1. Implement `pathscope.vision.detectors.base.Detector` in a new module.
2. Register it in `pathscope/vision/detectors/__init__.py`.
3. Add catalog entries in `pathscope/models/catalog.py` with honest licence
   and requirement information.
4. Add the runtime to `pathscope/vision/inference/runtime.py` if it needs
   a new probe.

## Adding a tracker

Implement `pathscope.vision.trackers.base.Tracker` and register it in
`pathscope/vision/trackers/__init__.py` together with its user-facing
settings.

## Pull requests

* Fork the repository and open the pull request from a branch of your fork.
  For anything larger than a fix, open an issue first so the approach can be
  agreed before you write the code.
* One topic per pull request, with tests for engine or API changes.
* Describe the observable behaviour change and how you verified it (the
  pull request template asks for it).
* Update the documentation under `docs/` when behaviour or setup changes.

### What CI checks, and what is not accepted

Every pull request must pass four checks before it can be merged:
`repo-guard`, `backend` (ruff and pytest), `frontend` (type check, tests,
build) and `dependency-review`. For first-time contributors the checks start
after a maintainer has looked at the change. Then a code owner reviews it,
and it is squash-merged.

Not accepted, and rejected by `repo-guard` where it can tell:

* binaries, model weights (`.pt`, `.onnx`, ...), pickles, archives,
  generated or minified code;
* pictures or videos outside `docs/`, and any material showing real people,
  places or number plates without their consent;
* keys, licence files, `.env` files, databases or exported data;
* dependencies installed from a URL or git instead of PyPI or npm, and new
  dependencies without an explanation in the pull request;
* invisible Unicode characters (bidirectional controls, zero-width spaces);
* unrelated changes to `.github/`, `scripts/`, Dockerfiles or the lockfile.

Maintainers: see `docs/maintainers.md` for the repository settings and how
pull requests are reviewed.
