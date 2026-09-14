"""The readable terminal report.

The point of the report is that an operator can see why a line passed or
failed, not a score. So every finding prints the rule that fired and the
evidence it relied on, and --explain prints the checks that passed too.
"""

from __future__ import annotations

import os
import sys

from estimate_check import __version__
from estimate_check.engine import unknown_codes
from estimate_check.model import AuditResult, Check, Evidence
from estimate_check.rulepack import RulePack

_COLORS = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "yellow": "\033[33m",
    "green": "\033[32m",
    "cyan": "\033[36m",
}

SEVERITY_COLOR = {"high": "red", "medium": "yellow", "low": "cyan"}


def use_color(stream=None) -> bool:
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


class Painter:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def __call__(self, text: str, *styles: str) -> str:
        if not self.enabled or not styles:
            return text
        prefix = "".join(_COLORS[style] for style in styles if style in _COLORS)
        return f"{prefix}{text}{_COLORS['reset']}"


def _evidence_lines(evidence: tuple[Evidence, ...], indent: str, paint: Painter) -> list[str]:
    out = []
    for item in evidence:
        detail = f" = {item.detail}" if item.detail else ""
        out.append(paint(f"{indent}{item.kind}: {item.ref}{detail}", "dim"))
    return out


def _check_lines(check: Check, indent: str, paint: Painter) -> list[str]:
    status_style = {"pass": "green", "fail": "red", "skipped": "dim"}[check.status]
    head = f"{indent}{check.rule_id:<9} {paint(check.status, status_style):<6} {check.reason}"
    lines = [head]
    lines.extend(_evidence_lines(check.evidence, indent + "  ", paint))
    return lines


def render(
    result: AuditResult,
    pack: RulePack,
    explain: bool = False,
    color: bool | None = None,
) -> str:
    paint = Painter(use_color() if color is None else color)
    job = result.job
    out: list[str] = []

    out.append(
        paint(f"estimate-check {__version__}", "bold")
        + paint(
            f"   rule pack {result.rulepack_id} {result.rulepack_version} (synthetic, see README)",
            "dim",
        )
    )
    loss_bits = [f"{job.loss_type} loss"]
    if job.water_category is not None:
        loss_bits.append(f"category {job.water_category}")
    if job.drying_class is not None:
        loss_bits.append(f"class {job.drying_class}")
    out.append(
        paint(job.job_id, "bold")
        + "  "
        + ", ".join(loss_bits)
        + f"  |  {len(job.areas)} areas, {len(job.line_items)} lines, {len(job.documents)} documents"
    )
    if job.description:
        out.append(paint(f"  {job.description}", "dim"))
    out.append("")

    out.append(paint("LINE ITEMS", "bold"))
    if not result.lines:
        out.append("  no line items on this estimate")
    for item in result.lines:
        if item.verdict == "fail":
            verdict = paint("FAIL", "red", "bold")
        elif item.verdict == "not_checked":
            verdict = paint("SKIP", "yellow")
        else:
            verdict = paint("PASS", "green")
        where = item.line.area_id or "job wide"
        out.append(
            f"  {verdict}  {item.line.line_id:<4} {item.line.code:<20} {where:<12} "
            f"{item.line.quantity:>9.2f} {item.line.unit}"
        )
        shown = [
            check
            for check in item.checks
            if explain or (item.verdict == "fail" and check.status != "pass")
        ]
        for check in shown:
            out.extend(_check_lines(check, "        ", paint))
    out.append("")

    orphan = [f for f in result.findings if f.subject.line_id is None]
    if orphan:
        out.append(paint("FINDINGS NOT TIED TO A BILLED LINE", "bold"))
        for finding in orphan:
            severity = paint(f"[{finding.severity}]", SEVERITY_COLOR[finding.severity])
            tail = paint(" (ambiguous)", "dim") if finding.ambiguous else ""
            where = finding.subject.area_id or "job wide"
            out.append(
                f"  {severity:<9} {finding.detector:<18} {finding.rule_id:<9} {where}{tail}"
            )
            out.append(f"        {finding.reason}")
            out.extend(_evidence_lines(finding.evidence, "        ", paint))
        out.append("")

    missing = unknown_codes(job, pack)
    if missing:
        out.append(paint("NOT CHECKED", "bold"))
        out.append(
            f"  {len(missing)} code(s) on this estimate are not defined in the rule pack "
            f"and were not verified: {', '.join(missing)}"
        )
        out.append("")

    passed = sum(1 for item in result.lines if item.verdict == "pass")
    failed = len(result.failed_lines)
    unchecked = sum(1 for item in result.lines if item.verdict == "not_checked")
    by_severity = result.counts_by("severity")
    ambiguous = sum(1 for f in result.findings if f.ambiguous)
    out.append(paint("SUMMARY", "bold"))
    out.append(
        f"  lines        {len(result.lines)} total, {passed} pass, {failed} fail"
        + (f", {unchecked} not checked" if unchecked else "")
    )
    severity_bits = "  ".join(
        f"{name} {by_severity.get(name, 0)}" for name in ("high", "medium", "low")
    )
    out.append(
        f"  findings     {len(result.findings)} total   {severity_bits}"
        + (f"   ({ambiguous} marked ambiguous)" if ambiguous else "")
    )
    by_detector = result.counts_by("detector")
    if by_detector:
        out.append(
            "  by detector  "
            + ", ".join(f"{name} {count}" for name, count in by_detector.items())
        )
    else:
        out.append("  by detector  nothing fired")
    if result.judge:
        reviewed = len(result.judge.get("reviews", ()))
        out.append(
            f"  judge        advisory only, reviewed {reviewed} ambiguous finding(s) "
            f"with {result.judge.get('model', 'unknown model')}"
        )
    return "\n".join(out)


def render_compact(result: AuditResult, color: bool | None = None) -> str:
    """One block per job, for the demo, where three jobs print at once."""
    paint = Painter(use_color() if color is None else color)
    by_severity = result.counts_by("severity")
    passed = sum(1 for item in result.lines if item.verdict == "pass")
    unchecked = sum(1 for item in result.lines if item.verdict == "not_checked")
    head = (
        f"{paint(result.job.job_id, 'bold')}  {result.job.description}\n"
        f"  {len(result.lines)} lines, {passed} pass, {len(result.failed_lines)} fail"
        + (f", {unchecked} not checked" if unchecked else "")
        + "   "
        f"findings: {len(result.findings)} "
        f"(high {by_severity.get('high', 0)}, medium {by_severity.get('medium', 0)}, low {by_severity.get('low', 0)})"
    )
    rows = [head]
    for finding in result.findings:
        severity = paint(f"[{finding.severity}]", SEVERITY_COLOR[finding.severity])
        where = finding.subject.line_id or finding.subject.area_id or "job wide"
        tail = paint(" (ambiguous)", "dim") if finding.ambiguous else ""
        rows.append(
            f"    {severity:<9} {finding.detector:<18} {finding.rule_id:<9} {where:<10} {finding.reason}{tail}"
        )
    return "\n".join(rows)
