"""missing_required: the scope implies a line item and the estimate does not have it.

This detector is the one that finds money, not just errors. A missing debris
haul or a missing carpet pad is work the contractor did and did not bill for.
The findings carry no line id because the subject is a line that should exist.
"""

from __future__ import annotations

from estimate_check.detectors.base import DetectorResult, condition_holds
from estimate_check.model import Evidence, Finding, Job, Subject
from estimate_check.rulepack import RulePack

NAME = "missing_required"


def run(job: Job, pack: RulePack) -> DetectorResult:
    findings: list[Finding] = []

    for rule in pack.required_rules:
        scope = rule.get("scope", "job")
        expect_any = tuple(rule.get("expect_any", ()))
        if not expect_any:
            continue
        targets = job.areas if scope == "area" else (None,)

        for area in targets:
            holds, evidence = condition_holds(rule.get("when", {}), job, area)
            if not holds:
                continue
            if scope == "area":
                present_codes = {line.code for line in job.lines_in_area(area.area_id)}
                where = area.name
                area_id = area.area_id
            else:
                present_codes = {line.code for line in job.line_items}
                where = "this estimate"
                area_id = None
            if set(expect_any) & present_codes:
                continue

            findings.append(
                Finding(
                    detector=NAME,
                    rule_id=rule["rule_id"],
                    severity=rule.get("severity", "medium"),
                    subject=Subject(
                        type="expected_line",
                        area_id=area_id,
                        line_id=None,
                        code=expect_any[0],
                        label=rule["title"],
                    ),
                    reason=(
                        f"{rule['reason']} {where} has none of {', '.join(expect_any)}."
                    ),
                    evidence=evidence
                    + (
                        Evidence(
                            kind="absence",
                            ref=f"expected line in {area_id or 'the estimate'}",
                            detail=f"none of {', '.join(expect_any)} is billed",
                        ),
                    ),
                    ambiguous=bool(rule.get("ambiguous", False)),
                )
            )

    return DetectorResult(tuple(findings), ())
