"""Offline licence validation for the recognition modules."""

from pathscope.recognition.licensing.license import (
    STATE_DISABLED,
    STATE_EXPIRED,
    STATE_LICENSED,
    STATE_NOT_LICENSED,
    LicenseError,
    LicenseManager,
    LicensePayload,
    LicenseVerdict,
    ModuleState,
    get_license_manager,
    hardware_id,
    issue_license,
    verify_document,
)

__all__ = [
    "STATE_DISABLED",
    "STATE_EXPIRED",
    "STATE_LICENSED",
    "STATE_NOT_LICENSED",
    "LicenseError",
    "LicenseManager",
    "LicensePayload",
    "LicenseVerdict",
    "ModuleState",
    "get_license_manager",
    "hardware_id",
    "issue_license",
    "verify_document",
]
