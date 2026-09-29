"""Anomaly Assistant: meaningful change from an expected, static scene.

A reusable module. The deterministic part needs only numpy and OpenCV::

    from pathscope.anomaly import AnomalyAssistant, AnomalySettings, AnomalyZoneSettings, EvidenceWriter

    settings = AnomalySettings(enabled=True, zones=[
        AnomalyZoneSettings(id="barn", name="North barn", expected_state="The stall is empty.", persistence_s=5),
    ])
    assistant = AnomalyAssistant(settings, (width, height), zones={"barn": [(0.1, 0.5), (0.6, 0.5), (0.6, 0.95), (0.1, 0.95)]})
    evidence = EvidenceWriter(Path("anomalies"))
    for t, frame in camera:                       # BGR frames with their time in seconds
        for update in assistant.observe(frame, t, objects=detections):
            files = evidence.write(update)          # before / event / after pictures
            alert(update.to_dict(), files)          # your rules, alerts, storage

The optional vision-language interpretation lives in ``pathscope.anomaly.llm``
(``interpret(settings, key, record, pictures)``); CV-Scope's own wiring
(database, run workers, API, alert publication) is in ``service`` and ``api``.
See docs/anomaly.md.
"""

from pathscope.anomaly.config import (
    FRAME_ZONE_ID,
    AnomalySettings,
    AnomalyZoneSettings,
    anomaly_settings,
)
from pathscope.anomaly.detector import AnomalyAssistant, AnomalyUpdate, ObservedObject
from pathscope.anomaly.evidence import EvidenceWriter

__all__ = [
    "FRAME_ZONE_ID",
    "AnomalyAssistant",
    "AnomalySettings",
    "AnomalyUpdate",
    "AnomalyZoneSettings",
    "EvidenceWriter",
    "ObservedObject",
    "anomaly_settings",
]
