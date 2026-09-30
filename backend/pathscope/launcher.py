"""Desktop launcher: start the CV-Scope server and open it in the browser.

The Windows installer's Start-menu and desktop shortcuts run
``pythonw -m pathscope.launcher``; ``cvscope launch`` does the same from a
terminal on any system. The launcher

* starts the server as a child process without a console window, its output
  going to ``<data>/logs/server.log``;
* waits until the API answers, then opens ``http://127.0.0.1:<port>/`` in the
  default browser;
* shows a small window with the address, Open and Stop buttons and links to
  the data folder and the server log. Closing the window stops the server,
  after asking when runs are in progress;
* reuses a server of the same installation (same data folder) that is already
  running instead of starting a second one, and moves to the next free port
  when another program, or another CV-Scope installation, holds the
  configured one. Starting the launcher a second time brings the first
  window forward and opens the browser again.

The child connects back to the launcher over a loopback socket and stops
cleanly (runs finalised, camera workers stopped) when the launcher sends
"stop" or the connection closes. A pipe on stdin would be simpler, but on
Windows a thread blocked reading a pipe stalls other I/O on it and the
server's start-up with it. On Windows a job object also ends every process of
the server tree when the launcher goes away or the server does not stop in
time, so no hidden worker keeps a camera open.

Without a display or tkinter (or with ``--console``) it prints the address and
stops the server on Ctrl+C.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from pathscope.config import REPO_ROOT, get_settings

WINDOW_TITLE = "CV-Scope"
# The installer's AppMutex: Setup and Uninstall wait while a launcher runs.
MUTEX_NAME = "CV-Scope-Launcher"
# Groups the launcher window with the installer's shortcuts on the taskbar.
APP_USER_MODEL_ID = "CVScope.Launcher"
PORT_SEARCH = 20
# The first start creates the database and imports PyTorch; a cold disk is slow.
STARTUP_TIMEOUT_S = 180.0
# Runs are finalised and camera workers stopped before the server exits.
STOP_TIMEOUT_S = 45.0
# Open live streams (MJPEG previews) never finish on their own.
GRACEFUL_SHUTDOWN_S = 8
LOG_GENERATIONS = 3
IS_WINDOWS = sys.platform == "win32"


# --------------------------------------------------------------------- helpers
def browser_host(host: str) -> str:
    """The address a browser on this machine uses for a server bound to ``host``."""
    return "127.0.0.1" if host in ("", "0.0.0.0", "::", "localhost") else host


def server_url(host: str, port: int) -> str:
    return f"http://{browser_host(host)}:{port}/"


def probe(host: str, port: int, timeout: float = 1.5) -> dict | None:
    """Status of a CV-Scope server listening on ``port``, or None."""
    try:
        r = httpx.get(f"{server_url(host, port)}api/system/status", timeout=timeout, trust_env=False)
        data = r.json() if r.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        return None
    return data if isinstance(data, dict) and "data_dir" in data and "version" in data else None


def same_installation(status: dict, data_dir: Path) -> bool:
    try:
        return Path(str(status.get("data_dir", ""))).resolve() == data_dir.resolve()
    except OSError:
        return False


def port_free(host: str, port: int) -> bool:
    bind_host = "" if host in ("0.0.0.0", "::") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if IS_WINDOWS:
            # Without it Windows lets a second socket share a port held with SO_REUSEADDR.
            s.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", socket.SO_REUSEADDR), 1)
        try:
            s.bind((bind_host, port))
        except OSError:
            return False
    return True


@dataclass
class PortChoice:
    port: int
    running: dict | None  # status of this installation's server already listening there


def choose_port(host: str, preferred: int, data_dir: Path, search: int = PORT_SEARCH) -> PortChoice:
    """The configured port, a server of this installation already on one of the
    next ports, or the first free port after it."""
    for port in range(preferred, preferred + search + 1):
        status = probe(host, port)
        if status is not None:
            if same_installation(status, data_dir):
                return PortChoice(port, status)
            continue  # another CV-Scope installation
        if port_free(host, port):
            return PortChoice(port, None)
    raise RuntimeError(f"No free port between {preferred} and {preferred + search}. Close other programs or set PATHSCOPE_PORT.")


def find_running(host: str, preferred: int, data_dir: Path, search: int = PORT_SEARCH) -> int | None:
    """Port of this installation's server among the ports a launcher may use."""
    for port in range(preferred, preferred + search + 1):
        status = probe(host, port, timeout=1.0)
        if status is not None and same_installation(status, data_dir):
            return port
    return None


