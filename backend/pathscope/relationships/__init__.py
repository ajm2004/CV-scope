"""Relationship & Event Correlation Engine.

Connects what CV-Scope observes (tracks, recognized identities, plates,
vehicles, zones, gates, routes, sensors, events) into time-bounded,
confidence-scored relationships, and correlates them into higher-level
events. Layout:

    entities.py      generic entity model and keys (extensible type registry)
    observations.py  the normalized observations every source publishes
    relations.py     relationship-type registry (observable relations only)
    spatial.py       distances with or without calibration, motion
    temporal.py      interval relations (PRECEDED, FOLLOWED_WITHIN, ...)
    confidence.py    evidence components, score and state
    rules.py         structured, versioned formation rules; experiment settings
    correlation.py   multi-step correlation and following through checkpoints
    engine.py        the per-run engine (worker or replay), no database
    replay.py        feeds a stored run through the engine again
    models.py        tables; store.py persistence; graph.py the graph API
    patterns.py      deviations from configured and learned patterns
    summary.py       deterministic summaries (optional model rewrite)
    access.py        roles, identity visibility, audit
    service.py       CV-Scope wiring; api.py the HTTP API

The engine never uses a language model: relationships come from rules,
measurements, recognition results and sensor observations only. See
docs/relationships.md.
"""

from pathscope.relationships.engine import EngineContext, RelationEngine
from pathscope.relationships.rules import (
    CompiledRule,
    RelationExperimentSettings,
    RelationRuleDefinition,
    relation_settings,
)

__all__ = [
    "CompiledRule",
    "EngineContext",
    "RelationEngine",
    "RelationExperimentSettings",
    "RelationRuleDefinition",
    "relation_settings",
]
