"""The recognition test bench: does this installation recognize the people it
has enrolled, and is the enrollment good enough?

Two questions are answered here, both read-only:

* **Identify a picture** (``identify_image``) — run the same detector, quality
  gate, alignment, embedding and matcher a run would use, and report every
  step: the face that was found, why a frame was refused, the ranked
  candidates with their similarity, the thresholds in force and the verdict.
  Nothing is stored and no event is written; it is a rehearsal, not a run.
* **Check the enrollment** (``enrollment_report``) — for every enrolled person,
  how well their own pictures agree, how close the nearest other person is,
  and what would make recognition steadier (more views, another look, a fresh
  enrollment after a model change).

A third step is the operator's answer: ``teach_picture`` adds a picture they
have confirmed to that person's enrollment, under its own look, so a profile
grows from what the camera really sees. It is not model training and it never
moves a threshold; it adds an enrollment picture, with the same quality gate
as any other, and it is audited.

Everything here refuses to invent: a face that is too small or too blurred is
reported as insufficient quality, never matched against the registry, and a
picture that does not match the profile is refused unless the operator
overrides it deliberately.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np

from pathscope.recognition.common.types import (
    INSUFFICIENT_QUALITY,
    POSSIBLE_MATCH,
    RECOGNIZED,
    UNKNOWN,
    QualityReport,
)
from pathscope.recognition.face.matcher import FaceMatcher, IdentityTemplates
from pathscope.recognition.registry.people import PeopleService

TOP_K = 5
# Pictures confirmed at the test bench go into their own look, so they can be
# told apart from the enrollment session and removed on their own.
LIVE_LOOK = "Live confirmations"


class TeachRefused(RuntimeError):
    """The picture was not added. ``code`` is ``quality`` or ``mismatch``."""

    def __init__(self, message: str, code: str = "quality", similarity: float | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.similarity = similarity


def _thresholds(stack: Any, values: dict) -> dict:
    match = values.get("recognition.face.match_threshold")
    possible = values.get("recognition.face.possible_threshold")
    return {
        "match": float(match) if match is not None else float(stack.embedder.default_match_threshold),
        "possible": float(possible) if possible is not None else float(stack.embedder.default_possible_threshold),
        "margin": float(values.get("recognition.face.margin", 0.05) or 0.0),
        "min_face_px": float(values.get("recognition.face.min_face_px", 40) or 40),
        "min_quality": float(values.get("recognition.face.min_quality", 0.45) or 0.0),
    }


def build_matcher(svc: PeopleService, stack: Any, values: dict) -> tuple[FaceMatcher, dict]:
    """A matcher over the identities a run would load, plus what was left out."""
    thr = _thresholds(stack, values)
    version = svc.model_version
    usable = svc.identities_for_worker(model_version=version)
    everyone = svc.identities_for_worker()
    identities = [
        IdentityTemplates(
            identity_id=str(i["id"]),
            display_name=str(i.get("name") or i["id"]),
            embeddings=np.asarray(i["templates"], dtype=np.float32),
            model_version=str(i.get("model_version", "")),
        )
        for i in usable
        if i.get("templates")
    ]
    matcher = FaceMatcher(identities, thr["match"], thr["possible"], thr["margin"])
    info = {
        "model_version": version,
        "identities": matcher.n_identities,
        "templates": matcher.n_templates,
        "identities_other_model": max(0, len(everyone) - len(usable)),
        "thresholds": thr,
    }
    return matcher, info


def _face_advice(status: str, quality: QualityReport | None, best_sim: float | None, thr: dict, n_identities: int) -> list[str]:
    """What the operator can do about this outcome, in plain words."""
    out: list[str] = []
    if quality is not None and quality.size_px < thr["min_face_px"]:
        out.append(f"The face is {quality.size_px:.0f} px high; recognition needs at least {thr['min_face_px']:.0f} px. Move the camera closer, zoom in or raise the resolution.")
    if quality is not None and quality.reasons:
        out.extend(quality.reasons)
    if status == UNKNOWN:
        if n_identities == 0:
            out.append("Nobody is enrolled for the models in use, so every face reads Unknown.")
        elif best_sim is not None and best_sim > 0.05:
            out.append(f"The closest enrolled person reached {best_sim:.2f}, below the Possible-match threshold {thr['possible']:.2f}. If this person is enrolled, add a look in this appearance and light.")
        else:
            out.append("No enrolled person is anywhere near this face. That is the right answer for someone who was never enrolled.")
    if status == POSSIBLE_MATCH:
        out.append("A possible match is never treated as an identity. More views, another look or a cleaner picture usually turns it into a match.")
    if status == RECOGNIZED and quality is not None and quality.score < 0.5:
        out.append("Recognized, but from a poor picture. Check it on a better frame before trusting the setting.")
    return out


def identify_image(svc: PeopleService, stack: Any, values: dict, img: np.ndarray, top_k: int = TOP_K, day: date | None = None) -> dict:
    """Run the recognition chain over one picture and explain the outcome."""
    matcher, info = build_matcher(svc, stack, values)
    return identify_with(matcher, info, stack, img, top_k=top_k, day=day)


def identify_with(matcher: FaceMatcher, info: dict, stack: Any, img: np.ndarray, top_k: int = TOP_K, day: date | None = None) -> dict:
    """The same test with a matcher that was built once (live sessions)."""
    thr = info["thresholds"]
    h, w = img.shape[:2]
    faces: list[dict] = []
    with stack.lock:
        dets = stack.detector.detect(img)
        for det in dets:
            quality: QualityReport = stack.quality.assess(img, det, w, h)
            big_enough = quality.size_px >= thr["min_face_px"]
            usable = bool(quality.usable and big_enough and quality.score >= thr["min_quality"])
            entry: dict = {
                "box": [round(float(v), 1) for v in det.box],
                "detector_score": round(float(getattr(det, "score", 0.0) or 0.0), 3),
                "quality": quality.to_dict(),
                "usable": usable,
                "status": INSUFFICIENT_QUALITY,
                "best": None,
                "runner_up": None,
                "candidates": [],
            }
            if usable and det.landmarks is not None:
                aligned = stack.aligner.align(img, det.landmarks)
                emb = stack.embedder.embed(aligned)
                if emb is None:
                    entry["usable"] = False
                    entry["quality"]["reasons"] = [*entry["quality"]["reasons"], "The face could not be encoded."]
                else:
                    result = matcher.match(emb, day=day, top_k=top_k)
                    entry["status"] = result.status
                    entry["runner_up"] = round(float(result.second_similarity), 3) if result.second_similarity > -1.0 else None
                    entry["candidates"] = [
                        {
                            "identity_id": c.identity_id,
                            "display_name": c.display_name,
                            "similarity": round(float(c.similarity), 3),
                            "over_match": float(c.similarity) >= thr["match"],
                            "over_possible": float(c.similarity) >= thr["possible"],
                        }
                        for c in result.candidates
                    ]
                    if result.best is not None:
                        entry["best"] = {"identity_id": result.best.identity_id, "display_name": result.best.display_name, "similarity": round(float(result.best.similarity), 3)}
            elif usable:
                entry["usable"] = False
                entry["quality"]["reasons"] = [*entry["quality"]["reasons"], "The detector found no landmarks, so the face could not be aligned."]
            best_sim = entry["candidates"][0]["similarity"] if entry["candidates"] else None
            entry["advice"] = _face_advice(entry["status"], quality, best_sim, thr, int(info.get("identities", 0)))
            faces.append(entry)
    faces.sort(key=lambda f: -(f["quality"]["size_px"] or 0))
    return {"width": w, "height": h, "n_faces": len(faces), "faces": faces, **info}


def _pairwise(vectors: list[np.ndarray]) -> tuple[float | None, float | None]:
    """Mean and worst cosine similarity inside one set of templates."""
    if len(vectors) < 2:
        return None, None
    mat = np.stack(vectors)
    sims = mat @ mat.T
    iu = np.triu_indices(len(vectors), k=1)
    vals = sims[iu]
    return float(vals.mean()), float(vals.min())


def enrollment_report(svc: PeopleService, values: dict) -> dict:
    """How strong each enrolled profile is, and what would make it stronger."""
    from sqlalchemy import select

    from pathscope.recognition.registry.models import RecognitionPerson

    version = svc.model_version
    min_views = int(values.get("recognition.face.enrollment_min_views", 3) or 3)
    min_consistency = float(values.get("recognition.face.enrollment_consistency", 0.35) or 0.0)
    possible = values.get("recognition.face.possible_threshold")
    possible_thr = float(possible) if possible is not None else (float(svc.stack.embedder.default_possible_threshold) if svc.stack else 0.3)

    people: list[dict] = []
    vectors: dict[str, np.ndarray] = {}
    for person in svc.session.scalars(select(RecognitionPerson).order_by(RecognitionPerson.display_name)):
        templates = svc.decrypted_templates(person)
        current = [(t, v) for t, v in templates if not version or t.model_version == version]
        looks = sorted({(t.variant or "") for t, _ in current})
        within, worst = _pairwise([v for _, v in current])
        people.append({
            "id": person.id,
            "display_name": person.display_name,
            "reference_id": person.reference_id,
            "active": person.active,
            "enrollment_status": person.enrollment_status,
            "enrollment_quality": person.enrollment_quality,
            "templates": len(current),
            "templates_other_model": len(templates) - len(current),
            "views": sorted({t.view for t, _ in current}),
            "looks": looks,
            "n_looks": len(looks),
            "self_similarity": round(within, 3) if within is not None else None,
            "weakest_pair": round(worst, 3) if worst is not None else None,
            "model_version": person.model_version,
            "nearest_other": None,
            "advice": [],
            "verdict": "ok",
        })
        if current:
            vectors[person.id] = np.stack([v for _, v in current])

    # Closest other person: the best pair between two registries is what would
    # cause a mix-up, so that is what gets reported.
    for row in people:
        mine = vectors.get(row["id"])
        if mine is None:
            continue
        best_id, best_sim = None, -1.0
        for other in people:
            if other["id"] == row["id"]:
                continue
            theirs = vectors.get(other["id"])
            if theirs is None:
                continue
            sim = float((mine @ theirs.T).max())
            if sim > best_sim:
                best_id, best_sim = other["id"], sim
        if best_id is not None:
            other = next(o for o in people if o["id"] == best_id)
            row["nearest_other"] = {"id": best_id, "display_name": other["display_name"], "similarity": round(best_sim, 3)}

    for row in people:
        advice: list[str] = []
        verdict = "ok"
        if row["templates"] == 0:
            verdict = "blocked"
            advice.append(
                "No usable template for the models in use. Enroll this person again."
                if row["templates_other_model"]
                else "This profile has no face template yet. Run the guided capture."
            )
        else:
            if row["enrollment_status"] != "enrolled":
                verdict = "blocked"
                advice.append("The profile is not finished; it is never matched. Open it and click Finish and check quality.")
            if row["templates_other_model"]:
                advice.append(f"{row['templates_other_model']} template(s) were made with other models and are ignored.")
            if len(row["views"]) < min_views:
                verdict = "weak" if verdict == "ok" else verdict
                advice.append(f"Only {len(row['views'])} of {min_views} views. Capture the missing ones.")
            if row["n_looks"] < 2:
                advice.append("Only one look. Enroll again wearing glasses, a hat or different clothes, or in different light, so everyday appearances are covered.")
            if row["self_similarity"] is not None and row["self_similarity"] < min_consistency:
                verdict = "weak"
                advice.append(f"The person's own pictures agree only at {row['self_similarity']:.2f} (minimum {min_consistency:.2f}). Some picture may show someone else or be too poor.")
            near = row["nearest_other"]
            if near and near["similarity"] >= possible_thr:
                verdict = "risk"
                advice.append(f"{near['display_name']} is close at {near['similarity']:.2f}, above the Possible-match threshold {possible_thr:.2f}. Add views and looks for both, or raise the Recognized threshold.")
            if not advice:
                advice.append("Enrollment looks healthy. Test with the live camera to confirm the site conditions.")
        row["advice"] = advice
        row["verdict"] = verdict

    return {
        "model_version": version,
        "min_views": min_views,
        "min_consistency": min_consistency,
        "possible_threshold": round(possible_thr, 3),
        "people": people,
        "counts": {
            "total": len(people),
            "ok": sum(1 for p in people if p["verdict"] == "ok"),
            "weak": sum(1 for p in people if p["verdict"] == "weak"),
            "risk": sum(1 for p in people if p["verdict"] == "risk"),
            "blocked": sum(1 for p in people if p["verdict"] == "blocked"),
        },
    }




def teach_picture(session, principal, person, img: np.ndarray, *, look: str = LIVE_LOOK, force: bool = False, source: str = "live", client: str | None = None, stack: Any = None) -> dict:
    """Add one confirmed picture to a profile and finalise the enrollment.

    The picture goes through the ordinary enrollment gate (size, sharpness,
    lighting, pose, one face only). It is also compared with that person's own
    templates: below the enrollment consistency the picture is refused, because
    teaching the wrong face into a profile is the one mistake that is hard to
    undo. An operator who is sure can override that, and the override is
    recorded in the audit trail."""
    from pathscope.recognition.common.audit import audit
    from pathscope.recognition.common.config import all_recognition_settings
    from pathscope.recognition.registry.people import EnrollmentError, clean_variant, person_to_dict
    from pathscope.recognition.registry.store import get_store
    from pathscope.recognition.service import enrollment_stack

    values = all_recognition_settings(session)
    stack = stack or enrollment_stack(values)
    svc = PeopleService(session, get_store(), stack, values)
    look = clean_variant(look) or LIVE_LOOK
    try:
        analysis = svc.analyze_image(img, "front", svc.front_baseline(person, look))
    except EnrollmentError as exc:
        raise TeachRefused(str(exc), "quality") from exc
    if not analysis.accepted:
        raise TeachRefused("; ".join(analysis.guidance) or "The picture was not good enough to learn from.", "quality")

    similarity = None
    templates = [v for t, v in svc.decrypted_templates(person) if t.model_version == svc.model_version]
    if templates and analysis.embedding is not None:
        similarity = float(max(float(np.dot(v, analysis.embedding)) for v in templates))
        bar = min(
            float(getattr(stack.embedder, "default_possible_threshold", 0.35)),
            float(values.get("recognition.face.enrollment_consistency", 0.35)),
        )
        if similarity < bar and not force:
            raise TeachRefused(
                f"This face matches {person.display_name} only at {similarity:.2f}, below {bar:.2f}. "
                "Confirm again to add it anyway, or register the person instead.",
                "mismatch",
                round(similarity, 3),
            )
    try:
        image_row, template = svc.store_image(person, img, analysis, bool(values.get("recognition.privacy.store_enrollment_images", True)), look)
    except EnrollmentError as exc:
        raise TeachRefused(str(exc), "quality") from exc
    result = svc.finalize(person)
    audit(
        session, principal, "test_taught", "person", person.id,
        {
            "look": look, "similarity": round(similarity, 3) if similarity is not None else None,
            "forced": bool(force and similarity is not None), "source": source,
            "image_id": image_row.id if image_row else None, "template": template is not None,
            "quality": (analysis.quality or {}).get("score"), "status": result["status"],
        },
        client,
    )
    session.commit()
    # Sessions here keep their objects after a commit, so the new picture and
    # template only show up in the reply after a refresh.
    session.refresh(person)
    return {
        "person": person_to_dict(person, include_images=True),
        "similarity": round(similarity, 3) if similarity is not None else None,
        "quality": analysis.quality,
        "enrollment": result,
        "look": look,
    }


__all__ = ["build_matcher", "enrollment_report", "identify_image", "identify_with", "teach_picture", "LIVE_LOOK", "TeachRefused", "RECOGNIZED", "POSSIBLE_MATCH"]
