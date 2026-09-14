"""The six deterministic detectors.

Order matters only for how findings are presented. Every detector is a pure
function of the job package and the rule pack.
"""

from estimate_check.detectors import (
    duplicate_scope,
    missing_required,
    quantity_mismatch,
    sequence_violation,
    undocumented_area,
    unsupported_line,
)

DETECTORS = (
    unsupported_line,
    missing_required,
    quantity_mismatch,
    duplicate_scope,
    sequence_violation,
    undocumented_area,
)

DETECTOR_NAMES = tuple(module.NAME for module in DETECTORS)

DETECTOR_SUMMARIES = {
    "unsupported_line": "a billed line with no documentation behind it",
    "missing_required": "the scope implies a line item that the estimate does not have",
    "quantity_mismatch": "a quantity that contradicts the room measurements",
    "duplicate_scope": "two line items billing the same work",
    "sequence_violation": "a line that depends on work nobody billed",
    "undocumented_area": "an area in scope with no photo, note or scan coverage",
}

__all__ = ["DETECTORS", "DETECTOR_NAMES", "DETECTOR_SUMMARIES"]
