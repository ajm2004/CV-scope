"""Licensed recognition modules: enrolled-face recognition and vehicle plate
recognition.

These modules are proprietary extensions that are NOT part of the open-source
core. Their code lives here so that the core can be built and tested with
them, but nothing in this package runs unless a valid licence is installed:

* ``licensing``  offline licence files signed by a trusted issuer key
                 (Ed25519); status Not licensed / Licensed / Expired / Disabled
* ``common``     shared types, quality scoring, encryption of templates and
                 enrollment media, access control (roles + tokens), audit
* ``face``       detector -> quality -> alignment -> embedding -> matcher,
                 plus the guided enrollment service
* ``plate``      detector -> preprocessing -> OCR -> parser (plate formats)
                 -> temporal consensus
* ``registry``   people and vehicle registries (encrypted biometric templates)
* ``events``     recognition events, retention and restricted export
* ``api``        the authenticated ``/api/recognition`` router
* ``runtime``    the per-run runtime the vision pipeline drives, and the
                 ``EntityResolver`` the rule engine consumes

The open-source core talks to this package only through a few stable entry
points (see ``docs/recognition.md``): the model catalog, the run payload
builder, the pipeline hook, the event recorder and the API router.
"""

from __future__ import annotations

MODULES: tuple[str, ...] = ("face", "plate")
MODULE_LABELS: dict[str, str] = {
    "face": "Face recognition (enrolled identities)",
    "plate": "Vehicle plate recognition",
}

__all__ = ["MODULES", "MODULE_LABELS"]
