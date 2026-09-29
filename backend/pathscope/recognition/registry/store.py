"""Encrypted storage of biometric templates, enrollment media and event crops.

* templates: float32 vectors sealed with the ``templates`` key, stored as
  bytes in ``recognition_face_templates`` (the key lives in a file, never in
  the database);
* enrollment images and recognition crops: JPEG bytes sealed with the
  ``media`` key, stored as files under ``<data>/recognition``.

Deleting a profile removes its templates immediately and its media either
immediately or after a configured grace period (quarantine folder).
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import numpy as np

from pathscope.recognition.common.crypto import KeyStore, open_sealed, seal


class RecognitionStore:
    def __init__(self, data_dir: Path, key_dir: Path | None = None) -> None:
        self.data_dir = Path(data_dir)
        self.root = self.data_dir / "recognition"
        self.keys = KeyStore(Path(key_dir) if key_dir else self.root / "keys")

    # ------------------------------------------------------------- templates
    def seal_embedding(self, embedding: np.ndarray, aad: str) -> bytes:
        vec = np.asarray(embedding, dtype=np.float32).reshape(-1)
        return seal(self.keys.key("templates"), vec.tobytes(), aad.encode("utf-8"))

    def open_embedding(self, sealed: bytes, aad: str, dim: int) -> np.ndarray:
        raw = open_sealed(self.keys.key("templates"), sealed, aad.encode("utf-8"))
        vec = np.frombuffer(raw, dtype=np.float32)
        if dim and vec.shape[0] != dim:
            raise ValueError("template dimension mismatch")
        return vec.copy()

    # ------------------------------------------------------------- media
    def media_path(self, person_id: str, image_id: str) -> Path:
        return self.root / "enrollment" / person_id / f"{image_id}.bin"

    def write_media(self, person_id: str, image_id: str, data: bytes) -> Path:
        p = self.media_path(person_id, image_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".bin.tmp")
        tmp.write_bytes(seal(self.keys.key("media"), data, f"media:{person_id}:{image_id}".encode()))
        os.replace(tmp, p)
        return p

    def read_media(self, person_id: str, image_id: str) -> bytes:
        return open_sealed(self.keys.key("media"), self.media_path(person_id, image_id).read_bytes(), f"media:{person_id}:{image_id}".encode())

    def delete_media(self, person_id: str, image_id: str) -> None:
        p = self.media_path(person_id, image_id)
        if p.exists():
            p.unlink()

    def delete_person_media(self, person_id: str, grace_days: int = 0) -> str:
        """Remove a profile's media folder now, or move it to quarantine for ``grace_days``."""
        folder = self.root / "enrollment" / person_id
        if not folder.exists():
            return "none"
        if grace_days > 0:
            q = self.root / "quarantine" / f"{int(time.time())}_{person_id}"
            q.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(folder), str(q))
            return "quarantined"
        shutil.rmtree(folder, ignore_errors=True)
        return "deleted"

    def purge_quarantine(self, older_than_days: int) -> int:
        q = self.root / "quarantine"
        if not q.exists():
            return 0
        cutoff = time.time() - older_than_days * 86400
        n = 0
        for entry in q.iterdir():
            try:
                stamp = int(entry.name.split("_", 1)[0])
            except ValueError:
                stamp = int(entry.stat().st_mtime)
            if stamp <= cutoff:
                shutil.rmtree(entry, ignore_errors=True)
                n += 1
        return n

    # ------------------------------------------------------------- crops
    def crop_path(self, event_id: int) -> Path:
        return self.root / "crops" / f"{event_id}.bin"

    def write_crop(self, event_id: int, jpeg: bytes) -> Path:
        p = self.crop_path(event_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(seal(self.keys.key("media"), jpeg, f"crop:{event_id}".encode()))
        return p

    def read_crop(self, event_id: int) -> bytes:
        return open_sealed(self.keys.key("media"), self.crop_path(event_id).read_bytes(), f"crop:{event_id}".encode())

    def delete_crop(self, event_id: int) -> None:
        p = self.crop_path(event_id)
        if p.exists():
            p.unlink()


_store: RecognitionStore | None = None


def get_store() -> RecognitionStore:
    global _store
    if _store is None:
        from pathscope.config import get_settings

        s = get_settings()
        _store = RecognitionStore(s.resolved_data_dir, s.recognition_key_dir)
    return _store


def reset_store_for_tests(data_dir: Path) -> RecognitionStore:
    global _store
    _store = RecognitionStore(data_dir)
    return _store
