"""quantity_mismatch: a billed quantity that contradicts the room measurements.

QTY-002 checks the unit first. If a line is billed in a unit the pack does not
use for that code, comparing the numbers is meaningless and QTY-001 is skipped.

QTY-001 compares the quantity against the basis the pack assigns to the code.
A band just outside tolerance is flagged as ambiguous rather than as an error:
a 12 percent overage is as likely to be a waste factor as a mistake, and this
tool does not know the contractor's waste convention.
"""

from __future__ import annotations

from estimate_check.detectors.base import DetectorResult, resolve_basis
from estimate_check.model import Check, Evidence, Finding, Job, Subject
from estimate_check.rulepack import RulePack

NAME = "quantity_mismatch"


def severity_for(relative_error: float, tolerance: float) -> tuple[str, bool]:
    """Map how far off a quantity is to a severity, and to whether it is ambiguous."""
    if relative_error <= tolerance * 2:
        return "low", True
    if relative_error <= 0.5:
        return "medium", False
    return "high", False


def run(job: Job, pack: RulePack) -> DetectorResult:
    findings: list[Finding] = []
    checks: list[tuple[str, Check]] = []

    for line in job.line_items:
        spec = pack.spec(line.code)
        if spec is None:
            checks.append(
                (
                    line.line_id,
                    Check(
                        "QTY-001",
                        NAME,
                        "skipped",
                        f"code {line.code} is not defined in rule pack {pack.rulepack_id}, so no quantity basis is known",
                    ),
                )
            )
            continue

        subject = Subject(
            type="line_item",
            area_id=line.area_id,
            line_id=line.line_id,
            code=line.code,
            label=spec.label,
        )

        if spec.unit and line.unit and line.unit != spec.unit:
            evidence = (
                Evidence(kind="line_item", ref=line.line_id, detail=f"billed in {line.unit}"),
                Evidence(kind="rule_constant", ref=f"{line.code}.unit", detail=spec.unit),
            )
            findings.append(
                Finding(
                    detector=NAME,
                    rule_id="QTY-002",
                    severity="medium",
                    subject=subject,
                    reason=f"{line.code} is billed in {line.unit}. The rule pack prices this code in {spec.unit}.",
                    evidence=evidence,
                )
            )
            checks.append(
                (line.line_id, Check("QTY-002", NAME, "fail", f"unit {line.unit} is not {spec.unit}", evidence))
            )
            checks.append(
                (
                    line.line_id,
                    Check("QTY-001", NAME, "skipped", "the unit does not match, so the quantity cannot be compared"),
                )
            )
            continue

        checks.append(
            (line.line_id, Check("QTY-002", NAME, "pass", f"billed in {line.unit or 'no unit'} as the pack expects"))
        )

        basis = resolve_basis(job, pack, line, spec.basis)
        if basis.value is None:
            checks.append((line.line_id, Check("QTY-001", NAME, "skipped", basis.skip_reason, basis.evidence)))
            continue

        expected = basis.value
        if expected == 0:
            if line.quantity > 0:
                evidence = basis.evidence or (
                    Evidence(kind="measurement", ref=basis.label, detail="0.00"),
                )
                findings.append(
                    Finding(
                        detector=NAME,
                        rule_id="QTY-001",
                        severity="high",
                        subject=subject,
                        reason=(
                            f"{line.quantity:g} {line.unit} of {line.code} is billed where the measured "
                            f"{basis.label} is zero."
                        ),
                        evidence=evidence,
                    )
                )
                checks.append(
                    (line.line_id, Check("QTY-001", NAME, "fail", f"measured {basis.label} is zero", evidence))
                )
            else:
                checks.append(
                    (line.line_id, Check("QTY-001", NAME, "pass", f"nothing billed and measured {basis.label} is zero"))
                )
            continue

        relative_error = abs(line.quantity - expected) / expected
        if relative_error <= spec.tolerance:
            checks.append(
                (
                    line.line_id,
                    Check(
                        "QTY-001",
                        NAME,
                        "pass",
                        (
                            f"{line.quantity:g} {line.unit} is within {spec.tolerance:.0%} of {basis.label} "
                            f"{expected:.2f}"
                        ),
                        basis.evidence,
                    ),
                )
            )
            continue

        severity, ambiguous = severity_for(relative_error, spec.tolerance)
        direction = "over" if line.quantity > expected else "under"
        reason = (
            f"{line.code} is billed at {line.quantity:g} {line.unit}. The rule pack basis {basis.label} "
            f"measures {expected:.2f}, so the line is {relative_error:.0%} {direction} a tolerance of {spec.tolerance:.0%}."
        )
        findings.append(
            Finding(
                detector=NAME,
                rule_id="QTY-001",
                severity=severity,
                subject=subject,
                reason=reason,
                evidence=basis.evidence,
                ambiguous=ambiguous,
            )
        )
        checks.append(
            (
                line.line_id,
                Check(
                    "QTY-001",
                    NAME,
                    "fail",
                    f"{line.quantity:g} is {relative_error:.0%} {direction} {basis.label} {expected:.2f}",
                    basis.evidence,
                ),
            )
        )

    return DetectorResult(tuple(findings), tuple(checks))
