"""``/api/recognition``: status, licence, access, settings, people, vehicles,
events, diagnostics, audit and benchmarks.

Everything except ``GET /status`` needs a recognition access token; roles are
documented in ``common/access.py``. Registry and event reads work in every
licence state (data must stay manageable and deletable after a licence
lapses); enrollment and registration need a licensed (or administratively
disabled) module; runs need an active one.
"""

from __future__ import annotations

import time
from datetime import datetime

import cv2
import numpy as np
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pathscope.api.deps import db_session, get_or_404
from pathscope.config import get_settings
from pathscope.db.models import Camera, Video
from pathscope.domain.entities import module_for_class
from pathscope.recognition import MODULES
from pathscope.recognition.api.schemas import (
    BenchmarkIn,
    BootstrapIn,
    CaptureIn,
    DeleteEventsIn,
    IdentifyIn,
    LicenseIn,
    PersonIn,
    PersonUpdate,
    PlateParseIn,
    RecognitionSettingsIn,
    ResolveIn,
    TestFeedbackIn,
    TokenIn,
    TrustedKeyIn,
    VehicleIn,
    VehicleUpdate,
)
from pathscope.recognition.common.access import (
    Principal,
    create_token,
    has_any_token,
    is_loopback,
    require_role,
)
from pathscope.recognition.common.audit import audit
from pathscope.recognition.common.config import (
    all_recognition_settings,
    definitions,
    set_recognition_settings,
)
from pathscope.recognition.events.recorder import (
    apply_filters,
    delete_events,
    event_to_dict,
    export_events,
    name_maps,
)
from pathscope.recognition.licensing import LicenseError, get_license_manager
from pathscope.recognition.registry.models import (
    RecognitionAccessToken,
    RecognitionAudit,
    RecognitionEvent,
    RecognitionPerson,
    RecognitionVehicle,
)
from pathscope.recognition.registry.people import (
    EnrollmentError,
    PeopleService,
    clean_variant,
    person_to_dict,
)
from pathscope.recognition.registry.store import get_store
from pathscope.recognition.registry.vehicles import (
    VehicleError,
    all_groups,
    create_vehicle,
    update_vehicle,
    vehicle_to_dict,
)
from pathscope.recognition.service import (
    RecognitionNotReady,
    enrollment_stack,
    module_states,
    status_payload,
)
from pathscope.recognition.testing import (
    LIVE_LOOK,
    TeachRefused,
    enrollment_report,
    identify_image,
    teach_picture,
)
from pathscope.workers.supervisor import get_supervisor

router = APIRouter(prefix="/recognition", tags=["recognition"])

viewer = require_role("viewer")
operator = require_role("operator")
admin = require_role("admin")


def _client(request: Request) -> str | None:
    return request.client.host if request.client else None


def _module_state_or_403(session: Session, module: str, states=("licensed", "disabled")) -> None:
    st = module_states(session)[module]
    if st.state not in states:
        raise HTTPException(403, f"{module.capitalize()} recognition is {st.state.replace('_', ' ')}: {st.reason}")


def _people_service(session: Session, need_stack: bool) -> PeopleService:
    values = all_recognition_settings(session)
    stack = None
    if need_stack:
        try:
            stack = enrollment_stack(values)
        except RecognitionNotReady as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"The face model stack could not be loaded: {exc}") from exc
    return PeopleService(session, get_store(), stack, values)


# ----------------------------------------------------------------------------- status / licence
@router.get("/status")
def status(session: Session = Depends(db_session)) -> dict:
    return status_payload(session)


