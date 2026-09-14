"""undocumented_area: an area in scope that nobody photographed, scanned or wrote up.

An area counts as in scope when it carries scope tags, affected measurements or
billed lines. Documentation counts when it is attached to the area. A photo
with no room assignment does not count here, which is deliberate and is the
detector's main weakness: see the limitations section of the README.
"""

from __future__ import annotations

from estimate_check.detectors.base import DetectorResult
from estimate_check.model import Evidence, Finding, Job, Subject
from estimate_check.rulepack import RulePack

NAME = "undocumented_area"


def in_scope(job: Job, area) -> tuple[bool, str]:
    if area.scope:
        return True, f"scope tags {', '.join(area.scope)}"
    affected = area.affected_floor_sf + area.affected_wall_sf + area.affected_ceiling_sf
    if affected > 0:
        return True, f"{affected:.2f} SF of affected surface"
    if job.lines_in_area(area.area_id):
        return True, f"{len(job.lines_in_area(area.area_id))} billed line(s)"
    return False, ""


def run(job: Job, pack: RulePack) -> DetectorResult:
    findings: list[Finding] = []
    rules = {rule["rule_id"]: rule for rule in pack.documentation_rules}
    rule = rules.get("DOC-001")
    if rule is None:
        return DetectorResult()

    unassigned = [doc for doc in job.documents if not doc.area_ids]

    for area in job.areas:
        scoped, why = in_scope(job, area)
        if not scoped:
            continue
        docs = job.documents_for_area(area.area_id)
        if docs:
            continue

        evidence = [
            Evidence(kind="scope", ref=f"{area.area_id}.scope", detail=why),
            Evidence(
                kind="absence",
                ref=f"documentation for {area.area_id}",
                detail="no document in the package is attached to this area",
            ),
        ]
        if unassigned:
            evidence.append(
                Evidence(
                    kind="document",
                    ref=", ".join(doc.doc_id for doc in unassigned[:5]),
                    detail=f"{len(unassigned)} document(s) in this package carry no area assignment and were not counted",
                )
            )
        findings.append(
            Finding(
                detector=NAME,
                rule_id="DOC-001",
                severity=rule.get("severity", "high"),
                subject=Subject(
                    type="area",
                    area_id=area.area_id,
                    line_id=None,
                    code=None,
                    label=area.name,
                ),
                reason=f"{area.name} is in scope ({why}) and no documentation is attached to it.",
                evidence=tuple(evidence),
            )
        )

    return DetectorResult(tuple(findings), ())
