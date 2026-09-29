"""Boxes drawn onto run previews for MJPEG viewers (Live page, camera views).

The Scene Builder draws its own overlays over the raw preview, so only the
MJPEG streams use these annotated frames.
"""

from __future__ import annotations

import cv2
import numpy as np

# BGR colours that stay legible on video; picked by track id.
_COLORS = [(230, 196, 41), (115, 210, 82), (50, 182, 242), (245, 125, 231), (60, 154, 255), (255, 255, 255)]


def identity_label(rec: dict | None) -> str:
    """The recognized name, plate or vehicle for one track, or "".

    The worker sends ``identity`` for an enrolled person and ``plate`` with an
    optional ``vehicle`` label for a vehicle (the entity form's
    ``display_name`` / ``vehicle_label`` are accepted too). ``=`` is a
    recognized identity, ``?`` a possible match, which must never be read as
    one. Only callers that checked a recognition token pass these on."""
    if not rec:
        return ""
    name = rec.get("identity") or rec.get("display_name") or rec.get("plate") or rec.get("vehicle") or rec.get("vehicle_label")
    if not name:
        return ""
    return f" {'?' if rec.get('status') == 'possible_match' else '='} {name}"


def annotate_jpeg(jpeg: bytes, tracks: list[dict], preview_w: int, source_w: int, quality: int = 80, identities: bool = False) -> bytes:
    """Draw a box and ``#id class`` label for every tracked object.

    With ``identities`` the label also carries the recognized person or plate;
    that frame is only served to a viewer with a recognition token."""
    img = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None or not tracks:
        return jpeg
    scale = preview_w / source_w if source_w else 1.0
    thick = max(1, round(img.shape[1] / 640))
    for t in tracks:
        if t.get("state") != "tracked":
            continue
        x1, y1, x2, y2 = (int(round(v * scale)) for v in t.get("box", (0, 0, 0, 0)))
        color = _COLORS[int(t.get("id", 0)) % len(_COLORS)]
        cv2.rectangle(img, (x1, y1), (x2, y2), color, thick, cv2.LINE_AA)
        label = f"#{t.get('id')} {t.get('cls', '')}"
        if identities:
            label += identity_label(t.get("recognition"))
        (tw, th), base = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        ty = max(th + 4, y1)
        cv2.rectangle(img, (x1, ty - th - 4), (x1 + tw + 6, ty + base - 2), (22, 20, 20), -1)
        cv2.putText(img, label, (x1 + 3, ty - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes() if ok else jpeg
