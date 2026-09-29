"""Accuracy metrics computed only from manual verdicts and ground-truth counts.

Nothing here is estimated: when no verdicts exist the metric is ``None``.
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from pathscope.db.models import Evaluation, Event, GroundTruthCount

VERDICTS = ["correct", "incorrect", "missed", "wrong_route", "wrong_class", "tracking_error"]


def evaluation_metrics(session: Session, run_id: int) -> dict:
    verdicts = list(session.scalars(select(Evaluation).where(Evaluation.run_id == run_id)))
    events = {e.id: e for e in session.scalars(select(Event).where(Event.run_id == run_id))}
    counts = Counter(v.verdict for v in verdicts)
    reviewed = [v for v in verdicts if v.event_id is not None]
    n_reviewed = len(reviewed)

    route_reviews = [v for v in reviewed if v.event_id in events and events[v.event_id].event_type == "route"]
    route_correct = sum(1 for v in route_reviews if v.verdict == "correct")
    route_accuracy = (100.0 * route_correct / len(route_reviews)) if route_reviews else None

    # Precision: reviewed events judged correct / reviewed events (excluding "missed" which has no event)
    judged = [v for v in reviewed if v.verdict in ("correct", "incorrect", "wrong_route", "wrong_class", "tracking_error")]
    tp = sum(1 for v in judged if v.verdict == "correct")
    fp = len(judged) - tp
    fn = counts.get("missed", 0)
    precision = (100.0 * tp / (tp + fp)) if (tp + fp) else None
    recall = (100.0 * tp / (tp + fn)) if (tp + fn) else None

    # Counting error against manual ground-truth counts per scene object
    gts = list(session.scalars(select(GroundTruthCount).where(GroundTruthCount.run_id == run_id)))
    counting = []
    for gt in gts:
        system = sum(1 for e in events.values() if e.object_id == gt.object_id and e.event_type in ("crossing", "zone_entry"))
        err = system - gt.count
        counting.append(
            {
                "object_id": gt.object_id,
                "label": gt.label,
                "ground_truth": gt.count,
                "system": system,
                "error": err,
                "error_percent": round(100.0 * err / gt.count, 1) if gt.count else None,
            }
        )

    return {
        "reviewed_events": n_reviewed,
        "verdicts": {v: counts.get(v, 0) for v in VERDICTS},
        "route_classification_accuracy_percent": round(route_accuracy, 1) if route_accuracy is not None else None,
        "route_reviews": len(route_reviews),
        "precision_percent": round(precision, 1) if precision is not None else None,
        "recall_percent": round(recall, 1) if recall is not None else None,
        "tracking_errors": counts.get("tracking_error", 0),
        "wrong_class": counts.get("wrong_class", 0),
        "counting": counting,
        "note": "Metrics are computed only from manual verdicts and entered ground-truth counts.",
    }
