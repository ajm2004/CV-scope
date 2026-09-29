"""Export events as CSV, JSON or Parquet."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime

from pathscope.db.models import Event

EVENT_COLUMNS = [
    "id", "run_id", "experiment_id", "camera_id", "track_id", "object_class", "event_type", "rule_id",
    "rule_name", "route", "object_id", "object_name", "direction", "frame_index", "media_time_s",
    "wall_time", "entered_at_s", "completed_at_s", "duration_s", "avg_speed", "speed_unit", "confidence",
    "context",
]


def event_row(e: Event) -> dict:
    row = {c: getattr(e, c) for c in EVENT_COLUMNS}
    if isinstance(row["wall_time"], datetime):
        row["wall_time"] = row["wall_time"].isoformat()
    return row


def export_events(events: list[Event], fmt: str = "csv") -> tuple[bytes, str, str]:
    """Return (payload, media type, file extension)."""
    rows = [event_row(e) for e in events]
    if fmt == "json":
        return json.dumps(rows, default=str, indent=2).encode("utf-8"), "application/json", "json"
    if fmt == "parquet":
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise RuntimeError("Parquet export requires the 'pyarrow' package (pip install pyarrow).") from exc
        flat = []
        for r in rows:
            r = dict(r)
            r["context"] = json.dumps(r["context"] or {})
            flat.append(r)
        table = pa.Table.from_pylist(flat)
        sink = io.BytesIO()
        pq.write_table(table, sink)
        return sink.getvalue(), "application/vnd.apache.parquet", "parquet"
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=EVENT_COLUMNS)
    writer.writeheader()
    for r in rows:
        r = dict(r)
        r["context"] = json.dumps(r["context"] or {})
        writer.writerow(r)
    return buf.getvalue().encode("utf-8"), "text/csv", "csv"
