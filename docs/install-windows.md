# Install CV-Scope on Windows

The Windows installer sets up everything CV-Scope needs in one go: a private
copy of Python, PyTorch for your processor or NVIDIA graphics card, the
detection models you pick and the sample videos. You do not need Python,
Node.js or Git, and you do not need administrator rights.

**Download:** [CV-Scope-Setup-Windows-x64.exe](https://github.com/ajm2004/CV-Scope/releases/latest/download/CV-Scope-Setup-Windows-x64.exe)
(about 16 MB) from the [latest release](https://github.com/ajm2004/CV-Scope/releases/latest).
Setup downloads the rest while it installs.

## Requirements

| | |
| --- | --- |
| Windows | Windows 10 version 1809 or newer, or Windows 11, 64-bit (x64). Windows on Arm is not supported. |
| Disk space | About 2 GB when CV-Scope runs on the processor, about 5 GB with NVIDIA graphics card support (plus 2.6 GB of temporary space on the system drive while installing), plus the models you choose (6 MB to 1.6 GB) and room for your videos and recordings. Setup checks the free space before it downloads anything. |
| Memory | 8 GB; 16 GB recommended for several cameras or the larger models. |
| Internet | Needed while installing. Setup downloads about 0.5 GB for the processor build or about 3 GB for an NVIDIA graphics card, plus the models you choose. Afterwards CV-Scope works offline. |
| NVIDIA graphics card (optional) | GeForce GTX 900 series or newer. GTX 900 to RTX 40 series: NVIDIA driver 528 or newer. RTX 50 series: driver 580 or newer. The CUDA Toolkit is **not** needed; PyTorch brings what it uses. AMD and Intel graphics are not used for detection: CV-Scope then runs on the processor, which works on any computer but detects more slowly. |
| Nothing else | No Python, Node.js, Git or Docker. No administrator rights: everything goes into your user profile. |

## 1. Download and check the installer

Download `CV-Scope-Setup-Windows-x64.exe` from the link above. Each release
also has a `SHA256SUMS.txt`. To check that the download is complete and
unchanged, open PowerShell in your Downloads folder and run

```powershell
(Get-FileHash .\CV-Scope-Setup-Windows-x64.exe -Algorithm SHA256).Hash
```

The result must match the value in `SHA256SUMS.txt` (upper or lower case
does not matter).

## 2. Start it (Windows SmartScreen)

The installer is not signed with a paid code-signing certificate yet, so
Windows may show **"Windows protected your PC"** when you open it. Click
**More info**, check that the app is `CV-Scope-Setup-Windows-x64.exe`, then
click **Run anyway**. If you want to be sure first, compare the checksum as
shown above.

## 3. Follow the setup wizard

1. **Welcome**: a summary of what Setup downloads.
2. **Destination**: where the application goes. The default,
   `%LOCALAPPDATA%\Programs\CV-Scope`, is right for almost everyone.
3. **Graphics card**: Setup looks for an NVIDIA graphics card and names the
   one it found. Choose **Use the NVIDIA graphics card** when it is offered
   (detection is several times faster), or **Use the processor only**. If the
   driver is too old, Setup says so; update it from nvidia.com/drivers and run
   Setup again.
4. **Components**: pick a preset or tick exactly what you want.

   | Preset | What it installs |
   | --- | --- |
   | Recommended | The application, the YOLO11n, s and m detectors (small, balanced and accurate), the sample videos and Claude support for the Anomaly Assistant |
   | All CV-Scope models | Every detector (YOLO11, YOLOv8, RT-DETR, ONNX versions, torchvision), the tracker's appearance model and the face and plate recognition models |
   | Minimal | The application only; download models later on the Models page |

   Optional extras: the face and plate recognition models (they are used only
   with a recognition licence; the InsightFace models are for non-commercial
   research only), a PostgreSQL driver, and a **local vision model for the
   Anomaly Assistant**, which installs [Ollama](https://ollama.com) and
   downloads the chosen model (1.7 to 6 GB).
5. **Data folder**: where CV-Scope keeps its database, videos, recordings,
   exports and downloaded models. The default is `%LOCALAPPDATA%\CV-Scope`.
   Choose a drive with room for recordings, and avoid folders that OneDrive or
   Dropbox synchronise (Setup warns you): synchronising the database while
   CV-Scope uses it can damage it.
6. **Shortcuts**: a desktop shortcut if you want one. The Start-menu entry is
   always created.
7. **Ready to install**: a summary with the total download size. Click
   **Install**.
8. **Downloading PyTorch**: the largest download, with a progress bar and an
   **Abort** button. Nothing has been installed yet at this point; after an
   abort or a network error you can click Install again.
9. **Installing**: Setup copies CV-Scope, installs Python and the packages,
   creates the database and downloads your models. This takes a few minutes;
   the line under the progress bar shows what it is doing.
10. **Finished**: leave **Start CV-Scope now** ticked and click Finish.

## 4. Start and stop CV-Scope

Open **CV-Scope** from the Start menu (or the desktop). A small CV-Scope
window appears, the server starts in the background (the first start can
take a minute) and your web browser opens CV-Scope at
<http://127.0.0.1:8420>. The window shows:

* whether CV-Scope is running, the address, and how many runs are in progress;
* **Open CV-Scope**, which opens the browser again, and **Stop** / **Start**;
* links to the **data folder** and the **server log**.

Closing the window stops CV-Scope. If runs are in progress, it asks first.
Opening the shortcut again while CV-Scope runs brings the window forward and
opens the browser; it never starts a second copy. If another program already
uses port 8420, CV-Scope takes the next free port and shows the address it
uses.

On the first visit the browser shows CV-Scope's own setup assistant. It
checks the hardware, recommends a detector (already downloaded if you chose
it in Setup), offers the sample videos with one click, and opens the Scene
Builder. From there, follow the guides under **Help → Guides**, starting with
*A first tour and setup*.

CV-Scope only listens on this computer (`127.0.0.1`). Read the guide
*Deploy a study* before opening it to a network.

## Update

Download the new installer and run it. It keeps your data, your settings and
your earlier choices, and it downloads only what changed (PyTorch is reused
when the version is the same). Close the CV-Scope window first; Setup asks
you to if it is open.

To switch between the processor and the graphics card, run the installer
again and change the choice on the **Graphics card** page.

## Uninstall

Open **Settings → Apps → Installed apps**, find **CV-Scope** and choose
**Uninstall**. Uninstall removes the application and its Python environment,
then asks whether to delete your data folder as well. The answer **No**
(the default) keeps your projects, recordings and models for a later
installation.

## Where things are

| What | Where (defaults) |
| --- | --- |
| Application, Python environment | `%LOCALAPPDATA%\Programs\CV-Scope` |
| Data: database, videos, recordings, exports, models | `%LOCALAPPDATA%\CV-Scope` (the folder chosen in Setup) |
| Sample videos | `%LOCALAPPDATA%\Programs\CV-Scope\samples\videos` |
| Server log | `logs\server.log` in the data folder (the previous three starts are kept) |
| Setup log | `%LOCALAPPDATA%\Programs\CV-Scope\logs\install.log` |
| Settings file | `%LOCALAPPDATA%\Programs\CV-Scope\.env` (see [installation](installation.md), "Configuration"; Setup keeps your lines when it updates) |

The command line is in the Python environment. In PowerShell:

```powershell
& "$env:LOCALAPPDATA\Programs\CV-Scope\.venv\Scripts\cvscope.exe" hardware
& "$env:LOCALAPPDATA\Programs\CV-Scope\.venv\Scripts\cvscope.exe" models install yolo11x
```

## Troubleshooting

* **"This step did not finish" during installation.** Usually the internet
  connection dropped or a proxy or firewall blocked a download. Click
  **Retry**. If you cancel, run Setup again later: it continues where it
  stopped. The details are in `install.log` (see the table above).
* **Behind a company proxy.** Setup downloads PyTorch with the Windows proxy
  settings. The package step and model downloads use the `HTTPS_PROXY`
  environment variable: set it for your user (for example
  `setx HTTPS_PROXY http://proxy.example:8080`), then run Setup again.
* **"Setup has detected that CV-Scope is currently running".** Close the
  CV-Scope window (not only the browser tab), then click OK.
* **The graphics card is not used.** Setup lists this on its last page. Open
  the **Hardware** page in CV-Scope: if CUDA is not available, update the
  NVIDIA driver (see the requirements), restart the computer and run Setup
  again with the graphics card option.
* **The browser does not open, or shows an error.** Click **Open CV-Scope**
  in the CV-Scope window, or open the address it shows. If the window says
  CV-Scope could not start, click **Server log** and look at the last lines.
* **An antivirus program blocks or slows the installation.** Setup starts
  `uv.exe` and Python to install packages, which some antivirus programs
  inspect closely. Allow CV-Scope's folder, or install while the scan is
  paused, then run Setup again.

## Unattended installation

For IT departments and lab computers, Setup runs silently:

```powershell
.\CV-Scope-Setup-Windows-x64.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART `
  /TORCH=auto /DATADIR="D:\CV-Scope data" `
  /COMPONENTS="detectors\yolo11n,detectors\yolo11s,samples" /TASKS="desktopicon" `
  /LOG="$env:TEMP\cvscope-setup.log"
```

| Option | Meaning |
| --- | --- |
| `/TORCH=auto\|cpu\|cu126\|cu130` | PyTorch build: chosen from the graphics card (default), processor only, CUDA 12.6 (GTX 900 to RTX 40 series) or CUDA 13.0 (RTX 50 series) |
| `/DATADIR=path` | Data folder (default `%LOCALAPPDATA%\CV-Scope`) |
| `/DIR=path` | Application folder |
| `/TYPE=recommended\|full\|minimal` | A preset instead of `/COMPONENTS` |
| `/COMPONENTS=...` | Comma-separated: `detectors\yolo11n`, `detectors\yolo11s`, `detectors\yolo11m`, `detectors\yolo11l`, `detectors\yolo11x`, `detectors\yolov8`, `detectors\rtdetr`, `detectors\onnx`, `detectors\torchvision`, `tracking`, `recognition\face`, `recognition\insightface`, `recognition\plate`, `samples`, `extras\claude`, `extras\postgres`, `localai\moondream`, `localai\qwen3b`, `localai\qwen7b` |
| `/TASKS="desktopicon"` | Create the desktop shortcut (`/TASKS=""` for none) |

Exit codes: `0` installed; `10` the installation failed (details in the log);
`11` installed, but some optional downloads (models, sample videos, the local
vision model) failed or the graphics card cannot be used yet. Uninstall
silently with `"%LOCALAPPDATA%\Programs\CV-Scope\unins000.exe" /VERYSILENT`,
which keeps the data folder.

How the installer is built and released is described in `installer/README.md`
in the repository.
