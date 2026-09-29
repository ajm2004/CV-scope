"""Aggregate API router."""

from __future__ import annotations

from fastapi import APIRouter

from pathscope.anomaly.api import router as anomaly_router
from pathscope.api.routes import (
    analytics,
    cameras,
    evaluation,
    events,
    experiments,
    hardware,
    models,
    preview,
    projects,
    recordings,
    runs,
    scenes,
    settings,
    system,
    videos,
)
from pathscope.location.api import router as locations_router
from pathscope.recognition.api import router as recognition_router
from pathscope.relationships.api import router as relationships_router

api_router = APIRouter(prefix="/api")
for r in (
    system.router,
    hardware.router,
    models.router,
    settings.router,
    projects.router,
    cameras.router,
    preview.router,
    videos.router,
    scenes.router,
    experiments.router,
    runs.router,
    recordings.router,
    events.router,
    analytics.router,
    evaluation.router,
    anomaly_router,  # Anomaly Assistant: anomalies, evidence, vision-model settings
    relationships_router,  # Relationship & Event Correlation Engine: rules, graph, timeline, search
    locations_router,  # Location Engine and cross-camera correlation: topology, site view, journeys
    recognition_router,  # licensed modules: locked without a licence, authenticated with tokens
):
    api_router.include_router(r)
