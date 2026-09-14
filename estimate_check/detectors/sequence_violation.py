"""sequence_violation: a line that depends on work nobody billed.

Drywall goes back up only where drywall came down. Floor covering goes down
only where floor covering came up. Finish paint over new board needs a sealer
first. Each rule names the codes it governs and the codes that satisfy it, so
the report can say which one was missing rather than just that something was.
"""

from __future__ import annotations

from estimate_check.detectors.base import DetectorResult
from estimate_check.model import Check, Evidence, Finding, Job, Subject
from estimate_check.rulepack import RulePack

NAME = "sequence_violation"


def _gate_holds(rule: dict, area_codes: set[str]) -> bool:
    has_any = rule.get("when_area_has_any")
    if has_any and not set(has_any) & area_codes:
        return False
    lacks_all = rule.get("when_area_lacks_all")
    if lacks_all and set(lacks_all) & area_codes:
        return False
    return True


def run(job: Job, pack: RulePack) -> DetectorResult:
    findings: list[Finding] = []
    checks: list[tuple[str, Check]] = []

    for line in job.line_items:
        spec = pack.spec(line.code)
        applicable = [rule for rule in pack.sequence_rules if line.code in rule.get("code_any", ())]
        if not applicable:
            checks.append(
                (
                    line.line_id,
                    Check(
                        "SEQ-000",
                        NAME,
                        "skipped",
                        f"no sequence rule in {pack.rulepack_id} names {line.code}",
                    ),
                )
            )
            continue

        scope_codes = {
            other.code: other.line_id
            for other in (
                job.lines_in_area(line.area_id) if line.area_id is not None else job.line_items
            )
        }
        area_codes = set(scope_codes)
        where = line.area_id or "job wide"

        for rule in applicable:
            rule_id = rule["rule_id"]
            if not _gate_holds(rule, area_codes):
                checks.append(
                    (
                        line.line_id,
                        Check(
                            rule_id,
                            NAME,
                            "skipped",
                            f"{rule['title']} does not apply to {where} on this job",
                        ),
                    )
                )
                continue

            satisfied = [code for code in rule.get("requires_any", ()) if code in area_codes]
            if satisfied:
                evidence = tuple(
                    Evidence(kind="line_item", ref=scope_codes[code], detail=f"{code} in {where}")
                    for code in satisfied
                )
                checks.append(
                    (
                        line.line_id,
                        Check(
                            rule_id,
                            NAME,
                            "pass",
                            f"{satisfied[0]} is billed on {scope_codes[satisfied[0]]} in {where}",
                            evidence,
                        ),
                    )
                )
                continue

            required = ", ".join(rule.get("requires_any", ()))
            evidence = (
                Evidence(kind="line_item", ref=line.line_id, detail=f"{line.code} in {where}"),
                Evidence(
                    kind="absence",
                    ref=f"predecessor in {where}",
                    detail=f"none of {required} is billed",
                ),
            )
            findings.append(
                Finding(
                    detector=NAME,
                    rule_id=rule_id,
                    severity=rule.get("severity", "medium"),
                    subject=Subject(
                        type="line_item",
                        area_id=line.area_id,
                        line_id=line.line_id,
                        code=line.code,
                        label=spec.label if spec else line.code,
                    ),
                    reason=f"{rule['reason']} None of {required} appears in {where}.",
                    evidence=evidence,
                    ambiguous=bool(rule.get("ambiguous", False)),
                )
            )
            checks.append(
                (
                    line.line_id,
                    Check(rule_id, NAME, "fail", f"none of {required} is billed in {where}", evidence),
                )
            )

    return DetectorResult(tuple(findings), tuple(checks))