@router.post("/license")
def install_license(body: LicenseIn, request: Request, principal: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
    lm = get_license_manager()
    try:
        verdict = lm.install(body.license)
    except LicenseError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(session, principal, "license_installed", "license", verdict.payload.license_id if verdict.payload else None, {"licensee": verdict.payload.licensee if verdict.payload else None, "modules": verdict.payload.modules if verdict.payload else [], "state": verdict.state}, _client(request))
    session.commit()
    return {"verdict": verdict.summary(), "status": status_payload(session)}


@router.delete("/license")
def remove_license(request: Request, principal: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
    removed = get_license_manager().remove()
    audit(session, principal, "license_removed", "license", None, {"removed": removed}, _client(request))
    session.commit()
    return {"removed": removed, "status": status_payload(session)}


@router.post("/license/trusted-keys")
def add_trusted_key(body: TrustedKeyIn, request: Request, principal: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
    """Register an issuer public key on this installation (vendor builds ship theirs through the environment)."""
    try:
        path = get_license_manager().add_trusted_key(body.public_key, body.name)
    except LicenseError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(session, principal, "setting_changed", "trusted_key", body.name, {"path": str(path)}, _client(request))
    session.commit()
    return {"path": str(path), "trusted_issuers": len(get_license_manager().trusted_keys())}


# ----------------------------------------------------------------------------- access
@router.post("/access/bootstrap")
def bootstrap(body: BootstrapIn, request: Request, session: Session = Depends(db_session)) -> dict:
    """Create the first administrator token: only from this computer and only while no token exists."""
    if has_any_token(session):
        raise HTTPException(409, "Access tokens already exist. Use an administrator token to create more, or the CLI.")
    if not is_loopback(request):
        raise HTTPException(403, "The first administrator token can only be created from the computer running CV-Scope (or with the CLI).")
    row, secret = create_token(session, body.name, "admin", created_by="bootstrap")
    audit(session, Principal(row.id, row.name, row.role), "token_created", "token", row.id, {"role": "admin", "bootstrap": True}, _client(request))
    session.commit()
    return {"token": secret, "id": row.id, "name": row.name, "role": row.role}


@router.get("/access/me")
def me(principal: Principal = Depends(viewer)) -> dict:
    return principal.to_dict()


@router.get("/access/tokens")
def list_tokens(principal: Principal = Depends(admin), session: Session = Depends(db_session)) -> list[dict]:
    rows = session.scalars(select(RecognitionAccessToken).order_by(RecognitionAccessToken.created_at.asc()))
    return [{"id": r.id, "name": r.name, "role": r.role, "active": r.active, "created_by": r.created_by, "created_at": r.created_at, "last_used_at": r.last_used_at, "expires_at": r.expires_at} for r in rows]


@router.post("/access/tokens", status_code=201)
def new_token(body: TokenIn, request: Request, principal: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
    row, secret = create_token(session, body.name, body.role, created_by=principal.name, expires_in_days=body.expires_in_days)
    audit(session, principal, "token_created", "token", row.id, {"role": body.role, "name": body.name}, _client(request))
    session.commit()
    return {"token": secret, "id": row.id, "name": row.name, "role": row.role}


@router.delete("/access/tokens/{token_id}")
def revoke_token(token_id: str, request: Request, principal: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
    row = get_or_404(session, RecognitionAccessToken, token_id, "Token")
    active_admins = session.scalar(select(func.count(RecognitionAccessToken.id)).where(RecognitionAccessToken.active.is_(True), RecognitionAccessToken.role == "admin")) or 0
    if row.role == "admin" and row.active and active_admins <= 1:
        raise HTTPException(409, "This is the last active administrator token; create another one first.")
    row.active = False
    audit(session, principal, "token_revoked", "token", row.id, {"name": row.name}, _client(request))
    session.commit()
    return {"revoked": True}


# ----------------------------------------------------------------------------- settings
@router.get("/settings")
def get_settings_(principal: Principal = Depends(operator), session: Session = Depends(db_session)) -> dict:
    from pathscope.recognition.face.stack import FACE_STACKS
    from pathscope.recognition.plate.parser import available_formats

    return {
        "values": all_recognition_settings(session),
        "definitions": definitions(),
        "face_stacks": {k: v["label"] for k, v in FACE_STACKS.items()},
        "plate_formats": [f.to_dict() for f in available_formats(get_settings().resolved_data_dir)],
        "modules": {m: st.to_dict() for m, st in module_states(session).items()},
    }


@router.put("/settings")
def put_settings(body: RecognitionSettingsIn, request: Request, principal: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
    try:
        values, changed = set_recognition_settings(session, body.values)
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    if changed:
        audit(session, principal, "setting_changed", "settings", None, {"keys": changed, "values": {k: values[k] for k in changed}}, _client(request))
        session.commit()
    return {"values": values, "changed": changed, "modules": {m: st.to_dict() for m, st in module_states(session, values).items()}}


# ----------------------------------------------------------------------------- people
@router.get("/people")
def list_people(include_disabled: bool = Query(default=True), principal: Principal = Depends(viewer), session: Session = Depends(db_session)) -> list[dict]:
    q = select(RecognitionPerson).order_by(RecognitionPerson.display_name.asc())
    if not include_disabled:
        q = q.where(RecognitionPerson.active.is_(True))
    return [person_to_dict(p) for p in session.scalars(q)]


@router.post("/people", status_code=201)
def create_person(body: PersonIn, request: Request, principal: Principal = Depends(operator), session: Session = Depends(db_session)) -> dict:
    _module_state_or_403(session, "face")
    svc = _people_service(session, need_stack=False)
    try:
        p = svc.create(body.display_name, body.reference_id, body.notes, body.valid_from, body.valid_until, created_by=principal.name)
    except EnrollmentError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(session, principal, "profile_created", "person", p.id, {"display_name": p.display_name, "reference_id": p.reference_id}, _client(request))
    session.commit()
    return person_to_dict(p, include_images=True)


@router.get("/people/{person_id}")
def get_person(person_id: str, principal: Principal = Depends(viewer), session: Session = Depends(db_session)) -> dict:
    p = get_or_404(session, RecognitionPerson, person_id, "Person")
    return person_to_dict(p, include_images=principal.at_least("operator"))


@router.put("/people/{person_id}")
def update_person(person_id: str, body: PersonUpdate, request: Request, principal: Principal = Depends(operator), session: Session = Depends(db_session)) -> dict:
    p = get_or_404(session, RecognitionPerson, person_id, "Person")
    data = body.model_dump(exclude_unset=True)
    changed = {}
    for key in ("display_name", "reference_id", "notes", "valid_from", "valid_until"):
        if key in data:
            setattr(p, key, data[key])
            changed[key] = str(data[key]) if data[key] is not None else None
    if body.clear_validity:
        p.valid_from = p.valid_until = None
        changed["validity"] = "cleared"
    audit(session, principal, "profile_updated", "person", p.id, changed, _client(request))
    session.commit()
    return person_to_dict(p, include_images=True)


@router.post("/people/{person_id}/disable")
def disable_person(person_id: str, request: Request, principal: Principal = Depends(operator), session: Session = Depends(db_session)) -> dict:
    p = get_or_404(session, RecognitionPerson, person_id, "Person")
    p.active = False
    audit(session, principal, "profile_disabled", "person", p.id, None, _client(request))
    session.commit()
    return person_to_dict(p)


@router.post("/people/{person_id}/enable")
def enable_person(person_id: str, request: Request, principal: Principal = Depends(operator), session: Session = Depends(db_session)) -> dict:
    p = get_or_404(session, RecognitionPerson, person_id, "Person")
    p.active = True
    audit(session, principal, "profile_enabled", "person", p.id, None, _client(request))
    session.commit()
    return person_to_dict(p)


@router.delete("/people/{person_id}")
def delete_person(person_id: str, request: Request, principal: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
    p = get_or_404(session, RecognitionPerson, person_id, "Person")
    values = all_recognition_settings(session)
    svc = PeopleService(session, get_store(), None, values)
    name = p.display_name
    result = svc.delete(p, int(values.get("recognition.retention.deleted_media_grace_days", 0) or 0))
    audit(session, principal, "profile_deleted", "person", person_id, {"display_name": name, **result}, _client(request))
    session.commit()
    return {"deleted": True, **result}


@router.post("/people/{person_id}/reenroll")
def reenroll_person(person_id: str, request: Request, principal: Principal = Depends(operator), session: Session = Depends(db_session)) -> dict:
    _module_state_or_403(session, "face")
    p = get_or_404(session, RecognitionPerson, person_id, "Person")
    result = PeopleService(session, get_store(), None, all_recognition_settings(session)).reenroll(p)
    audit(session, principal, "profile_reenrolled", "person", p.id, result, _client(request))
    session.commit()
    return person_to_dict(p, include_images=True)


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read()
    if not data:
        raise HTTPException(400, "The uploaded file is empty.")
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(400, "The image is larger than 25 MB.")
    return data


@router.post("/people/{person_id}/enrollment/analyze")
async def analyze_enrollment_image(person_id: str, file: UploadFile = File(...), view: str = Form(default="front"), variant: str = Form(default=""), principal: Principal = Depends(operator), session: Session = Depends(db_session)) -> dict:
    """Quality check and guidance without storing anything."""
    _module_state_or_403(session, "face")
    person = get_or_404(session, RecognitionPerson, person_id, "Person")
    data = await _read_upload(file)
    svc = _people_service(session, need_stack=(view != "rear"))
    try:
        return svc.analyze(data, view, svc.front_baseline(person, variant)).to_dict()
    except EnrollmentError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/people/{person_id}/enrollment/images", status_code=201)
async def add_enrollment_image(person_id: str, request: Request, file: UploadFile = File(...), view: str = Form(default="front"), variant: str = Form(default=""), principal: Principal = Depends(operator), session: Session = Depends(db_session)) -> dict:
    _module_state_or_403(session, "face")
    p = get_or_404(session, RecognitionPerson, person_id, "Person")
    data = await _read_upload(file)
    values = all_recognition_settings(session)
    svc = _people_service(session, need_stack=(view != "rear"))
    try:
        image_row, template, analysis = svc.add_image(p, data, view, keep_image=bool(values.get("recognition.privacy.store_enrollment_images", True)), baseline=svc.front_baseline(p, variant), variant=variant)
    except EnrollmentError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(session, principal, "enrollment_image_added", "person", p.id, {"view": view, "variant": clean_variant(variant), "image_id": image_row.id if image_row else None, "template": template is not None, "quality": (analysis.quality or {}).get("score")}, _client(request))
    session.commit()
    return {"analysis": analysis.to_dict(), "image_id": image_row.id if image_row else None, "template_id": template.id if template else None, "person": person_to_dict(p, include_images=True)}


def _grab_camera_frame(session: Session, camera: Camera, t: float) -> np.ndarray:
    from pathscope.services.preview import PreviewConfig, PreviewUnavailable, get_preview_manager
    from pathscope.vision.preprocessing import PreprocessConfig, apply_preprocess
    from pathscope.vision.sources.base import SourceError
    from pathscope.vision.sources.file_source import read_frame_at

    if camera.source_type == "file":
        uri = camera.source_uri
        if camera.video_id is not None:
            video = session.get(Video, camera.video_id)
            uri = video.path if video else ""
        try:
            frame, _info = read_frame_at(uri, t)
        except SourceError as exc:
            raise HTTPException(400, str(exc)) from exc
        if frame is None:
            raise HTTPException(400, "Could not read a frame from this video.")
        return apply_preprocess(frame, PreprocessConfig(rotation=camera.rotation, crop=camera.crop))
    run = next((h for h in get_supervisor().active() if h.spec.camera_id == camera.id), None)
    if run is not None and run.latest_preview is not None:
        img = cv2.imdecode(np.frombuffer(run.latest_preview.jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise HTTPException(400, "No usable frame from the running camera.")
        return img
    manager = get_preview_manager()
    try:
        live = manager.acquire(PreviewConfig.from_camera(camera))
    except PreviewUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    try:
        if not live.wait_for_frame(12.0, min_live_s=0.6 if camera.source_type == "usb" else 0.0):
            raise HTTPException(400, live.error or "The camera did not deliver a frame.")
        img = cv2.imdecode(np.frombuffer(live.jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    finally:
        manager.release(live)
    if img is None:
        raise HTTPException(400, "No usable frame from the camera.")
    return img


@router.post("/people/{person_id}/enrollment/capture")
def capture_enrollment_image(person_id: str, body: CaptureIn, request: Request, principal: Principal = Depends(operator), session: Session = Depends(db_session)) -> dict:
    """Grab one frame from a camera on the server side, analyse it and optionally store it."""
    _module_state_or_403(session, "face")
    p = get_or_404(session, RecognitionPerson, person_id, "Person")
    camera = get_or_404(session, Camera, body.camera_id, "Camera")
    frame = _grab_camera_frame(session, camera, body.t)
    ok, enc = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not ok:
        raise HTTPException(500, "Could not encode the frame.")
    data = enc.tobytes()
    values = all_recognition_settings(session)
    svc = _people_service(session, need_stack=(body.view != "rear"))
    baseline = svc.front_baseline(p, body.variant)
    try:
        if body.store:
            image_row, template, analysis = svc.add_image(p, data, body.view, keep_image=bool(values.get("recognition.privacy.store_enrollment_images", True)), baseline=baseline, variant=body.variant)
            audit(session, principal, "enrollment_image_added", "person", p.id, {"view": body.view, "variant": clean_variant(body.variant), "image_id": image_row.id if image_row else None, "template": template is not None, "camera_id": camera.id}, _client(request))
            session.commit()
            return {"analysis": analysis.to_dict(), "stored": True, "image_id": image_row.id if image_row else None, "person": person_to_dict(p, include_images=True)}
        return {"analysis": svc.analyze(data, body.view, baseline).to_dict(), "stored": False}
    except EnrollmentError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/people/{person_id}/enrollment/images/{image_id}/file")
def enrollment_image_file(person_id: str, image_id: str, principal: Principal = Depends(operator), session: Session = Depends(db_session)):
    p = get_or_404(session, RecognitionPerson, person_id, "Person")
    svc = PeopleService(session, get_store(), None, all_recognition_settings(session))
    try:
        data = svc.read_image(p, image_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"The image could not be decrypted: {exc}") from exc
    if data is None:
        raise HTTPException(404, "image not found")
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.delete("/people/{person_id}/enrollment/images/{image_id}")
def delete_enrollment_image(person_id: str, image_id: str, request: Request, principal: Principal = Depends(operator), session: Session = Depends(db_session)) -> dict:
    p = get_or_404(session, RecognitionPerson, person_id, "Person")
    svc = PeopleService(session, get_store(), None, all_recognition_settings(session))
    if not svc.delete_image(p, image_id):
        raise HTTPException(404, "image not found")
    audit(session, principal, "enrollment_image_deleted", "person", p.id, {"image_id": image_id}, _client(request))
    session.commit()
    return person_to_dict(p, include_images=True)


@router.delete("/people/{person_id}/enrollment/looks/{variant}")
def delete_look(person_id: str, variant: str, request: Request, principal: Principal = Depends(operator), session: Session = Depends(db_session)) -> dict:
    """Remove one look with its pictures and templates (not the first enrollment)."""
    p = get_or_404(session, RecognitionPerson, person_id, "Person")
    svc = PeopleService(session, get_store(), None, all_recognition_settings(session))
    try:
        result = svc.delete_variant(p, variant)
    except EnrollmentError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(session, principal, "enrollment_look_deleted", "person", p.id, result, _client(request))
    session.commit()
    return person_to_dict(p, include_images=True)


@router.post("/people/{person_id}/enrollment/finalize")
def finalize_enrollment(person_id: str, request: Request, principal: Principal = Depends(operator), session: Session = Depends(db_session)) -> dict:
    _module_state_or_403(session, "face")
    p = get_or_404(session, RecognitionPerson, person_id, "Person")
    result = PeopleService(session, get_store(), None, all_recognition_settings(session)).finalize(p)
    audit(session, principal, "enrollment_finalized", "person", p.id, {"status": result["status"], "quality": result.get("quality"), "templates": result.get("templates")}, _client(request))
    session.commit()
    return {"result": result, "person": person_to_dict(p, include_images=True)}


# ----------------------------------------------------------------------------- vehicles
@router.get("/vehicles")
def list_vehicles(principal: Principal = Depends(viewer), session: Session = Depends(db_session)) -> list[dict]:
    return [vehicle_to_dict(v) for v in session.scalars(select(RecognitionVehicle).order_by(RecognitionVehicle.plate.asc()))]


@router.get("/vehicles/groups")
def vehicle_groups(principal: Principal = Depends(viewer), session: Session = Depends(db_session)) -> list[str]:
    return all_groups(session)


@router.post("/vehicles", status_code=201)
def create_vehicle_(body: VehicleIn, request: Request, principal: Principal = Depends(operator), session: Session = Depends(db_session)) -> dict:
    _module_state_or_403(session, "plate")
    try:
        v = create_vehicle(session, body.model_dump())
    except VehicleError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(session, principal, "vehicle_created", "vehicle", v.id, {"plate": v.plate, "groups": v.groups}, _client(request))
    session.commit()
    return vehicle_to_dict(v)


@router.get("/vehicles/{vehicle_id}")
def get_vehicle(vehicle_id: str, principal: Principal = Depends(viewer), session: Session = Depends(db_session)) -> dict:
    return vehicle_to_dict(get_or_404(session, RecognitionVehicle, vehicle_id, "Vehicle"))


@router.put("/vehicles/{vehicle_id}")
def update_vehicle_(vehicle_id: str, body: VehicleUpdate, request: Request, principal: Principal = Depends(operator), session: Session = Depends(db_session)) -> dict:
    v = get_or_404(session, RecognitionVehicle, vehicle_id, "Vehicle")
    data = body.model_dump(exclude_unset=True)
    try:
        update_vehicle(session, v, data)
    except VehicleError as exc:
        raise HTTPException(400, str(exc)) from exc
    action = "vehicle_updated"
    if list(data.keys()) == ["active"]:
        action = "vehicle_enabled" if data["active"] else "vehicle_disabled"
    audit(session, principal, action, "vehicle", v.id, {k: (v_ if not isinstance(v_, list) else list(v_)) for k, v_ in data.items()}, _client(request))
    session.commit()
    return vehicle_to_dict(v)


@router.delete("/vehicles/{vehicle_id}")
def delete_vehicle(vehicle_id: str, request: Request, principal: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
    v = get_or_404(session, RecognitionVehicle, vehicle_id, "Vehicle")
    plate = v.plate
    session.delete(v)
    audit(session, principal, "vehicle_deleted", "vehicle", vehicle_id, {"plate": plate}, _client(request))
    session.commit()
    return {"deleted": True}


@router.post("/plates/parse")
def parse_plate(body: PlateParseIn, principal: Principal = Depends(viewer), session: Session = Depends(db_session)) -> dict:
    from pathscope.recognition.plate.parser import PlateParser, load_formats

    values = all_recognition_settings(session)
    formats = load_formats(get_settings().resolved_data_dir, body.formats or str(values.get("recognition.plate.formats") or "generic"))
    parser = PlateParser(formats, default_region=str(values.get("recognition.plate.default_region") or ""))
    parsed = parser.parse(body.text, region_hint=body.region_hint)
    return {**parsed.to_dict(), "exact": parser.parse_exact(body.text, body.region_hint).to_dict(), "formats_tried": [f.id for f in formats]}


# ----------------------------------------------------------------------------- events
def _event_filters(run_id, experiment_id, camera_id, module, kind, person_id, vehicle_id, plate, track_id, from_time, to_time) -> dict:
    return {"run_id": run_id, "experiment_id": experiment_id, "camera_id": camera_id, "module": module, "kind": kind, "person_id": person_id, "vehicle_id": vehicle_id, "plate": plate, "track_id": track_id, "from_time": from_time, "to_time": to_time}


@router.get("/events")
def list_events(
    run_id: int | None = None, experiment_id: int | None = None, camera_id: int | None = None, module: str | None = None, kind: str | None = None,
    person_id: str | None = None, vehicle_id: str | None = None, plate: str | None = None, track_id: int | None = None,
    from_time: datetime | None = None, to_time: datetime | None = None,
    page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=500),
    principal: Principal = Depends(viewer), session: Session = Depends(db_session),
) -> dict:
    base = apply_filters(select(RecognitionEvent), _event_filters(run_id, experiment_id, camera_id, module, kind, person_id, vehicle_id, plate, track_id, from_time, to_time))
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = list(session.scalars(base.order_by(RecognitionEvent.id.desc()).offset((page - 1) * page_size).limit(page_size)))
    names, vehicles = name_maps(session, rows)
    return {"items": [event_to_dict(e, names, vehicles) for e in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/events/export")
def export_events_(
    request: Request, format: str = Query(default="csv", pattern="^(csv|json)$"),
    run_id: int | None = None, experiment_id: int | None = None, camera_id: int | None = None, module: str | None = None, kind: str | None = None,
    person_id: str | None = None, vehicle_id: str | None = None, plate: str | None = None, track_id: int | None = None,
    from_time: datetime | None = None, to_time: datetime | None = None,
    principal: Principal = Depends(admin), session: Session = Depends(db_session),
):
    filters = _event_filters(run_id, experiment_id, camera_id, module, kind, person_id, vehicle_id, plate, track_id, from_time, to_time)
    payload, media_type, ext = export_events(session, filters, format)
    audit(session, principal, "export_created", "events", None, {"format": format, "filters": {k: str(v) for k, v in filters.items() if v is not None}, "bytes": len(payload)}, _client(request))
    session.commit()
    return Response(content=payload, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="cvscope_recognition_{int(time.time())}.{ext}"'})


@router.get("/events/{event_id}")
def get_event(event_id: int, principal: Principal = Depends(viewer), session: Session = Depends(db_session)) -> dict:
    e = get_or_404(session, RecognitionEvent, event_id, "Recognition event")
    names, vehicles = name_maps(session, [e])
    return event_to_dict(e, names, vehicles)


@router.get("/events/{event_id}/crop")
def event_crop(event_id: int, principal: Principal = Depends(operator), session: Session = Depends(db_session)):
    e = get_or_404(session, RecognitionEvent, event_id, "Recognition event")
    if not e.crop_path:
        raise HTTPException(404, "no crop was stored for this event")
    try:
        data = get_store().read_crop(e.id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"The crop could not be decrypted: {exc}") from exc
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.delete("/events/{event_id}")
def delete_event(event_id: int, request: Request, principal: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
    get_or_404(session, RecognitionEvent, event_id, "Recognition event")
    n = delete_events(session, ids=[event_id])
    audit(session, principal, "events_deleted", "events", str(event_id), {"count": n}, _client(request))
    session.commit()
    return {"deleted": n}


@router.post("/events/delete")
def delete_events_(body: DeleteEventsIn, request: Request, principal: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
    filters = {k: v for k, v in body.model_dump().items() if k != "ids" and v is not None}
    if not body.ids and not filters:
        raise HTTPException(400, "Give event ids or a filter.")
    n = delete_events(session, ids=body.ids, filters=filters)
    audit(session, principal, "events_deleted", "events", None, {"count": n, "ids": body.ids, "filters": filters}, _client(request))
    session.commit()
    return {"deleted": n}



# ----------------------------------------------------------------------------- names for stored events / live tracks
@router.post("/resolve")
def resolve_entities(body: ResolveIn, principal: Principal = Depends(viewer), session: Session = Depends(db_session)) -> dict:
    """Names for the opaque ids in ordinary events.

    Stored events carry ``context.entity`` with ids only, so the core API and
    every export stay anonymous. A viewer with a recognition token can ask
    here what those ids stand for; nothing else is disclosed."""
    identities: dict[str, dict] = {}
    vehicles: dict[str, dict] = {}
    ids = [i for i in dict.fromkeys(body.identity_ids) if i]
    if ids:
        for p in session.scalars(select(RecognitionPerson).where(RecognitionPerson.id.in_(ids))):
            identities[p.id] = {"id": p.id, "display_name": p.display_name, "reference_id": p.reference_id, "active": p.active, "enrollment_status": p.enrollment_status}
    vids = [i for i in dict.fromkeys(body.vehicle_ids) if i]
    if vids:
        for v in session.scalars(select(RecognitionVehicle).where(RecognitionVehicle.id.in_(vids))):
            vehicles[v.id] = {"id": v.id, "plate": v.plate, "label": v.description or v.plate, "groups": list(v.groups or []), "active": v.active}
    return {"identities": identities, "vehicles": vehicles, "missing": sorted(set(ids) - set(identities)) + sorted(set(vids) - set(vehicles))}


@router.get("/live/{run_id}/tracks")
def live_tracks(run_id: int, principal: Principal = Depends(viewer)) -> dict:
    """What the run recognizes on the newest preview frame, track by track."""
    h = get_supervisor().get(run_id)
    if h is None:
        raise HTTPException(404, "run is not active")
    msg = h.latest_preview
    tracks = []
    for t in (msg.tracks if msg else []) or []:
        entity = t.get("recognition")
        if not entity:
            continue
        # The worker sends the pipeline's overlay form: identity / plate /
        # vehicle. The entity form (display_name, vehicle_label) is accepted
        # too, so either producer can be read here.
        name = entity.get("identity") or entity.get("display_name")
        vehicle = entity.get("vehicle") or entity.get("vehicle_label")
        kind = entity.get("kind")
        if kind is None:
            if entity.get("identity_id"):
                kind = "enrolled_person"
            elif entity.get("vehicle_id"):
                kind = "registered_vehicle"
            elif entity.get("plate"):
                kind = "recognized_plate"
            else:
                kind = f"anonymous_{'vehicle' if module_for_class(str(t.get('cls') or '')) == 'plate' else 'person'}"
        tracks.append({
            "track_id": t.get("id"),
            "object_class": t.get("cls"),
            "state": t.get("state"),
            "kind": kind,
            "status": entity.get("status"),
            "identity_id": entity.get("identity_id"),
            "display_name": name,
            "plate": entity.get("plate"),
            "vehicle_id": entity.get("vehicle_id"),
            "vehicle_label": vehicle,
            "groups": entity.get("groups") or [],
            "confidence": entity.get("confidence"),
        })
    return {"run_id": run_id, "camera_id": h.spec.camera_id, "seq": h.preview_seq, "active": not h.finished, "tracks": tracks}


# ----------------------------------------------------------------------------- test bench
def _identify(session: Session, img: np.ndarray) -> dict:
    values = all_recognition_settings(session)
    svc = _people_service(session, need_stack=True)
    try:
        return identify_image(svc, svc.stack, values, img)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"The picture could not be identified: {exc}") from exc


@router.post("/test/identify")
async def test_identify(file: UploadFile = File(...), principal: Principal = Depends(operator), session: Session = Depends(db_session)) -> dict:
    """Try one uploaded picture against the enrolled identities. Nothing is stored."""
    _module_state_or_403(session, "face")
    data = await _read_upload(file)
    img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "The file is not a readable image.")
    return _identify(session, img)


@router.post("/test/identify/camera")
def test_identify_camera(body: IdentifyIn, principal: Principal = Depends(operator), session: Session = Depends(db_session)) -> dict:
    """Take one frame from a camera and try it. Nothing is stored."""
    _module_state_or_403(session, "face")
    camera = get_or_404(session, Camera, body.camera_id, "Camera")
    return _identify(session, _grab_camera_frame(session, camera, body.t))


@router.get("/test/enrollment")
def test_enrollment(principal: Principal = Depends(operator), session: Session = Depends(db_session)) -> dict:
    """How strong every enrolled profile is and what would make it stronger."""
    _module_state_or_403(session, "face")
    values = all_recognition_settings(session)
    svc = _people_service(session, need_stack=True)
    return enrollment_report(svc, values)




# ----------------------------------------------------------------------------- teaching from the test bench
@router.post("/test/teach")
async def test_teach(
    request: Request,
    file: UploadFile = File(...),
    person_id: str = Form(...),
    look: str = Form(default=LIVE_LOOK),
    force: bool = Form(default=False),
    principal: Principal = Depends(operator),
    session: Session = Depends(db_session),
) -> dict:
    """Add a picture the operator has confirmed to that person's enrollment."""
    _module_state_or_403(session, "face")
    person = get_or_404(session, RecognitionPerson, person_id, "Person")
    data = await _read_upload(file)
    img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "The file is not a readable image.")
    try:
        return teach_picture(session, principal, person, img, look=look, force=force, source="picture", client=_client(request), stack=_people_service(session, need_stack=True).stack)
    except TeachRefused as exc:
        raise HTTPException(409 if exc.code == "mismatch" else 400, str(exc)) from exc


@router.post("/test/feedback")
def test_feedback(body: TestFeedbackIn, request: Request, principal: Principal = Depends(operator), session: Session = Depends(db_session)) -> dict:
    """Record whether a recognition shown by the test bench was right.

    This is a log, not training: it never changes a threshold or a template by
    itself. It shows how often the installation is right on this site, and the
    corrections point at the profiles that need more pictures."""
    _module_state_or_403(session, "face")
    detail = {k: v for k, v in body.model_dump().items() if v not in (None, "")}
    if body.person_id:
        person = session.get(RecognitionPerson, body.person_id)
        if person is not None:
            detail["display_name"] = person.display_name
    audit(session, principal, "test_feedback", "person", body.person_id, detail, _client(request))
    session.commit()
    return {"recorded": True, **_feedback_counts(session)}


def _feedback_counts(session: Session) -> dict:
    rows = list(session.scalars(select(RecognitionAudit).where(RecognitionAudit.action == "test_feedback").order_by(RecognitionAudit.id.desc()).limit(500)))
    correct = sum(1 for r in rows if (r.detail or {}).get("verdict") == "correct")
    wrong = sum(1 for r in rows if (r.detail or {}).get("verdict") == "wrong")
    unknown = sum(1 for r in rows if (r.detail or {}).get("verdict") == "unknown_person")
    taught = session.scalar(select(func.count(RecognitionAudit.id)).where(RecognitionAudit.action == "test_taught")) or 0
    return {"checked": correct + wrong, "correct": correct, "wrong": wrong, "unknown_person": unknown, "taught": int(taught)}


@router.get("/test/feedback")
def test_feedback_log(limit: int = Query(default=50, ge=1, le=500), principal: Principal = Depends(operator), session: Session = Depends(db_session)) -> dict:
    rows = session.scalars(
        select(RecognitionAudit).where(RecognitionAudit.action.in_(("test_feedback", "test_taught"))).order_by(RecognitionAudit.id.desc()).limit(limit)
    )
    return {
        **_feedback_counts(session),
        "recent": [{"id": r.id, "at": r.at, "action": r.action, "actor": r.actor, "target_id": r.target_id, "detail": r.detail} for r in rows],
    }


# ----------------------------------------------------------------------------- diagnostics / audit
@router.get("/diagnostics/runs/{run_id}")
def run_diagnostics(run_id: int, principal: Principal = Depends(viewer)) -> dict:
    h = get_supervisor().get(run_id)
    if h is None:
        raise HTTPException(404, "run is not active")
    diag = getattr(h, "recognition_diag", None)
    return {"run_id": run_id, "active": not h.finished, "diagnostics": diag, "recognition": (h.spec.recognition or {}).get("warnings") if h.spec.recognition else None, "modules": [m for m in MODULES if h.spec.recognition and m in h.spec.recognition]}


@router.get("/diagnostics/active")
def active_runs(principal: Principal = Depends(viewer)) -> list[dict]:
    out = []
    for h in get_supervisor().active():
        out.append({"run_id": h.run_id, "camera_id": h.spec.camera_id, "experiment_id": h.spec.experiment_id, "state": h.state, "modules": [m for m in MODULES if h.spec.recognition and m in h.spec.recognition], "has_diagnostics": getattr(h, "recognition_diag", None) is not None})
    return out


@router.get("/audit")
def audit_log(limit: int = Query(default=200, ge=1, le=2000), action: str | None = None, principal: Principal = Depends(admin), session: Session = Depends(db_session)) -> list[dict]:
    q = select(RecognitionAudit).order_by(RecognitionAudit.id.desc()).limit(limit)
    if action:
        q = q.where(RecognitionAudit.action == action)
    return [{"id": a.id, "at": a.at, "actor": a.actor, "actor_role": a.actor_role, "action": a.action, "target_type": a.target_type, "target_id": a.target_id, "detail": a.detail, "client": a.client} for a in session.scalars(q)]


# ----------------------------------------------------------------------------- benchmark
@router.post("/benchmark")
def benchmark(body: BenchmarkIn, principal: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
    from pathscope.recognition.benchmark import run_recognition_benchmark

    values = all_recognition_settings(session)
    try:
        return run_recognition_benchmark(body.module, values, device=body.device, iterations=body.iterations)
    except RecognitionNotReady as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Benchmark failed: {exc}") from exc
