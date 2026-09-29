# CV-Scope backend

The FastAPI server, vision pipeline, engines, migrations and command line of
[CV-Scope](../README.md), a computer-vision monitoring and research platform
for fixed cameras.

The Python package is called `pathscope` (the project's earlier name); the
command line is `cvscope` (`pathscope` still works as an alias), and
`python -m pathscope` runs the same command line.

```bash
pip install -e "backend[ultralytics,onnx-cpu,export,dev]"
cvscope migrate
cvscope serve            # http://127.0.0.1:8420
cvscope --help           # hardware, models, benchmark, recognition, anomaly
```

Tests: `python -m pytest backend/tests`. See `docs/developer.md` for the code
layout and `docs/installation.md` for full setups.
