"""Guided live enrollment over a WebSocket.

``/ws/recognition/enrollment/{person_id}?camera_id=..&rtoken=..&variant=..``

``variant`` is the look being captured: empty for the first enrollment, or a
label such as ``Glasses`` for a later session that adds the same person in a
different appearance. Each look keeps its own set of views.

The browser shows the camera picture and one instruction; the server watches
the same frames, decides the instruction, and keeps the best frame by itself
once the person holds the requested pose. Frames are taken from the shared
live preview of the camera, or from the run that currently uses it, so no
device is opened twice.

Messages to the browser: ``ready``, ``frame`` (JSON followed by the JPEG),
``analysis``, ``captured``, ``note``, ``error``. From the browser:
``{"type": "target", "view": "left"}`` and ``{"type": "stop"}``.

The same plumbing serves the live recognition test,
``/ws/recognition/test/live?camera_id=..&rtoken=..``: it identifies whoever
stands in front of the camera against the enrolled identities and reports the
candidates and thresholds. It stores nothing by itself; the operator can
answer, and only then something is written:

* ``{"type": "feedback", "verdict": "correct"|"wrong"|"unknown_person", ...}``
  records the verdict in the audit trail (a record of accuracy, not training).
* ``{"type": "confirm", "person_id": ..., "force": false}`` adds the frame on
  screen to that person's enrollment, under the "Live confirmations" look.
* ``{"type": "reload"}`` rebuilds the matcher after someone was enrolled.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from pathscope.db.models import Camera
from pathscope.db.session import get_session_factory
from pathscope.logging_setup import get_logger
from pathscope.recognition.common.access import Principal, authenticate
from pathscope.recognition.common.audit import audit
from pathscope.recognition.common.config import all_recognition_settings
from pathscope.recognition.common.types import BIOMETRIC_VIEWS, ENROLLMENT_VIEWS
from pathscope.recognition.face.enrollment.guidance import VIEW_INSTRUCTIONS, VIEW_LABELS
from pathscope.recognition.face.enrollment.live import (
    GUIDED_EXTRAS,
    GUIDED_PLAN,
    GuidedSession,
    decode_frame,
    observe_frame,
)
from pathscope.recognition.registry.models import RecognitionPerson
from pathscope.recognition.registry.people import (
    EnrollmentError,
    PeopleService,
    clean_variant,
    person_to_dict,
)
from pathscope.recognition.registry.store import get_store
from pathscope.recognition.service import RecognitionNotReady, enrollment_stack, module_states
from pathscope.recognition.testing import (
    LIVE_LOOK,
    TeachRefused,
    build_matcher,
    identify_with,
    teach_picture,
)
from pathscope.services.preview import PreviewConfig, PreviewUnavailable, get_preview_manager
from pathscope.workers.supervisor import get_supervisor

ws_router = APIRouter(tags=["recognition"])
log = get_logger(__name__)

FRAME_INTERVAL = 1.0 / 15.0
ANALYSIS_INTERVAL = 0.12
IDLE_ANALYSIS_INTERVAL = 0.4


class Refused(RuntimeError):
    """The session cannot start; the message goes to the browser."""


@dataclass
class LiveSetup:
    principal: Principal
    person_id: str
    person: dict
    camera_id: int
    camera_name: str
    source_type: str
    cfg: PreviewConfig | None
    stack: Any
    values: dict
    session: GuidedSession
    variant: str
    keep_images: bool
    match_threshold: float
    reference: np.ndarray | None = field(default=None, repr=False)

    def plan(self) -> dict:
        return {
            "plan": [{"view": v, "label": VIEW_LABELS[v], "instruction": VIEW_INSTRUCTIONS[v], "required": v == "front"} for v in GUIDED_PLAN],
            "extras": [{"view": v, "label": VIEW_LABELS[v], "instruction": VIEW_INSTRUCTIONS[v], "required": False} for v in GUIDED_EXTRAS],
        }


def _prepare(person_id: str, camera_id: int, token: str | None, variant: str = "") -> LiveSetup:
    """Authenticate, load everything the session needs and open no camera yet."""
    db = get_session_factory()()
    try:
        principal = authenticate(db, token)
        if principal is None:
            raise Refused("A recognition access token is required.")
        if not principal.at_least("operator"):
            raise Refused("Guided enrollment needs the operator role.")
        state = module_states(db)["face"]
        if state.state not in ("licensed", "disabled"):
            raise Refused(f"Face recognition is {state.state.replace('_', ' ')}: {state.reason}")
        person = db.get(RecognitionPerson, person_id)
        if person is None:
            raise Refused("This person profile no longer exists.")
        camera = db.get(Camera, camera_id)
        if camera is None:
            raise Refused("This camera no longer exists.")
        if camera.source_type == "file":
            raise Refused("Guided capture needs a live camera; video files are enrolled from single pictures.")
        values = all_recognition_settings(db)
        try:
            stack = enrollment_stack(values)
        except RecognitionNotReady as exc:
            raise Refused(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise Refused(f"The face model stack could not be loaded: {exc}") from exc
        svc = PeopleService(db, get_store(), stack, values)
        templates = [vec for t, vec in svc.decrypted_templates(person) if t.model_version == svc.model_version]
        reference = None
        if templates:
            mean = np.mean(np.stack(templates), axis=0)
            norm = float(np.linalg.norm(mean))
            reference = (mean / norm).astype(np.float32) if norm > 1e-9 else None
        look = clean_variant(variant)
        # Each look is captured from scratch; views of other looks do not count.
        captured = {im.view for im in person.images if (im.variant or "") == look}
        session = GuidedSession(
            min_face_px=svc.min_enrollment_face_px,
            min_quality=float(values.get("recognition.face.enrollment_min_quality", 0.6)),
            baseline=svc.front_baseline(person, look),
            captured=captured,
        )
        return LiveSetup(
            principal=principal,
            person_id=person.id,
            person=person_to_dict(person, include_images=True),
            camera_id=camera.id,
            camera_name=camera.name,
            source_type=camera.source_type,
            cfg=PreviewConfig.from_camera(camera),
            stack=stack,
            values=values,
            session=session,
            variant=look,
            keep_images=bool(values.get("recognition.privacy.store_enrollment_images", True)),
            # Guard against a different face stepping in halfway through the
            # session. A turned or tilted view of the same person scores lower
            # than a frontal one, so the bar is the consistency the finished
            # enrollment has to reach anyway, not the recognition threshold.
            match_threshold=min(
                float(getattr(stack.embedder, "default_possible_threshold", 0.35)),
                float(values.get("recognition.face.enrollment_consistency", 0.35)),
            ),
            reference=reference,
        )
    finally:
        db.close()


def _store_capture(setup: LiveSetup, frame: np.ndarray, view: str, client: str | None) -> dict:
    """Analyse the held frame once more and store it (runs in a worker thread)."""
    db = get_session_factory()()
    try:
        person = db.get(RecognitionPerson, setup.person_id)
        if person is None:
            return {"status": "error", "message": "This person profile no longer exists."}
        svc = PeopleService(db, get_store(), setup.stack, setup.values)
        analysis = svc.analyze_image(frame, view, setup.session.baseline)
        if not analysis.accepted:
            return {"status": "retry", "guidance": analysis.guidance}
        if view in BIOMETRIC_VIEWS and setup.reference is not None and analysis.embedding is not None:
            similarity = float(np.dot(setup.reference, analysis.embedding))
            if similarity < setup.match_threshold:
                return {"status": "different_person", "similarity": round(similarity, 3)}
        image_row, template = svc.store_image(person, frame, analysis, setup.keep_images, setup.variant)
        audit(
            db, setup.principal, "enrollment_image_added", "person", person.id,
            {"view": view, "variant": setup.variant, "image_id": image_row.id if image_row else None, "template": template is not None, "quality": (analysis.quality or {}).get("score"), "guided": True, "camera_id": setup.camera_id},
            client,
        )
        db.commit()
        return {
            "status": "ok",
            "view": view,
            "image_id": image_row.id if image_row else None,
            "template_id": template.id if template else None,
            "quality": analysis.quality,
            "analysis": analysis.to_dict(),
            "person": person_to_dict(person, include_images=True),
            "embedding": analysis.embedding,
        }
    except EnrollmentError as exc:
        db.rollback()
        return {"status": "retry", "guidance": [str(exc)]}
    except Exception as exc:  # noqa: BLE001 - one bad capture must not end the session
        db.rollback()
        log.warning("guided capture failed", person_id=setup.person_id, view=view, error=str(exc)[:200])
        return {"status": "error", "message": f"The picture could not be stored: {exc}"}
    finally:
        db.close()


def _run_frames(camera_id: int):
    """The preview of the run that currently uses this camera, if any."""
    handle = next((h for h in get_supervisor().active() if h.spec.camera_id == camera_id), None)
    if handle is None or handle.latest_preview is None:
        return None
    return handle.preview_seq, handle.latest_preview.jpeg


@ws_router.websocket("/ws/recognition/enrollment/{person_id}")
async def guided_enrollment_ws(websocket: WebSocket, person_id: str) -> None:
    await websocket.accept()
    params = websocket.query_params
    token = params.get("rtoken")
    try:
        camera_id = int(params.get("camera_id", ""))
    except ValueError:
        await websocket.send_text(json.dumps({"type": "error", "message": "camera_id is required."}))
        await websocket.close()
        return
    try:
        setup = await run_in_threadpool(_prepare, person_id, camera_id, token, params.get("variant") or "")
    except Refused as exc:
        await websocket.send_text(json.dumps({"type": "error", "message": str(exc)}))
        await websocket.close()
        return
    except Exception as exc:  # noqa: BLE001
        log.warning("guided enrollment refused", person_id=person_id, error=str(exc)[:200])
        await websocket.send_text(json.dumps({"type": "error", "message": f"{type(exc).__name__}: {exc}"}))
        await websocket.close()
        return

    session = setup.session
    manager = get_preview_manager()
    preview = None
    analysis_task: asyncio.Task | None = None
    client = websocket.client.host if websocket.client else None
    await websocket.send_text(json.dumps({
        "type": "ready",
        "person": setup.person,
        "camera": {"id": setup.camera_id, "name": setup.camera_name, "source_type": setup.source_type},
        "mirror": setup.source_type == "usb",
        "variant": setup.variant,
        "hold_needed": session.hold_frames,
        "min_views": int(setup.values.get("recognition.face.enrollment_min_views", 3)),
        "min_face_px": session.min_face_px,
        **setup.plan(),
        **session.plan_state(),
    }, default=str))

    last_seq = -1
    last_frame_sent = 0.0
    last_analysis = 0.0
    try:
        while True:
            # ---- commands from the browser
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=0.02)
                try:
                    cmd = json.loads(raw)
                except ValueError:
                    cmd = {}
                if cmd.get("type") == "target":
                    view = cmd.get("view")
                    if view is not None and view not in ENROLLMENT_VIEWS:
                        view = None
                    session.set_target(view)
                elif cmd.get("type") == "stop":
                    break
            except TimeoutError:
                pass

            # ---- the newest frame: from the run that owns the camera, else the shared preview
            frames = _run_frames(setup.camera_id)
            if frames is not None:
                if preview is not None:
                    manager.release(preview)
                    preview = None
                seq, jpeg = frames
            else:
                if preview is None or not preview.alive:
                    if preview is not None:
                        manager.release(preview)
                        preview = None
                    try:
                        preview = await run_in_threadpool(manager.acquire, setup.cfg)
                        last_seq = -1
                    except PreviewUnavailable:
                        await asyncio.sleep(0.3)
                        continue
                    except Exception as exc:  # noqa: BLE001
                        await websocket.send_text(json.dumps({"type": "error", "message": f"The camera could not be opened: {exc}"}))
                        break
                if preview.state == "error" and preview.seq == 0:
                    await websocket.send_text(json.dumps({"type": "error", "message": preview.error or "The camera did not deliver a frame."}))
                    break
                seq, jpeg = preview.seq, preview.jpeg
            if jpeg is None:
                await asyncio.sleep(0.05)
                continue

            now = time.time()
            new_frame = seq != last_seq
            if new_frame:
                last_seq = seq
                if now - last_frame_sent >= FRAME_INTERVAL:
                    last_frame_sent = now
                    await websocket.send_text(json.dumps({"type": "frame", "seq": seq}))
                    await websocket.send_bytes(jpeg)

            # ---- analysis, in a worker thread so frames keep flowing
            interval = ANALYSIS_INTERVAL if session.target else IDLE_ANALYSIS_INTERVAL
            if analysis_task is None and new_frame and now - last_analysis >= interval:
                last_analysis = now
                payload = jpeg
                analysis_task = asyncio.create_task(run_in_threadpool(_analyze, setup, payload, seq))
            if analysis_task is not None and analysis_task.done():
                obs = analysis_task.result()
                analysis_task = None
                if obs is not None:
                    decision = session.feed(obs)
                    await websocket.send_text(json.dumps({"type": "analysis", **session.describe(obs, decision)}, default=str))
                    if decision.capture and decision.frame is not None:
                        view = decision.view or ""
                        session.set_target(None)  # no second capture while this one is stored
                        result = await run_in_threadpool(_store_capture, setup, decision.frame, view, client)
                        if result["status"] == "ok":
                            session.on_captured(view, result.get("quality"))
                            if setup.reference is None and result.get("embedding") is not None:
                                setup.reference = result["embedding"]
                            await websocket.send_text(json.dumps({
                                "type": "captured",
                                "view": view,
                                "image_id": result["image_id"],
                                "template_id": result["template_id"],
                                "analysis": result["analysis"],
                                "person": result["person"],
                                **session.plan_state(),
                            }, default=str))
                        elif result["status"] == "different_person":
                            session.set_target(view)
                            await websocket.send_text(json.dumps({"type": "note", "level": "warn", "view": view, "message": "This does not look like the same person as the front view. Only the person being enrolled should be in front of the camera."}))
                        elif result["status"] == "retry":
                            session.set_target(view)
                            await websocket.send_text(json.dumps({"type": "note", "level": "warn", "view": view, "message": "; ".join(result.get("guidance") or ["The picture was not accepted; try again."])}))
                        else:
                            session.set_target(view)
                            await websocket.send_text(json.dumps({"type": "note", "level": "err", "view": view, "message": result.get("message", "The picture could not be stored.")}))
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 - the viewer went away or the socket broke
        log.debug("guided enrollment ended", person_id=person_id, error=str(exc)[:200])
    finally:
        if analysis_task is not None:
            analysis_task.cancel()
        if preview is not None:
            manager.release(preview)
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass


def _analyze(setup: LiveSetup, jpeg: bytes, seq: int):
    """Decode and score one frame (worker thread)."""
    img = decode_frame(jpeg)
    if img is None:
        return None
    try:
        return observe_frame(setup.stack, img, seq=seq)
    except Exception as exc:  # noqa: BLE001 - a bad frame must not end the session
        log.debug("guided analysis failed", error=str(exc)[:200])
        return None


# ----------------------------------------------------------------------------- live recognition test
TEST_INTERVAL = 0.25


@dataclass
class TestSetup:
    """One live test session. The matcher is rebuilt when someone is enrolled."""

    principal: Principal
    camera_id: int
    camera_name: str
    source_type: str
    cfg: PreviewConfig | None
    stack: Any
    matcher: Any
    info: dict


def _prepare_test(camera_id: int, token: str | None) -> TestSetup:
    db = get_session_factory()()
    try:
        principal = authenticate(db, token)
        if principal is None:
            raise Refused("A recognition access token is required.")
        if not principal.at_least("operator"):
            raise Refused("The recognition test needs the operator role.")
        state = module_states(db)["face"]
        if state.state not in ("licensed", "disabled"):
            raise Refused(f"Face recognition is {state.state.replace('_', ' ')}: {state.reason}")
        camera = db.get(Camera, camera_id)
        if camera is None:
            raise Refused("This camera no longer exists.")
        if camera.source_type == "file":
            raise Refused("The live test needs a live camera; use a picture for video files.")
        values = all_recognition_settings(db)
        try:
            stack = enrollment_stack(values)
        except RecognitionNotReady as exc:
            raise Refused(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise Refused(f"The face model stack could not be loaded: {exc}") from exc
        svc = PeopleService(db, get_store(), stack, values)
        matcher, info = build_matcher(svc, stack, values)
        return TestSetup(
            principal=principal,
            camera_id=camera.id,
            camera_name=camera.name,
            source_type=camera.source_type,
            cfg=PreviewConfig.from_camera(camera),
            stack=stack,
            matcher=matcher,
            info=info,
        )
    finally:
        db.close()


def _identify_frame(setup: TestSetup, jpeg: bytes, seq: int) -> dict | None:
    """Decode and identify one frame (worker thread)."""
    img = decode_frame(jpeg)
    if img is None:
        return None
    try:
        return {"seq": seq, **identify_with(setup.matcher, setup.info, setup.stack, img)}
    except Exception as exc:  # noqa: BLE001 - a bad frame must not end the session
        log.debug("live test failed", error=str(exc)[:200])
        return None


def _live_teach(setup: TestSetup, jpeg: bytes, person_id: str, force: bool, client: str | None) -> dict:
    """Add the frame on screen to a profile (worker thread)."""
    img = decode_frame(jpeg)
    if img is None:
        return {"status": "error", "message": "That frame could not be read any more; try again."}
    db = get_session_factory()()
    try:
        person = db.get(RecognitionPerson, person_id)
        if person is None:
            return {"status": "error", "message": "This person profile no longer exists."}
        result = teach_picture(db, setup.principal, person, img, look=LIVE_LOOK, force=force, source="live", client=client, stack=setup.stack)
        return {"status": "ok", **result}
    except TeachRefused as exc:
        db.rollback()
        return {"status": "refused", "code": exc.code, "message": str(exc), "similarity": exc.similarity}
    except Exception as exc:  # noqa: BLE001 - one bad picture must not end the session
        db.rollback()
        log.warning("live teach failed", person_id=person_id, error=str(exc)[:200])
        return {"status": "error", "message": f"The picture could not be added: {exc}"}
    finally:
        db.close()


def _live_feedback(setup: TestSetup, cmd: dict, client: str | None) -> dict:
    """Record the operator's verdict on one recognition (worker thread)."""
    from pathscope.recognition.api.routes import _feedback_counts

    db = get_session_factory()()
    try:
        verdict = str(cmd.get("verdict") or "")
        if verdict not in ("correct", "wrong", "unknown_person"):
            return {"status": "error", "message": "unknown verdict"}
        person_id = cmd.get("person_id") or None
        detail = {
            "verdict": verdict, "source": "live", "camera_id": setup.camera_id,
            "similarity": cmd.get("similarity"), "corrected_person_id": cmd.get("corrected_person_id"),
        }
        if person_id:
            person = db.get(RecognitionPerson, str(person_id))
            if person is not None:
                detail["display_name"] = person.display_name
        audit(db, setup.principal, "test_feedback", "person", str(person_id) if person_id else None, {k: v for k, v in detail.items() if v is not None}, client)
        db.commit()
        return {"status": "ok", "verdict": verdict, **_feedback_counts(db)}
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.warning("live feedback failed", error=str(exc)[:200])
        return {"status": "error", "message": str(exc)[:200]}
    finally:
        db.close()


