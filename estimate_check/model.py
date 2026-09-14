"""Core data types for a job package, an audit run, and its findings.

Everything here is a frozen dataclass. The audit is a pure function of the job
package plus the rule pack, which is what makes the output reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SEVERITIES = ("high", "medium", "low")
SEVERITY_ORDER = {"high": 3, "medium": 2, "low": 1}


@dataclass(frozen=True)
class Area:
    """One room or area on the job, with the measurements a rule can cite."""

    area_id: str
    name: str
    floor_sf: float = 0.0
    ceiling_sf: float = 0.0
    perimeter_lf: float = 0.0
    height_ft: float = 8.0
    affected_floor_sf: float = 0.0
    affected_wall_sf: float = 0.0
    affected_ceiling_sf: float = 0.0
    materials: dict[str, str] = field(default_factory=dict)
    scope: tuple[str, ...] = ()
    note: str = ""

    @property
    def wall_sf(self) -> float:
        return self.perimeter_lf * self.height_ft

    @property
    def affected_volume_cuft(self) -> float:
        return self.affected_floor_sf * self.height_ft


@dataclass(frozen=True)
class Document:
    """A photo, note, scan, moisture reading or voice walkthrough segment.

    area_ids may be empty. That is not a data error: in the field a lot of
    documentation arrives with no room assignment at all.
    """

    doc_id: str
    kind: str
    area_ids: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    text: str = ""
    captured_at: str | None = None

    def covers(self, area_id: str) -> bool:
        return area_id in self.area_ids


@dataclass(frozen=True)
class LineItem:
    """A proposed estimate line. area_id None means the line is job wide."""

    line_id: str
    code: str
    description: str = ""
    area_id: str | None = None
    quantity: float = 0.0
    unit: str = ""
    unit_price: float | None = None

    @property
    def extended_price(self) -> float | None:
        if self.unit_price is None:
            return None
        return round(self.quantity * self.unit_price, 2)


@dataclass(frozen=True)
class Job:
    """A job package: what was documented, what was measured, what is billed."""

    job_id: str
    loss_type: str = "water"
    water_category: int | None = None
    drying_class: int | None = None
    planned_drying_days: int = 0
    includes_rebuild: bool = False
    areas: tuple[Area, ...] = ()
    documents: tuple[Document, ...] = ()
    line_items: tuple[LineItem, ...] = ()
    description: str = ""
    source: str = ""

    def area(self, area_id: str | None) -> Area | None:
        if area_id is None:
            return None
        for area in self.areas:
            if area.area_id == area_id:
                return area
        return None

    def lines_in_area(self, area_id: str | None) -> tuple[LineItem, ...]:
        return tuple(line for line in self.line_items if line.area_id == area_id)

    def documents_for_area(self, area_id: str) -> tuple[Document, ...]:
        return tuple(doc for doc in self.documents if doc.covers(area_id))


@dataclass(frozen=True)
class Evidence:
    """A pointer to what a rule looked at, including what it failed to find.

    kind is one of: document, measurement, scope, line_item, rule_constant,
    absence. An absence is still evidence and is reported as such.
    """

    kind: str
    ref: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "ref": self.ref, "detail": self.detail}


@dataclass(frozen=True)
class Subject:
    """What a finding is about: a billed line, a line that should exist, an area."""

    type: str
    area_id: str | None = None
    line_id: str | None = None
    code: str | None = None
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "area_id": self.area_id,
            "line_id": self.line_id,
            "code": self.code,
            "label": self.label,
        }


@dataclass(frozen=True)
class Finding:
    detector: str
    rule_id: str
    severity: str
    subject: Subject
    reason: str
    evidence: tuple[Evidence, ...] = ()
    ambiguous: bool = False

    @property
    def target(self) -> str:
        """The key an operator or a labelled seed set would use to name this."""
        return self.subject.line_id or self.subject.code or self.subject.area_id or ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "detector": self.detector,
            "rule_id": self.rule_id,
            "severity": self.severity,
            "subject": self.subject.to_dict(),
            "reason": self.reason,
            "evidence": [item.to_dict() for item in self.evidence],
            "ambiguous": self.ambiguous,
        }


def finding_id(finding: "Finding") -> str:
    """A stable identity for one finding.

    Used by the labelled seed set to match a finding against ground truth, and
    by the optional judge to refer to a finding it was asked about.
    """
    area = finding.subject.area_id or "-"
    return f"{finding.detector}|{finding.rule_id}|{area}|{finding.target or '-'}"


@dataclass(frozen=True)
class Check:
    """One rule evaluated against one line item.

    status is pass, fail or skipped. A skipped check is reported, not hidden:
    if the rule pack has nothing to say about a line, the operator should know.
    """

    rule_id: str
    detector: str
    status: str
    reason: str
    evidence: tuple[Evidence, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "detector": self.detector,
            "status": self.status,
            "reason": self.reason,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class LineVerdict:
    line: LineItem
    verdict: str
    checks: tuple[Check, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_id": self.line.line_id,
            "code": self.line.code,
            "description": self.line.description,
            "area_id": self.line.area_id,
            "quantity": self.line.quantity,
            "unit": self.line.unit,
            "verdict": self.verdict,
            "checks": [check.to_dict() for check in self.checks],
        }


@dataclass(frozen=True)
class AuditResult:
    job: Job
    rulepack_id: str
    rulepack_version: str
    lines: tuple[LineVerdict, ...]
    findings: tuple[Finding, ...]
    judge: dict[str, Any] | None = None

    @property
    def failed_lines(self) -> tuple[LineVerdict, ...]:
        return tuple(item for item in self.lines if item.verdict == "fail")

    def counts_by(self, attr: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in self.findings:
            key = getattr(finding, attr)
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items()))

    def max_severity(self) -> str | None:
        if not self.findings:
            return None
        return max((f.severity for f in self.findings), key=lambda s: SEVERITY_ORDER[s])

    def to_dict(self) -> dict[str, Any]:
        from estimate_check import __version__

        return {
            "schema_version": "1.0",
            "tool": {"name": "estimate-check", "version": __version__},
            "rulepack": {"id": self.rulepack_id, "version": self.rulepack_version},
            "job": {
                "job_id": self.job.job_id,
                "loss_type": self.job.loss_type,
                "water_category": self.job.water_category,
                "drying_class": self.job.drying_class,
                "areas": len(self.job.areas),
                "documents": len(self.job.documents),
                "line_items": len(self.job.line_items),
                "source": self.job.source,
            },
            "summary": {
                "lines_passed": sum(1 for item in self.lines if item.verdict == "pass"),
                "lines_failed": len(self.failed_lines),
                "lines_not_checked": sum(
                    1 for item in self.lines if item.verdict == "not_checked"
                ),
                "findings": len(self.findings),
                "by_severity": self.counts_by("severity"),
                "by_detector": self.counts_by("detector"),
                "ambiguous": sum(1 for f in self.findings if f.ambiguous),
            },
            "lines": [item.to_dict() for item in self.lines],
            "findings": [f.to_dict() for f in self.findings],
            "judge": self.judge,
        }
