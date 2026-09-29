# Installation

CV-Scope runs locally without any cloud service. The backend is a Python
FastAPI application; the frontend is a React application served by Vite in
development or bundled into the backend in production and Docker builds.

## Requirements

| Component | Requirement |
| --- | --- |
| Python | 3.11 or newer (3.11 tested) |
| Node | 20 or newer (for the frontend build) |
| Operating system | Windows 10/11, Linux, macOS |
| GPU (optional) | NVIDIA GPU with a driver supporting CUDA 12.6 or newer; Apple silicon (Metal) is supported through PyTorch MPS |
| Disk | 3–5 GB for Python packages with CUDA PyTorch, plus model weights (5–130 MB each) |

## Scripted setup (recommended)

```
bash scripts/setup.sh              # Linux / macOS
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1   # Windows
```

The script creates `.venv`, installs the CUDA build of PyTorch when
`nvidia-smi` is present (CPU build otherwise, `--cpu` forces it), installs the
backend with the `ultralytics`, `onnx-cpu`, `export` and `dev` extras, installs
the frontend packages, applies database migrations, downloads the sample
videos and prints the hardware summary.

Start everything with `bash scripts/dev.sh` (or `scripts\dev.ps1`) and open
http://localhost:5173.

## Manual setup

### CPU-only

```
python -m venv .venv
. .venv/bin/activate                     # Windows: .venv\Scripts\activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install -e "backend[ultralytics,onnx-cpu,export,dev]"
cd frontend && npm install && cd ..
cvscope migrate
cvscope serve                          # API on http://127.0.0.1:8420
cd frontend && npm run dev               # UI on http://localhost:5173
```

### NVIDIA GPU (CUDA)

Install a CUDA build of PyTorch instead of the CPU build:

```
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
```

Then continue as above. The Hardware page shows whether CUDA is available to
PyTorch. For ONNX Runtime with CUDA or TensorRT execution providers, install
`onnxruntime-gpu` instead of `onnxruntime` (never both):

```
pip install -e "backend[ultralytics,onnx-gpu,export]"
```

TensorRT engines are used through ONNX Runtime when the TensorRT execution
provider is available in your `onnxruntime-gpu` build.

### Apple silicon

`pip install torch torchvision` (default wheels) provides Metal (MPS)
acceleration. Choose device `auto` or `mps`.

### Without Ultralytics (permissive licences only)

Skip the `ultralytics` extra. The torchvision detectors (BSD-3-Clause) and any
ONNX model you export elsewhere remain available. See `docs/models.md`.

### Licensed recognition modules

Nothing extra is required to install CV-Scope: the face and plate
recognition modules stay locked until a signed licence is installed
(`docs/recognition.md`). When licensed, the default face stack runs on
OpenCV alone; the plate models and the InsightFace face stack need ONNX
Runtime (the `onnx-cpu` or `onnx-gpu` extra, which the setup scripts already
install). The licensed build sets `PATHSCOPE_RECOGNITION_ISSUER_KEYS` (the
issuer's public key, not a secret) and, optionally,
`PATHSCOPE_RECOGNITION_KEY_DIR` to keep the encryption keys of biometric
templates on another volume.

## Production build (single process)

```
cd frontend && npm run build && cd ..
cvscope serve --host 0.0.0.0 --port 8420
```

When `frontend/dist` exists the API serves the UI at the root URL.

## Docker

```
docker compose up                        # CPU image
docker compose --profile gpu up cvscope-gpu   # NVIDIA image; needs the NVIDIA Container Toolkit
docker compose --profile postgres up     # adds a PostgreSQL service
```

Data (database, uploaded videos, model weights) lives in the `cvscope-data`
volume. To use videos already on the host, mount a folder (see the commented
line in `docker-compose.yml`) and register the file from the Cameras page.
USB cameras require device pass-through (`--device /dev/video0`) on Linux.

## Configuration

Copy `.env.example` to `.env` and edit as needed. Every value is optional.

| Variable | Default | Meaning |
| --- | --- | --- |
| `PATHSCOPE_DATA_DIR` | `./data` | Database, videos, models, exports, logs |
| `PATHSCOPE_DATABASE_URL` | SQLite in the data directory | Any SQLAlchemy URL, e.g. `postgresql+psycopg://user:pass@host:5432/pathscope` (install the `postgres` extra) |
| `PATHSCOPE_HOST` / `PATHSCOPE_PORT` | `127.0.0.1` / `8420` | API bind address |
| `PATHSCOPE_CORS_ORIGINS` | Vite dev origins | Allowed browser origins |
| `PATHSCOPE_DEVICE` | `auto` | Default inference device |
| `PATHSCOPE_MODELS_DIR` | `<data>/models` | Where weights are stored |
| `PATHSCOPE_STORE_TRAJECTORIES` | `true` | Store sampled trajectories |
| `PATHSCOPE_KEEP_SOURCE_VIDEO` | `true` | Keep uploaded videos |
| `PATHSCOPE_RETENTION_DAYS` | `0` | Event retention (0 = forever) |
| `PATHSCOPE_LOG_LEVEL` / `PATHSCOPE_LOG_FORMAT` | `info` / `console` | Structured logging |

Settings that do not need a restart (presets, preview rate, retention,
export format, logging level for new workers) are edited on the Settings page.

## Database migrations

Migrations run automatically when the API starts. To run them manually:

```
cvscope migrate
```

PostgreSQL and SQLite use the same migration files.

## Verifying the installation

```
cvscope hardware            # hardware probe and recommendations
cvscope models list         # catalog with install state
cvscope models install yolo11n
cvscope benchmark yolo11n --video samples/videos/people-detection.mp4
python -m pytest backend/tests
```

## Troubleshooting

* **CUDA not available although an NVIDIA GPU is present.** The installed
  PyTorch is a CPU build. Reinstall from the `cu126` index (see above) and
  check the Hardware page.
* **`opencv` cannot open a video.** Convert it to H.264 MP4 (`ffmpeg -i in.avi
  -c:v libx264 out.mp4`). Browser playback in the review page also needs
  H.264/VP9.
* **RTSP stream connects but no frame arrives.** Use TCP transport (default),
  check the stream path in the camera's documentation and its concurrent
  viewer limit. The connection test on the Cameras page reports the failing
  stage.
* **USB camera is busy.** Close other applications that use it; on Windows
  only one process can open a camera at a time.
* **USB camera runs at only ~5 fps at 720p or 1080p.** The camera is sending
  uncompressed video, which USB 2.0 cannot carry at full rate. On Windows
  CV-Scope opens webcams through Media Foundation, which negotiates a
  compressed format (a Logitech Brio 100 went from 4.8 to 30 fps at 720p),
  and falls back to DirectShow. CV-Scope sets
  `OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS=0` when it starts; with that
  variable set to 1, opening a camera takes about 20 seconds. On Linux,
  CV-Scope asks V4L2 for MJPG.
