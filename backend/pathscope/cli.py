"""Command line entry point: ``cvscope serve|launch|migrate|hardware|models|benchmark|recognition|anomaly``."""

from __future__ import annotations

import argparse
import json
import sys


def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    from pathscope.config import get_settings

    s = get_settings()
    uvicorn.run(
        "pathscope.main:app",
        host=args.host or s.host,
        port=args.port or s.port,
        reload=args.reload,
        log_level=s.log_level,
        ws_ping_interval=20,
        ws_ping_timeout=20,
    )


def _migrate(_args: argparse.Namespace) -> None:
    from pathscope.db.migrate import upgrade_database

    upgrade_database()
    print("database is up to date")


def _hardware(_args: argparse.Namespace) -> None:
    from pathscope.config import get_settings
    from pathscope.hardware import build_recommendations, probe_hardware
    from pathscope.models.manager import get_model_manager

    hw = probe_hardware(get_settings().resolved_data_dir)
    d = hw.to_dict()
    print(f"OS:      {d['os']}")
    print(f"CPU:     {d['cpu']['model']} ({d['cpu']['physical_cores']} cores / {d['cpu']['logical_cores']} threads)")
    print(f"Memory:  {d['memory']['total_bytes'] / 1024**3:.1f} GB total, {d['memory']['available_bytes'] / 1024**3:.1f} GB available")
    for g in d["gpus"]:
        vram = f"{g['vram_total_bytes'] / 1024**3:.1f} GB" if g["vram_total_bytes"] else "unknown VRAM"
        print(f"GPU:     {g['name']} ({vram}){' [integrated]' if g['integrated'] else ''}")
    acc = d["acceleration"]
    print(f"CUDA:    {'available ' + str(acc['cuda_version']) if acc['cuda_available'] else 'not available'}")
    print(f"MPS:     {'available' if acc['mps_available'] else 'not available'}")
    print(f"ORT EPs: {', '.join(acc['onnxruntime_providers']) or 'onnxruntime not installed'}")
    recs = build_recommendations(hw, get_model_manager().installed_ids())
    print(f"\nWorkload: {recs.workload_class} - {recs.workload_summary}")
    print(f"Runtime:  {recs.runtime_label} ({recs.runtime_reason})")
    for t in recs.tiers:
        mark = "*" if t.tier == recs.default_tier else " "
        print(f" {mark} {t.title:14s} {t.model_name:28s} {t.device:8s} {t.image_size}px  {'installed' if t.installed else 'not installed'}")
    for w in recs.warnings:
        print(f"Warning: {w}")


def _models(args: argparse.Namespace) -> None:
    from pathscope.models.manager import get_model_manager

    manager = get_model_manager()
    if args.action == "list":
        for m in manager.list_models():
            print(f"{m['id']:26s} {m['name']:30s} {m['provider']:12s} {m['license']:14s} {'installed' if m['installed'] else '-'}")
    elif args.action == "install":
        import time

        if not args.model_id:
            print("name one or more model ids (cvscope models list)", file=sys.stderr)
            sys.exit(2)
        # A terminal gets one updating line; a pipe (the Windows installer) whole lines.
        tty = sys.stdout.isatty()
        failed = []
        for model_id in args.model_id:
            try:
                job = manager.install(model_id)
            except KeyError as exc:
                print(f"failed: {exc.args[0]}", flush=True)
                failed.append(model_id)
                continue
            shown = -1
            while job.status in ("queued", "running"):
                if tty:
                    print(f"\r{job.message} {job.progress * 100:5.1f}%", end="", flush=True)
                elif int(job.progress * 10) != shown:
                    shown = int(job.progress * 10)
                    print(f"{model_id}: {job.message or 'starting'} {job.progress * 100:.0f}%", flush=True)
                time.sleep(0.5)
            print(f"{chr(10) if tty else ''}{job.status}: {job.error or job.path}", flush=True)
            if job.status == "failed":
                failed.append(model_id)
        if failed:
            if len(args.model_id) > 1:
                print(f"not installed: {', '.join(failed)}", flush=True)
            sys.exit(1)


def _launch(args: argparse.Namespace) -> None:
    from pathscope.launcher import main as launcher_main

    argv = ["--port", str(args.port)] if args.port else []
    argv += ["--no-browser"] * args.no_browser + ["--console"] * args.console
    sys.exit(launcher_main(argv))


def _benchmark(args: argparse.Namespace) -> None:
    from pathscope.models.benchmark import run_benchmark

    res = run_benchmark(args.model_id, args.device, args.image_size, args.video, tracker_id=args.tracker)
    print(json.dumps(res, indent=2))


