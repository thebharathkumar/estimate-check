"""Scoring the detectors against a hand labelled seed set.

The protocol, so the numbers can be argued with:

1. The jobs in data/jobs are invented. They were written first.
2. data/seed/labels.json lists every finding a careful reviewer should raise on
   those jobs. Labels were written by reading each job against the synthetic
   rule pack, including cases the detectors cannot catch. A label with
   rule_id "none" marks a finding no rule in the pack can produce, which is a
   permanent false negative and is counted as one.
3. A finding matches a label when job, detector, area, rule id and target are
   all equal. Matched label is a true positive, unmatched finding is a false
   positive, unmatched label is a false negative.
4. Precision and recall are truncated, never rounded up.

The obvious weakness is that the same person wrote the detectors and the
labels. That is stated in the README and it is the main reason these numbers
are presented as a sanity check and not as an accuracy claim.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from estimate_check.detectors import DETECTOR_NAMES
from estimate_check.engine import audit
from estimate_check.loader import load_job
from estimate_check.model import Finding
from estimate_check.rulepack import RulePack, load_rulepack

DEFAULT_LABELS = Path(__file__).parent / "data" / "seed" / "labels.json"
NO_RULE = "none"


def truncate2(value: float) -> float:
    """Round toward zero at two decimals so a figure is never reported higher than it is."""
    return math.floor(value * 100) / 100


def finding_key(finding: Finding) -> tuple[str, str, str, str]:
    return (
        finding.detector,
        finding.subject.area_id or "",
        finding.rule_id,
        finding.target or "",
    )


def label_key(label: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        label["detector"],
        label.get("area_id") or "",
        label.get("rule_id") or NO_RULE,
        label.get("target") or "",
    )


@dataclass(frozen=True)
class DetectorMetrics:
    detector: str
    true_positives: int
    false_positives: int
    false_negatives: int

    @property
    def precision(self) -> float | None:
        denominator = self.true_positives + self.false_positives
        if denominator == 0:
            return None
        return truncate2(self.true_positives / denominator)

    @property
    def recall(self) -> float | None:
        denominator = self.true_positives + self.false_negatives
        if denominator == 0:
            return None
        return truncate2(self.true_positives / denominator)

    def to_dict(self) -> dict[str, Any]:
        return {
            "detector": self.detector,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "precision": self.precision,
            "recall": self.recall,
        }


@dataclass(frozen=True)
class EvaluationReport:
    seed_set_id: str
    job_count: int
    label_count: int
    line_item_count: int
    metrics: tuple[DetectorMetrics, ...]
    false_positives: tuple[dict[str, Any], ...]
    false_negatives: tuple[dict[str, Any], ...]
    unreachable_labels: int

    @property
    def totals(self) -> DetectorMetrics:
        return DetectorMetrics(
            detector="all",
            true_positives=sum(m.true_positives for m in self.metrics),
            false_positives=sum(m.false_positives for m in self.metrics),
            false_negatives=sum(m.false_negatives for m in self.metrics),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed_set_id": self.seed_set_id,
            "jobs": self.job_count,
            "labelled_findings": self.label_count,
            "line_items": self.line_item_count,
            "labels_no_rule_can_produce": self.unreachable_labels,
            "per_detector": [m.to_dict() for m in self.metrics],
            "totals": self.totals.to_dict(),
            "false_positives": list(self.false_positives),
            "false_negatives": list(self.false_negatives),
        }


def load_labels(path: str | Path | None = None) -> dict[str, Any]:
    path = Path(path) if path is not None else DEFAULT_LABELS
    if not path.exists():
        raise FileNotFoundError(f"seed labels not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    for label in payload.get("labels", ()):
        if label.get("detector") not in DETECTOR_NAMES:
            raise ValueError(f"{path}: label names unknown detector {label.get('detector')!r}")
        if not label.get("job_id"):
            raise ValueError(f"{path}: every label needs a job_id")
    return payload


def evaluate(
    labels_path: str | Path | None = None,
    jobs_dir: str | Path | None = None,
    pack: RulePack | None = None,
) -> EvaluationReport:
    payload = load_labels(labels_path)
    pack = pack or load_rulepack()
    jobs_dir = Path(jobs_dir) if jobs_dir else Path(__file__).parent / "data" / "jobs"

    labels_by_job: dict[str, list[dict[str, Any]]] = {}
    for label in payload.get("labels", ()):
        labels_by_job.setdefault(label["job_id"], []).append(label)

    true_positives: Counter[str] = Counter()
    false_positives: Counter[str] = Counter()
    false_negatives: Counter[str] = Counter()
    fp_detail: list[dict[str, Any]] = []
    fn_detail: list[dict[str, Any]] = []

    job_paths = sorted(jobs_dir.glob("*.json"))
    line_items = 0
    for path in job_paths:
        job = load_job(path)
        line_items += len(job.line_items)
        result = audit(job, pack)
        remaining = list(result.findings)
        for label in labels_by_job.get(job.job_id, ()):
            match = next((f for f in remaining if finding_key(f) == label_key(label)), None)
            if match is not None:
                remaining.remove(match)
                true_positives[label["detector"]] += 1
            else:
                false_negatives[label["detector"]] += 1
                fn_detail.append(
                    {
                        "job_id": job.job_id,
                        "detector": label["detector"],
                        "area_id": label.get("area_id"),
                        "rule_id": label.get("rule_id") or NO_RULE,
                        "target": label.get("target"),
                        "note": label.get("note", ""),
                    }
                )
        for finding in remaining:
            false_positives[finding.detector] += 1
            fp_detail.append(
                {
                    "job_id": job.job_id,
                    "detector": finding.detector,
                    "area_id": finding.subject.area_id,
                    "rule_id": finding.rule_id,
                    "target": finding.target,
                    "reason": finding.reason,
                }
            )

    metrics = tuple(
        DetectorMetrics(
            detector=name,
            true_positives=true_positives[name],
            false_positives=false_positives[name],
            false_negatives=false_negatives[name],
        )
        for name in DETECTOR_NAMES
    )

    unreachable = sum(
        1 for label in payload.get("labels", ()) if (label.get("rule_id") or NO_RULE) == NO_RULE
    )

    return EvaluationReport(
        seed_set_id=payload.get("seed_set_id", "unnamed"),
        job_count=len(job_paths),
        label_count=len(payload.get("labels", ())),
        line_item_count=line_items,
        metrics=metrics,
        false_positives=tuple(fp_detail),
        false_negatives=tuple(fn_detail),
        unreachable_labels=unreachable,
    )


def _format_ratio(value: float | None) -> str:
    return "n/a " if value is None else f"{value:.2f}"


def render(report: EvaluationReport) -> str:
    out: list[str] = []
    out.append(
        f"seed set {report.seed_set_id}: {report.job_count} invented jobs, "
        f"{report.line_item_count} line items, {report.label_count} labelled findings"
    )
    out.append(
        f"{report.unreachable_labels} of those labels describe a finding no rule in the pack can "
        "produce, and are counted as false negatives"
    )
    out.append("")
    out.append(f"{'detector':<20} {'TP':>3} {'FP':>3} {'FN':>3}  {'precision':>9}  {'recall':>6}")
    out.append("-" * 56)
    for metric in report.metrics:
        out.append(
            f"{metric.detector:<20} {metric.true_positives:>3} {metric.false_positives:>3} "
            f"{metric.false_negatives:>3}  {_format_ratio(metric.precision):>9}  "
            f"{_format_ratio(metric.recall):>6}"
        )
    totals = report.totals
    out.append("-" * 56)
    out.append(
        f"{'all detectors':<20} {totals.true_positives:>3} {totals.false_positives:>3} "
        f"{totals.false_negatives:>3}  {_format_ratio(totals.precision):>9}  "
        f"{_format_ratio(totals.recall):>6}"
    )
    out.append("")
    out.append(
        "Precision and recall are truncated at two decimals, never rounded up. A seed set "
        "this small cannot estimate either reliably: read the counts, not the ratios."
    )
    if report.false_positives:
        out.append("")
        out.append("findings with no matching label (false positives)")
        for item in report.false_positives:
            out.append(
                f"  {item['job_id']:<10} {item['detector']:<18} {item['rule_id']:<9} "
                f"{item['target'] or item['area_id']}"
            )
    if report.false_negatives:
        out.append("")
        out.append("labels with no matching finding (false negatives)")
        for item in report.false_negatives:
            out.append(
                f"  {item['job_id']:<10} {item['detector']:<18} {item['rule_id']:<9} "
                f"{item['target'] or item['area_id']}"
            )
            if item["note"]:
                out.append(f"      {item['note']}")
    return "\n".join(out)
