"""People registry and the guided enrollment service.

    Person -> Create profile -> Capture / upload enrollment images
    -> Validate image quality -> Generate face embeddings -> Store securely

Enrollment collects several views (front, left, right, above / below,
lighting variation). A rear view is kept only as an appearance reference and
never produces a template. Poor-quality images are refused with guidance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import cv2
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from pathscope.recognition.common.types import BIOMETRIC_VIEWS, ENROLLMENT_VIEWS, QualityReport
from pathscope.recognition.face.enrollment import PoseBaseline, guidance_for, view_pose_ok
from pathscope.recognition.face.stack import FaceStack
from pathscope.recognition.registry.models import (
    RecognitionEnrollmentImage,
    RecognitionFaceTemplate,
    RecognitionPerson,
)
from pathscope.recognition.registry.store import RecognitionStore

MAX_IMAGE_SIDE = 1600


MAX_VARIANT_CHARS = 40


def clean_variant(value: str | None) -> str:
    """Normalise a look label. Empty means the first enrollment."""
    text = " ".join(str(value or "").split())
    text = "".join(ch for ch in text if ch.isprintable())
    if len(text) > MAX_VARIANT_CHARS:
        text = text[:MAX_VARIANT_CHARS].rstrip()
    return text


class EnrollmentError(ValueError):
    pass


@dataclass
class ImageAnalysis:
    view: str
    face_found: bool
    accepted: bool
    guidance: list[str]
    box: list[float] | None = None
    quality: dict | None = None
    width: int = 0
    height: int = 0
    embedding: np.ndarray | None = field(default=None, repr=False)
    model_version: str = ""

    def to_dict(self) -> dict:
        return {"view": self.view, "face_found": self.face_found, "accepted": self.accepted, "guidance": self.guidance, "box": self.box, "quality": self.quality, "width": self.width, "height": self.height, "model_version": self.model_version}


def decode_image(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise EnrollmentError("The file is not a readable image (use JPEG or PNG).")
    h, w = img.shape[:2]
    if max(h, w) > MAX_IMAGE_SIDE:
        s = MAX_IMAGE_SIDE / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    return img


class PeopleService:
    def __init__(self, session: Session, store: RecognitionStore, stack: FaceStack | None, settings: dict) -> None:
        self.session = session
        self.store = store
        self.stack = stack
        self.settings = settings

    # ------------------------------------------------------------- settings helpers
    def _setting(self, key: str, default):
        return self.settings.get(f"recognition.face.{key}", default)

    @property
    def min_enrollment_face_px(self) -> float:
        return 2.0 * float(self._setting("min_face_px", 40))

    # ------------------------------------------------------------- profiles
    def get(self, person_id: str) -> RecognitionPerson | None:
        return self.session.get(RecognitionPerson, person_id)

    def create(self, display_name: str, reference_id: str | None = None, notes: str = "", valid_from: date | None = None, valid_until: date | None = None, created_by: str = "") -> RecognitionPerson:
        if not display_name.strip():
            raise EnrollmentError("A display name is required.")
        p = RecognitionPerson(display_name=display_name.strip(), reference_id=(reference_id or None), notes=notes or "", valid_from=valid_from, valid_until=valid_until, created_by=created_by)
        self.session.add(p)
        self.session.flush()
        return p

    def delete(self, person: RecognitionPerson, media_grace_days: int = 0) -> dict:
        """Templates go immediately (cascade); media now or after the grace period."""
        n_templates = len(person.templates)
        n_images = len(person.images)
        media = self.store.delete_person_media(person.id, media_grace_days)
        self.session.delete(person)
        self.session.flush()
        return {"templates_deleted": n_templates, "images": n_images, "media": media}

    def reenroll(self, person: RecognitionPerson) -> dict:
        n = len(person.templates)
        for im in list(person.images):
            self.store.delete_media(person.id, im.id)
        # removing from the collections deletes the rows (delete-orphan cascade)
        person.templates.clear()
        person.images.clear()
        person.enrollment_status = "draft"
        person.enrollment_quality = None
        person.enrollment_summary = {}
        person.enrolled_at = None
        self.session.flush()
        return {"templates_deleted": n}

    # ------------------------------------------------------------- images
    @property
    def model_version(self) -> str:
        return f"{self.stack.detector.model_version}+{self.stack.embedder.model_version}" if self.stack else ""

    def front_baseline(self, person: RecognitionPerson, variant: str | None = None) -> PoseBaseline | None:
        """The person's own front view as the zero point for relative pose.

        Only a front view measured with the model stack in use counts: the
        yaw and pitch a detector reports are not comparable between models."""
        version = self.model_version
        images = sorted(person.images, key=lambda i: i.created_at.timestamp() if i.created_at else 0.0, reverse=True)
        if variant is not None:
            # This look's own front view first, then any other front view.
            want = clean_variant(variant)
            images = [im for im in images if im.variant == want] + [im for im in images if im.variant != want]
        for im in images:
            if im.view != "front":
                continue
            detail = im.quality_detail or {}
            if detail.get("yaw") is None:
                continue
            template = next((t for t in person.templates if t.image_id == im.id), None)
            if version and template is not None and template.model_version != version:
                continue
            return PoseBaseline.from_quality(detail)
        return None

    def analyze(self, image_bytes: bytes, view: str, baseline: PoseBaseline | None = None) -> ImageAnalysis:
        self._check_view(view)
        return self.analyze_image(decode_image(image_bytes), view, baseline)

    def analyze_image(self, img: np.ndarray, view: str, baseline: PoseBaseline | None = None) -> ImageAnalysis:
        """Judge one decoded picture for one view. ``baseline`` makes the pose
        relative to the person's front view (see the guidance module)."""
        self._check_view(view)
        h, w = img.shape[:2]
        if view == "rear":
            return ImageAnalysis(view, False, True, [], None, None, w, h)
        if self.stack is None:
            raise EnrollmentError("The face model stack is not available (install the face models on the Models page).")
        min_q = float(self._setting("enrollment_min_quality", 0.6))
        with self.stack.lock:
            dets = self.stack.detector.detect(img)
            if not dets:
                return ImageAnalysis(view, False, False, guidance_for(None, view, self.min_enrollment_face_px), None, None, w, h)
            det = dets[0]
            quality: QualityReport = self.stack.quality.assess(img, det, w, h)
            hints = guidance_for(quality, view, self.min_enrollment_face_px, baseline)
            if len(dets) > 1 and dets[1].height > 0.5 * det.height:
                hints.append("More than one face is visible; only the enrolled person should be in the picture.")
            pose_ok, _ = view_pose_ok(view, quality.yaw, quality.pitch, baseline)
            accepted = quality.usable and quality.size_px >= self.min_enrollment_face_px and quality.score >= min_q and pose_ok and not hints
            analysis = ImageAnalysis(view, True, accepted, hints, [round(float(v), 1) for v in det.box], quality.to_dict(), w, h, model_version=self.model_version)
            if accepted and det.landmarks is not None:
                aligned = self.stack.aligner.align(img, det.landmarks)
                emb = self.stack.embedder.embed(aligned)
                if emb is None:
                    analysis.accepted = False
                    analysis.guidance.append("The face could not be encoded; try another picture.")
                else:
                    analysis.embedding = emb
        if not analysis.accepted and not analysis.guidance:
            analysis.guidance.append(f"Image quality {quality.score:.2f} is below the enrollment minimum {min_q:.2f}.")
        return analysis

    def store_image(self, person: RecognitionPerson, img: np.ndarray, analysis: ImageAnalysis, keep_image: bool = True, variant: str = "") -> tuple[RecognitionEnrollmentImage | None, RecognitionFaceTemplate | None]:
        """Write an accepted picture: encrypted media and a sealed template."""
        if not analysis.accepted:
            raise EnrollmentError("; ".join(analysis.guidance) or "The image was not accepted.")
        biometric = analysis.view in BIOMETRIC_VIEWS
        image_row: RecognitionEnrollmentImage | None = None
        if keep_image or not biometric:
            image_row = RecognitionEnrollmentImage(person_id=person.id, view=analysis.view, variant=clean_variant(variant), biometric=biometric, path="", width=analysis.width, height=analysis.height, quality=(analysis.quality or {}).get("score"), quality_detail=analysis.quality or {})
            self.session.add(image_row)
            self.session.flush()
            # re-encode as JPEG so no original metadata is kept
            ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
            if not ok:
                raise EnrollmentError("The picture could not be encoded.")
            image_row.path = str(self.store.write_media(person.id, image_row.id, enc.tobytes()))
        template: RecognitionFaceTemplate | None = None
        if biometric and analysis.embedding is not None:
            template = RecognitionFaceTemplate(person_id=person.id, image_id=image_row.id if image_row else None, view=analysis.view, variant=clean_variant(variant), quality=float((analysis.quality or {}).get("score") or 0.0), dim=int(analysis.embedding.shape[0]), model_version=analysis.model_version, sealed=b"")
            self.session.add(template)
            self.session.flush()
            template.sealed = self.store.seal_embedding(analysis.embedding, f"template:{person.id}:{template.id}")
        person.updated_at = datetime.now(UTC)
        self.session.flush()
        return image_row, template

    def add_image(self, person: RecognitionPerson, image_bytes: bytes, view: str, keep_image: bool = True, baseline: PoseBaseline | None = None, variant: str = "") -> tuple[RecognitionEnrollmentImage | None, RecognitionFaceTemplate | None, ImageAnalysis]:
        img = decode_image(image_bytes)
        analysis = self.analyze_image(img, view, baseline)
        if not analysis.accepted:
            raise EnrollmentError("; ".join(analysis.guidance) or "The image was not accepted.")
        image_row, template = self.store_image(person, img, analysis, keep_image, variant)
        return image_row, template, analysis

    @staticmethod
    def _check_view(view: str) -> None:
        if view not in ENROLLMENT_VIEWS:
            raise EnrollmentError(f"Unknown view '{view}'. Use one of: {', '.join(ENROLLMENT_VIEWS)}.")

    def delete_image(self, person: RecognitionPerson, image_id: str) -> bool:
        row = next((im for im in person.images if im.id == image_id), None)
        if row is None:
            return False
        for t in [t for t in person.templates if t.image_id == image_id]:
            person.templates.remove(t)
        self.store.delete_media(person.id, image_id)
        person.images.remove(row)
        self.session.flush()
        return True

    def delete_variant(self, person: RecognitionPerson, variant: str) -> dict:
        """Remove one look with its pictures and templates. The first
        enrollment ("") can only be removed by starting over."""
        want = clean_variant(variant)
        if not want:
            raise EnrollmentError("Use 'start over' to remove the first enrollment.")
        images = [im for im in person.images if im.variant == want]
        templates = [t for t in person.templates if t.variant == want]
        if not images and not templates:
            raise EnrollmentError(f"This person has no look called '{want}'.")
        for t in templates:
            person.templates.remove(t)
        for im in images:
            self.store.delete_media(person.id, im.id)
            person.images.remove(im)
        self.session.flush()
        return {"variant": want, "images_deleted": len(images), "templates_deleted": len(templates)}

    def read_image(self, person: RecognitionPerson, image_id: str) -> bytes | None:
        row = next((im for im in person.images if im.id == image_id), None)
        if row is None:
            return None
        return self.store.read_media(person.id, image_id)

    # ------------------------------------------------------------- templates
    def decrypted_templates(self, person: RecognitionPerson) -> list[tuple[RecognitionFaceTemplate, np.ndarray]]:
        out = []
        for t in person.templates:
            try:
                out.append((t, self.store.open_embedding(t.sealed, f"template:{person.id}:{t.id}", t.dim)))
            except Exception:  # noqa: BLE001 - a corrupt template is skipped, never guessed
                continue
        return out

    def finalize(self, person: RecognitionPerson) -> dict:
        """Compute enrollment quality; mark the profile enrolled or insufficient.

        Pictures are grouped by look: a person enrolled again in glasses or in
        work clothes has several looks. Consistency is judged inside a look,
        because two looks of one face score lower against each other than two
        pictures of the same look; every later look must still be linked to the
        first enrollment by at least one good pair, which is what catches a
        different person."""
        templates = self.decrypted_templates(person)
        views = sorted({t.view for t, _ in templates})
        min_views = int(self._setting("enrollment_min_views", 3))
        min_consistency = float(self._setting("enrollment_consistency", 0.35))
        min_q = float(self._setting("enrollment_min_quality", 0.6))
        problems: list[str] = []
        if "front" not in views:
            problems.append("A front view is required.")
        if len(views) < min_views:
            problems.append(f"{min_views} different views are required (have {len(views)}: {', '.join(views) or 'none'}).")
        qualities = [t.quality for t, _ in templates]
        mean_quality = float(np.mean(qualities)) if qualities else 0.0

        by_look: dict[str, list] = {}
        for row, vec in templates:
            by_look.setdefault(row.variant or "", []).append((row, vec))
        base_name = "" if "" in by_look else (max(by_look, key=lambda k: len(by_look[k])) if by_look else "")

        def _within(items):
            if len(items) < 2:
                return None
            mat = np.stack([v for _, v in items])
            sims = mat @ mat.T
            iu = np.triu_indices(len(items), k=1)
            return float(sims[iu].mean())

        looks: list[dict] = []
        consistencies: list[float] = []
        for name in sorted(by_look, key=lambda k: (k != base_name, k)):
            items = by_look[name]
            within = _within(items)
            link = None
            if name != base_name and by_look.get(base_name):
                a = np.stack([v for _, v in items])
                b = np.stack([v for _, v in by_look[base_name]])
                link = float((a @ b.T).max())
                if link < min_consistency:
                    problems.append(f"The look {name!r} does not match the first enrollment (best pair {link:.2f}); it may show someone else.")
            if within is not None:
                consistencies.append(within)
                if within < min_consistency:
                    if name == base_name and len(by_look) == 1:
                        problems.append("The enrollment images are not consistent with each other; they may show different people or be of poor quality.")
                    else:
                        problems.append(f"The pictures of the look {name or 'first enrollment'!r} are not consistent with each other.")
            looks.append({
                "name": name,
                "templates": len(items),
                "views": sorted({r.view for r, _ in items}),
                "mean_quality": round(float(np.mean([r.quality for r, _ in items])), 3),
                "consistency": round(within, 3) if within is not None else None,
                "link_to_first": round(link, 3) if link is not None else None,
                "is_first": name == base_name,
            })
        consistency = float(np.mean(consistencies)) if consistencies else None

        coverage = min(1.0, len(views) / max(min_views, 1)) if "front" in views else 0.0
        quality = 0.5 * mean_quality + 0.3 * coverage + 0.2 * (consistency if consistency is not None else (1.0 if len(templates) == 1 else 0.0))
        quality = float(max(0.0, min(1.0, quality)))
        if templates and mean_quality < min_q:
            problems.append(f"Mean image quality {mean_quality:.2f} is below {min_q:.2f}.")
        status = "enrolled" if templates and not problems else ("insufficient" if templates else "draft")
        summary = {
            "views": views, "templates": len(templates), "mean_quality": round(mean_quality, 3), "consistency": round(consistency, 3) if consistency is not None else None,
            "coverage": round(coverage, 3), "problems": problems, "model_version": templates[0][0].model_version if templates else "",
            "looks": looks, "n_looks": len(looks),
            "finalized_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        person.enrollment_status = status
        person.enrollment_quality = quality if templates else None
        person.enrollment_summary = summary
        person.model_version = summary["model_version"]
        person.enrolled_at = datetime.now(UTC) if status == "enrolled" else None
        self.session.flush()
        return {"status": status, "quality": person.enrollment_quality, **summary}

    def identities_for_worker(self, model_version: str | None = None, today: date | None = None) -> list[dict]:
        """Enrolled, active, currently valid identities with their decrypted templates (memory only)."""
        today = today or date.today()
        out: list[dict] = []
        for person in self.session.scalars(select(RecognitionPerson).where(RecognitionPerson.active.is_(True), RecognitionPerson.enrollment_status == "enrolled")):
            if person.valid_from and today < person.valid_from:
                continue
            if person.valid_until and today > person.valid_until:
                continue
            templates = [v for t, v in self.decrypted_templates(person) if not model_version or t.model_version == model_version]
            if not templates:
                continue
            out.append({"id": person.id, "name": person.display_name, "templates": [v.tolist() for v in templates], "valid_from": person.valid_from.isoformat() if person.valid_from else None, "valid_until": person.valid_until.isoformat() if person.valid_until else None, "active": True, "model_version": person.model_version})
        return out


def _looks(p: RecognitionPerson) -> list[dict]:
    """The looks this person was enrolled in, first enrollment first."""
    names = sorted({im.variant or "" for im in p.images} | {t.variant or "" for t in p.templates}, key=lambda n: (n != "", n))
    summary = {str(li.get("name", "")): li for li in (p.enrollment_summary or {}).get("looks", []) if isinstance(li, dict)}
    out = []
    for name in names:
        images = [im for im in p.images if (im.variant or "") == name]
        templates = [t for t in p.templates if (t.variant or "") == name]
        li = summary.get(name, {})
        out.append({
            "name": name,
            "images": len(images),
            "templates": len(templates),
            "views": sorted({t.view for t in templates} | {im.view for im in images}),
            "consistency": li.get("consistency"),
            "link_to_first": li.get("link_to_first"),
            "created_at": min((im.created_at.isoformat() for im in images if im.created_at), default=None),
        })
    return out


def person_to_dict(p: RecognitionPerson, include_images: bool = False) -> dict:
    d = {
        "id": p.id, "display_name": p.display_name, "reference_id": p.reference_id, "notes": p.notes, "active": p.active,
        "valid_from": p.valid_from.isoformat() if p.valid_from else None, "valid_until": p.valid_until.isoformat() if p.valid_until else None,
        "enrollment_status": p.enrollment_status, "enrollment_quality": p.enrollment_quality, "enrollment_summary": p.enrollment_summary or {},
        "model_version": p.model_version, "enrolled_at": p.enrolled_at.isoformat() if p.enrolled_at else None,
        "n_templates": len(p.templates), "n_images": len(p.images), "views": sorted({t.view for t in p.templates}),
        "looks": _looks(p),
        "created_by": p.created_by, "created_at": p.created_at.isoformat() if p.created_at else None, "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }
    if include_images:
        d["images"] = [
            {"id": im.id, "view": im.view, "variant": im.variant, "biometric": im.biometric, "width": im.width, "height": im.height, "quality": im.quality, "quality_detail": im.quality_detail or {}, "created_at": im.created_at.isoformat() if im.created_at else None}
            for im in p.images
        ]
    return d