def _rebuild_matcher(setup: TestSetup) -> dict:
    """Pick up profiles enrolled since the session started (worker thread)."""
    db = get_session_factory()()
    try:
        values = all_recognition_settings(db)
        svc = PeopleService(db, get_store(), setup.stack, values)
        setup.matcher, setup.info = build_matcher(svc, setup.stack, values)
        return setup.info
    finally:
        db.close()


@ws_router.websocket("/ws/recognition/test/live")
async def live_test_ws(websocket: WebSocket) -> None:
    """Identify whoever is in front of a camera, live. Nothing is stored."""
    await websocket.accept()
    params = websocket.query_params
    try:
        camera_id = int(params.get("camera_id", ""))
    except ValueError:
        await websocket.send_text(json.dumps({"type": "error", "message": "camera_id is required."}))
        await websocket.close()
        return
    try:
        setup = await run_in_threadpool(_prepare_test, camera_id, params.get("rtoken"))
    except Refused as exc:
        await websocket.send_text(json.dumps({"type": "error", "message": str(exc)}))
        await websocket.close()
        return
    except Exception as exc:  # noqa: BLE001
        log.warning("live test refused", camera_id=camera_id, error=str(exc)[:200])
        await websocket.send_text(json.dumps({"type": "error", "message": f"{type(exc).__name__}: {exc}"}))
        await websocket.close()
        return

    manager = get_preview_manager()
    preview = None
    task: asyncio.Task | None = None
    await websocket.send_text(json.dumps({
        "type": "ready",
        "camera": {"id": setup.camera_id, "name": setup.camera_name, "source_type": setup.source_type},
        "mirror": setup.source_type == "usb",
        **setup.info,
    }, default=str))

    last_seq = -1
    last_frame_sent = 0.0
    last_test = 0.0
    shown: bytes | None = None  # the frame the newest result was made from
    tested: bytes | None = None  # the frame the running analysis is working on
    client = websocket.client.host if websocket.client else None
    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=0.02)
                try:
                    cmd = json.loads(raw)
                except ValueError:
                    cmd = {}
                kind = cmd.get("type")
                if kind == "stop":
                    break
                if kind == "feedback":
                    out = await run_in_threadpool(_live_feedback, setup, cmd, client)
                    await websocket.send_text(json.dumps({"type": "feedback", **out}, default=str))
                elif kind == "confirm":
                    person_id = str(cmd.get("person_id") or "")
                    if not person_id or shown is None:
                        await websocket.send_text(json.dumps({"type": "note", "level": "warn", "message": "Nothing to add yet; wait for a face on screen."}))
                    else:
                        out = await run_in_threadpool(_live_teach, setup, shown, person_id, bool(cmd.get("force")), client)
                        if out["status"] == "ok":
                            await run_in_threadpool(_rebuild_matcher, setup)
                            await websocket.send_text(json.dumps({"type": "taught", **out, **setup.info}, default=str))
                        elif out["status"] == "refused":
                            await websocket.send_text(json.dumps({"type": "refused", **out}, default=str))
                        else:
                            await websocket.send_text(json.dumps({"type": "note", "level": "err", "message": out.get("message", "The picture could not be added.")}))
                elif kind == "reload":
                    info = await run_in_threadpool(_rebuild_matcher, setup)
                    await websocket.send_text(json.dumps({"type": "reloaded", **info}, default=str))
            except TimeoutError:
                pass

            frames = _run_frames(setup.camera_id)
            if frames is not None:
                if preview is not None:
                    manager.release(preview)
                    preview = None
                seq, jpeg = frames
            else:
                if preview is None or not preview.alive:
                    if preview is not None:
                        manager.release(preview)
                        preview = None
                    try:
                        preview = await run_in_threadpool(manager.acquire, setup.cfg)
                        last_seq = -1
                    except PreviewUnavailable:
                        await asyncio.sleep(0.3)
                        continue
                    except Exception as exc:  # noqa: BLE001
                        await websocket.send_text(json.dumps({"type": "error", "message": f"The camera could not be opened: {exc}"}))
                        break
                if preview.state == "error" and preview.seq == 0:
                    await websocket.send_text(json.dumps({"type": "error", "message": preview.error or "The camera did not deliver a frame."}))
                    break
                seq, jpeg = preview.seq, preview.jpeg
            if jpeg is None:
                await asyncio.sleep(0.05)
                continue

            now = time.time()
            new_frame = seq != last_seq
            if new_frame:
                last_seq = seq
                if now - last_frame_sent >= FRAME_INTERVAL:
                    last_frame_sent = now
                    await websocket.send_text(json.dumps({"type": "frame", "seq": seq}))
                    await websocket.send_bytes(jpeg)

            if task is None and new_frame and now - last_test >= TEST_INTERVAL:
                last_test = now
                tested = jpeg
                task = asyncio.create_task(run_in_threadpool(_identify_frame, setup, jpeg, seq))
            if task is not None and task.done():
                result = task.result()
                task = None
                if result is not None:
                    shown = tested  # what the operator is answering about
                    await websocket.send_text(json.dumps({"type": "result", **result}, default=str))
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 - the viewer went away or the socket broke
        log.debug("live test ended", camera_id=camera_id, error=str(exc)[:200])
    finally:
        if task is not None:
            task.cancel()
        if preview is not None:
            manager.release(preview)
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
