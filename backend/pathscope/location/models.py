"""Tables of the Location Engine and of cross-camera correlation.

* ``location_nodes`` - the place hierarchy (organization, site, building,
  floor, area, room, road network, road, junction, gate, zone, parking...),
  cameras and external sensors included. ``parent_id`` is INSIDE. A node with
  a ``layout`` (floor plan, schematic or map) gives the coordinate frame of
  the nodes placed below it; coordinates are logical (metres or plain units),
  GPS is optional.
* ``location_links`` - movement and visibility between nodes: CONNECTED_TO,
  ADJACENT_TO, LEADS_TO (traversable, optionally one-way, with an expected
  travel time), VISIBLE_FROM (a place a camera covers), ABOVE / BELOW.
* ``location_zone_links`` - which location node a camera's scene zone, line
  or route is (Location Resolution: ``zone:c3.z_gate`` -> "Gate North").
* ``crosscam_transitions`` - one entity's move from one camera to another,
  with every piece of evidence it rests on. The relationship graph gets
  MOVED_FROM / MOVED_TO / MOVED_THROUGH / SEEN_AT / ENTERED_SITE_AT rows that
  point back here; this table stays the record of why.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from pathscope.db.base import Base, UtcDateTime, utcnow


class LocationNode(Base):
    __tablename__ = "location_nodes"
    __table_args__ = (
        Index("ix_location_nodes_parent", "parent_id"),
        UniqueConstraint("camera_id", name="uq_location_camera"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("location_nodes.id", ondelete="CASCADE"), nullable=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    # a camera or an external sensor placed in the hierarchy
    camera_id: Mapped[int | None] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"), nullable=True)
    sensor_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # position in the layout frame (nearest ancestor with a layout), in its units
    x: Mapped[float | None] = mapped_column(Float, nullable=True)
    y: Mapped[float | None] = mapped_column(Float, nullable=True)
    w: Mapped[float | None] = mapped_column(Float, nullable=True)
    h: Mapped[float | None] = mapped_column(Float, nullable=True)
    shape: Mapped[list[list[float]]] = mapped_column(JSON, default=list)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # cameras: which way they look (degrees clockwise from the layout's up), field of view, reach
    orientation_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    fov_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    view_range: Mapped[float | None] = mapped_column(Float, nullable=True)
    # {mode: plan | schematic | map, width, height, unit: m | units, image, bounds}
    layout: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    is_entry: Mapped[bool] = mapped_column(Boolean, default=False)
    restricted: Mapped[bool] = mapped_column(Boolean, default=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


class LocationLink(Base):
    __tablename__ = "location_links"
    __table_args__ = (
        Index("ix_location_links_source", "source_id"),
        Index("ix_location_links_target", "target_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("location_nodes.id", ondelete="CASCADE"))
    target_id: Mapped[int] = mapped_column(ForeignKey("location_nodes.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20), default="CONNECTED_TO")
    one_way: Mapped[bool] = mapped_column(Boolean, default=False)
    travel_min_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    travel_max_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    # camera to camera: the place in between, and a place both cameras see
    via_id: Mapped[int | None] = mapped_column(ForeignKey("location_nodes.id", ondelete="SET NULL"), nullable=True)
    shared_id: Mapped[int | None] = mapped_column(ForeignKey("location_nodes.id", ondelete="SET NULL"), nullable=True)
    overlap: Mapped[bool] = mapped_column(Boolean, default=False)
    distance: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class LocationZoneLink(Base):
    __tablename__ = "location_zone_links"
    __table_args__ = (UniqueConstraint("camera_id", "object_id", name="uq_location_zone"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"))
    object_id: Mapped[str] = mapped_column(String(100))
    object_kind: Mapped[str] = mapped_column(String(20), default="zone")  # zone | line | route
    node_id: Mapped[int] = mapped_column(ForeignKey("location_nodes.id", ondelete="CASCADE"))


class CrossCameraTransition(Base):
    __tablename__ = "crosscam_transitions"
    __table_args__ = (
        Index("ix_crosscam_subject", "subject_id", "arrived_at"),
        Index("ix_crosscam_arrived", "arrived_at"),
        Index("ix_crosscam_to_run", "to_run_id"),
        Index("ix_crosscam_from_run", "from_run_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    uid: Mapped[str] = mapped_column(String(32), unique=True)
    # the identity (recognized person, plate, registered vehicle) or, for an
    # anonymous transition, the track it continues
    subject_id: Mapped[int] = mapped_column(ForeignKey("relation_entities.id", ondelete="CASCADE"))
    basis: Mapped[str] = mapped_column(String(20))  # face | plate | registered | anonymous
    # kept (as None) when a track is deleted, so later runs can be re-correlated without it
    from_track_id: Mapped[int | None] = mapped_column(ForeignKey("relation_entities.id", ondelete="SET NULL"), nullable=True)
    to_track_id: Mapped[int | None] = mapped_column(ForeignKey("relation_entities.id", ondelete="SET NULL"), nullable=True)
    from_camera_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    to_camera_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    from_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    to_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    from_node_id: Mapped[int | None] = mapped_column(ForeignKey("location_nodes.id", ondelete="SET NULL"), nullable=True)
    to_node_id: Mapped[int | None] = mapped_column(ForeignKey("location_nodes.id", ondelete="SET NULL"), nullable=True)
    from_place: Mapped[str | None] = mapped_column(String(200), nullable=True)  # entity key of the scene zone
    to_place: Mapped[str | None] = mapped_column(String(200), nullable=True)
    left_at: Mapped[datetime] = mapped_column(UtcDateTime)
    arrived_at: Mapped[datetime] = mapped_column(UtcDateTime)
    left_media_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    arrived_media_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    gap_s: Mapped[float] = mapped_column(Float, default=0.0)
    expected_min_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_max_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_source: Mapped[str] = mapped_column(String(20), default="unknown")  # link | path | distance | unknown
    topology: Mapped[str] = mapped_column(String(20), default="unconnected")  # direct | path | overlap | same_camera | unconnected
    path: Mapped[list[int]] = mapped_column(JSON, default=list)
    hops: Mapped[int | None] = mapped_column(Integer, nullable=True)
    identity_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    components: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    state: Mapped[str] = mapped_column(String(20), default="possible")
    sensor_evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | withdrawn
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)
