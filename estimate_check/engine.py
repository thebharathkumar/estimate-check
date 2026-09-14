"""The audit itself: run every detector over a job package and assemble the result.

audit() is deterministic. Same job package plus same rule pack gives the same
bytes out, with no timestamps in the output, so two runs can be diffed.
"""

from __future__ import annotations

from estimate_check.detectors import DETECTORS
from estimate_check.model import (
    SEVERITY_ORDER,
    AuditResult,
    Check,
    Finding,
    Job,
    LineVerdict,
)
from estimate_check.rulepack import RulePack, load_rulepack

CHECK_ORDER = {"fail": 0, "pass": 1, "skipped": 2}


def _finding_sort_key(finding: Finding) -> tuple:
    return (
        -SEVERITY_ORDER[finding.severity],
        finding.detector,
        finding.subject.area_id or "",
        finding.subject.line_id or "",
        finding.rule_id,
    )


def unknown_codes(job: Job, pack: RulePack) -> tuple[str, ...]:
    """Codes on the estimate that the rule pack has never heard of.

    These lines are reported as not checked rather than as passing. A verifier
    that silently passes what it cannot read is worse than no verifier.
    """
    return tuple(sorted({line.code for line in job.line_items if pack.spec(line.code) is None}))


def audit(job: Job, pack: RulePack | None = None) -> AuditResult:
    pack = pack or load_rulepack()

    findings: list[Finding] = []
    checks_by_line: dict[str, list[Check]] = {line.line_id: [] for line in job.line_items}

    for detector in DETECTORS:
        result = detector.run(job, pack)
        findings.extend(result.findings)
        for line_id, check in result.checks:
            checks_by_line.setdefault(line_id, []).append(check)

    failed_line_ids = {
        finding.subject.line_id for finding in findings if finding.subject.line_id is not None
    }
    unverifiable = set(unknown_codes(job, pack))

    lines = tuple(
        LineVerdict(
            line=line,
            verdict=(
                "fail"
                if line.line_id in failed_line_ids
                else "not_checked"
                if line.code in unverifiable
                else "pass"
            ),
            checks=tuple(
                sorted(
                    checks_by_line.get(line.line_id, []),
                    key=lambda check: (CHECK_ORDER[check.status], check.rule_id),
                )
            ),
        )
        for line in job.line_items
    )

    return AuditResult(
        job=job,
        rulepack_id=pack.rulepack_id,
        rulepack_version=pack.version,
        lines=lines,
        findings=tuple(sorted(findings, key=_finding_sort_key)),
    )