def _recognition(args: argparse.Namespace) -> None:
    """Licensed recognition modules: issuer keys, licences, access tokens, status."""
    from pathlib import Path

    from pathscope.recognition.licensing import (
        LicenseError,
        LicensePayload,
        get_license_manager,
        hardware_id,
        issue_license,
    )
    from pathscope.recognition.licensing.license import (
        generate_issuer_keypair,
        parse_document,
        verify_document,
    )

    action = args.action
    if action == "keygen":
        pair = generate_issuer_keypair()
        out = Path(args.out or "cvscope-issuer.key")
        if out.exists() and not args.force:
            print(f"{out} exists; use --force to overwrite", file=sys.stderr)
            sys.exit(1)
        out.write_text(json.dumps({"secret_hex": pair.secret_hex, "public_hex": pair.public_hex, "created_at": pair.created_at}, indent=2), encoding="utf-8")
        print(f"Issuer key pair written to {out} (keep it private).")
        print(f"Public key (configure it on licensed installations with PATHSCOPE_RECOGNITION_ISSUER_KEYS):\n{pair.public_hex}")
        return
    if action == "issue":
        key = json.loads(Path(args.key).read_text(encoding="utf-8"))
        payload = LicensePayload(
            license_id=args.license_id or f"LIC-{int(__import__('time').time())}", licensee=args.licensee, issuer=args.issuer, issued_at=args.issued or __import__("datetime").date.today().isoformat(),
            expires_at=args.expires, modules=[m.strip() for m in args.modules.split(",") if m.strip()], max_cameras=args.max_cameras, hardware_id=args.hardware_id, notes=args.notes or "",
        )
        doc = issue_license(payload, bytes.fromhex(key["secret_hex"]))
        text = json.dumps(doc, indent=2, sort_keys=True)
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
            print(f"Licence written to {args.out}")
        else:
            print(text)
        return
    if action == "inspect":
        doc = parse_document(Path(args.file).read_bytes())
        lm = get_license_manager()
        verdict = verify_document(doc, lm.trusted_keys(), machine_id=hardware_id())
        print(json.dumps(verdict.summary(), indent=2))
        return
    if action == "install":
        lm = get_license_manager()
        try:
            verdict = lm.install(Path(args.file).read_bytes())
        except LicenseError as exc:
            print(f"refused: {exc}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(verdict.summary(), indent=2))
        return
    if action == "trust":
        path = get_license_manager().add_trusted_key(args.public_key, args.name or "issuer")
        print(f"trusted issuer key written to {path}")
        return
    if action == "hardware-id":
        print(hardware_id())
        return
    if action == "status":
        from pathscope.db.session import get_session_factory
        from pathscope.recognition.service import status_payload

        session = get_session_factory()()
        try:
            print(json.dumps(status_payload(session), indent=2, default=str))
        finally:
            session.close()
        return
    if action == "token":
        from pathscope.db.session import get_session_factory
        from pathscope.recognition.common.access import create_token
        from pathscope.recognition.common.audit import audit

        session = get_session_factory()()
        try:
            row, secret = create_token(session, args.name or "cli", args.role, created_by="cli", expires_in_days=args.expires_in_days)
            audit(session, None, "token_created", "token", row.id, {"role": args.role, "name": row.name, "cli": True})
            session.commit()
        finally:
            session.close()
        print(f"Token ({args.role}) for '{row.name}', shown once:\n{secret}")
        return
    print(f"unknown action {action}", file=sys.stderr)
    sys.exit(2)


def _parse_zone(text: str) -> tuple[str, list[tuple[float, float]]]:
    """``name=x1,y1 x2,y2 x3,y3`` (normalized 0..1) or just the points."""
    name, _, pts = text.rpartition("=") if "=" in text else ("", "", text)
    points = []
    for pair in pts.replace(";", " ").split():
        x, y = pair.split(",")
        points.append((float(x), float(y)))
    if len(points) < 3:
        raise SystemExit(f"a zone needs at least three points: {text!r}")
    return name or f"Zone {len(points)}", points


def _anomaly(args: argparse.Namespace) -> None:
    """Run the Anomaly Assistant on a video file or camera, outside the platform."""
    import time
    from pathlib import Path

    import cv2

    from pathscope.anomaly import (
        AnomalyAssistant,
        AnomalySettings,
        AnomalyZoneSettings,
        EvidenceWriter,
    )

    zone_kw = {"sensitivity": args.sensitivity, "accept_after_s": args.accept_after}
    if args.persistence is not None:
        zone_kw["persistence_s"] = args.persistence
    if args.min_area is not None:
        zone_kw["min_area_pct"] = args.min_area
    zones, polys = [], {}
    for i, text in enumerate(args.zone or []):
        name, points = _parse_zone(text)
        zid = f"zone_{i + 1}"
        zones.append(AnomalyZoneSettings(id=zid, name=name, **zone_kw))
        polys[zid] = points
    if not zones:
        zones.append(AnomalyZoneSettings(id="frame", name="Whole picture", **zone_kw))
    settings = AnomalySettings(enabled=True, zones=zones, analysis_fps=args.fps, learn_s=args.learn, lighting_events=args.lighting)
    source = int(args.source) if args.source.isdigit() else args.source
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise SystemExit(f"cannot open {args.source}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    ok, frame = cap.read()
    if not ok:
        raise SystemExit("no frames")
    assistant = AnomalyAssistant(settings, (frame.shape[1], frame.shape[0]), polys)
    if args.out:
        Path(args.out).mkdir(parents=True, exist_ok=True)
    writer = EvidenceWriter(Path(args.out)) if args.out else None
    log = open(Path(args.out) / "anomalies.jsonl", "a", encoding="utf-8") if args.out else None  # noqa: SIM115
    live = isinstance(source, int) or str(source).startswith(("rtsp:", "http:", "https:"))
    t0, i, n = time.time(), 0, 0
    try:
        while ok:
            t = (time.time() - t0) if live else i / fps
            for u in assistant.observe(frame, t, wall_time=time.time()):
                n += 1
                files = writer.write(u) if writer else {}
                print(f"{t:8.1f} s  {u.phase:9s}  {u.zone_name}: {u.summary}  (confidence {u.confidence:.2f})")
                if log:
                    log.write(json.dumps({**u.to_dict(), "evidence": files}) + "\n")
            ok, frame = cap.read()
            i += 1
        for u in assistant.finish():
            print(f"{i / fps:8.1f} s  {u.phase:9s}  {u.zone_name}: {u.summary}")
            if log:
                log.write(json.dumps({**u.to_dict(), "evidence": writer.write(u) if writer else {}}) + "\n")
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        if log:
            log.close()
    s = assistant.status()
    print(f"{i} frames, {s['analyses']} analyses ({s['analysis_ms']:.1f} ms each), {n} updates; per zone: " + ", ".join(f"{z['name']} {z['confirmed']} confirmed / {z['filtered']} filtered" for z in s["zones"]))


def _anomaly_setup_local(args: argparse.Namespace) -> None:
    """Install Ollama (Windows) and download local vision models, as the
    Anomaly Assistant page does, printing progress lines."""
    import platform
    import time

    from pathscope.anomaly.llm.local import get_local_models, ollama_root
    from pathscope.config import get_settings

    local = get_local_models()
    root = ollama_root(args.url)

    def wait(job, label: str) -> bool:
        """Print a line when the message changes or progress passes a 5 % step."""
        shown: tuple[str, int] | None = None
        while job.status == "running":
            step = int(job.progress * 20) if job.progress is not None else -1
            if shown != (job.message, step):
                shown = (job.message, step)
                pct = f" {job.progress * 100:.0f}%" if job.progress is not None else ""
                print(f"{label}: {job.message}{pct}", flush=True)
            time.sleep(1.0)
        print(f"{label}: {job.status}{': ' + job.error if job.error else ''}", flush=True)
        return job.status == "done"

    status = local.status(root)
    if not status["installed"]:
        if platform.system() != "Windows":
            raise SystemExit(f"Install Ollama first: {status['install_command'] or 'https://ollama.com/download'}")
        if not wait(local.install(root, get_settings().resolved_data_dir / "anomaly" / "downloads"), "Ollama"):
            sys.exit(1)
    elif not status["running"]:
        print(local.start(root)["message"], flush=True)
    failed = [m for m in args.models if not wait(local.pull(root, m), m)]
    if failed:
        print(f"not downloaded: {', '.join(failed)}", flush=True)
        sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="cvscope", description="CV-Scope command line")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("serve", help="Run the API server")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--reload", action="store_true")
    p.set_defaults(func=_serve)

    p = sub.add_parser("launch", help="Start the server, open it in the browser and show a small control window")
    p.add_argument("--port", type=int, help="port to use (default PATHSCOPE_PORT, 8420; the next free one when taken)")
    p.add_argument("--no-browser", action="store_true", help="do not open the browser")
    p.add_argument("--console", action="store_true", help="no window: print the address and stop on Ctrl+C")
    p.set_defaults(func=_launch)

    p = sub.add_parser("migrate", help="Apply database migrations")
    p.set_defaults(func=_migrate)

    p = sub.add_parser("hardware", help="Print hardware discovery and recommendations")
    p.set_defaults(func=_hardware)

    p = sub.add_parser("models", help="List or install models")
    p.add_argument("action", choices=["list", "install"])
    p.add_argument("model_id", nargs="*", help="one or more model ids to install")
    p.set_defaults(func=_models)

    p = sub.add_parser("benchmark", help="Benchmark a model on this machine")
    p.add_argument("model_id")
    p.add_argument("--device", default="auto")
    p.add_argument("--image-size", type=int)
    p.add_argument("--video")
    p.add_argument("--tracker", default="bytetrack", choices=["bytetrack", "botsort"])
    p.set_defaults(func=_benchmark)

    p = sub.add_parser("recognition", help="Licensed recognition modules: keys, licences, tokens, status")
    rs = p.add_subparsers(dest="action", required=True)
    k = rs.add_parser("keygen", help="Create an issuer key pair (vendor side)")
    k.add_argument("--out")
    k.add_argument("--force", action="store_true")
    i = rs.add_parser("issue", help="Sign a licence with an issuer key (vendor side, after reviewing the request)")
    i.add_argument("--key", required=True, help="issuer key file from keygen")
    i.add_argument("--licensee", required=True)
    i.add_argument("--issuer", default="CV-Scope licensing")
    i.add_argument("--modules", default="face,plate", help="comma separated: face, plate")
    i.add_argument("--expires", help="YYYY-MM-DD (omit for a perpetual licence)")
    i.add_argument("--issued")
    i.add_argument("--license-id")
    i.add_argument("--max-cameras", type=int)
    i.add_argument("--hardware-id", help="bind the licence to one machine (cvscope recognition hardware-id)")
    i.add_argument("--notes")
    i.add_argument("--out")
    ins = rs.add_parser("inspect", help="Verify a licence file against the trusted issuers of this installation")
    ins.add_argument("file")
    st = rs.add_parser("install", help="Validate and install a licence file")
    st.add_argument("file")
    tr = rs.add_parser("trust", help="Register an issuer public key on this installation")
    tr.add_argument("public_key")
    tr.add_argument("--name")
    rs.add_parser("hardware-id", help="Print this machine's fingerprint for a hardware-bound licence")
    rs.add_parser("status", help="Print module status")
    tk = rs.add_parser("token", help="Create a recognition access token")
    tk.add_argument("--name")
    tk.add_argument("--role", default="admin", choices=["viewer", "operator", "admin"])
    tk.add_argument("--expires-in-days", type=int)
    p.set_defaults(func=_recognition)

    p = sub.add_parser("anomaly", help="Anomaly Assistant on a video or camera, outside the platform (pixel changes only, no detector)")
    an = p.add_subparsers(dest="action", required=True)
    a = an.add_parser("analyse", help="Print anomalies of a video file, camera index or stream URL")
    a.add_argument("source", help="video file, USB camera index or rtsp/http URL")
    a.add_argument("--zone", action="append", help="name=x1,y1 x2,y2 x3,y3 ... in 0..1 of the picture (repeatable); none = the whole picture")
    a.add_argument("--sensitivity", default="medium", choices=["low", "medium", "high"])
    a.add_argument("--persistence", type=float, help="seconds a change must last")
    a.add_argument("--min-area", type=float, help="smallest change in percent of the zone")
    a.add_argument("--accept-after", type=float, default=120.0, help="seconds after which a still change is the new normal (0 = never)")
    a.add_argument("--fps", type=float, default=4.0, help="analyses per second")
    a.add_argument("--learn", type=float, default=8.0, help="seconds of normal picture learned first")
    a.add_argument("--lighting", action="store_true", help="also report lighting changes")
    a.add_argument("--out", help="folder for the evidence pictures and anomalies.jsonl")
    a.set_defaults(func=_anomaly)
    lo = an.add_parser("setup-local", help="Install Ollama (Windows) and download local vision models for the Anomaly Assistant")
    lo.add_argument("models", nargs="*", help="models to download, for example qwen2.5vl:3b")
    lo.add_argument("--url", help="Ollama address (default http://127.0.0.1:11434)")
    lo.set_defaults(func=_anomaly_setup_local)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