def rotate_logs(path: Path, keep: int = LOG_GENERATIONS) -> None:
    """server.log -> server.log.1 -> ... so that each start begins a new file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    for i in range(keep, 0, -1):
        src = path if i == 1 else path.with_name(f"{path.name}.{i - 1}")
        if src.exists():
            with contextlib.suppress(OSError):
                src.replace(path.with_name(f"{path.name}.{i}"))


def console_python() -> str:
    """python.exe next to pythonw.exe: the server writes its log to a console stream."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
        return str(exe.with_name("python.exe"))
    return str(exe)


def open_path(path: Path) -> None:
    """Show a file, or its folder when the file does not exist yet."""
    target = path if path.exists() else path.parent
    if IS_WINDOWS:
        os.startfile(str(target))  # noqa: S606 - a folder or log the user asked to see
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(target)])  # noqa: S603


# --------------------------------------------------------------------- Windows
class _WinJob:
    """A job object that ends the server and every worker it started when the
    launcher's handle closes (the launcher exits or is killed)."""

    def __init__(self, pid: int) -> None:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
        k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        k32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)

        class IoCounters(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("r_ops", "w_ops", "o_ops", "r_bytes", "w_bytes", "o_bytes")]

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD),
            ]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        job_object_extended_limit_information = 9
        job_object_limit_kill_on_job_close = 0x2000
        process_set_quota, process_terminate = 0x0100, 0x0001
        self._k32 = k32
        self.handle = k32.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = ExtendedLimits()
        info.BasicLimitInformation.LimitFlags = job_object_limit_kill_on_job_close
        if not k32.SetInformationJobObject(self.handle, job_object_extended_limit_information, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        proc = k32.OpenProcess(process_set_quota | process_terminate, False, pid)
        if not proc:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not k32.AssignProcessToJobObject(self.handle, proc):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            k32.CloseHandle(proc)

    def terminate(self) -> None:
        self._k32.TerminateJobObject(self.handle, 1)


_mutex_handles: list = []


def _win_first_instance(data_dir: Path) -> bool:
    """Hold the launcher mutexes; False when a launcher of this installation
    (same data folder) already runs. The fixed name is what the installer
    checks; the second one lets other installations run side by side."""
    import ctypes
    import hashlib

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    k32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
    _mutex_handles.append(k32.CreateMutexW(None, False, MUTEX_NAME))  # released when the process ends
    key = hashlib.sha256(str(data_dir.resolve()).lower().encode("utf-8")).hexdigest()[:16]
    _mutex_handles.append(k32.CreateMutexW(None, False, f"{MUTEX_NAME}-{key}"))
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


def _win_show_existing_window() -> None:
    import ctypes

    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = ctypes.c_void_p
    hwnd = user32.FindWindowW(None, WINDOW_TITLE)
    if hwnd:
        user32.ShowWindow(ctypes.c_void_p(hwnd), 9)  # SW_RESTORE
        user32.SetForegroundWindow(ctypes.c_void_p(hwnd))


def _win_prepare_gui() -> None:
    import ctypes

    with contextlib.suppress(Exception):
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    with contextlib.suppress(Exception):
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # crisp text on scaled displays


# --------------------------------------------------------------------- server
TOKEN_ENV = "CVSCOPE_LAUNCHER_TOKEN"


class ServerProcess:
    """The CV-Scope server as a child process (``python -m pathscope.launcher --child``)."""

    def __init__(self, host: str, port: int, log_path: Path) -> None:
        self.host, self.port, self.log_path = host, port, log_path
        self.proc: subprocess.Popen | None = None
        self._job: _WinJob | None = None
        self._log = None
        self._listener: socket.socket | None = None
        self._control: socket.socket | None = None
        self._token = ""

    def start(self) -> None:
        import secrets

        rotate_logs(self.log_path)
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(4)
        self._listener.setblocking(False)
        self._token = secrets.token_hex(16)
        self._log = open(self.log_path, "ab")  # noqa: SIM115 - closed in stop()
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", **{TOKEN_ENV: self._token})
        flags = (subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if IS_WINDOWS else 0
        cmd = [console_python(), "-m", "pathscope.launcher", "--child", "--host", self.host, "--port", str(self.port),
               "--control", str(self._listener.getsockname()[1])]
        self.proc = subprocess.Popen(  # noqa: S603 - our own interpreter and module
            cmd, stdin=subprocess.DEVNULL, stdout=self._log, stderr=subprocess.STDOUT, cwd=str(REPO_ROOT),
            env=env, creationflags=flags, start_new_session=not IS_WINDOWS,
        )
        if IS_WINDOWS:
            try:
                self._job = _WinJob(self.proc.pid)
            except OSError:
                self._job = None

    def accept_control(self) -> bool:
        """Take the child's control connection once it arrives (non-blocking)."""
        if self._control is not None or self._listener is None:
            return self._control is not None
        try:
            conn, _ = self._listener.accept()
        except (BlockingIOError, OSError):
            return False
        try:
            conn.setblocking(True)
            conn.settimeout(5.0)
            token = conn.recv(64).decode("ascii", "replace").strip()
        except OSError:
            token = ""
        if token != self._token:
            conn.close()  # not our child
            return False
        conn.settimeout(None)
        self._control = conn
        self._listener.close()
        self._listener = None
        return True

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self, timeout: float = STOP_TIMEOUT_S) -> int | None:
        """Ask the server to stop, wait, and end the process tree if it does not."""
        proc = self.proc
        if proc is None:
            return None
        if proc.poll() is None:
            self.accept_control()
            if self._control is not None:
                with contextlib.suppress(OSError):
                    self._control.sendall(b"stop\n")
                try:
                    proc.wait(timeout)
                except subprocess.TimeoutExpired:
                    pass
            if proc.poll() is None:  # no control connection yet, or it did not stop in time
                self.kill()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(10)
        for s in (self._control, self._listener):
            if s is not None:
                with contextlib.suppress(OSError):
                    s.close()
        self._control = self._listener = None
        if self._log is not None:
            self._log.close()
            self._log = None
        return proc.returncode

    def kill(self) -> None:
        if self._job is not None:
            self._job.terminate()
        elif self.proc is not None and self.proc.poll() is None:
            if IS_WINDOWS:
                self.proc.kill()
            else:
                import signal

                with contextlib.suppress(OSError):
                    os.killpg(self.proc.pid, signal.SIGKILL)


def run_child(host: str, port: int, control_port: int | None) -> None:
    """Server process: uvicorn, stopped when the launcher sends "stop" or its
    control connection closes."""
    control = None
    if control_port:
        # Connect before the slow imports so the launcher knows its child early.
        control = socket.create_connection(("127.0.0.1", control_port), timeout=10)
        control.sendall(os.environ.get(TOKEN_ENV, "").encode("ascii") + b"\n")
        control.settimeout(None)

    import uvicorn

    settings = get_settings()
    server = uvicorn.Server(uvicorn.Config(
        "pathscope.main:app", host=host, port=port, log_level=settings.log_level,
        ws_ping_interval=20, ws_ping_timeout=20, timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_S,
    ))

    def watch(conn: socket.socket) -> None:
        with contextlib.suppress(OSError):
            while True:
                data = conn.recv(64)
                if not data or b"stop" in data:
                    break
        server.should_exit = True

    if control is not None:
        threading.Thread(target=watch, args=(control,), daemon=True, name="launcher-control").start()
    server.run()


# --------------------------------------------------------------------- controller
class Launcher:
    """Starts or finds the server and reports its state through ``on_state``.

    States: idle, starting, running, stopping, stopped, failed. ``start`` and
    ``stop`` block and are called from worker threads by the window."""

    def __init__(self, port: int | None = None, open_browser: bool = True, on_state: Callable[[str, str], None] | None = None) -> None:
        self.settings = get_settings()
        self.host = self.settings.host
        self.preferred_port = port or self.settings.port
        self.port = self.preferred_port
        self.open_browser = open_browser
        self.on_state = on_state or (lambda state, detail: None)
        self.server: ServerProcess | None = None
        self.external = False  # a server of this installation that another process started
        self.state = "idle"
        self.status: dict | None = None
        self._lock = threading.Lock()  # one start, stop or refresh at a time
        self._cancel = threading.Event()

    @property
    def url(self) -> str:
        return server_url(self.host, self.port)

    @property
    def data_dir(self) -> Path:
        return self.settings.resolved_data_dir

    @property
    def log_path(self) -> Path:
        return self.settings.logs_dir / "server.log"

    def _set(self, state: str, detail: str = "") -> None:
        self.state = state
        self.on_state(state, detail)

    def start(self) -> bool:
        """Find or start the server and wait until it answers."""
        with self._lock:
            self._cancel.clear()
            return self._start()

    def _start(self) -> bool:
        self._set("starting")
        try:
            choice = choose_port(self.host, self.preferred_port, self.data_dir)
        except RuntimeError as exc:
            self._set("failed", str(exc))
            return False
        self.port = choice.port
        if choice.running is not None:
            self.external, self.status = True, choice.running
            self._set("running")
            self._browse()
            return True
        self.external = False
        server = self.server = ServerProcess(self.host, self.port, self.log_path)
        try:
            server.start()
        except OSError as exc:
            self.server = None
            self._set("failed", f"The server could not be started: {exc}")
            return False
        deadline = time.monotonic() + STARTUP_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._cancel.is_set():
                self._set("stopping")
                server.stop()
                self.server = None
                self._set("stopped")
                return False
            if not server.running():
                code = server.stop()
                self.server = None
                self._set("failed", f"The server stopped while starting (exit code {code}). The server log has the details.")
                return False
            if not server.accept_control():
                time.sleep(0.2)
                continue
            status = probe(self.host, self.port)
            if status is not None and same_installation(status, self.data_dir):
                self.status = status
                self._set("running")
                self._browse()
                return True
            time.sleep(0.5)
        server.stop(timeout=10)
        self.server = None
        self._set("failed", "The server did not answer within three minutes. The server log has the details.")
        return False

    def _browse(self) -> None:
        if self.open_browser:
            webbrowser.open(self.url)

    def cancel(self) -> None:
        """Abandon a start in progress (the window was closed while starting)."""
        self._cancel.set()

    def refresh(self) -> None:
        """Poll the server: active runs, or a server that stopped on its own."""
        if not self._lock.acquire(blocking=False):
            return  # a start or stop is in progress
        try:
            if self.state != "running":
                return
            server = self.server
            if server is not None and not server.running():
                code = server.stop()
                self.server = None
                self._set("failed", f"The server stopped unexpectedly (exit code {code}). The server log has the details.")
                return
            status = probe(self.host, self.port)
            if status is None and self.external:
                self._set("stopped", "The server that was already running has stopped.")
            elif status is not None:
                self.status = status
                self._set("running")
        finally:
            self._lock.release()

    def active_runs(self) -> int:
        return len((self.status or {}).get("active_runs") or [])

    def stop(self) -> None:
        with self._lock:
            server = self.server
            if server is not None and server.running():
                self._set("stopping")
                server.stop()
            self.server = None
            self.status = None
            self._set("stopped")


# --------------------------------------------------------------------- window
class LauncherWindow:
    ACCENT = "#0b6b8a"
    MUTED = "#545e58"
    FAINT = "#86908a"
    COLORS = {"starting": "#b7791f", "running": "#2b7a3d", "stopping": "#b7791f", "stopped": "#86908a", "failed": "#b3261e", "idle": "#86908a"}
    HEADLINES = {
        "idle": "Preparing...",
        "starting": "Starting CV-Scope...",
        "running": "CV-Scope is running",
        "stopping": "Stopping CV-Scope...",
        "stopped": "CV-Scope is stopped",
        "failed": "CV-Scope could not start",
    }

    def __init__(self, launcher: Launcher) -> None:
        import tkinter as tk
        from tkinter import font as tkfont
        from tkinter import messagebox, ttk

        self.messagebox = messagebox
        self.launcher = launcher
        self.events: queue.Queue[Callable[[], None]] = queue.Queue()
        launcher.on_state = lambda state, detail: self.events.put(lambda: self._show(state, detail))
        self.closing = False
        self.closed = False

        root = self.root = tk.Tk()
        root.title(WINDOW_TITLE)
        root.resizable(False, False)
        icon = REPO_ROOT / "cvscope.ico"
        if IS_WINDOWS and icon.is_file():
            with contextlib.suppress(tk.TclError):
                root.iconbitmap(default=str(icon))
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        scale = root.winfo_fpixels("1i") / 96.0

        def px(n: float) -> int:
            return int(round(n * scale))

        base = tkfont.nametofont("TkDefaultFont")
        base.configure(size=10)
        title_font = base.copy()
        title_font.configure(size=15, weight="bold")
        small_font = base.copy()
        small_font.configure(size=9)
        link_font = small_font.copy()
        link_font.configure(underline=True)
        address_font = base.copy()
        address_font.configure(underline=True)

        frame = ttk.Frame(root, padding=(px(20), px(16), px(20), px(14)))
        frame.grid(sticky="nsew")
        frame.columnconfigure(0, minsize=px(380))  # same width whether or not the progress bar shows
        ttk.Label(frame, text="CV-Scope", font=title_font, foreground=self.ACCENT).grid(row=0, column=0, sticky="w")

        status_row = ttk.Frame(frame)
        status_row.grid(row=1, column=0, sticky="w", pady=(px(8), 0))
        size = px(11)
        background = style.lookup("TFrame", "background") or root.cget("bg")
        self.dot = tk.Canvas(status_row, width=size, height=size, highlightthickness=0, bd=0, bg=background)
        self.dot_item = self.dot.create_oval(1, 1, size - 1, size - 1, fill=self.COLORS["idle"], outline="")
        self.dot.grid(row=0, column=0, padx=(0, px(8)))
        self.headline = ttk.Label(status_row, text=self.HEADLINES["idle"])
        self.headline.grid(row=0, column=1, sticky="w")

        self.address = ttk.Label(frame, text="", foreground=self.ACCENT, cursor="hand2", font=address_font)
        self.address.grid(row=2, column=0, sticky="w", pady=(px(4), 0))
        self.address.bind("<Button-1>", lambda _e: self._open())
        self.detail = ttk.Label(frame, text="", wraplength=px(380), font=small_font, foreground=self.MUTED)
        self.detail.grid(row=3, column=0, sticky="w", pady=(px(4), 0))
        self.progress = ttk.Progressbar(frame, mode="indeterminate", length=px(380))
        self.progress.grid(row=4, column=0, sticky="we", pady=(px(10), 0))

        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, sticky="w", pady=(px(14), 0))
        self.open_button = ttk.Button(buttons, text="Open CV-Scope", command=self._open, default="active")
        self.open_button.grid(row=0, column=0, padx=(0, px(8)))
        self.toggle_button = ttk.Button(buttons, text="Stop", command=self._toggle)
        self.toggle_button.grid(row=0, column=1)

        links = ttk.Frame(frame)
        links.grid(row=6, column=0, sticky="w", pady=(px(14), 0))
        for i, (text, path) in enumerate((("Data folder", launcher.data_dir), ("Server log", launcher.log_path))):
            link = ttk.Label(links, text=text, foreground=self.ACCENT, cursor="hand2", font=link_font)
            link.grid(row=0, column=i, padx=(0, px(16)))
            link.bind("<Button-1>", lambda _e, p=path: open_path(p))
        ttk.Label(frame, text="Closing this window stops CV-Scope.", font=small_font, foreground=self.FAINT).grid(
            row=7, column=0, sticky="w", pady=(px(10), 0))

        root.protocol("WM_DELETE_WINDOW", self._close)
        # Windows sign-out and shutdown (Tk maps WM_QUERYENDSESSION to this protocol)
        root.protocol("WM_SAVE_YOURSELF", self._session_end)
        root.bind("<Return>", lambda _e: self._open())
        self._show("starting", "")
        root.after(100, self._pump)
        root.after(3000, self._poll)

    # -- state
    def _show(self, state: str, detail: str) -> None:
        if self.closed:
            return
        lr = self.launcher
        running = state == "running"
        self.dot.itemconfigure(self.dot_item, fill=self.COLORS.get(state, self.COLORS["idle"]))
        headline = self.HEADLINES.get(state, state)
        if state == "failed" and "unexpectedly" in detail:
            headline = "CV-Scope stopped unexpectedly"
        self.headline.configure(text=headline)
        self.address.configure(text=lr.url if running else "")
        if running:
            n = lr.active_runs()
            parts = [f"{n} run{'s' if n != 1 else ''} in progress." if n else "",
                     "It was already running; stop it where it was started." if lr.external else ""]
            detail = " ".join(p for p in parts if p)
        elif state == "starting" and not detail:
            detail = "The first start can take a minute."
        self.detail.configure(text=detail)
        if state in ("starting", "stopping"):
            self.progress.grid()
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.grid_remove()
        self.open_button.state(["!disabled"] if running else ["disabled"])
        self.toggle_button.configure(text="Stop" if running or state in ("starting", "stopping") else "Start")
        busy = state in ("starting", "stopping")
        self.toggle_button.state(["disabled"] if busy or (running and lr.external) else ["!disabled"])
        if self.closing and state in ("stopped", "failed"):
            self.closed = True
            self.root.destroy()
        elif self.closing and running and not lr.external:
            threading.Thread(target=lr.stop, daemon=True, name="launcher-stop").start()

    def _pump(self) -> None:
        with contextlib.suppress(queue.Empty):
            while not self.closed:
                self.events.get_nowait()()
        if not self.closed:
            self.root.after(100, self._pump)

    def _poll(self) -> None:
        if self.closed:
            return
        threading.Thread(target=self.launcher.refresh, daemon=True, name="launcher-poll").start()
        self.root.after(3000, self._poll)

    # -- actions
    def _open(self) -> None:
        if self.launcher.state == "running":
            webbrowser.open(self.launcher.url)

    def _toggle(self) -> None:
        state = self.launcher.state
        if state == "running":
            if self._confirm_stop():
                threading.Thread(target=self.launcher.stop, daemon=True, name="launcher-stop").start()
        elif state in ("stopped", "failed", "idle"):
            self.launcher.open_browser = True
            self.start()

    def _confirm_stop(self) -> bool:
        n = self.launcher.active_runs()
        if not n:
            return True
        many = n != 1
        return bool(self.messagebox.askyesno(
            WINDOW_TITLE,
            f"{n} run{'s are' if many else ' is'} in progress. Stopping CV-Scope ends {'them' if many else 'it'}.\n\nStop CV-Scope?",
            icon="warning", parent=self.root,
        ))

    def _close(self) -> None:
        lr = self.launcher
        if lr.state == "running" and not lr.external:
            if not self._confirm_stop():
                return
            self.closing = True
            threading.Thread(target=lr.stop, daemon=True, name="launcher-stop").start()
        elif lr.state in ("starting", "stopping"):
            self.closing = True
            lr.cancel()
        else:
            self.closed = True
            self.root.destroy()

    def _session_end(self) -> None:
        """Stop the server before Windows ends the session and kills it."""
        server = self.launcher.server
        if server is not None and server.running():
            server.stop(timeout=10)

    def start(self) -> None:
        threading.Thread(target=self.launcher.start, daemon=True, name="launcher-start").start()

    def run(self) -> None:
        self.start()
        self.root.mainloop()
        server = self.launcher.server
        if server is not None and server.running():
            server.stop()


