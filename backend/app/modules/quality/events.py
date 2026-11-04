"""Quality events (events.md §3.10: ids and the subject only) and the ``QC-YYYY-NNNN`` sequence."""

from __future__ import annotations

from app.platform.numbering.defs import SequenceDef

INSPECTION_REQUESTED = "quality.inspection.requested"
INSPECTION_PASSED = "quality.inspection.passed"
INSPECTION_FAILED = "quality.inspection.failed"

EMITTED_EVENTS: tuple[str, ...] = (INSPECTION_REQUESTED, INSPECTION_PASSED, INSPECTION_FAILED)

INSPECTION_SEQUENCE = SequenceDef(
    key="quality.inspection",
    name="Quality inspection number",
    format_template="QC-{yyyy}-{seq:04}",
    reset_policy="yearly",
    resource_type="quality.inspection",
)
