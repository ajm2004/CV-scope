"""The facade the open-source core calls.

Everything the core needs from the recognition modules goes through here:
module status for the UI and the privacy list, the run payload for a worker,
the load estimate for the hardware recommendations. All of it fails closed:
without a valid licence nothing is built.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from pathscope.config import get_settings
from pathscope.domain.rules import Rule
from pathscope.domain.scene import VEHICLE_CLASSES
from pathscope.recognition import MODULE_LABELS, MODULES
from pathscope.recognition.common.config import all_recognition_settings, module_config
from pathscope.recognition.licensing import ModuleState, get_license_manager
from pathscope.recognition.registry.store import get_store


class RecognitionNotReady(RuntimeError):
    """A run needs recognition but it cannot start (models missing, ...)."""


@dataclass
class ModelPaths:
    face: dict | None
    plate: dict | None
    missing: list[str]


def module_states(session: Session, values: dict | None = None) -> dict[str, ModuleState]:
    values = values or all_recognition_settings(session)
    lm = get_license_manager()
    return {m: lm.module_state(m, enabled=bool(values.get(f"recognition.{m}.enabled", True))) for m in MODULES}


def active_modules(session: Session, values: dict | None = None) -> set[str]:
    return {m for m, st in module_states(session, values).items() if st.active}


def face_stack_id(values: dict) -> str:
    return str(values.get("recognition.face.stack") or "opencv")


def model_paths(values: dict) -> ModelPaths:
    """Weights of the configured stacks, from the model manager."""
    from pathscope.models.catalog import CATALOG_BY_ID
    from pathscope.models.manager import get_model_manager
    from pathscope.recognition.face.stack import FACE_STACKS

    manager = get_model_manager()
    missing: list[str] = []

    def path_of(model_id: str) -> str | None:
        spec = CATALOG_BY_ID.get(model_id)
        if spec is None:
            missing.append(model_id)
            return None
        if not manager.is_installed(spec):
            missing.append(spec.name)
            return None
        return str(manager.weights_path(spec))

    face: dict | None = None
    stack = face_stack_id(values)
    if stack == "stub":
        face = {"stack": "stub", "detector": "", "embedder": ""}
    elif stack in FACE_STACKS:
        det = path_of(FACE_STACKS[stack]["detector"])
        emb = path_of(FACE_STACKS[stack]["embedder"])
        if det and emb:
            det_spec = CATALOG_BY_ID[FACE_STACKS[stack]["detector"]]
            emb_spec = CATALOG_BY_ID[FACE_STACKS[stack]["embedder"]]
            face = {"stack": stack, "detector": det, "embedder": emb, "detector_version": det_spec.model_version, "embedder_version": emb_spec.model_version, "embedder_meta": dict(emb_spec.meta)}
    else:
        missing.append(f"face stack '{stack}'")
    plate: dict | None = None
    det_id = str(values.get("recognition.plate.detector_model") or "plate-det-yolov9t-384")
    ocr_id = str(values.get("recognition.plate.ocr_model") or "plate-ocr-cct-s-v2")
    if det_id == "stub" or ocr_id == "stub":
        plate = {"stack": "stub"}
    else:
        det = path_of(det_id)
        ocr = path_of(ocr_id)
        if det and ocr:
            ocr_spec = CATALOG_BY_ID[ocr_id]
            cfg_file = ocr_spec.meta.get("ocr_config_file")
            ocr_config = str(manager.model_dir(ocr_spec) / cfg_file) if cfg_file else None
            plate = {"stack": "onnx", "detector": det, "ocr": ocr, "ocr_config": ocr_config, "ocr_meta": dict(ocr_spec.meta), "detector_version": CATALOG_BY_ID[det_id].model_version, "ocr_version": ocr_spec.model_version}
    return ModelPaths(face, plate, missing)


def rules_need(rules: list[dict]) -> set[str]:
    needed: set[str] = set()
    for r in rules or []:
        try:
            rule = Rule.model_validate(r)
        except Exception:  # noqa: BLE001
            continue
        if rule.enabled:
            needed |= rule.modules_needed
    return needed


def build_run_payload(session: Session, experiment, camera=None) -> dict | None:
    """What a worker needs for this run, or ``None`` when no module applies.

    A module is included when it is licensed and enabled and the experiment
    tracks its object class. Rules that need an inactive module are reported
    (the rule engine keeps them inactive); rules that need an active module
    whose models are missing stop the run with a clear message."""
    values = all_recognition_settings(session)
    states = module_states(session, values)
    classes = set(experiment.object_classes or [])
    wants_face = not classes or "person" in classes
    wants_plate = not classes or bool(classes & set(VEHICLE_CLASSES))
    needed = rules_need(experiment.rules or [])
    paths = model_paths(values)
    settings = get_settings()
    payload: dict = {"grace_s": float(values.get("recognition.rules.subject_grace_s", 5.0)), "store_crops": bool(values.get("recognition.privacy.store_recognition_crops", False)), "warnings": []}
    if states["face"].active and wants_face:
        if paths.face is None:
            if "face" in needed:
                raise RecognitionNotReady("Face recognition is licensed but its models are not installed. Install the face detector and embedding model on the Models page, or remove the recognition condition from the rules.")
            payload["warnings"].append("Face recognition is licensed but its models are not installed; people stay anonymous in this run.")
        else:
            from pathscope.recognition.face.stack import FACE_STACKS, stub_allowed
            from pathscope.recognition.registry.people import PeopleService

            stack = paths.face["stack"]
            if stack == "stub" and not stub_allowed():
                raise RecognitionNotReady("The stub face stack is only available in tests.")
            people = PeopleService(session, get_store(), None, values)
            expected_version = None if stack == "stub" else f"{paths.face['detector_version']}+{paths.face['embedder_version']}"
            identities = people.identities_for_worker(expected_version)
            cfg = module_config(values, "face")
            payload["face"] = {"stack": stack, "models": {"detector": paths.face["detector"], "embedder": paths.face["embedder"]}, "config": cfg, "identities": identities, "label": FACE_STACKS.get(stack, {}).get("label", stack)}
            if not identities:
                payload["warnings"].append("Face recognition is active but no enrolled, valid identity exists; people stay anonymous.")
    elif "face" in needed:
        payload["warnings"].append(f"Rules with a person recognition condition are inactive: face recognition is {states['face'].state.replace('_', ' ')}.")
    if states["plate"].active and wants_plate:
        if paths.plate is None:
            if "plate" in needed:
                raise RecognitionNotReady("Plate recognition is licensed but its models are not installed. Install the plate detector and OCR model on the Models page, or remove the recognition condition from the rules.")
            payload["warnings"].append("Plate recognition is licensed but its models are not installed; vehicles stay anonymous in this run.")
        else:
            from pathscope.recognition.plate.parser import load_formats
            from pathscope.recognition.registry.vehicles import vehicles_for_worker

            cfg = module_config(values, "plate")
            formats = [f.to_dict() for f in load_formats(settings.resolved_data_dir, str(values.get("recognition.plate.formats") or "generic"))]
            payload["plate"] = {"stack": paths.plate["stack"], "models": {k: v for k, v in paths.plate.items() if k != "stack"}, "config": cfg, "vehicles": vehicles_for_worker(session), "formats": formats}
    elif "plate" in needed:
        payload["warnings"].append(f"Rules with a vehicle recognition condition are inactive: plate recognition is {states['plate'].state.replace('_', ' ')}.")
    if "face" not in payload and "plate" not in payload:
        return {"warnings": payload["warnings"]} if payload["warnings"] else None
    return payload


def payload_summary(payload: dict | None) -> dict:
    """What a run snapshot records (never templates or plates)."""
    if not payload:
        return {"modules": []}
    out: dict = {"modules": [m for m in ("face", "plate") if m in payload], "warnings": payload.get("warnings", [])}
    if "face" in payload:
        out["face"] = {"stack": payload["face"]["stack"], "identities": len(payload["face"].get("identities") or [])}
    if "plate" in payload:
        out["plate"] = {"vehicles": len(payload["plate"].get("vehicles") or []), "formats": [f["id"] for f in payload["plate"].get("formats") or []]}
    return out


def privacy_items(session: Session) -> list[dict]:
    """Rows for the "What this installation stores" list."""
    states = module_states(session)
    values = all_recognition_settings(session)
    face, plate = states["face"], states["plate"]
    items = []
    if face.licensed:
        items.append({"item": "Faces or identities (licensed module)", "stored": True, "detail": f"Face recognition is {face.state.replace('_', ' ')}. Only deliberately enrolled identities are matched; their encrypted templates and enrollment images are kept under data/recognition. Unknown people stay anonymous tracks. No demographic attribute is inferred."})
    else:
        items.append({"item": "Faces or identities", "stored": False, "detail": "No face recognition, identity storage, or matching of people across runs or cameras. (A licensed module exists; it is not licensed on this installation.)"})
    if plate.licensed:
        keep_unknown = bool(values.get("recognition.plate.record_unknown_plates", True))
        items.append({"item": "Vehicle plates (licensed module)", "stored": True, "detail": f"Plate recognition is {plate.state.replace('_', ' ')}. Plate reads are stored as recognition events" + (" including plates that are not registered." if keep_unknown else "; only registered vehicles are kept.")})
    else:
        items.append({"item": "Vehicle plates", "stored": False, "detail": "No plate reading. (A licensed module exists; it is not licensed on this installation.)"})
    if face.licensed or plate.licensed:
        items.append({"item": "Recognition events", "stored": True, "detail": f"Kept for {values.get('recognition.retention.events_days')} days (0 = forever); unregistered plate reads for {values.get('recognition.retention.unknown_plate_days')} days. Visible only with a recognition access token."})
        items.append({"item": "Face / plate crops with recognition events", "stored": bool(values.get("recognition.privacy.store_recognition_crops", False)), "detail": "Encrypted at rest; off by default."})
    return items


def status_payload(session: Session) -> dict:
    """Public status: module states, licence summary, access bootstrap state, model readiness."""
    from pathscope.recognition.common.access import has_any_token

    values = all_recognition_settings(session)
    states = module_states(session, values)
    lm = get_license_manager()
    paths = model_paths(values)
    return {
        "modules": {m: {**states[m].to_dict(), "label": MODULE_LABELS[m], "models_ready": (paths.face if m == "face" else paths.plate) is not None} for m in MODULES},
        "license": lm.describe(),
        "access": {"has_tokens": has_any_token(session)},
        "missing_models": paths.missing,
        "face_stack": face_stack_id(values),
        "any_licensed": any(st.licensed for st in states.values()),
    }


_stack_cache: dict[str, object] = {}


def enrollment_stack(values: dict):
    """The face stack used for enrollment in the API process (cached per configuration)."""
    from pathscope.recognition.face.stack import create_face_stack

    paths = model_paths(values)
    if paths.face is None:
        raise RecognitionNotReady("The face models are not installed. Install the face detector and embedding model on the Models page." + (f" Missing: {', '.join(paths.missing)}." if paths.missing else ""))
    key = f"{paths.face['stack']}|{paths.face['detector']}|{paths.face['embedder']}|{values.get('recognition.face.min_face_px')}|{values.get('recognition.face.min_quality')}"
    stack = _stack_cache.get(key)
    if stack is None:
        for old in list(_stack_cache.values()):
            try:
                old.close()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass
        _stack_cache.clear()
        stack = _stack_cache[key] = create_face_stack(paths.face["stack"], {"detector": paths.face["detector"], "embedder": paths.face["embedder"]}, device=str(values.get("recognition.face.device") or "auto"), cfg=module_config(values, "face"))
    return stack


def data_dir() -> Path:
    return get_settings().resolved_data_dir