# --------------------------------------------------------------------- entry points
def _console(launcher: Launcher) -> int:
    def report(state: str, detail: str) -> None:
        if state == "starting":
            print("Starting CV-Scope ...", flush=True)
        elif state == "running":
            suffix = " (it was already running)" if launcher.external else ""
            print(f"CV-Scope is running at {launcher.url}{suffix}", flush=True)
        elif state == "failed":
            print(f"CV-Scope could not start: {detail}\nServer log: {launcher.log_path}", file=sys.stderr, flush=True)

    launcher.on_state = report
    if not launcher.start():
        return 1
    if launcher.external:
        return 0
    print("Press Ctrl+C to stop it.", flush=True)
    try:
        while launcher.server is not None and launcher.server.running():
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("Stopping CV-Scope ...", flush=True)
    launcher.stop()
    return 0


def _second_instance(launcher: Launcher) -> int:
    """Another launcher owns the server: bring its window forward and open the
    browser once its server answers. Never starts a second server."""
    with contextlib.suppress(Exception):
        _win_show_existing_window()
    if not launcher.open_browser:
        return 0
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    while time.monotonic() < deadline:
        port = find_running(launcher.host, launcher.preferred_port, launcher.data_dir)
        if port is not None:
            webbrowser.open(server_url(launcher.host, port))
            return 0
        time.sleep(1.0)
    return 1


