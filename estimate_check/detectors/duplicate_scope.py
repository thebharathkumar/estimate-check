"""duplicate_scope: two line items billing the same work.

DUP-001 is the same code twice in one area. DUP-002 is two different codes
from one exclusivity group in one area, for example a 2 ft flood cut and a 4 ft
flood cut in the same room.

The finding is attached to the later of the two lines and names the earlier one
as evidence, so an operator gets one finding per pair rather than two.
"""

from __future__ import annotations

from estimate_check.detectors.base import DetectorResult
from estimate_check.model import Check, Evidence, Finding, Job, Subject
from estimate_check.rulepack import RulePack

NAME = "duplicate_scope"


def run(job: Job, pack: RulePack) -> DetectorResult:
    findings: list[Finding] = []
    checks: list[tuple[str, Check]] = []
    flagged: set[str] = set()

    seen_code: dict[tuple[str, str], str] = {}
    seen_group: dict[tuple[str, str], tuple[str, str]] = {}

    for line in job.line_items:
        where = line.area_id or "job wide"
        spec = pack.spec(line.code)
        label = spec.label if spec else line.code
        subject = Subject(
            type="line_item",
            area_id=line.area_id,
            line_id=line.line_id,
            code=line.code,
            label=label,
        )

        code_key = (where, line.code)
        if code_key in seen_code:
            first = seen_code[code_key]
            evidence = (
                Evidence(kind="line_item", ref=first, detail=f"{line.code} already billed in {where}"),
                Evidence(kind="line_item", ref=line.line_id, detail=f"{line.code} billed again in {where}"),
            )
            findings.append(
                Finding(
                    detector=NAME,
                    rule_id="DUP-001",
                    severity="high",
                    subject=subject,
                    reason=f"{line.code} is billed twice in {where}, on {first} and on {line.line_id}.",
                    evidence=evidence,
                )
            )
            checks.append(
                (line.line_id, Check("DUP-001", NAME, "fail", f"{line.code} is already billed on {first}", evidence))
            )
            flagged.add(line.line_id)
            continue
        seen_code[code_key] = line.line_id

        group = spec.duplicate_group if spec else None
        if group:
            group_key = (where, group)
            if group_key in seen_group:
                first_id, first_code = seen_group[group_key]
                evidence = (
                    Evidence(kind="line_item", ref=first_id, detail=f"{first_code} in {where}"),
                    Evidence(kind="line_item", ref=line.line_id, detail=f"{line.code} in {where}"),
                    Evidence(
                        kind="rule_constant",
                        ref=f"duplicate_group.{group}",
                        detail=", ".join(pack.codes_in_group(group)),
                    ),
                )
                findings.append(
                    Finding(
                        detector=NAME,
                        rule_id="DUP-002",
                        severity="high",
                        subject=subject,
                        reason=(
                            f"{line.line_id} bills {line.code} in {where} where {first_id} already bills "
                            f"{first_code}. Both codes are in the {group} group, which bills one piece of work once."
                        ),
                        evidence=evidence,
                    )
                )
                checks.append(
                    (
                        line.line_id,
                        Check("DUP-002", NAME, "fail", f"{group} work is already billed on {first_id}", evidence),
                    )
                )
                flagged.add(line.line_id)
                continue
            seen_group[group_key] = (line.line_id, line.code)

        if line.line_id not in flagged:
            checks.append(
                (
                    line.line_id,
                    Check(
                        "DUP-001",
                        NAME,
                        "pass",
                        f"no earlier line bills {line.code}"
                        + (f" or anything else in the {group} group" if group else "")
                        + f" in {where}",
                    ),
                )
            )

    return DetectorResult(tuple(findings), tuple(checks))