def _report_crash(exc: BaseException) -> None:
    """pythonw has no console: keep the traceback in a file and show the error."""
    text = "".join(traceback.format_exception(exc))
    try:
        path = get_settings().logs_dir / "launcher.log"
    except Exception:  # noqa: BLE001 - the settings themselves may be what failed
        path = Path(os.environ.get("TEMP") or ".") / "cvscope-launcher.log"
    with contextlib.suppress(OSError):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    if sys.stderr is not None:
        print(text, file=sys.stderr)
    with contextlib.suppress(Exception):
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(WINDOW_TITLE, f"CV-Scope could not start:\n\n{exc}\n\nDetails: {path}")
        root.destroy()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cvscope launch", description="Start CV-Scope and open it in the browser.")
    parser.add_argument("--port", type=int, help="port to use (default PATHSCOPE_PORT, 8420; the next free one when taken)")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    parser.add_argument("--console", action="store_true", help="no window: print the address and stop on Ctrl+C")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--host", help=argparse.SUPPRESS)
    parser.add_argument("--control", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.child:
        settings = get_settings()
        run_child(args.host or settings.host, args.port or settings.port, args.control)
        return 0
    try:
        launcher = Launcher(port=args.port, open_browser=not args.no_browser)
        if IS_WINDOWS and not _win_first_instance(launcher.data_dir):
            return _second_instance(launcher)
        if args.console:
            return _console(launcher)
        try:
            if IS_WINDOWS:
                _win_prepare_gui()
            window = LauncherWindow(launcher)
        except Exception:  # noqa: BLE001 - no display or no tkinter: use the console
            if sys.stdout is None:
                raise
            return _console(launcher)
        window.run()
        return 0
    except Exception as exc:  # noqa: BLE001
        _report_crash(exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
